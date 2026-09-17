#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
折叠 ⇄ 展开"过程感"的端到端验收：Edge 无头 + CDP 真实指针拖拽。

被测行为（2026-09-14 小修改）：
  1. AI 栏折叠后，边缘手柄仍可见、可命中、可拖（不再 display:none）。
  2. 折叠态拖拽 = 连续跟手的拉出过程（inline 宽度逐帧跟随），越过阈值才展开，
     展开时面板挂 dock-appear（复用 dockIn 动画）——不是瞬间跳变。
  3. 导航栏折叠态拖拽同理：宽度连续跟随，越过 200px 摘 .mini，文字经
     120ms 延迟过渡逐步显现（不是瞬间出现）。
  4. 设置页"点按钮切状态"不再弹 toast（set-motion / plugin-sw）。

★ 区分度说明：
  - T2/T3 都有"中途采样"：拖到一半断言 inline 宽度 ≈ 起始宽+位移 且 class 未摘。
    若实现是"跨阈值才一次性跳宽"，中途采样就会失败 —— 探针能看见跳变。
  - T4 用双证据：toast 函数拦截标志 + #toastHost .toast 节点计数。
  - 折叠导航栏用真实拖拽（拖到 ≤176 松手触发 fold），不用 state 快捷方式。
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
        for rel in (("Microsoft", "Edge", "Application", "msedge.exe"),
                    ("Microsoft", "Edge Beta", "Application", "msedge.exe")):
            c = root.joinpath(*rel)
            if c.exists():
                return str(c)
    return shutil.which("msedge")


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class WS:
    def __init__(self, sock, initial):
        self.s = sock
        self.buf = initial
        self._id = 0

    def _need(self, n):
        while len(self.buf) < n:
            chunk = self.s.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _frame(self):
        b0, b1 = self._need(2)
        op = b0 & 0x0F
        ln = b1 & 0x7F
        if ln == 126:
            ln = struct.unpack(">H", self._need(2))[0]
        elif ln == 127:
            ln = struct.unpack(">Q", self._need(8))[0]
        if b1 & 0x80:
            mask = self._need(4)
            data = bytes(c ^ mask[i % 4] for i, c in enumerate(self._need(ln)))
        else:
            data = self._need(ln)
        return op, data

    def send(self, text, op=0x1):
        data = text.encode()
        h = bytearray([0x80 | op])
        n = len(data)
        if n < 126:
            h.append(0x80 | n)
        elif n < 65536:
            h.append(0x80 | 126)
            h += struct.pack(">H", n)
        else:
            h.append(0x80 | 127)
            h += struct.pack(">Q", n)
        mask = os.urandom(4)
        h += mask
        self.s.sendall(bytes(h) + bytes(c ^ mask[i % 4] for i, c in enumerate(data)))

    def call(self, method, params=None, timeout=90):
        self._id += 1
        mid = self._id
        self.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        self.s.settimeout(timeout)
        while True:
            op, data = self._frame()
            if op == 0x9:
                self.send(data.decode("utf-8", "replace"), op=0xA)
                continue
            if op == 0x8:
                raise RuntimeError("closed by peer")
            if op not in (0x1, 0x2):
                continue
            msg = json.loads(data.decode("utf-8", "replace"))
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


def connect(port, tries=60):
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
                    while b"\r\n\r\n" not in buf:
                        buf += s.recv(4096)
                    head, rest = buf.split(b"\r\n\r\n", 1)
                    if b"101" not in head.split(b"\r\n")[0]:
                        raise RuntimeError("handshake: " + head.decode("latin1")[:200])
                    return WS(s, rest)
        except Exception:
            pass
        time.sleep(0.4)
    raise RuntimeError("cannot attach to CDP")


