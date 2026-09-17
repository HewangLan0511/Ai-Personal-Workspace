#!/usr/bin/env python3
"""TECH-01 验收 · Edge headless + CDP 实测 Test 1~8。

方法：`ui/dist` 用本地静态服务（SPA 回退）承载，Edge `--headless=new`
+ remote-debugging-port + 标准库 WebSocket 客户端驱动真实页面；
所有断言都在"功能坏了会变红"的方向上构造（有区分度断言）。

诚实声明（覆盖边界）：
- 驱动的是**真实构建产物**（vite build，与安装包同一份前端代码）；
- 交互为 CDP 合成事件（el.click / dispatchEvent），非真人鼠标；
- core 后端不在场，页面数据通道走降级/空态 —— 本脚本验证的是
  Motion Runtime 与 S2 行为，不验证业务数据链路。

Test 1  S2：过滤/重排不 remount、scrollTop 不变
Test 2  Conflict Guard：Hover→Drag 让位、Press→Drag 让位
Test 3  Workspace Cinema：Interactive Gate ≈240ms
Test 4  Cinema Resize：取消空间动画→重算布局→快速收敛（< 560ms）
Test 5  A→B→C→D 连续导航：latest-wins，只保留最终 D
Test 6  Motion=Reduced：intensity 降、duration 不变（解耦证据）
Test 7  Motion=Off：装饰动画消失，必要反馈豁免仍在
Test 8  ?motion=novt：VT 通道关闭走 fallback；无参数时 VT 正常启用
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "ui" / "dist"
PY = sys.executable

# ---------------------------------------------------------------- WebSocket


class CDPWebSocket:
    """标准库手搓的极简 WebSocket 客户端（见 edge-headless-ui-verify skill）。"""

    def __init__(self, url: str, timeout: float = 30.0):
        assert url.startswith("ws://"), url
        rest = url[5:]
        hostport, path = rest.split("/", 1)
        path = "/" + path
        host, port = hostport.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {hostport}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("websocket handshake EOF")
            resp += chunk
        status = resp.split(b"\r\n", 1)[0]
        assert b"101" in status, status
        self._id = 0
        self._lock = threading.Lock()

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._lock:
            self.sock.sendall(header + mask + masked)

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("websocket EOF")
            buf += chunk
        return buf

    def _recv_frame(self) -> tuple[int, bytes]:
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        length = b2 & 0x7F
        if length == 126:
            (length,) = struct.unpack(">H", self._recv_exact(2))
        elif length == 127:
            (length,) = struct.unpack(">Q", self._recv_exact(8))
        payload = self._recv_exact(length) if length else b""
        return opcode, payload

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self._id += 1
        mid = self._id
        msg = json.dumps({"id": mid, "method": method, "params": params or {}})
        self._send_frame(0x1, msg.encode())
        self.sock.settimeout(timeout)
        deadline = time.time() + timeout
        while True:
            if time.time() > deadline:
                raise TimeoutError(f"CDP {method} 超时 {timeout}s")
            opcode, payload = self._recv_frame()
            if opcode == 0x9:  # ping → pong
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise ConnectionError("websocket closed by peer")
            if opcode != 0x1:
                continue
            data = json.loads(payload.decode())
            if data.get("id") != mid:
                continue  # 事件帧丢弃
            if "error" in data:
                raise RuntimeError(f"CDP {method}: {data['error']}")
            return data.get("result", {})

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


# ---------------------------------------------------------------- 基建


def find_edge() -> str:
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        for rel in (
            ("Microsoft", "Edge", "Application", "msedge.exe"),
            ("Microsoft", "Edge Beta", "Application", "msedge.exe"),
        ):
            cand = Path(base).joinpath(*rel)
            if cand.exists():
                return str(cand)
    found = __import__("shutil").which("msedge")
    if found:
        return found
    raise RuntimeError("找不到 msedge.exe")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """ui/dist 静态服务 + SPA 回退（history 路由深链全部回 index.html）。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST), **kwargs)

    def translate_path(self, path: str) -> str:
        real = super().translate_path(path)
        if not os.path.exists(real) or os.path.isdir(real) and not os.path.exists(os.path.join(real, "index.html")):
            return str(DIST / "index.html")
        return real

    def log_message(self, *args):  # 静音
        pass


