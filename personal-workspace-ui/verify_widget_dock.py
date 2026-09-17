#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：组件区拖拽换位 + dock 状态切换不重建内容区（Edge 无头 + CDP）。

背景（2026-09-14 UI-03 增补）：
  1. 组件区 .wcard 的 enableSort 曾绑在 #widgetCol 上，而卡片的真实父容器是
     内层 .wscroll —— insertBefore(src, ref) 因 ref 不是 container 子节点抛
     NotFoundError，真实拖拽第一次 dragover 就静默失效。修复后绑 .wscroll。
  2. toggle-dock / ai-mode 原来调 render()，把 view 内容区整个重建 ——
     设置页会重播 swap-in 淡入（"刷新视效"）。修复后走 applyDockLocal()
     局部同步，内容区 DOM 节点身份不变。

用例判据（★ 判据是 DOM 节点身份 / 数据顺序，不是"看起来没动"）：
  T1 组件区合成拖拽：DOM 顺序 + WIDGETS 数据顺序都变；300ms 后无残留 transform。
  T2 故障对照组：直接调 render() → 探针标记必须被抹掉（证明探针有区分度）。
  T3 设置页展开 dock：view 身份不变 + dock 展开 + 面板可见。
  T4 设置页收起 dock：view 身份不变 + dock 折叠。
  T5 ai 模式切换：view 身份不变 + state.aiMode 变化 + dock 内容真的换了。
  T6 run 模式 AI 标签 = 开关：收起 → 标签灭 + ai-fab 出现 + 被拖过窗口的 inline
     位置保留（证明没重绘）；再点 → 展开 + 标签亮 + fab 消失。