def main():
    EDGE = find_edge()
    if not EDGE:
        print("FAIL 找不到 Edge")
        return 2
    port = free_port()
    profile = tempfile.mkdtemp(prefix="edge_ce_")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=1600,1000", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", PAGE],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = []
    try:
        ws = connect(port)

        def ev(js):
            r = ws.call("Runtime.evaluate", {
                "expression": js, "returnByValue": True, "awaitPromise": True}, timeout=30)
            if r.get("exceptionDetails"):
                raise RuntimeError("页面求值异常: "
                                   + json.dumps(r["exceptionDetails"])[:300])
            return r.get("result", {}).get("value")

        def wait_ready():
            for _ in range(40):
                if ev("!!document.querySelector('.rsh--nav') && !!document.querySelector('.rsh--ai')"):
                    return True
                time.sleep(0.25)
            return False

        def drag(handle_sel, steps, dx_total, sample_after=None):
            """真实指针拖拽。sample_after=N 时在第 N 步后采一次"中途事实"。
               返回 (mid_facts_or_None, final_error_or_None)。"""
            rect = ev(f"JSON.stringify(document.querySelector('{handle_sel}').getBoundingClientRect())")
            r = json.loads(rect)
            x, y = r["left"] + r["width"] / 2, r["top"] + r["height"] / 2
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mousePressed", "x": x, "y": y, "button": "left",
                     "buttons": 1, "clickCount": 1})
            mid = None
            sx, per = x, dx_total / steps
            for i in range(1, steps + 1):
                ws.call("Input.dispatchMouseEvent",
                        {"type": "mouseMoved", "x": sx + per * i, "y": y,
                         "button": "left", "buttons": 1})
                time.sleep(0.06)
                if sample_after is not None and i == sample_after:
                    time.sleep(0.15)   # 等 rAF flush 把跟随宽度写上
                    mid = ev(f"""(() => {{
                        const h = document.querySelector('{handle_sel}');
                        const anyH = document.querySelector('.rsh--nav');
                        const shell = document.getElementById('shell');
                        const host = h ? h.parentElement
                                   : (anyH ? anyH.parentElement : null);
                        const cs = host ? getComputedStyle(host) : null;
                        return {{ found: !!h, shellCls: shell.className,
                                  anyNavHandle: !!anyH, anyNavInShell: !!(anyH && shell.contains(anyH)),
                                  inline: host ? (host.style.width || '') : '',
                                  w: host && cs ? Math.round(host.getBoundingClientRect().width) : -1,
                                  cls: host ? host.className : '',
                                  mini: shell.classList.contains('mini') }};
                    }})()""")
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseReleased", "x": sx + dx_total, "y": y,
                     "button": "left", "buttons": 0})
            return mid, None

        def step(name, check):
            try:
                ok, note = check()
            except Exception as e:
                results.append((False, name, "用例异常（不连坐）: " + str(e)[:300]))
                return
            results.append((ok, name, note))

        if not wait_ready():
            print("FAIL 应用未就绪（找不到拖拽手柄）")
            return 2

        # ---------- T1 AI 折叠后手柄可见、可命中 ----------
        def t1():
            ev("""(async () => {
                const wait = async (fn, ms=3000) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                const btn = document.querySelector('#aiDock [data-act="toggle-dock"]');
                if(!btn) return false;
                btn.click();
                return wait(() => !!document.querySelector('.ai-dock.collapsed'));
            })()""")
            time.sleep(0.3)
            f = ev("""(() => {
                const h = document.querySelector('.ai-dock.collapsed .rsh--ai');
                if(!h) return { err: '折叠态找不到 .rsh--ai（被删了？）' };
                const cs = getComputedStyle(h);
                const rc = h.getBoundingClientRect();
                const hit = document.elementFromPoint(rc.left + rc.width/2, rc.top + rc.height/2);
                return { display: cs.display, w: Math.round(rc.width),
                         hitHandle: !!(hit && hit.closest('.rsh--ai')) };
            })()""")
            if not isinstance(f, dict) or f.get("err"):
                return False, "探针失败: %s" % json.dumps(f, ensure_ascii=False)
            ok = f["display"] != "none" and f["w"] > 0 and f["hitHandle"]
            return ok, "display=%(display)s 宽=%(w)spx 命中=%(hitHandle)s —— 折叠态手柄必须可见且可点" % f

        step("T1 AI折叠态｜边缘手柄可见且可命中（不再 display:none）", t1)

        # ---------- T2 AI 折叠态拖拽：连续跟手 + 越阈值展开 + dock-appear ----------
        def t2():
            mid, err = drag(".ai-dock.collapsed .rsh--ai", steps=12, dx_total=-324,
                            sample_after=3)   # -324*dir(-1)=+324 → raw 48+324=372 ≥340 展开
            if err:
                return False, err
            if not isinstance(mid, dict):
                return False, "中途采样失败: %r" % (mid,)
            mid_inline = float(mid["inline"].replace("px", "") or 0) if mid["inline"] else 0
            # 中途：3 步 × -27px → raw = 48 + 81 = 129 ±若干；必须已写 inline 且仍是 collapsed
            mid_ok = mid["cls"].find("collapsed") >= 0 and 100 <= mid_inline <= 160 \
                     if mid_inline else (mid["cls"].find("collapsed") >= 0 and mid["w"] > 48)
            time.sleep(0.5)
            f = ev("""(() => {
                const d = document.getElementById('aiDock');
                const p = d.querySelector('.dock-panel');
                return { collapsed: d.classList.contains('collapsed'),
                         panelVisible: !!p && getComputedStyle(p).display !== 'none',
                         animName: p ? getComputedStyle(p).animationName : '',
                         w: Math.round(d.getBoundingClientRect().width),
                         resizingLeftover: document.body.classList.contains('is-resizing') };
            })()""")
            ok = (mid_ok and not f["collapsed"] and f["panelVisible"]
                  and f["animName"] == "dockIn" and f["w"] >= 340 and not f["resizingLeftover"])
            return ok, ("中途 inline=%(inline)s cls=%(cls)s；终点 collapsed=%(collapsed)s "
                        "panel=%(panelVisible)s 动画=%(animName)s 宽=%(w)s 拖拽态残留=%(resizingLeftover)s"
                        ) % {**f, "inline": mid["inline"], "cls": mid["cls"][:60]}

        step("T2 AI折叠拖拽｜宽度连续跟手拉出，越 340px 阈值展开并播 dockIn", t2)

        # ---------- T3 导航折叠（真实拖到 ≤176 松手）→ 拖拽连续展开 + 文字渐显 ----------
        def t3():
            # 先拖折叠：nav 手柄在侧栏右缘，向左 -100 → raw 136 ≤ 176 → 松手折叠
            mid, err = drag(".rsh--nav", steps=6, dx_total=-100)
            if err:
                return False, err
            folded = ev("""(async () => {
                const wait = async (fn, ms=2500) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                return wait(() => document.getElementById('shell').classList.contains('mini'));
            })()""")
            if not folded:
                return False, "拖到 ≤176 松手后未进入 mini 折叠态"
            # ★ class 立即生效但宽度还在 236→64 过渡中；startW 取的是实际渲染宽度，
            #   不等动画收敛就会一步跨过展开阈值（第一版脚本踩的坑）。
            conv = ev("""(async () => {
                const wait = async (fn, ms=3000) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                return wait(() => document.getElementById('sidebar').getBoundingClientRect().width <= 66);
            })()""")
            if not conv:
                return False, "折叠宽度未收敛到 64px（过渡动画未完成或折叠失效）"
            # 再拖展开：+30×2 采样（raw≈124，必须 inline 跟手且仍是 mini），再拉到 ≥200 展开
            mid, err = drag(".shell.mini .rsh--nav", steps=10, dx_total=210, sample_after=2)
            if err:
                return False, err
            if not isinstance(mid, dict):
                return False, "中途采样失败: %r" % (mid,)
            mid_inline = float(mid["inline"].replace("px", "") or 0) if mid["inline"] else 0
            mid_ok = mid["mini"] and 90 <= mid_inline <= 170
            time.sleep(0.8)   # 等文字 120ms 延迟 + 过渡收敛
            f = ev("""(() => {
                const shell = document.getElementById('shell');
                const sb = document.getElementById('sidebar');
                const lbl = sb.querySelector('.nav-item .lbl');
                const cs = lbl ? getComputedStyle(lbl) : null;
                return { mini: shell.classList.contains('mini'),
                         w: Math.round(sb.getBoundingClientRect().width),
                         lblOpacity: cs ? cs.opacity : '',
                         lblDelay: cs ? cs.transitionDelay : '',
                         inlineLeft: sb.style.width || '' };
            })()""")
            ok = (mid_ok and not f["mini"] and 200 <= f["w"] <= 300
                  and f["lblOpacity"] == "1" and f["lblDelay"].find("0.12") >= 0)
            return ok, ("中途 inline=%(inline)s mini=%(mini)s；终点 mini=%(mini2)s 宽=%(w)s "
                        "文字opacity=%(lblOpacity)s 文字延迟=%(lblDelay)s"
                        ) % {**f, "mini": mid["mini"], "inline": mid["inline"], "mini2": f["mini"]}

        step("T3 导航折叠拖拽｜宽度连续跟手，越阈值摘 mini，文字 120ms 延迟渐显", t3)

        # ---------- T5 到阈值：脉冲提示 + 停顿 + 重锚续跟（2026-09-14 定稿，替代磁吸） ----------
        # nav expandAt=200。拖到 214 越过阈值 → ①立即展开（mini 摘除）②边缘脉冲（.crest）
        # ③停顿期宽度钉在 200（指针继续动也不跟）④停顿结束重锚基准，继续 1:1 跟手（无跳变）。
        def t5():
            # 前置：折叠（拖到 ≤176 松手）并等宽度收敛
            drag(".rsh--nav", steps=6, dx_total=-100)
            folded = ev("""(async () => {
                const wait = async (fn, ms=2500) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                const ok = await wait(() => document.getElementById('shell').classList.contains('mini'));
                await wait(() => document.getElementById('sidebar').getBoundingClientRect().width <= 66);
                return ok;
            })()""")
            if not folded:
                return False, "前置折叠失败"
            # 真实指针拖拽：8 步 ×18.75 → raw=214 越过阈值；再继续动指针（停顿期应钉住）
            rect = ev("JSON.stringify(document.querySelector('.shell.mini .rsh--nav').getBoundingClientRect())")
            r = json.loads(rect)
            x, y = r["left"] + r["width"] / 2, r["top"] + r["height"] / 2
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mousePressed", "x": x, "y": y, "button": "left",
                     "buttons": 1, "clickCount": 1})
            for i in range(1, 9):
                ws.call("Input.dispatchMouseEvent",
                        {"type": "mouseMoved", "x": x + 18.75 * i, "y": y,
                         "button": "left", "buttons": 1})
                time.sleep(0.06)
            time.sleep(0.1)   # 越阈后 ~100ms：应在停顿期内
            mid = ev("""(() => {
                const h = document.querySelector('.rsh--nav');
                return { mini: document.getElementById('shell').classList.contains('mini'),
                         w: Math.round(document.getElementById('sidebar').getBoundingClientRect().width),
                         crest: h.classList.contains('crest') };
            })()""")
            # 指针继续动（停顿期内 + 跨过停顿点），看宽度是否先钉住、后恢复跟手
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": x + 175, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.3)   # 停顿（260ms）已过，重锚已发生
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": x + 215, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.15)
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": x + 245, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.1)
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": x + 275, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.2)
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseReleased", "x": x + 275, "y": y, "button": "left", "buttons": 0})
            time.sleep(0.3)
            fin = ev("""(() => ({
                mini: document.getElementById('shell').classList.contains('mini'),
                w: Math.round(document.getElementById('sidebar').getBoundingClientRect().width),
                inline: document.getElementById('sidebar').style.width || '',
                leftover: document.body.classList.contains('is-resizing') }))()""")
            ok = (mid["mini"] is False and abs(mid["w"] - 200) <= 6 and mid["crest"]
                  and fin["mini"] is False and fin["w"] >= 240
                  and fin["inline"] == "" and not fin["leftover"])
            return ok, ("越阈后100ms：mini=%(mini1)s 宽=%(w1)s 脉冲=%(crest)s（停顿期钉在200）｜"
                        "停顿结束继续拖后：宽=%(w2)s inline='%(inline)s' 残留=%(left)s"
                        ) % {"mini1": mid["mini"], "w1": mid["w"], "crest": mid["crest"],
                             "w2": fin["w"], "inline": fin["inline"], "left": fin["leftover"]}

        step("T5 到阈值｜边缘脉冲提示 + 短暂停顿，展开速率跟随拖拽（停顿后重锚续跟）", t5)

        # ---------- T7 惯性滑行：折叠态外拉未到阈值就松手 → 从当前速度递减滑到阈值展开 ----------
        # nav expandAt=200，foldW=64。拖到 raw=154（<200）松手：
        # ① 松手瞬间不得直接展开也不得折回 —— 应从 ~154 以 ease-out 滑向 200（中途采样 mini 仍 True、宽在中间值）；
        # ② 到位后摘壳展开（mini=False、宽=200）、边缘脉冲（crest）。
        # 若实现是"松手即折回"，fin 必红；若是"松手直接跳展开态"，mid 必红。
        def t7():
            # 前置：折叠（拖到 ≤176 松手）并等宽度收敛
            drag(".rsh--nav", steps=6, dx_total=-100)
            folded = ev("""(async () => {
                const wait = async (fn, ms=2500) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                const ok = await wait(() => document.getElementById('shell').classList.contains('mini'));
                await wait(() => document.getElementById('sidebar').getBoundingClientRect().width <= 66);
                return ok;
            })()""")
            if not folded:
                return False, "前置折叠失败"
            rect = ev("JSON.stringify(document.querySelector('.shell.mini .rsh--nav').getBoundingClientRect())")
            r = json.loads(rect)
            x, y = r["left"] + r["width"] / 2, r["top"] + r["height"] / 2
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mousePressed", "x": x, "y": y, "button": "left",
                     "buttons": 1, "clickCount": 1})
            for i in range(1, 7):   # 6 步 ×15px → raw=154（未到 200），~60ms/步 → v≈0.25px/ms
                ws.call("Input.dispatchMouseEvent",
                        {"type": "mouseMoved", "x": x + 15 * i, "y": y,
                         "button": "left", "buttons": 1})
                time.sleep(0.06)
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseReleased", "x": x + 90, "y": y, "button": "left", "buttons": 0})
            time.sleep(0.08)   # 滑行中（dur≈200ms）
            mid = ev("""(() => ({
                mini: document.getElementById('shell').classList.contains('mini'),
                w: Math.round(document.getElementById('sidebar').getBoundingClientRect().width) }))()""")
            time.sleep(0.55)   # 滑行到位 + 摘壳完成
            fin = ev("""(() => {
                const h = document.querySelector('.rsh--nav');
                return { mini: document.getElementById('shell').classList.contains('mini'),
                         w: Math.round(document.getElementById('sidebar').getBoundingClientRect().width),
                         inline: document.getElementById('sidebar').style.width || '',
                         crest: h.classList.contains('crest'),
                         leftover: document.body.classList.contains('is-resizing') };
            })()""")
            ok = (mid["mini"] is True and 155 <= mid["w"] <= 194
                  and fin["mini"] is False and 194 <= fin["w"] <= 206
                  and fin["inline"] == "" and not fin["leftover"] and fin["crest"])
            return ok, ("松手后80ms：mini=%(mini1)s 宽=%(w1)s（滑行中，未到阈值未展开）｜"
                        "≈0.6s 后：mini=%(mini2)s 宽=%(w2)s 脉冲=%(crest)s 残留=%(left)s"
                        ) % {"mini1": mid["mini"], "w1": mid["w"], "mini2": fin["mini"],
                             "w2": fin["w"], "crest": fin["crest"], "left": fin["leftover"]}

        step("T7 惯性滑行｜未到阈值松手：从当前速度递减滑到展开态最小宽度，到位摘壳展开", t7)

        # ---------- T6 蓄力中间态：450ms 时必须还在"蓄力"而未折叠（560ms 延长的判据） ----------
        def t6():
            # 前置：确保展开态（T5 正常会留下展开态；被连坐时自行拉到展开）
            w0 = ev("Math.round(document.getElementById('sidebar').getBoundingClientRect().width)")
            if w0 < 150:
                drag(".shell.mini .rsh--nav", steps=8, dx_total=210)
                time.sleep(0.5)
                w0 = ev("Math.round(document.getElementById('sidebar').getBoundingClientRect().width)")
            # 前置：导航折叠（拖到 ≤176 松手）并等宽度收敛
            drag(".rsh--nav", steps=6, dx_total=-100)
            folded = ev("""(async () => {
                const wait = async (fn, ms=2500) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                const ok = await wait(() => document.getElementById('shell').classList.contains('mini'));
                await wait(() => document.getElementById('sidebar').getBoundingClientRect().width <= 66);
                return ok;
            })()""")
            if not folded:
                return False, "前置折叠失败"
            drag(".shell.mini .rsh--nav", steps=8, dx_total=210)   # 拉到展开（越过磁吸点）
            time.sleep(0.5)
            # 拖到最小值并停住，观察蓄力时序。dx 动态取：raw 必须 ≤ 160（arm 触发区）
            w1 = ev("Math.round(document.getElementById('sidebar').getBoundingClientRect().width)")
            dx = min(-96, 160 - w1 - 8)
            rect = ev("JSON.stringify(document.querySelector('.rsh--nav').getBoundingClientRect())")
            r = json.loads(rect)
            x, y = r["left"] + r["width"] / 2, r["top"] + r["height"] / 2
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mousePressed", "x": x, "y": y, "button": "left",
                     "buttons": 1, "clickCount": 1})
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseMoved", "x": x + dx, "y": y, "button": "left", "buttons": 1})
            time.sleep(0.45)   # 450ms：旧 dwell(320) 此刻已折叠；新 dwell(560) 必须仍在蓄力
            mid = ev("""(() => {
                const h = document.querySelector('.rsh--nav');
                return { arming: h.classList.contains('arming'),
                         mini: document.getElementById('shell').classList.contains('mini') };
            })()""")
            time.sleep(0.55)   # 累计 ≈1s > 560ms → 必须已自动折叠
            fin = ev("""(() => ({ mini: document.getElementById('shell').classList.contains('mini') }))()""")
            ws.call("Input.dispatchMouseEvent",
                    {"type": "mouseReleased", "x": x + dx, "y": y, "button": "left", "buttons": 0})
            time.sleep(0.2)
            after = ev("""(() => ({ stillResizing: document.body.classList.contains('is-resizing') }))()""")
            ev("""(async () => {   // 收尾：拖回来展开，别影响后续用例
                const h = document.querySelector('.rsh--nav');
                const wait = async (fn, ms=2500) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                await wait(() => document.getElementById('sidebar').getBoundingClientRect().width <= 66);
                return true;
            })()""")
            drag(".shell.mini .rsh--nav", steps=8, dx_total=160)
            ok = mid["arming"] and not mid["mini"] and fin["mini"] and not after["stillResizing"]
            return ok, ("停 450ms：蓄力=%(arming)s 未折叠=%(notmini)s；≈1s：已折叠=%(mini2)s；"
                        "松手后拖拽态残留=%(left)s") % {"arming": mid["arming"],
                                                        "notmini": not mid["mini"],
                                                        "mini2": fin["mini"],
                                                        "left": after["stillResizing"]}

        step("T6 蓄力中间态｜dwell 560ms：450ms 仍在蓄力未折叠，之后才自动折叠", t6)

        # ---------- T4 设置页切状态不再弹 toast（双证据）----------
        def t4():
            ev("""(async () => {
                const wait = async (fn, ms=3000) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                location.hash = '#/settings';
                return wait(() => !!document.querySelector('[data-act="set-motion"]'));
            })()""")
            ev("""(() => {
                window.__toastCalled = false;
                const orig = window.toast;
                window.toast = function(){ window.__toastCalled = true; return orig.apply(this, arguments); };
            })()""")
            ev("""document.querySelector('[data-act="set-motion"] button[data-v="off"]').click()""")
            time.sleep(0.5)
            f = ev("""(() => ({
                called: window.__toastCalled === true,
                dom: document.querySelectorAll('#toastHost .toast').length,
                motion: state.motion,
                on: [...document.querySelectorAll('[data-act="set-motion"] button')]
                        .map(b => b.dataset.v + ':' + b.classList.contains('on')).join(',')
            }))()""")
            ev("""(async () => {
                const wait = async (fn, ms=3000) => { const t0=Date.now();
                    while(Date.now()-t0<ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,40)); } return false; };
                location.hash = '#/plugins';
                return wait(() => !!document.querySelector('[data-act="plugin-sw"]'));
            })()""")
            ev("""(() => {
                window.__toastCalled2 = false;
                const orig = window.toast;
                window.toast = function(){ window.__toastCalled2 = true; return orig.apply(this, arguments); };
            })()""")
            ev("""document.querySelector('[data-act="plugin-sw"]').click()""")
            time.sleep(0.5)
            f2 = ev("""(() => ({
                called: window.__toastCalled2 === true,
                dom: document.querySelectorAll('#toastHost .toast').length,
                on: document.querySelector('[data-act="plugin-sw"]').classList.contains('on')
            }))()""")
            ok = (not f["called"] and f["dom"] == 0 and f["motion"] == "off"
                  and not f2["called"] and f2["dom"] == 0)
            return ok, ("set-motion: 拦截=%(called)s DOM=%(dom)s 档位=%(motion)s 选中态[%(on)s]｜"
                        "plugin-sw: 拦截=%(called2)s DOM=%(dom2)s 开关on=%(on2)s"
                        ) % {**f, "called2": f2["called"], "dom2": f2["dom"], "on2": f2["on"]}

        step("T4 设置页切状态｜只留按钮选中态动画，toast（函数拦截 + DOM）均为零", t4)

    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)

    print("=" * 78)
    fails = 0
    for ok, name, note in results:
        print(("PASS " if ok else "FAIL ") + name)
        print("      " + note)
        if not ok:
            fails += 1
    print("=" * 78)
    print("TOTAL %d passed, %d failed" % (len(results) - fails, fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
