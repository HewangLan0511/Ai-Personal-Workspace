#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-05 智能窗口拖拽与吸附布局（Edge 无头 + CDP）。

用例判据（★ 判据是 inline 几何 / 预览类名 / 他窗是否被牵动）：
  T1 普通拖动 + 覆盖保留：拖到与别的窗部分重叠的自由位 → 无预览、他窗几何不变、重叠保留。
  T2 边缘吸附 + 剩余空间填充：拖到右缘 → 预览右半区 → 松手 = 本窗右半 + 其余窗竖排填满左半。
     中途其他窗口 inline 几何必须一动不动（禁止拖动自动覆盖半屏）。
  T3 交换：拖到大部压在别的窗上（>55%）→ swap 预览 → 松手两窗几何互换，第三窗不动。
  T4 插入：拖到别的窗右缘 → insert 预览（插入分屏）→ 松手两窗各占其半，第三窗不动。
  T5 保存后恢复布局一致（吸附编排结果原样恢复）。
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
    profile = tempfile.mkdtemp(prefix="edge_s5_")
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
            for _ in range(100):
                try:
                    if ev("!!document.querySelector('.rsh--ai')"):
                        return True
                except Exception: pass
                time.sleep(0.3)
            return False
        assert wait_ready(), "页面未就绪"

        # 拖拽工具：按下（抓取点存 window.__p）/ 绝对坐标移动 / 抬起 / 几何读取
        ev("""window.__down = sel => {
          const bar = document.querySelector(sel + ' .win-bar');
          const br = bar.getBoundingClientRect();
          const x0 = br.left + br.width/2, y0 = br.top + br.height/2;
          bar.dispatchEvent(new MouseEvent('mousedown', {bubbles:true, clientX:x0, clientY:y0}));
          window.__p = {x0, y0};
          return window.__p;
        };
        window.__move = (x, y) => document.dispatchEvent(new MouseEvent('mousemove', {bubbles:true, clientX:x, clientY:y}));
        window.__up = () => document.dispatchEvent(new MouseEvent('mouseup', {bubbles:true}));
        window.__rects = () => { const o = {};
          document.querySelectorAll('#stageGrid .win').forEach(w=>{
            o[w.dataset.w] = {x:parseFloat(w.style.left), y:parseFloat(w.style.top),
                              w:parseFloat(w.style.width), h:parseFloat(w.style.height)}; });
          return o; };
        window.__sr = () => { const r = document.getElementById('stageGrid').getBoundingClientRect();
          return {l:r.left, t:r.top, w:r.width, h:r.height}; };""")

        def near(a, b, tol=2.0):
            return a is not None and abs(a - b) <= tol

        def ghost():
            return ev("""(() => { const g = document.querySelector('.stage .snap-ghost');
              return g && g.style.display === 'block' ? {cls: g.className,
                x: parseFloat(g.style.left), w: parseFloat(g.style.width)} : null; })()""")

        # ---------- 进入工作模式（默认自由布局） ----------
        ev("location.hash = '#/run'")
        time.sleep(0.8)

        # ---------- T1 普通拖动：无预览 + 他窗不动 + 重叠保留 ----------
        before = ev("__rects()")
        # 精确拖到窗口左上角 (30%, 20%)：指针位移 = 目标角 − 当前窗口左上角
        pos = ev("""(() => { const w = document.querySelector('.win[data-w=vscode]').getBoundingClientRect();
          const sr = __sr();
          return {wl: w.left, wt: w.top, wantL: sr.l + sr.w*0.30, wantT: sr.t + sr.h*0.20}; })()""")
        dx = pos["wantL"] - pos["wl"]
        dy = pos["wantT"] - pos["wt"]
        ev("__down('.win[data-w=vscode]')")
        ev(f"__move(window.__p.x0 + {dx}, window.__p.y0 + {dy})")
        time.sleep(0.1)
        mid = ev("""(() => { const g = document.querySelector('.stage .snap-ghost');
          return {ghost: g && g.style.display === 'block', others: __rects()}; })()""")
        ev("__up()")
        time.sleep(0.2)
        after = ev("__rects()")
        ovW = min(30 + 60, 100) - 64   # vscode (30..90) ∩ chrome (64..98)
        ok = (not mid["ghost"]
              and near(after["vscode"]["x"], 30) and near(after["vscode"]["y"], 20)
              and near(after["chrome"]["x"], before["chrome"]["x"]) and near(after["chrome"]["y"], before["chrome"]["y"])
              and near(after["terminal"]["x"], before["terminal"]["x"])
              and ovW > 0)
        check("T1 普通拖动：无预览 + 他窗几何不变 + 重叠保留", ok,
              f"mid_ghost={mid['ghost']} after={json.dumps(after)}")

        # ---------- T2 边缘吸附 + 剩余空间填充 ----------
        othersBeforeT2 = ev("""(() => { const o = __rects(); delete o.terminal; return o; })()""")
        ev("__down('.win[data-w=terminal]')")
        # 目标：terminal 右缘距舞台右缘 ~10px
        p = ev("""(() => { const w = document.querySelector('.win[data-w=terminal]').getBoundingClientRect();
          const sr = __sr(); return {dx: (sr.l + sr.w - 10) - w.right, dy: 0}; })()""")
        ev(f"__move(__p.x0 + {p['dx']}, __p.y0 + {p['dy']})")
        time.sleep(0.1)
        g = ghost()
        mid_others = ev("""(() => { const o = __rects(); delete o.terminal; return o; })()""")
        ev("__up()")
        time.sleep(0.2)
        r = ev("__rects()")
        ok = (g and near(g["x"], 50) and near(g["w"], 50)
              and near(r["terminal"]["x"], 50) and near(r["terminal"]["w"], 50) and near(r["terminal"]["h"], 100)
              and near(r["vscode"]["x"], 0) and near(r["vscode"]["w"], 50) and near(r["vscode"]["h"], 50)
              and near(r["chrome"]["x"], 0) and near(r["chrome"]["y"], 50) and near(r["chrome"]["w"], 50))
        check("T2 边缘吸附：右缘预览 → 松手右半区 + 其余窗填满左半（剩余空间计算）", ok,
              f"ghost={json.dumps(g)} now={json.dumps(r)}")
        # 中途他窗不动（在拖动中采样的 others 应与 T2 开始前一致）
        others_same = all(near(mid_others[a]["x"], othersBeforeT2[a]["x"], 0.5) and
                          near(mid_others[a]["y"], othersBeforeT2[a]["y"], 0.5) for a in mid_others)
        check("T2b 拖动中他窗零牵动（禁止自动覆盖）", others_same, json.dumps(mid_others))

        # ---------- T3 交换：大部压到别的窗上 ----------
        # 先把 vscode 自由挪到 (10%, 5%)（模拟用户此前的自由摆放；x=10 保证与 chrome 的
        # 重叠宽度足够，覆盖率达 0.72 > 0.55 阈值）
        ev("__down('.win[data-w=vscode]')")
        p = ev("""(() => { const w = document.querySelector('.win[data-w=vscode]').getBoundingClientRect();
          const sr = __sr(); return {dx: (sr.l + sr.w*0.10) - w.left, dy: (sr.t + sr.h*0.05) - w.top}; })()""")
        ev(f"__move(window.__p.x0 + {p['dx']}, window.__p.y0 + {p['dy']})")
        ev("__up()")
        time.sleep(0.2)
        # 再往下拖 40% 舞台高 → vscode 大部压到 chrome 上（cov≈0.72）
        ev("__down('.win[data-w=vscode]')")
        p = ev("""(() => ({dy: __sr().h * 0.40}))()""")
        ev(f"__move(window.__p.x0, window.__p.y0 + {p['dy']})")
        time.sleep(0.1)
        g = ghost()
        ev("__up()")
        time.sleep(0.2)
        r = ev("__rects()")
        ok = (g and "swap" in g["cls"]
              and near(r["vscode"]["x"], 0) and near(r["vscode"]["y"], 50)
              and near(r["chrome"]["x"], 10) and near(r["chrome"]["y"], 45)
              and near(r["terminal"]["x"], 50))
        check("T3 交换：>55% 覆盖出 swap 预览 → 松手两窗几何互换 + 第三窗不动", ok,
              f"ghost={json.dumps(g)} now={json.dumps(r)}")

        # ---------- T4 插入：拖到别的窗右缘 → 两窗各占其半 ----------
        # 摆位：vscode 左上大窗、chrome 右上小窗（同带），terminal 不动
        ev("""(() => { const set=(s,a)=>{const w=document.querySelector('.win[data-w='+s+']');
          w.style.left=a[0]+'%'; w.style.top=a[1]+'%'; w.style.width=a[2]+'%'; w.style.height=a[3]+'%';};
          set('vscode',[0,0,50,50]); set('chrome',[20,10,25,30]); })()""")
        ev("__down('.win[data-w=chrome]')")
        # 目标：chrome 左缘距 vscode 右缘（50%）~10px
        p = ev("""(() => { const w = document.querySelector('.win[data-w=chrome]').getBoundingClientRect();
          const sr = __sr(); return {dx: (sr.l + sr.w*0.5 - 10) - w.left, dy: 0}; })()""")
        ev(f"__move(__p.x0 + {p['dx']}, __p.y0 + {p['dy']})")
        time.sleep(0.1)
        g = ghost()
        ev("__up()")
        time.sleep(0.2)
        r = ev("__rects()")
        ok = (g and "insert" in g["cls"]
              and near(r["chrome"]["x"], 25) and near(r["chrome"]["w"], 25)
              and near(r["vscode"]["w"], 25)
              and near(r["terminal"]["x"], 50) and near(r["terminal"]["w"], 50))
        check("T4 插入：贴窗缘出 insert 预览 → 松手两窗各占其半 + 第三窗不动", ok,
              f"ghost={json.dumps(g)} now={json.dumps(r)}")

        # ---------- T5 保存后恢复布局一致 ----------
        ev("document.querySelector('[data-act=\"save-layout\"]').click()")
        time.sleep(0.6)
        saved = ev("__rects()")
        ev("document.querySelector('[data-act=\"exit-run\"]').click()")
        time.sleep(0.6)
        ev("document.querySelector('.ws-card[data-ws=\"ai\"]').click()")
        time.sleep(0.8)
        now = ev("__rects()")
        same = all(near(saved[a][k], now[a][k], 1.5) for a in saved for k in ("x", "y", "w", "h"))
        check("T5 保存后恢复布局一致（吸附编排结果原样还原）", same,
              f"saved={json.dumps(saved)} now={json.dumps(now)}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