"""
import base64, json, os, shutil, socket, struct, subprocess, sys, tempfile, time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "index.html").as_uri()


def find_edge():
    roots = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        b = os.environ.get(var)
        if b:
            roots.append(Path(b))
    for root in roots:
        c = root.joinpath("Microsoft", "Edge", "Application", "msedge.exe")
        if c.exists():
            return str(c)
    return shutil.which("msedge")


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class WS:
    def __init__(self, sock, initial):
        self.s = sock; self.buf = initial; self._id = 0

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk: raise RuntimeError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]; return out

    def _frame(self):
        b0, b1 = self._need(2)
        op = b0 & 0x0F; ln = b1 & 0x7F
        if ln == 126: ln = struct.unpack(">H", self._need(2))[0]
        elif ln == 127: ln = struct.unpack(">Q", self._need(8))[0]
        if b1 & 0x80:
            mask = self._need(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._need(ln)))
        else: data = self._need(ln)
        return op, data

    def send(self, text, op=0x1):
        data = text.encode()
        h = bytearray([0x80 | op]); n = len(data)
        if n < 126: h.append(0x80 | n)
        elif n < 65536: h.append(0x80 | 126); h += struct.pack(">H", n)
        else: h.append(0x80 | 127); h += struct.pack(">Q", n)
        mask = os.urandom(4); h += mask
        self.s.sendall(bytes(h) + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def call(self, method, params=None, timeout=90):
        self._id += 1; mid = self._id
        self.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        self.s.settimeout(timeout)
        while True:
            op, data = self._frame()
            if op == 0x9: self.send(data.decode("utf-8", "replace"), op=0xA); continue
            if op == 0x8: raise RuntimeError("closed by peer")
            if op not in (0x1, 0x2): continue
            msg = json.loads(data.decode("utf-8", "replace"))
            if msg.get("id") != mid: continue
            if "error" in msg: raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


def connect(port, tries=60):
    last = ""
    for _ in range(tries):
        try:
            raw = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2).read()
            for t in json.loads(raw):
                if t.get("type") == "page" and t.get("webSocketDebuggerUrl"):
                    u = urlparse(t["webSocketDebuggerUrl"])
                    s = socket.create_connection((u.hostname, u.port), timeout=20)
                    key = base64.b64encode(os.urandom(16)).decode()
                    s.sendall((f"GET {u.path} HTTP/1.1\r\nHost: {u.hostname}:{u.port}\r\n"
                               f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
                    buf = b""
                    while b"\r\n\r\n" not in buf: buf += s.recv(4096)
                    head, rest = buf.split(b"\r\n\r\n", 1)
                    if "101" not in head.split(b"\r\n")[0].decode("latin1"):
                        raise RuntimeError("handshake fail")
                    return WS(s, rest)
        except Exception as e:
            last = repr(e)[:160]
        time.sleep(0.4)
    raise RuntimeError("cannot attach; last=" + last)


def main():
    EDGE = find_edge()
    if not EDGE:
        print("FAIL 找不到 Edge"); return 2
    port = free_port()
    profile = tempfile.mkdtemp(prefix="edge_wd_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=1600,1000", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", PAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = []
    def check(name, ok, detail):
        results.append((name, ok, detail))
        print(("PASS" if ok else "FAIL"), name, "｜", detail)

    try:
        ws = connect(port)
        def ev(js):
            r = ws.call("Runtime.evaluate", {"expression": js, "returnByValue": True,
                                             "awaitPromise": True}, timeout=30)
            if r.get("exceptionDetails"):
                raise RuntimeError("页面求值异常: " + json.dumps(r["exceptionDetails"])[:300])
            return r.get("result", {}).get("value")

        def wait_ready():
            last = ""
            for _ in range(100):
                try:
                    if ev("!!document.querySelector('.wcard') && !!document.querySelector('.rsh--ai')"):
                        return True
                    last = ev("document.readyState + '|' + location.hash + '|cards=' + document.querySelectorAll('.wcard').length")
                except Exception as e:
                    last = repr(e)[:120]
                time.sleep(0.3)
            print("页面未就绪，最后状态:", last)
            return False
        assert wait_ready(), "页面未就绪"

        # ---------- T1 组件区合成拖拽 ----------
        a = ev("""(() => {
          const wc = document.getElementById('widgetCol');
          const sc = wc.querySelector('.wscroll');
          const cards = [...sc.querySelectorAll('.wcard')];
          const dt = new DataTransfer();
          const fire = (el, t) => el.dispatchEvent(new DragEvent(t, {bubbles:true, cancelable:true, dataTransfer:dt}));
          let hErr = null; const hFn = e => { hErr = (e.message||'').slice(0,150); };
          window.addEventListener('error', hFn);
          fire(cards[0], 'dragstart');
          const dragCls = cards[0].classList.contains('dragging');
          fire(cards[2], 'dragover');
          const orderMid = [...sc.querySelectorAll('.wcard')].map(c=>c.dataset.wid);
          fire(cards[2], 'drop');
          fire(cards[0], 'dragend');
          window.removeEventListener('error', hFn);
          return {dragCls, orderMid, hErr,
                  dataOrder: WIDGETS.filter(w=>w.on).map(w=>w.id)};
        })()""")
        time.sleep(0.35)   # 等 FLIP 动画收尾
        b = ev("""(() => { const sc = document.querySelector('#widgetCol .wscroll');
          const cs = [...sc.querySelectorAll('.wcard')];
          return {order: cs.map(c=>c.dataset.wid),
                  leftover: cs.some(c=>c.style.transform)}; })()""")
        ok = (a["dragCls"] and not a["hErr"] and a["orderMid"][0] == "todo"
              and b["order"][0] == "todo" and b["order"][2] == "weather"
              and a["dataOrder"][0] == "todo" and not b["leftover"])
        check("T1 组件区拖拽换位（DOM+数据+FLIP 无残留）", ok,
              f"mid={a['orderMid']} final={b['order']} data={a['dataOrder']} hErr={a['hErr']!r} leftover={b['leftover']}")

        # ---------- T2 故障对照组：探针必须能抓到重建 ----------
        ev("document.querySelector('.view').firstElementChild.dataset.probe = 'keepme'")
        ev("render()")
        r = ev("document.querySelector('.view').firstElementChild.dataset.probe !== 'keepme'")
        check("T2 故障对照组（render() 必须抹掉身份标记）", r is True, f"rebuilt={r}")

        # ---------- T3/T4 设置页 dock 收起/展开（dock 初始为展开态） ----------
        ev("location.hash = '#/settings'")
        time.sleep(0.5)
        ev("document.querySelector('.view').firstElementChild.dataset.probe = 'keepme'")
        ev("document.querySelector('#aiDock .rail-btn').click()")
        time.sleep(0.6)
        r = ev("""(() => { const v = document.querySelector('.view').firstElementChild;
          const d = document.getElementById('aiDock');
          return {kept: v.dataset.probe === 'keepme',
                  collapsed: d.classList.contains('collapsed')}; })()""")
        check("T3 设置页收起 dock 不重建内容区", r["kept"] and r["collapsed"],
              f"kept={r['kept']} collapsed={r['collapsed']}")
        ev("document.querySelector('#aiDock .dock-panel [data-act=toggle-dock]').click()")
        time.sleep(0.6)
        r = ev("""(() => { const v = document.querySelector('.view').firstElementChild;
          const d = document.getElementById('aiDock');
          return {kept: v.dataset.probe === 'keepme', expanded: !d.classList.contains('collapsed')}; })()""")
        check("T4 设置页展开 dock 不重建内容区", r["kept"] and r["expanded"],
              f"kept={r['kept']} expanded={r['expanded']}")

        # ---------- T5 ai 模式切换（T4 后 dock 已展开） ----------
        ev("document.querySelector('#aiDock [data-act=ai-mode][data-v=workspace]').click()")
        time.sleep(0.6)
        r = ev("""(() => { const v = document.querySelector('.view').firstElementChild;
          const d = document.getElementById('aiDock');
          return {kept: v.dataset.probe === 'keepme', mode: state.aiMode,
                  wsSegOn: !!d.querySelector('[data-act=ai-mode][data-v=workspace].on'),
                  permWs: d.textContent.includes('已允许访问')}; })()""")
        check("T5 ai 模式切换不重建内容区", r["kept"] and r["mode"] == "workspace"
              and r["wsSegOn"] and r["permWs"],
              f"kept={r['kept']} mode={r['mode']} segOn={r['wsSegOn']} permWs={r['permWs']}")

        # ---------- T6 run 模式 AI 标签 = 展开⇄折叠开关 ----------
        ev("location.hash = '#/run'")
        time.sleep(0.8)
        ev("""(() => { const w = document.querySelector('.win');
          w.style.left = '13.37%';          // 模拟用户手动拖过的窗口位置
          w.dataset.probe = 'winkeep'; })()""")
        ev("document.querySelector('.apptab[data-v=ai]').click()")   # 展开→收起
        time.sleep(0.6)
        r1 = ev("""(() => ({collapsed: document.getElementById('aiDock').classList.contains('collapsed'),
          tabOn: document.querySelector('.apptab[data-v=ai]').classList.contains('on'),
          fab: !!document.querySelector('.ai-fab'),
          winKept: document.querySelector('.win').dataset.probe === 'winkeep'
                   && document.querySelector('.win').style.left === '13.37%'}))()""")
        ev("document.querySelector('.apptab[data-v=ai]').click()")   # 收起→展开
        time.sleep(0.6)
        r2 = ev("""(() => ({collapsed: document.getElementById('aiDock').classList.contains('collapsed'),
          tabOn: document.querySelector('.apptab[data-v=ai]').classList.contains('on'),
          fab: !!document.querySelector('.ai-fab'),
          mode: state.aiMode,
          winKept: document.querySelector('.win').dataset.probe === 'winkeep'}))()""")
        ok = (r1["collapsed"] and not r1["tabOn"] and r1["fab"] and r1["winKept"]
              and not r2["collapsed"] and r2["tabOn"] and not r2["fab"] and r2["winKept"]
              and r2["mode"] == "workspace")
        check("T6 run AI 标签切换 + 窗口位置不被重绘", ok,
              f"collapse={json.dumps(r1)} expand={json.dumps(r2)}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
