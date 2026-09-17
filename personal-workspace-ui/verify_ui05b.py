#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端验收：UI-05-B 工作空间状态系统（Edge 无头 + CDP）。

用例判据：
  T1 状态栏结构：进入工作模式可见 当前任务/应用列表/布局状态，应用 chip = 窗口应用 + AI。
  T2 工作目标：设置目标 → 状态栏局部更新（壳节点身份不变），舞台窗口不受影响。
  T3 应用状态：点击应用 chip 三态循环 运行中→等待打开→已关闭→运行中，仅状态展示变化。
  T4 布局结构：drawer 行数 = 窗口数，含位置描述。
  T5 布局状态联动：切回自动排列 → 状态栏显示 自动布局。
  T6 创建模式：工作空间页 创建模式 → 自定义模式卡出现。
  T7 切换模板：点击编程模式 → 准备 overlay → 进入 run，目标/模式/应用同步，窗口布局完好。
  T8 run 内切换模板：状态栏「模式」→ 学习模式 → 窗口重建为该空间布局且几何合法。
  T9 响应式：1920 / 1366 / 900 三档 run 页无横向溢出。
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
    profile = tempfile.mkdtemp(prefix="edge_s5b_")
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

        # ---------- T1 状态栏结构 ----------
        ev("location.hash = '#/run'")
        time.sleep(0.9)
        s1 = ev("""(() => {
          const rs = document.getElementById('runStatus');
          if(!rs) return {ok:false};
          const t = rs.textContent;
          return {ok:true, t,
            apps: rs.querySelectorAll('.rs-app').length,
            goalBtn: !!rs.querySelector('[data-act="run-goal-open"]'),
            hasTask: t.includes('当前任务'), hasNoGoal: t.includes('未设置工作目标'),
            hasApps: t.includes('应用'), hasLayout: t.includes('布局'), hasAuto: t.includes('自动布局')};
        })()""")
        ok = (s1 and s1["ok"] and s1["apps"] == 4 and s1["goalBtn"]
              and s1["hasTask"] and s1["hasNoGoal"] and s1["hasApps"] and s1["hasLayout"] and s1["hasAuto"])
        check("T1 进入工作模式：状态栏含 当前任务/应用列表(4)/布局状态", ok, json.dumps(s1, ensure_ascii=False)[:220])

        # ---------- T2 工作目标（S2：壳节点身份不变 + 窗口不动） ----------
        ev("window.__rs0 = document.getElementById('runStatus'); window.__w0 = document.querySelectorAll('#stageGrid .win').length;")
        ev("document.querySelector('[data-act=\"run-goal-open\"]').click()")
        time.sleep(0.4)
        drawer_open = ev("!!document.querySelector('.drawer input#goalName')")
        ev("document.querySelector('[data-act=\"run-goal-suggest\"]').click()")
        time.sleep(0.1)
        val = ev("document.getElementById('goalName').value")
        ev("document.querySelector('[data-act=\"run-goal-save\"]').click()")
        time.sleep(0.5)
        s2 = ev("""(() => {
          const rs = document.getElementById('runStatus');
          return {same: rs === window.__rs0, t: rs.textContent,
                  wins: document.querySelectorAll('#stageGrid .win').length,
                  drawerGone: !document.querySelector('.drawer')};
        })()""")
        ok = (drawer_open and val == "RGB-T 视觉项目" and s2["same"]
              and "正在进行：RGB-T 视觉项目" in s2["t"] and s2["wins"] == 3 and s2["drawerGone"])
        check("T2 设置工作目标：状态栏局部更新（壳节点不变）+ 窗口不受影响", ok,
              f"drawer={drawer_open} val={val} same={s2['same']} wins={s2['wins']}")

        # ---------- T3 应用状态三态循环 ----------
        seq = ev("""(() => {
          const out = [];
          for(let i=0;i<3;i++){
            /* refreshRunStatus 每次都重建 chip —— 必须现查现点，拿旧引用点不到委派层 */
            document.querySelector('.rs-app').click();
            out.push(document.querySelector('.rs-app .rs-st').textContent);
          }
          return {sts: out, same: document.getElementById('runStatus') === window.__rs0,
                  wins: document.querySelectorAll('#stageGrid .win').length};
        })()""")
        ok = (seq["sts"][0] == "等待打开" and seq["sts"][1] == "已关闭" and seq["sts"][2] == "运行中"
              and seq["same"] and seq["wins"] == 3)
        check("T3 应用状态：chip 点击三态循环（运行中→等待打开→已关闭→运行中）", ok, json.dumps(seq, ensure_ascii=False))

        # ---------- T4 布局结构 ----------
        ev("document.querySelector('[data-act=\"run-struct\"]').click()")
        time.sleep(0.4)
        s4 = ev("""(() => {
          const d = document.querySelector('.drawer');
          if(!d) return {ok:false};
          return {ok:true, rows: d.querySelectorAll('.drawer-body .row').length,
                  t: d.querySelector('.drawer-body').textContent};
        })()""")
        ok = (s4 and s4["ok"] and s4["rows"] == 3 and "├" in s4["t"]
              and any(k in s4["t"] for k in ("左侧", "右侧", "居中", "浮动")))
        check("T4 布局结构：drawer 行数=窗口数(3) 且含位置描述", ok, json.dumps(s4, ensure_ascii=False)[:200])
        ev("document.querySelector('.drawer [data-act=\"close-layer\"]').click()")
        time.sleep(0.4)

        # ---------- T5 布局状态联动（自动排列） ----------
        ev("document.querySelector('[data-act=\"run-mode\"][data-v=\"auto\"]').click()")
        time.sleep(0.5)
        t5 = ev("document.getElementById('runStatus').textContent")
        ok = "自动布局" in t5 and "手动调整" not in t5
        check("T5 布局状态联动：切自动排列 → 状态栏显示 自动布局", ok, t5[:120])

        # ---------- T6 工作空间页：创建模式 ----------
        ev("location.hash = '#/workspaces'")
        time.sleep(0.9)
        s6a = ev("""(() => ({
          cards: document.querySelectorAll('.wf-mode').length,
          t: document.querySelector('.wf-row').textContent
        }))()""")
        ev("document.querySelector('[data-act=\"run-mode-create\"]').click()")
        time.sleep(0.4)
        ev("document.getElementById('modeName').value='自定义模式'")
        ev("document.getElementById('modeGoal').value='项目复盘'")
        ev("document.querySelector('[data-act=\"run-mode-create-save\"]').click()")
        time.sleep(0.5)
        s6b = ev("""(() => {
          const d = document.querySelector('.drawer');
          return {listHasNew: d && d.textContent.includes('自定义模式') && d.textContent.includes('项目复盘')};
        })()""")
        ev("document.querySelector('.drawer [data-act=\"close-layer\"]').click()")
        time.sleep(0.4)
        s6c = ev("""(() => ({
          cards: document.querySelectorAll('.wf-mode').length,
          hasNew: document.querySelector('.wf-row').textContent.includes('项目复盘')
        }))()""")
        ok = (s6a["cards"] == 3 and "编程模式" in s6a["t"] and "学习模式" in s6a["t"] and "创建模式" in s6a["t"]
              and s6b["listHasNew"] and s6c["cards"] == 4 and s6c["hasNew"])
        check("T6 创建模式：预设 2 模板 + 创建模式入口 → 自定义模式卡出现（页内即时）", ok,
              f"cards {s6a['cards']}→{s6c['cards']} new={s6c['hasNew']}")

        # ---------- T7 切换模板（工作空间页 → 准备反馈 → run） ----------
        ev("document.querySelector('.wf-mode[data-act=\"run-mode-apply\"][data-v=\"dev\"]').click()")
        time.sleep(0.5)
        prep = ev("""(() => {
          const p = document.getElementById('runPrep');
          return p ? {ok:true, t:p.textContent, done: p.querySelectorAll('.rp-step.done').length} : {ok:false};
        })()""")
        time.sleep(2.0)
        s7 = ev("""(() => {
          const rs = document.getElementById('runStatus');
          const wins = [...document.querySelectorAll('#stageGrid .win')];
          const inb = wins.every(w => { const g = {x:parseFloat(w.style.left), y:parseFloat(w.style.top),
            w:parseFloat(w.style.width), h:parseFloat(w.style.height)};
            return g.x>=-0.5 && g.y>=-0.5 && g.x+g.w<=100.5 && g.y+g.h<=100.5; });
          return {isRun: document.querySelector('.shell').classList.contains('cinema'),
            t: rs ? rs.textContent : '', wins: wins.length, inb,
            toast: (document.getElementById('toastHost')||{}).textContent || ''};
        })()""")
        ok = (prep and prep["ok"] and "正在准备工作空间" in prep["t"]
              and s7["isRun"] and "正在进行：软件开发" in s7["t"] and "编程模式" in s7["t"]
              and s7["wins"] == 3 and s7["inb"] and "工作空间已准备完成" in s7["toast"])
        check("T7 切换模板：准备 overlay → 进入 run，目标/模式同步 + 窗口布局完好", ok,
              f"prep_done={prep and prep.get('done')} wins={s7['wins']} inb={s7['inb']} toast={'工作空间已准备完成' in s7['toast']}")

        # ---------- T8 run 内切换模板 ----------
        ev("document.querySelector('[data-act=\"run-mode-open\"]').click()")
        time.sleep(0.4)
        ev("document.querySelector('.drawer [data-act=\"run-mode-apply\"][data-v=\"study\"]').click()")
        time.sleep(2.2)
        s8 = ev("""(() => {
          const rs = document.getElementById('runStatus');
          const wins = [...document.querySelectorAll('#stageGrid .win')];
          const apps = wins.map(w=>w.dataset.w);
          const inb = wins.every(w => { const g = {x:parseFloat(w.style.left), y:parseFloat(w.style.top),
            w:parseFloat(w.style.width), h:parseFloat(w.style.height)};
            return g.x>=-0.5 && g.y>=-0.5 && g.x+g.w<=100.5 && g.y+g.h<=100.5; });
          return {t: rs ? rs.textContent : '', apps, inb,
                  drag: !!document.querySelector('#stageGrid .win .win-bar')};
        })()""")
        ok = ("正在进行：课程学习" in s8["t"] and "学习模式" in s8["t"]
              and sorted(s8["apps"]) == ["chrome", "word"] and s8["inb"] and s8["drag"])
        check("T8 run 内切换模板：目标/应用/布局全部就位且窗口可拖（win-bar 在）", ok,
              f"apps={s8['apps']} inb={s8['inb']}")

        # ---------- T9 响应式 1920 / 1366 / 900 ----------
        resp = []
        for w in (1920, 1366, 900):
            ws.call("Emulation.setDeviceMetricsOverride",
                    {"width": w, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
            time.sleep(0.5)
            r = ev("""(() => ({
              sw: document.documentElement.scrollWidth, iw: window.innerWidth,
              rs: !!document.getElementById('runStatus')
            }))()""")
            resp.append((w, r))
        ws.call("Emulation.clearDeviceMetricsOverride")
        ok = all(r["sw"] <= r["iw"] + 1 and r["rs"] for _, r in resp)
        check("T9 响应式：1920/1366/900 run 页均无横向溢出", ok,
              " ".join(f"{w}:sw{r['sw']}/iw{r['iw']}" for w, r in resp))
    finally:
        proc.terminate()

    total = len(results); passed = sum(1 for _, ok, _ in results if ok)
    print("=" * 60)
    print(f"TOTAL {passed} passed, {total - passed} failed")
    return 0 if passed == total else 1


sys.exit(main())