def start_server() -> tuple[int, http.server.ThreadingHTTPServer]:
    port = free_port()
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), SPAHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port, srv


# ---------------------------------------------------------------- 断言辅助

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def ev(ws: CDPWebSocket, js: str, timeout: float = 30.0) -> dict:
    """Runtime.evaluate + Execution context destroyed 重试（skill 坑 1）。"""
    last: Exception | None = None
    for attempt in range(6):
        try:
            res = ws.call(
                "Runtime.evaluate",
                {
                    "expression": js,
                    "awaitPromise": True,
                    "returnByValue": True,
                },
                timeout=timeout,
            )
            exc = res.get("exceptionDetails")
            if exc:
                raise RuntimeError(f"页面内异常: {json.dumps(exc, ensure_ascii=False)[:400]}")
            return res.get("result", {}).get("value")
        except RuntimeError:
            raise
        except (TimeoutError, ConnectionError, OSError) as e:  # context destroyed 等
            last = e
            time.sleep(0.4 * (attempt + 1))
    raise last if last else RuntimeError("evaluate 失败")


def wait_for(ws: CDPWebSocket, js: str, timeout: float = 25.0, interval: float = 0.3) -> object:
    """轮询直到 js 为真值（skill 坑 2/6：不假设 DOM/状态已就绪）。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            last = ev(ws, js, timeout=10)
            if last:
                return last
        except (RuntimeError, TimeoutError):
            pass
        time.sleep(interval)
    raise TimeoutError(f"等待超时: {js[:120]} (last={last!r})")


VT_SPY = """
(() => {
  window.__vtSpy = { calls: 0 };
  const orig = document.startViewTransition && document.startViewTransition.bind(document);
  if (orig) {
    document.startViewTransition = (...a) => { window.__vtSpy.calls += 1; return orig(...a); };
  }
})();
"""


# ---------------------------------------------------------------- 测试


def test_conflict(ws: CDPWebSocket) -> None:
    r = ev(ws, """
(() => {
  const M = window.__pwMotion;
  const el = document.createElement('div');
  document.body.appendChild(el);
  const events = [];
  // 场景 A：Hover 在飞 → Drag 声明 → Hover 立即让位
  const hover = M.claim(el, 'hover', () => events.push('hover-superseded'));
  const hoverWasPrimary = hover.isPrimary;
  const drag = M.claim(el, 'drag', () => events.push('drag-superseded'));
  const dragPrimary = drag.isPrimary;
  const hoverDemoted = !hover.isPrimary && events.includes('hover-superseded');
  const dragNotSuperseded = !events.includes('drag-superseded');
  // 场景 B：Press 在飞 → Drag 声明 → Press 快速结束并进入 Drag（§十一）
  const press = M.claim(document.body, 'local', () => events.push('local-superseded'));
  const pressWasPrimary = press.isPrimary;
  const drag2 = M.claim(document.body, 'drag', () => events.push('drag2-superseded'));
  const pressEndedForDrag = !press.isPrimary && events.includes('local-superseded');
  // 场景 C：Drag 在飞 → 新的低优先级声明不成为 Primary（且不算"被让位"）
  const lateHover = M.claim(el, 'hover', () => events.push('late-hover-superseded'));
  const lateHoverNotPrimary = !lateHover.isPrimary;
  const noFalseSupersede = !events.includes('late-hover-superseded');
  hover.release(); drag.release(); press.release(); drag2.release(); lateHover.release();
  el.remove();
  return { hoverWasPrimary, dragPrimary, hoverDemoted, dragNotSuperseded,
           pressWasPrimary, pressEndedForDrag, lateHoverNotPrimary, noFalseSupersede };
})()
""", timeout=10)
    ok = all(r.values()) if isinstance(r, dict) else False
    check("Test2 Conflict Guard (Hover→Drag / Press→Drag)", ok, json.dumps(r, ensure_ascii=False))


def test_cinema_gate(ws: CDPWebSocket) -> None:
    r = ev(ws, """
