#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：工作模式视窗点击置顶（Edge 无头 + CDP）。

背景（2026-09-15 增补）：
  原 mousedown 处理把所有被点窗口都写成 zIndex=5 —— 叠放次序实际退化为 DOM
  顺序，点一个被盖住的窗口并不能真正浮到最上层。修复为递增 z-index 的
  frontWin(win)（initStage mousedown 与 run-tab 聚焦两处统一走它）。

用例判据（★ 判据是 inline z-index 数值 + elementFromPoint 真实叠放，不是 class）：
  T1 点窗口 B 标题栏 → B.zIndex > A.zIndex，sel 在 B。
  T2 再点窗口 A 的 body 区（非标题栏）→ A.zIndex > B.zIndex，sel 归 A。
  T3 叠放实证：把两窗摆成重叠，点 A 后 elementFromPoint 命中 A。
  T4 run 页 appbar 标签聚焦对应窗口 → 该窗口 z 最大。
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
    profile = tempfile.mkdtemp(prefix="edge_wf_")
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
                    if ev("!!document.querySelector('.rsh--ai')"):
                        return True
                    last = ev("document.readyState + '|' + location.hash")
                except Exception as e:
                    last = repr(e)[:120]
                time.sleep(0.3)
            print("页面未就绪，最后状态:", last)
            return False
        assert wait_ready(), "页面未就绪"

        MDOWN = "new MouseEvent('mousedown', {bubbles:true, cancelable:true})"
        MUP = "document.dispatchEvent(new MouseEvent('mouseup'))"

        # ---------- 进入 run 模式，两窗摆成重叠 ----------
        ev("location.hash = '#/run'")
        time.sleep(0.8)
        ev("""(() => { const ws = [...document.querySelectorAll('.win')];
          if(ws.length < 2) throw new Error('wins<2');
          // 摆成大面积重叠：A 在下、B 在上（DOM 顺序无关紧要，位置造重叠）
          ws[0].style.left = '15%'; ws[0].style.top = '20%';
          ws[0].style.width = '40%'; ws[0].style.height = '50%';
          ws[1].style.left = '20%'; ws[1].style.top = '25%';
          ws[1].style.width = '40%'; ws[1].style.height = '50%';
          ws[0].removeAttribute('style');  // 只留 left/top/width/height
          ws[0].style.left='15%'; ws[0].style.top='20%'; ws[0].style.width='40%'; ws[0].style.height='50%';
        })()""")

        def zof(i):
            return ev(f"+document.querySelectorAll('.win')[{i}].style.zIndex || 0")

        def selof():
            return ev("[...document.querySelectorAll('.win')].findIndex(w=>w.classList.contains('sel'))")

        # ---------- T1 点 B 标题栏 → B 置顶（+ appbar 标签同步） ----------
        ev(f"""(() => {{
          const w = document.querySelectorAll('.win')[1].querySelector('.win-bar');
          w.dispatchEvent({MDOWN}); {MUP};
        }})()""")
        time.sleep(0.1)
        z0, z1, sel = zof(0), zof(1), selof()
        r = ev("""(() => { const w = document.querySelectorAll('.win')[1];
          const app = w.dataset.w;
          return {app, tab: state.run.tab,
                  tabOn: document.querySelector('.apptab[data-v="'+app+'"]').classList.contains('on')}; })()""")
        check("T1 点窗口 B 标题栏 → B z 更高且 sel + appbar 标签同步", z1 > z0 and sel == 1
              and r["tab"] == r["app"] and r["tabOn"],
              f"zA={z0} zB={z1} sel={sel} tab={r['tab']}/{r['app']} tabOn={r['tabOn']}")

        # ---------- T2 点 A 的 body（非标题栏）→ A 反超 ----------
        ev(f"""(() => {{
          const w = document.querySelectorAll('.win')[0].querySelector('.win-body');
          w.dispatchEvent({MDOWN}); {MUP};
        }})()""")
        time.sleep(0.1)
        z0, z1, sel = zof(0), zof(1), selof()
        check("T2 点窗口 A body → A z 反超且 sel", z0 > z1 and sel == 0,
              f"zA={z0} zB={z1} sel={sel}")

        # ---------- T3 elementFromPoint 实证叠放 ----------
        ev("""(() => { const w = document.querySelectorAll('.win')[1];
          w.querySelector('.win-bar').dispatchEvent(new MouseEvent('mousedown',{bubbles:true}));
          document.dispatchEvent(new MouseEvent('mouseup')); })()""")
        time.sleep(0.1)
        r = ev("""(() => {
          const ws = document.querySelectorAll('.win');
          const a = ws[0].getBoundingClientRect();
          const x = a.left + a.width*0.9, y = a.top + a.height*0.9;   // A 右下角 = 重叠区
          const el = document.elementFromPoint(x, y);
          const hit = el ? el.closest('.win') : null;
          return {hitIdx: hit ? [...ws].indexOf(hit) : -1,
                  cls: el ? (el.className||'').toString().slice(0,40) : ''};
        })()""")
        check("T3 重叠区 elementFromPoint 命中刚点过的 B", r["hitIdx"] == 1,
              f"hit={r['hitIdx']} cls={r['cls']!r}")

        # ---------- T4 appbar 标签聚焦对应窗口到最前（其余窗口参数不变） ----------
        r = ev("""(() => {
          const tab = [...document.querySelectorAll('.apptab')].find(t=>t.dataset.v && t.dataset.v!=='ai');
          if(!tab) return {skip:true};
          const app = tab.dataset.v;
          // 事故锚点：给所有窗口打身份标记 + 记录 inline 几何与 z（模拟用户拖过没保存）
          const ws = [...document.querySelectorAll('.win')];
          ws.forEach((w,i)=>{ w.dataset.probe='keep'+i;
            if(w.dataset.w!==app){ w.style.left='27.77%'; w.style.top='13.55%'; } });
          const zsBefore = ws.map(w=>+w.style.zIndex||0);
          tab.click();
          return {skip:false, app, zsBefore};
        })()""")
        time.sleep(0.4)
        if r.get("skip"):
            check("T4 appbar 聚焦窗口", False, "找不到非 ai 的 apptab")
        else:
            app = json.dumps(r["app"])   # JSON 带引号的字符串字面量，安全嵌入 JS
            js = f"""(() => {{
              const ws=[...document.querySelectorAll('.win')];
              return {{zs: ws.map(w=>+w.style.zIndex||0),
                      hit: ws.findIndex(w=>w.dataset.w==={app}),
                      probes: ws.map(w=>w.dataset.probe),
                      othersKept: ws.every((w,i)=> w.dataset.w==={app} ||
                        (w.dataset.probe==='keep'+i && w.style.left==='27.77%' && w.style.top==='13.55%')),
                      tabOn: document.querySelector('.apptab[data-v={app}]').classList.contains('on')}};
            }})()"""
            zmax = ev(js)
            zs, hit = zmax["zs"], zmax["hit"]
            ok = (hit >= 0 and zs[hit] == max(zs) and zs[hit] > 0
                  and zmax["othersKept"] and zmax["tabOn"]
                  and all(zs[i] == r["zsBefore"][i] for i in range(len(zs)) if i != hit))
            check("T4 appbar 标签聚焦窗口 + 其余窗口身份/几何/层级不变", ok,
                  f"app={r['app']} hit={hit} zsBefore={r['zsBefore']} zs={zs} "
                  f"kept={zmax['othersKept']} tabOn={zmax['tabOn']}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
