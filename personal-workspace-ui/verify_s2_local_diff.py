#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
S2 局部 diff 的端到端验收：Edge 无头 + CDP 真实点击。

为什么需要它：S2 的主张是"局部更新不整页重绘"。静态 grep 只能证明"代码里写的是 patchSettings"，
证明不了"点下去真的没整页重绘"。唯一诚实的判据是——给侧栏/组件区/AI 侧栏打上标记，
点一下，看这些标记还在不在同一个节点上。

★ 区分度（最容易骗过自己的一步）：
  先跑一次"旧路径"（直接调 render()）确认标记会被抹掉 —— 否则"标记还在"什么都证明不了。
  T1 是控制组，T2 起才是被测组。
"""
import base64, json, os, shutil, socket, struct, subprocess, sys, tempfile, time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
PAGE = (HERE / "index.html").as_uri()
EDGE = None


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
            if op == 0x9:                      # ping → 必须回 pong
                self.send(data.decode("utf-8", "replace"), op=0xA)
                continue
            if op == 0x8:
                raise RuntimeError("closed by peer")
            if op not in (0x1, 0x2):
                continue
            msg = json.loads(data.decode("utf-8", "replace"))
            if msg.get("id") != mid:
                continue                        # 事件帧，丢掉
            if "error" in msg:
                raise RuntimeError(json.dumps(msg["error"])[:400])
            return msg.get("result", {})


def connect(port, want_url, tries=60):
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
    profile = tempfile.mkdtemp(prefix="edge_e2e_")
    url = PAGE + "#/settings"
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         "--remote-allow-origins=*", "--allow-file-access-from-files",
         "--window-size=1600,1000", f"--remote-debugging-port={port}",
         f"--user-data-dir={profile}", url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    results = []
    try:
        ws = connect(port, url)
        ws.call("Runtime.enable")
        # 等应用首帧就绪（前端有 render 前的初始化）
        for _ in range(40):
            v = ev(ws, "!!document.querySelector('.set-layout')")
            if v:
                break
            time.sleep(0.25)

        def step(name, js, check):
            """js 返回事实字典；check(facts) 返回 (ok, 说明)。
               单点失败不连坐：探针自身抛异常也只记一条 FAIL，后续用例照跑。"""
            try:
                facts = ev(ws, js)
            except Exception as e:
                results.append((False, name, "探针异常（不连坐，继续后续用例）: " + str(e)[:300]))
                return
            if isinstance(facts, dict) and facts.get("err"):
                results.append((False, name, "探针报错: " + str(facts["err"])))
                return
            try:
                ok, note = check(facts)
            except Exception as e:
                results.append((False, name, "判据自身异常（事实=%s）: %s"
                                % (json.dumps(facts, ensure_ascii=False)[:200], str(e)[:200])))
                return
            results.append((ok, name, note + " | " + json.dumps(facts, ensure_ascii=False)[:400]))

        # ---------- T1 控制组：先证明探针能看见"整页重绘" ----------
        # 注意标记的是"子节点"而不是容器本身：paint() 重写的是 #sidebar 的 innerHTML，
        # 容器元素永远活着 —— 标在容器上就永远测不到重绘（这是本脚本第一版踩的坑）。
        step("T1 控制组｜走旧路径 render() 时，子节点标记必须被抹掉", """
        (async () => {
          const waitUntil = async (fn, ms=2500) => {   // 等到"期望值收敛"，而不是固定 sleep
            const t0 = Date.now();
            while(Date.now()-t0 < ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,30)); }
            return false;
          };
          const sb = document.getElementById('sidebar');
          const kid0 = sb.firstElementChild;
          if(!kid0) return { err:'侧栏没有子节点' };
          kid0.setAttribute('data-probe','keep');
          const marked = sb.firstElementChild.getAttribute('data-probe');
          render();                                  // 旧路径：整页重绘
          await waitUntil(() => {
            const k = document.getElementById('sidebar').firstElementChild;
            return !k || k.getAttribute('data-probe') === null;
          });
          const kid1 = document.getElementById('sidebar').firstElementChild;
          return { marked, survived: kid1 ? kid1.getAttribute('data-probe') : null,
                   sameNode: kid0 === kid1 };
        })()
        """, lambda f: (f["marked"] == "keep" and f["survived"] is None and f["sameNode"] is False,
                        "marked=%r survived=%r sameNode=%r（survived 必须为 None、sameNode 必须 false，"
                        "否则探针无区分度）" % (f["marked"], f["survived"], f["sameNode"])))

        # ---------- T2 设置页切分类：只有 .set-body 换内容 ----------
        step("T2 设置页切分类｜四个容器都不重建；内容壳留下、内容子节点被换掉", """
        (async () => {
          const waitUntil = async (fn, ms=2500) => {
            const t0 = Date.now();
            while(Date.now()-t0 < ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,30)); }
            return false;
          };
          const mk = id => { const c = document.getElementById(id).firstElementChild; if(c) c.setAttribute('data-probe','keep'); };
          const kid = id => { const c = document.getElementById(id).firstElementChild; return c ? c.getAttribute('data-probe') : null; };
          ['sidebar','widgetCol','aiDock'].forEach(mk);
          const view = document.getElementById('view');
          const body = view.querySelector('.set-body');
          body.setAttribute('data-probe','keepbody');
          const bodyKid0 = body.firstElementChild;
          if(!bodyKid0) return { err:'内容区没有子节点' };
          bodyKid0.setAttribute('data-probe','keepbodykid');
          const beforeText = body.textContent.replace(/\\s+/g,'');
          view.scrollTop = 140;
          const beforeScroll = view.scrollTop;
          const btn = view.querySelector('[data-act="set-cat"][data-v="plugins"]');
          if(!btn) return { err: '找不到「插件」分类项' };
          btn.click();
          await waitUntil(() => {
            const a = document.querySelector('.subnav .nav-item.active');
            const b = document.querySelector('.set-body');
            return a && a.getAttribute('data-v') === 'plugins' && b && b.textContent.indexOf('开发者模式') >= 0;
          });
          const v2 = document.getElementById('view');
          const body2 = v2.querySelector('.set-body');
          const bodyKid1 = body2.firstElementChild;
          const act = document.querySelector('.subnav .nav-item.active');
          return {
            sidebarKid: kid('sidebar'), widgetKid: kid('widgetCol'), aiKid: kid('aiDock'),
            bodyShell: body2.getAttribute('data-probe'),
            bodyKidMarker: bodyKid1 ? bodyKid1.getAttribute('data-probe') : null,
            bodyKidSameNode: bodyKid0 === bodyKid1,
            activeCat: act ? act.getAttribute('data-v') : null,
            bodyTextChanged: body2.textContent.replace(/\\s+/g,'') !== beforeText,
            bodyHasDevToggle: body2.textContent.indexOf('开发者模式') >= 0,
            hash: location.hash,
            beforeScroll: beforeScroll,
            afterScroll: v2.scrollTop
          };
        })()
        """, lambda f: (f["sidebarKid"] == "keep" and f["widgetKid"] == "keep" and f["aiKid"] == "keep"
                        and f["bodyShell"] == "keepbody"
                        and f["bodyKidMarker"] is None and f["bodyKidSameNode"] is False
                        and f["activeCat"] == "plugins"
                        and f["bodyTextChanged"] and f["bodyHasDevToggle"] and f["hash"] == "#/settings",
                        "侧栏/组件/AI 的子节点存活 + 内容壳存活 + 内容子节点确被换掉 + activeCat 正确"))

        # ---------- T3 开发者模式：导航项增减，但仍不整页重绘 ----------
        step("T3 开发者模式｜导航要新增「开发者」项，侧栏仍不重建", """
        (async () => {
          const waitUntil = async (fn, ms=2500) => {
            const t0 = Date.now();
            while(Date.now()-t0 < ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,30)); }
            return false;
          };
          const sb = document.getElementById('sidebar');
          sb.firstElementChild.setAttribute('data-probe','keep');
          const sw = document.querySelector('[data-act="toggle-dev"]');
          if(!sw) return { err:'找不到开发者模式开关' };
          sw.click();
          await waitUntil(() => {
            const d = document.querySelector('.subnav .nav-item[data-v="dev"]');
            const a = document.querySelector('.subnav .nav-item.active');
            return !!d && a && a.getAttribute('data-v') === 'dev';
          });
          const navItems = [...document.querySelectorAll('.subnav .nav-item')].map(b=>b.getAttribute('data-v'));
          const act = document.querySelector('.subnav .nav-item.active');
          const body = document.querySelector('.set-body');
          const k = document.getElementById('sidebar').firstElementChild;
          return {
            sidebarKid: k ? k.getAttribute('data-probe') : null,
            navItems: navItems,
            activeCat: act ? act.getAttribute('data-v') : null,
            hasDevNav: navItems.indexOf('dev') >= 0,
            bodySaysDev: body.textContent.indexOf('开发者模式') >= 0
          };
        })()
        """, lambda f: (f["sidebarKid"] == "keep" and f["hasDevNav"] and f["activeCat"] == "dev"
                        and f["bodySaysDev"],
                        "侧栏子节点存活 + 导航出现 dev + 已切到 dev 分类"))

        # ---------- T4 set-motion：这正是委派层 d.v 恒为 undefined 的回归点 ----------
        step("T4 动效档位｜点「减弱」必须真的切到 reduced（委派层取值回归）", """
        (async () => {
          const waitUntil = async (fn, ms=2500) => {
            const t0 = Date.now();
            while(Date.now()-t0 < ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,30)); }
            return false;
          };
          document.getElementById('sidebar').firstElementChild.setAttribute('data-probe','keep');
          const back = document.querySelector('[data-act="set-cat"][data-v="appearance"]');
          if(back) back.click();
          await waitUntil(() => {
            const a = document.querySelector('.subnav .nav-item.active');
            return a && a.getAttribute('data-v') === 'appearance';
          });
          const btn = document.querySelector('[data-act="set-motion"] button[data-v="reduced"]');
          if(!btn) return { err:'找不到「减弱」按钮' };
          btn.click();
          await waitUntil(() => document.documentElement.getAttribute('data-motion') === 'reduced');
          const seg = [...document.querySelectorAll('[data-act="set-motion"] button')];
          const k = document.getElementById('sidebar').firstElementChild;
          return {
            sidebarKid: k ? k.getAttribute('data-probe') : null,
            motionAttr: document.documentElement.getAttribute('data-motion'),
            stateMotion: (typeof state !== 'undefined') ? state.motion : 'n/a',
            onStates: seg.map(b=>b.getAttribute('data-v') + ':' + b.classList.contains('on'))
          };
        })()
        """, lambda f: (f["motionAttr"] == "reduced" and f["stateMotion"] == "reduced"
                        and f["onStates"] == ["standard:false", "reduced:true", "off:false"]
                        and f["sidebarKid"] == "keep",
                        "data-motion/state.motion 都要是 reduced，且只有「减弱」处于 on"))

        # ---------- T5 set-layout：纯本地状态，不该整页重绘 ----------
        step("T5 首页布局｜点「固定」只改分段控件与状态", """
        (async () => {
          const waitUntil = async (fn, ms=2500) => {
            const t0 = Date.now();
            while(Date.now()-t0 < ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,30)); }
            return false;
          };
          document.getElementById('sidebar').firstElementChild.setAttribute('data-probe','keep');
          const btn = document.querySelector('[data-act="set-layout"] button[data-v="fixed"]');
          if(!btn) return { err:'找不到「固定」按钮' };
          btn.click();
          await waitUntil(() => {
            const b = document.querySelector('[data-act="set-layout"] button[data-v="fixed"]');
            return b && b.classList.contains('on');
          });
          const seg = [...document.querySelectorAll('[data-act="set-layout"] button')];
          const k = document.getElementById('sidebar').firstElementChild;
          return {
            sidebarKid: k ? k.getAttribute('data-probe') : null,
            layoutMode: (typeof state !== 'undefined') ? state.layoutMode : 'n/a',
            onStates: seg.map(b=>b.getAttribute('data-v') + ':' + b.classList.contains('on'))
          };
        })()
        """, lambda f: (f["layoutMode"] == "fixed" and f["onStates"] == ["auto:false", "fixed:true"]
                        and f["sidebarKid"] == "keep",
                        "state.layoutMode=fixed，只有「固定」处于 on，侧栏子节点存活"))

        # ---------- T6 /plugins 页：开关只改数字与开关自己 ----------
        step("T6 插件页｜开关只刷新页头计数，不整页重绘", """
        (async () => {
          const waitUntil = async (fn, ms=3000) => {
            const t0 = Date.now();
            while(Date.now()-t0 < ms){ try{ if(fn()) return true; }catch(e){} await new Promise(r=>setTimeout(r,30)); }
            return false;
          };
          const goB = document.querySelector('[data-act="go"][data-r="plugins"]');
          if(!goB) return { err:'导航里找不到「插件」' };
          goB.click();
          await waitUntil(() => location.hash === '#/plugins' && !!document.getElementById('plugCount'));
          const cnt0 = (document.getElementById('plugCount')||{}).textContent;
          if(cnt0 === undefined) return { err:'插件页没渲染出 #plugCount' };
          document.getElementById('sidebar').firstElementChild.setAttribute('data-probe','keep');
          const sw0 = document.querySelector('[data-act="plugin-sw"][data-v="message"]');
          if(!sw0) return { err:'找不到「消息」插件的开关' };
          const on0 = sw0.classList.contains('on');
          sw0.click();
          await waitUntil(() => {
            const c = document.getElementById('plugCount');
            return c && c.textContent !== cnt0;
          });
          const cnt1 = (document.getElementById('plugCount')||{}).textContent;
          const sw1 = document.querySelector('[data-act="plugin-sw"][data-v="message"]');
          const k = document.getElementById('sidebar').firstElementChild;
          return {
            countBefore: cnt0, countAfter: cnt1,
            countChanged: cnt0 !== cnt1,
            switchOnBefore: on0, switchOnAfter: sw1 ? sw1.classList.contains('on') : null,
            sameSwitchNode: sw1 === sw0,
            sidebarKid: k ? k.getAttribute('data-probe') : null,
            hash: location.hash
          };
        })()
        """, lambda f: (f["countChanged"] and f["switchOnAfter"] is not None
                        and f["switchOnAfter"] != f["switchOnBefore"]
                        and f["sameSwitchNode"] is True          # 走 render() 的话这个节点会被换掉
                        and f["sidebarKid"] == "keep" and f["hash"] == "#/plugins",
                        "页头计数变了 + 开关翻转 + 开关仍是同一个 DOM 节点 + 侧栏子节点存活"))
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        shutil.rmtree(profile, ignore_errors=True)

    npass = sum(1 for r in results if r[0])
    print("=" * 78)
    for ok, name, note in results:
        print(("PASS " if ok else "FAIL ") + name)
        print("      " + note)
    print("=" * 78)
    print("TOTAL %d passed, %d failed" % (npass, len(results) - npass))
    return 0 if npass == len(results) else 1


def ev(ws, expr, timeout=90):
    """Runtime.evaluate + 上下文被销毁时重试（file:// 首帧偶发整体重载）"""
    last = None
    for attempt in range(6):
        try:
            r = ws.call("Runtime.evaluate", {"expression": expr, "awaitPromise": True,
                                             "returnByValue": True}, timeout=timeout)
            if "exceptionDetails" in r:
                raise RuntimeError("JS 异常: " + json.dumps(r["exceptionDetails"], ensure_ascii=False)[:400])
            return r.get("result", {}).get("value")
        except RuntimeError as e:
            last = e
            if "Execution context was destroyed" in str(e) and attempt < 5:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise
    raise last


if __name__ == "__main__":
    sys.exit(main())