(async () => {
  const M = window.__pwMotion;
  const t0 = performance.now();
  const h = M.startCinema({ layout: () => {} });
  const gateRes = await h.whenInteractive;
  const gateWall = performance.now() - t0;
  h.finish();
  await h.stable;
  return { gateRes, gateWall, phase: h.phase, trace: h.trace };
})()
""", timeout=15)
    ok = (
        r.get("gateRes") == "gate"
        and 150 <= r.get("gateWall", 0) <= 450
        and r.get("phase") == "stable"
        and any(e.get("phase") == "gate" for e in r.get("trace", []))
    )
    check("Test3 Cinema Interactive Gate ≈240ms", ok, f"gateWall={r.get('gateWall')}ms trace={r.get('trace')}")


def test_cinema_resize(ws: CDPWebSocket) -> None:
    r = ev(ws, """
(async () => {
  const M = window.__pwMotion;
  const t0 = performance.now();
  let layoutCalls = 0;
  const h = M.startCinema({ layout: () => { layoutCalls += 1; } });
  await new Promise(r => setTimeout(r, 260));     // 初始定位（240ms）完成后触发 resize
  window.dispatchEvent(new Event('resize'));
  const stableRes = await h.stable;
  const stableWall = performance.now() - t0;
  return { stableRes, stableWall, layoutCalls, phase: h.phase, trace: h.trace };
})()
""", timeout=15)
    ok = (
        r.get("stableRes") == "stable"
        and r.get("stableWall", 9e9) < 560  # 快速收敛：必须早于完整时间轴
        and r.get("layoutCalls", 0) >= 2    # 初始布局 + resize 重算
        and r.get("phase") == "stable"
    )
    check("Test4 Cinema Resize 快速收敛", ok, f"stableWall={r.get('stableWall')}ms layoutCalls={r.get('layoutCalls')}")


def test_reduced(ws: CDPWebSocket) -> None:
    r = ev(ws, """
(() => {
  const M = window.__pwMotion;
  const cs = () => getComputedStyle(document.documentElement);
  const iBefore = cs().getPropertyValue('--mt-intensity').trim();
  const durBefore = cs().getPropertyValue('--mt-dur-quick').trim();
  M.setLevel('reduced');
  const iAfter = cs().getPropertyValue('--mt-intensity').trim();
  const durAfter = cs().getPropertyValue('--mt-dur-quick').trim();
  const blurAfter = cs().getPropertyValue('--mt-blur').trim();
  const dataset = document.documentElement.dataset.motion;
  M.setLevel('standard');
  const datasetRestored = document.documentElement.dataset.motion;
  return { iBefore, durBefore, iAfter, durAfter, blurAfter, dataset, datasetRestored };
})()
""", timeout=10)
    cond = {
        "iBefore==1": r.get("iBefore") == "1",
        "iAfter==0.35": r.get("iAfter") in ("0.35", ".35"),  # getComputedStyle 规范化 0.35→.35
        "blur==0": r.get("blurAfter") == "0",
        "dataset==reduced": r.get("dataset") == "reduced",
        "durEq": r.get("durBefore") == r.get("durAfter"),   # Duration 与 Intensity 解耦
        "durNonZero": r.get("durBefore") not in ("0s", ""),  # duration token 纹丝不动
        "restored": r.get("datasetRestored") == "standard",
    }
    check("Test6 Motion=Reduced（intensity 降 / duration 不变）", all(cond.values()),
          json.dumps({"r": r, "cond": cond}, ensure_ascii=False))


def test_off(ws: CDPWebSocket) -> None:
    r = ev(ws, """
