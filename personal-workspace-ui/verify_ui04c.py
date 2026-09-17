#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-04-C 首页响应式系统 + 全局滚动体验（Edge 无头 + CDP）。

核心机制：断点从「窗口宽度」改为「内容区宽度」（.view clientWidth，ResizeObserver
驱动，shell[data-cw] = lg/md/sm/xs）。窗口断点感知不到三侧栏占用与手动拖宽，
是"换设备尺寸后首页挤兑、标题竖排"的根因。

用例判据（★ 判据是 shell[data-cw] 档位 + computed grid 列数 + 内容完整性文本）：
  T1 宽裕（窗口 2000，三侧栏全开）→ cw 为空档，最近使用 6 列，Hero 双列。
  T2 挤兑复现档（窗口 1000：原方案下标题竖排区）→ md 档：Hero 单列堆叠、
     行动中心移到下方（文本仍在，不删内容）、最近使用 3 列。
  T3 极限档（窗口 680）→ xs 档：侧边导航自动折叠（shell.mini + state.cwMini）；
     拉回 2000 → 自动恢复。
  T4 首页完整性：xs 极限档下问候语/继续工作/最近使用/今日行动中心/工作空间卡全部在场。
  T5 滚动体验：.view scrollbar-gutter=stable + overscroll-behavior=contain。
  T6 故障对照：把 shell.dataset.cw 手写错值后窗口变化必须被 RO 纠正（探针有区分度）。
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
    profile = tempfile.mkdtemp(prefix="edge_c_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=2000,1000", f"--remote-debugging-port={port}",
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

        def resize(w, h=1000):
            ws.call("Emulation.setDeviceMetricsOverride",
                    {"width": w, "height": h, "deviceScaleFactor": 0, "mobile": False})
            time.sleep(0.6)   # 等 RO(rAF) 收敛

        def cw():
            return ev("({cw: document.getElementById('shell').dataset.cw || '',"
                      " vw: document.querySelector('.view').clientWidth})")

        # ---------- T1 宽裕档 ----------
        resize(2000)
        r = ev("""(() => {
          const cs = getComputedStyle(document.getElementById('recentGrid'));
          const hero = getComputedStyle(document.querySelector('.hero'));
          return {cw: document.getElementById('shell').dataset.cw || '',
                  cols: cs.gridTemplateColumns.split(' ').length,
                  heroCols: hero.gridTemplateColumns.split(' ').length};
        })()""")
        ok = r["cw"] == "" and r["cols"] == 6 and r["heroCols"] == 2
        check("T1 宽裕档：无档位标记 + 最近使用 6 列 + Hero 双列", ok,
              f"cw={r['cw']!r} cols={r['cols']} heroCols={r['heroCols']}")

        # ---------- T2 挤兑复现档（窗口 1000）→ compact 态 + 内容兜底堆叠 ----------
        resize(1000)
        r = ev("""(() => {
          const cs = getComputedStyle(document.getElementById('recentGrid'));
          const hero = getComputedStyle(document.querySelector('.hero'));
          const split = getComputedStyle(document.querySelector('.home-split'));
          const t = document.body.textContent;
          return {rs: document.getElementById('shell').dataset.rs,
                  cw: document.getElementById('shell').dataset.cw || '',
                  heroCols: hero.gridTemplateColumns.split(' ').length,
                  splitCols: split.gridTemplateColumns.split(' ').length,
                  recentCols: cs.gridTemplateColumns.split(' ').length,
                  navLbl: getComputedStyle(document.querySelector('.nav-item .lbl')).display !== 'none',
                  todayKept: t.includes('今日行动中心') && t.includes('今日任务'),
                  heroKept: t.includes('晚上好，白宇') && t.includes('继续工作')};
        })()""")
        ok = (r["rs"] == "compact" and r["cw"] == "sm" and r["heroCols"] == 1 and r["splitCols"] == 1
              and r["recentCols"] == 3 and r["navLbl"] and r["todayKept"] and r["heroKept"])
        check("T2 窗口 1000（原挤兑区）：compact 态 + 内容兜底堆叠 + 内容零删除", ok, json.dumps(r))

        # ---------- T3 极限档 → 辅助区折叠（导航图标化 + AI 竖条），拉宽恢复 ----------
        resize(680)
        r1 = ev("""(() => ({rs: document.getElementById('shell').dataset.rs,
                  mini: document.getElementById('shell').classList.contains('mini'),
                  state: state.rsMini,
                  aiRail: getComputedStyle(document.querySelector('.ai-dock .dock-rail')).display !== 'none'}))()""")
        resize(2000)
        r2 = ev("""(() => ({rs: document.getElementById('shell').dataset.rs,
                  mini: document.getElementById('shell').classList.contains('mini'),
                  state: state.rsMini}))()""")
        ok = (r1["rs"] == "collapsed" and r1["mini"] and r1["state"] and r1["aiRail"]
              and r2["rs"] == "full" and not r2["mini"] and not r2["state"])
        check("T3 极限档辅助区折叠（导航图标+AI 入口条）+ 拉宽自动恢复", ok,
              f"xs={json.dumps(r1)} back={json.dumps(r2)}")

        # ---------- T4 首页完整性（回极限档逐项点名） ----------
        resize(680)
        r = ev("""(() => { const t = document.body.textContent;
          return {greet: t.includes('晚上好，白宇'),
                  cta: t.includes('继续工作') && t.includes('切换工作空间'),
                  recent: t.includes('最近使用'),
                  today: t.includes('今日行动中心'),
                  ws: t.includes('我的工作空间') && t.includes('AI 项目开发')}; })()""")
        ok = all(r.values())
        check("T4 xs 极限档首页完整性：五区块零删除", ok, json.dumps(r))

        # ---------- T5 全局滚动体验 ----------
        r = ev("""(() => { const v = getComputedStyle(document.querySelector('.view'));
          return {gutter: v.scrollbarGutter, contain: v.overscrollBehavior}; })()""")
        ok = r["gutter"] == "stable" and r["contain"] == "contain"
        check("T5 滚动体验：gutter=stable + overscroll=contain", ok, json.dumps(r))

        # ---------- T6 故障对照：RO 必须纠正手写的错档位 ----------
        resize(2000)
        ev("document.getElementById('shell').dataset.cw = 'sm'")   # 手写错档
        resize(800)
        r = ev("document.getElementById('shell').dataset.cw")
        ok = r in ("md", "sm")   # 800 视口下内容宽 <=920 必为 md/sm，绝不残留手写值语义
        # 更强判据：先缩到 xs 再放大，档位必须被 RO 重算
        resize(680); resize(2000)
        r2 = ev("document.getElementById('shell').dataset.cw")
        ok = r2 == ""
        check("T6 故障对照组：档位由 RO 实测驱动，不被静态值欺骗", ok, f"mid={r!r} final={r2!r}")
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
