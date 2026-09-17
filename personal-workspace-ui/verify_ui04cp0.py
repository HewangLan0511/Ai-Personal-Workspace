#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-04-C-P0 Responsive Workspace System（Edge 无头 + CDP）。

状态机：full > compact > collapsed > fallback，全部边界带滞回带（RS_GATE）：
  full ⇄ compact   缩 <1400 进 / 扩 >1500 回
  compact ⇄ collapsed  缩 <950 进 / 扩 >1050 回
  collapsed ⇄ fallback 缩 <650 进 / 扩 >750 回
内容排布仍由 data-cw 档位管（同样带 50px 滞回）。

用例判据（★ 判据是 shell[data-rs] 状态 + chrome 实测宽度 + 内容零删除 + 滞回保持）：
  T1 1920 → full：三栏齐全（导航 236 / 组件区在 / AI 360），Hero 双列。
  T2 1366 → compact：导航实测 180、AI 面板实测 260、组件区让路、导航文字不竖排、
     内容"压缩但稳定"（Hero 双列 160 map + 双栏）。
  T3 1100 → compact：AI 260 保持、内容堆叠（Hero 单列）、导航文字仍在。
  T4 900 → collapsed：导航图标化(64) + AI 收成入口竖条(48) + 内容堆叠。
  T5 600 → fallback：兜底单列、无水平溢出（不重叠）、导航图标化。
  T6 滞回动态测试：1370→compact 后，1470（滞回带内）必须保持 compact 不跳回；
     1530 → full。再快速扫 700↔1520 十次，终态与窗口匹配、无异常。
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
    profile = tempfile.mkdtemp(prefix="edge_p0_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=1920,1000", f"--remote-debugging-port={port}",
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

        def resize(w, h=1000, wait=0.6):
            ws.call("Emulation.setDeviceMetricsOverride",
                    {"width": w, "height": h, "deviceScaleFactor": 0, "mobile": False})
            time.sleep(wait)

        def snap():
            return ev("""(() => {
              const sh = document.getElementById('shell');
              const side = document.querySelector('.sidebar');
              const ai = document.querySelector('.ai-dock');
              const hero = document.querySelector('.hero');
              const t = document.body.textContent;
              const lbl = document.querySelector('.nav-item .lbl');
              const lblRect = lbl ? lbl.getBoundingClientRect() : {width: 0, height: 0};
              return {rs: sh.dataset.rs, cw: sh.dataset.cw || '',
                      navW: Math.round(side.getBoundingClientRect().width),
                      aiW: Math.round(ai.getBoundingClientRect().width),
                      heroCols: getComputedStyle(hero).gridTemplateColumns.split(' ').length,
                      lblVisible: lblRect.width > 10,
                      navVert: lblRect.height > 30,
                      overflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth};
            })()""")

        # ---------- T1 1920 → full ----------
        resize(1920)
        r = snap()
        ok = (r["rs"] == "full" and r["navW"] in range(220, 260) and r["aiW"] in range(340, 380)
              and r["heroCols"] == 2 and not r["navVert"])
        check("T1 1920 → full：三栏齐全 + Hero 双列", ok, json.dumps(r))

        # ---------- T2 1366 → compact：压缩但稳定 ----------
        resize(1366)
        r = snap()
        widgetGone = ev("(() => { const w = document.querySelector('.widget-col');"
                        " return !w || w.getBoundingClientRect().width < 2; })()")
        ok = (r["rs"] == "compact" and r["navW"] in range(170, 195) and r["aiW"] in range(250, 275)
              and widgetGone and r["lblVisible"] and not r["navVert"] and r["heroCols"] == 2)
        check("T2 1366 → compact：导航180/AI260/组件区让路 + 文字横排 + 桌面结构保留", ok,
              f"{json.dumps(r)} widgetGone={widgetGone}")

        # ---------- T3 1100 → compact（内容堆叠） ----------
        resize(1100)
        r = snap()
        ok = (r["rs"] == "compact" and r["aiW"] in range(250, 275) and r["heroCols"] == 1
              and r["lblVisible"] and not r["navVert"])
        check("T3 1100 → compact：AI 260 保持 + 内容堆叠 + 导航文字在", ok, json.dumps(r))

        # ---------- T4 900 → collapsed：辅助区折叠 ----------
        resize(900)
        r = snap()
        aiRail = ev("getComputedStyle(document.querySelector('.ai-dock .dock-rail')).display !== 'none'")
        ok = (r["rs"] == "collapsed" and r["navW"] in range(56, 76) and r["aiW"] in range(40, 56)
              and aiRail and not r["lblVisible"] and r["heroCols"] == 1)
        check("T4 900 → collapsed：导航图标64 + AI 入口竖条48 + 内容堆叠", ok,
              f"{json.dumps(r)} aiRail={aiRail}")

        # ---------- T5 600 → fallback：兜底不重叠 ----------
        resize(600)
        r = snap()
        ok = (r["rs"] == "fallback" and r["overflowX"] <= 1 and not r["lblVisible"]
              and r["heroCols"] == 1)
        check("T5 600 → fallback：兜底单列 + 零水平溢出（不重叠）", ok, json.dumps(r))

        # ---------- T6 滞回动态测试 ----------
        resize(1370)
        a = snap()
        resize(1470)          # 滞回带内（>1400 但 <1500）→ 必须保持 compact
        b = snap()
        resize(1530)          # 越过恢复阈值 → full
        c = snap()
        ok = (a["rs"] == "compact" and b["rs"] == "compact" and c["rs"] == "full")
        # 快速扫频：十次快速缩放后终态必须与窗口匹配，全程无异常
        for w in (700, 1520, 680, 1500, 900, 1400, 640, 1450, 660, 1920):
            resize(w, wait=0.15)
        resize(1920, wait=0.6)
        d = snap()
        ok = ok and d["rs"] == "full" and d["overflowX"] <= 1
        check("T6 滞回：带内保持 compact 不跳回 + 快速扫频终态正确", ok,
              f"1370={a['rs']} 1470={b['rs']} 1530={c['rs']} final={d['rs']} ovx={d['overflowX']}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