(() => {
  const M = window.__pwMotion;
  M.setLevel('off');
  const probe = document.createElement('button');
  probe.style.transition = 'opacity 500ms';
  document.body.appendChild(probe);
  const essential = document.createElement('div');
  essential.className = 'pw-motion-essential';
  essential.style.transition = 'opacity 1000ms';
  document.body.appendChild(essential);
  const res = {
    dataset: document.documentElement.dataset.motion,
    intensity: getComputedStyle(document.documentElement).getPropertyValue('--mt-intensity').trim(),
    probeDur: getComputedStyle(probe).transitionDuration,
    essentialDur: getComputedStyle(essential).transitionDuration,
  };
  probe.remove(); essential.remove();
  M.setLevel('standard');
  res.datasetRestored = document.documentElement.dataset.motion;
  return res;
})()
""", timeout=10)
    ok = (
        r.get("dataset") == "off"
        and r.get("intensity") == "0"
        and r.get("probeDur") == "0s"      # 装饰动画消失
        and r.get("essentialDur") == "1s"  # 必要反馈豁免仍在
        and r.get("datasetRestored") == "standard"
    )
    check("Test7 Motion=Off（装饰关 / 必要反馈豁免）", ok, json.dumps(r))


def test_s2(ws: CDPWebSocket, base: str) -> None:
    ws.call("Page.navigate", {"url": f"{base}/dev/motion"}, timeout=15)
    wait_for(ws, "!!(document.querySelector('.dmh-scroller') && document.querySelectorAll('.dmh-list li').length > 100)")
    r = ev(ws, """
(async () => {
  const scroller = document.querySelector('.dmh-scroller');
  const root = document.querySelector('.dmh-root');
  scroller.scrollTop = 150;
  await new Promise(r => setTimeout(r, 120));
  const before = scroller.scrollTop;
  const rowsBefore = scroller.querySelectorAll('li').length;
  document.querySelector('.dmh-filter').click();
  await new Promise(r => setTimeout(r, 300));
  const after = scroller.scrollTop;
  const rowsAfter = scroller.querySelectorAll('li').length;
  const markerKept = root.__dmhMounted !== undefined;   // remount 探针
  const firstBefore = scroller.querySelector('li')?.dataset.rowId;
  document.querySelector('.dmh-reorder').click();
  await new Promise(r => setTimeout(r, 300));
  const firstAfter = scroller.querySelector('li')?.dataset.rowId;
  const scrollTopAfterReorder = scroller.scrollTop;
  document.querySelector('.dmh-filter').click();        // 还原
  return { before, after, rowsBefore, rowsAfter, markerKept, firstBefore, firstAfter, scrollTopAfterReorder };
})()
""", timeout=20)
    ok = (
        r.get("before") == r.get("after")               # 过滤不改 scrollTop
        and r.get("rowsAfter") == r.get("rowsBefore") / 2  # 过滤真的生效（有区分度）
        and r.get("markerKept") is True                 # 局部更新未 remount
        and r.get("firstAfter") != r.get("firstBefore") # 重排真的生效
        and r.get("scrollTopAfterReorder") == r.get("after")  # 重排不改 scrollTop
    )
    check("Test1 S2（过滤/重排不 remount · scrollTop 不变）", ok, json.dumps(r))


def test_latest_wins(ws: CDPWebSocket, base: str) -> None:
    ws.call("Page.navigate", {"url": base}, timeout=15)
    wait_for(ws, "!!document.querySelector('#app .app-shell')")
    wait_for(ws, "document.querySelectorAll('.app-shell a[href]').length > 3")
    r = ev(ws, """
(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pick = href => document.querySelector(`.app-shell a[href="${href}"]`);
  const seq = ['/software', '/life', '/plugins', '/device'];
  for (const href of seq) {
    const a = pick(href);
    if (!a) return { error: 'anchor missing: ' + href };
    a.click();
    await sleep(40);   // 快速连续导航：模拟 A→B→C→D
  }
  await sleep(1500);   // 等所有过渡收敛
  const main = document.querySelector('.app-main');
  return {
    path: location.pathname,
    deviceVisible: (main?.textContent || '').includes('设备'),
    softwareGone: !document.querySelector('.apps-side'),
    opacity: main?.firstElementChild ? getComputedStyle(main.firstElementChild).opacity : null,
    pending: window.__pwMotion.hasPendingPageAnims(),
    vtCalls: window.__vtSpy.calls,
  };
})()
""", timeout=30)
    ok = (
        r.get("path") == "/device"
        and r.get("deviceVisible") is True
        and r.get("softwareGone") is True
        and r.get("opacity") == "1"     # 最终态不残留半透明（§十二）
        and r.get("pending") is False
        and r.get("vtCalls") == 0       # 页面过渡走 fallback/WAAPI，不用 VT
    )
    check("Test5 A→B→C→D latest-wins", ok, json.dumps(r, ensure_ascii=False))


def test_novt(ws: CDPWebSocket, base: str) -> None:
    # 带 ?motion=novt 加载：VT 必须被关闭且走同步 fallback
    ws.call("Page.navigate", {"url": f"{base}/?motion=novt"}, timeout=15)
    wait_for(ws, "!!(window.__pwMotion && document.querySelector('#app .app-shell'))")
    r = ev(ws, """
(() => {
  const M = window.__pwMotion;
  const enabled = M.vtEnabled();
  let ran = false;
  const ret = M.motionViewTransition(() => { ran = true; });
  return { enabled, ran, isPromise: !!(ret && typeof ret.then === 'function'), vtCalls: window.__vtSpy.calls };
})()
""", timeout=10)
    ok = (
        r.get("enabled") is False
        and r.get("ran") is True            # fallback 真的执行了业务更新
        and r.get("isPromise") is False     # 且是同步路径
        and r.get("vtCalls") == 0           # startViewTransition 一次都没被调
    )
    check("Test8a ?motion=novt 强制 fallback", ok, json.dumps(r))

    # 无参数：VT 正常启用（双向断言，避免"恒 fallback"假通过）
    ws.call("Page.navigate", {"url": base}, timeout=15)
    wait_for(ws, "!!(window.__pwMotion && document.querySelector('#app .app-shell'))")
    r = ev(ws, """
(async () => {
  const M = window.__pwMotion;
  const enabled = M.vtEnabled();
  let ran = false;
  await M.motionViewTransition(() => { ran = true; });
  return { enabled, ran, vtCalls: window.__vtSpy.calls };
})()
""", timeout=15)
    ok = (
        r.get("enabled") is True
        and r.get("ran") is True
        and r.get("vtCalls") == 1           # VT 通道被真实走到
    )
    check("Test8b 无参数时 VT 正常启用", ok, json.dumps(r))


# ---------------------------------------------------------------- 主流程


def main() -> int:
    if not DIST.exists():
        print(f"FATAL ui/dist 不存在：{DIST}（先 vite build）")
        return 2
    edge = find_edge()
    port, srv = start_server()
    base = f"http://127.0.0.1:{port}"
    dbg_port = free_port()
    profile = tempfile.mkdtemp(prefix="pw-motion-verify-")
    cmd = [
        edge, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", f"--user-data-dir={profile}",
        f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
        "--window-size=1440,900", "about:blank",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as resp:
                    targets = json.loads(resp.read().decode())
                pages = [t for t in targets if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        if not ws_url:
            print("FATAL 连不上 CDP")
            return 2
        ws = CDPWebSocket(ws_url)
        ws.call("Page.enable")
        # VT spy 在每次文档创建时注入（先于应用脚本）
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": VT_SPY})
        ws.call("Page.navigate", {"url": base}, timeout=15)
        # 注意：returnByValue 序列化 DOM 节点会得到 {}（falsy），必须布尔包装
        wait_for(ws, "!!(window.__pwMotion && document.querySelector('#app .app-shell'))")
        # Edge headless 默认上报 prefers-reduced-motion: reduce —— Motion Guard
        # 会正确地自动进 reduced 档（这本身是 Guard 生效的证据）。
        # 测试基线需要 standard：显式覆盖，并留档初始档位。
        boot_level = ev(ws, "document.documentElement.dataset.motion || 'none'", timeout=8)
        print(f"[boot] 初始 Motion Guard 档位（headless 环境偏好）: {boot_level}")
        ev(ws, "window.__pwMotion.setLevel('standard')", timeout=8)
        wait_for(ws, "getComputedStyle(document.documentElement).getPropertyValue('--mt-intensity').trim() === '1'")

        print("=== TECH-01 验收（Edge headless + CDP）===")
        test_conflict(ws)
        test_cinema_gate(ws)
        test_cinema_resize(ws)
        test_reduced(ws)
        test_off(ws)
        test_s2(ws, base)
        test_latest_wins(ws, base)
        test_novt(ws, base)

        passed = sum(1 for _, ok, _ in RESULTS if ok)
        total = len(RESULTS)
        print(f"=== 汇总 {passed}/{total} ===")
        return 0 if passed == total else 1
    finally:
        proc.terminate()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
