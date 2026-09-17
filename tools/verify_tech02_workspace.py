#!/usr/bin/env python3
"""TECH-02 验收 · Workspace Runtime（T1~T6）。

驱动方式与 `verify_tech01.py` 同源：`ui/dist` 静态服务（SPA 回退）+ Edge
`--headless=new` + remote-debugging-port + 标准库手搓 WebSocket 客户端。
**测的是最终构建产物**（vite build），不是开发态。

## 被测面
`/dev/workspace` 固件页（`DevWorkspaceHarness.vue`）—— Workspace Runtime 的**唯一消费者**。
所有断言都走真实页面：静态检查读源码，动态检查读 DOM / `window.__pwWorkspace`。

## 用例
T1  Runtime 存在且 UI 不直接访问 mock（静态：私有种子不被导出、UI 不 import store/layout；
    动态：门面方法齐全、返回值冻结克隆、写不穿真身）
T2  模板 create → read → reload（重载后自定义模板消失 = 无持久化的正/反双向证据）
T3  Layout Snapshot：save → 真实拖拽移动 → restore 回原几何；clear 回落 auto
T4  windowEvent open/close/focus 真改 UI（含"未匹配事件不改状态"的对照组）
T5  S2：状态更新不整页重绘（**节点身份**判据）+ 对照组证明探针有区分度
T6  响应式 1920 / 1366 / 900 布局不破（含 900 断点堆叠的判别性断言）

## 可信度纪律（见 acceptance-script-integrity skill）
- 就绪门是"DOM 条件成立"（窗口真的渲染出来了），不是"标记非空"；
- 每条否定断言都带对照组（T2 reload、T4 未匹配事件、T5 换模板）；
- T5 探针打在**会变的节点**上，并先用对照组证明它会红；
- 单个用例失败不连坐：逐个 try/except，失败打印原始异常文本后继续；
- 收尾清干净：临时 profile 目录删除，Edge / 静态服务进程终止。
"""

from __future__ import annotations

import base64
import http.server
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "ui" / "dist"
SRC = ROOT / "ui" / "src"

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
    found = shutil.which("msedge")
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
        if not os.path.exists(real) or (
            os.path.isdir(real) and not os.path.exists(os.path.join(real, "index.html"))
        ):
            return str(DIST / "index.html")
        return real

    def log_message(self, *args):  # 静音
        pass


class QuietServer(http.server.ThreadingHTTPServer):
    """Edge 主动断连（页面导航/退出）会在 stderr 刷一大堆栈，属正常现象 —— 静音。"""

    def handle_error(self, request, client_address):  # noqa: D102
        pass


def start_server() -> tuple[int, QuietServer]:
    port = free_port()
    srv = QuietServer(("127.0.0.1", port), SPAHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port, srv


# ---------------------------------------------------------------- 断言辅助

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def ev(ws: CDPWebSocket, js: str, timeout: float = 30.0):
    """Runtime.evaluate + Execution context destroyed 重试（skill 坑 1）。"""
    last: Exception | None = None
    for attempt in range(6):
        try:
            res = ws.call(
                "Runtime.evaluate",
                {"expression": js, "awaitPromise": True, "returnByValue": True},
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


def wait_for(ws: CDPWebSocket, js: str, timeout: float = 25.0, interval: float = 0.3):
    """轮询直到 js 为真值（不假设 DOM/状态已就绪）。"""
    deadline = time.time() + timeout
    last = None
    for _ in range(int(timeout / max(interval, 0.01)) + 1):
        if time.time() > deadline:
            break
        try:
            last = ev(ws, js, timeout=10)
            if last:
                return last
        except (RuntimeError, TimeoutError):
            pass
        time.sleep(interval)
    raise TimeoutError(f"等待超时: {js[:120]} (last={last!r})")


# ---------------------------------------------------------------- 页面内工具（注入一次）

HELPERS = r"""
window.__t2 = (() => {
  const W = () => window.__pwWorkspace;
  const canvas = () => document.querySelector('[data-wwr-canvas]');
  const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  // 与 layout.ts 同基准：窗口矩形相对 canvas 内容盒左上角
  const measure = () => {
    const c = canvas();
    if (!c) return [];
    const cr = c.getBoundingClientRect();
    const ox = cr.left + c.clientLeft, oy = cr.top + c.clientTop;
    return [...c.querySelectorAll('[data-app-id]')].map(el => {
      const r = el.getBoundingClientRect();
      return { appId: el.dataset.appId, x: Math.round(r.left - ox), y: Math.round(r.top - oy),
               w: Math.round(r.width), h: Math.round(r.height) };
    });
  };
  const pointer = (type, x, y) => new PointerEvent(type, {
    clientX: x, clientY: y, bubbles: true, cancelable: true,
    isPrimary: true, pointerId: 1, pointerType: 'mouse', buttons: 1,
  });
  /** 真实指针事件拖拽第一个窗口（走固件自己的 pointerdown/move/up 监听） */
  const dragFirst = async (dx, dy) => {
    const el = canvas().querySelector('[data-app-id]');
    const bar = el.querySelector('.dwh-window-bar');
    const r = bar.getBoundingClientRect();
    const x0 = r.left + 24, y0 = r.top + 8;
    bar.dispatchEvent(pointer('pointerdown', x0, y0));
    window.dispatchEvent(pointer('pointermove', x0 + dx, y0 + dy));
    window.dispatchEvent(pointer('pointerup', x0 + dx, y0 + dy));
    await frame();
    return { x0, y0, moved: [x0 + dx, y0 + dy] };
  };
  const badge = (appId) => {
    const el = document.querySelector(`[data-wwr-status="${appId}"]`);
    return el ? el.textContent.trim() : null;
  };
  const uiStatuses = () => [...document.querySelectorAll('[data-wwr-canvas] [data-app-id]')]
    .map(el => ({ appId: el.dataset.appId, dom: el.dataset.status, badge: badge(el.dataset.appId) }));
  return { W, canvas, frame, measure, dragFirst, badge, uiStatuses };
})();
"""


def go_harness(ws: CDPWebSocket, base: str, expect_apps: int = 3, template: str = "tpl-seed-dev") -> None:
    """导航到固件页并**把状态收敛到一个确定的起点**：固定模板 + 固定应用数。

    就绪门是"窗口真的渲染出来了"（DOM 条件），不是"某个标记非空"。
    注意：种子模板 `layoutSnapshot: null`，prepare 后应用是 `waiting`（这是正确语义：
    没有布局快照就没有窗口就位）—— 因此这里**不**断言 running，只断言数量与几何可测。
    """
    ws.call("Page.navigate", {"url": f"{base}/dev/workspace"}, timeout=15)
    wait_for(ws, "!!(window.__pwWorkspace && document.querySelector('[data-wwr-canvas]'))", timeout=25)
    ev(ws, HELPERS, timeout=10)
    ev(ws, f"window.__pwWorkspace.prepareWorkspace({template!r}, {{}})", timeout=20)
    wait_for(
        ws,
        f"document.querySelectorAll('[data-wwr-canvas] [data-app-id]').length === {expect_apps}"
        f" && window.__t2.measure().length === {expect_apps}"
        f" && window.__t2.measure().every(g => g.w > 0 && g.h > 0)",
    )
    ev(ws, HELPERS, timeout=10)
    ev(ws, "window.__t2.frame()", timeout=10)


# ---------------------------------------------------------------- T1


def t1_static() -> None:
    """静态：种子模板私有 + UI 不直连 store/layout。"""
    store = (SRC / "workspace" / "store.ts").read_text(encoding="utf-8")
    seed_declared = re.search(r"^const __SEED_TEMPLATES", store, re.M) is not None
    seed_exported = re.search(r"^export\s+(?:const|let|var)\s+__SEED_TEMPLATES", store, re.M) is not None
    check(
        "T1a 种子模板__SEED_TEMPLATES 私有（声明了但未导出）",
        seed_declared and not seed_exported,
        f"declared={seed_declared} exported={seed_exported}",
    )

    offenders: list[str] = []
    for path in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        if path.name in ("store.ts", "layout.ts"):  # 模块自身不算
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"""from\s+['"]([^'"]*workspace/(?:store|layout))['"]""", text):
            offenders.append(f"{path.relative_to(SRC)} ← {m.group(1)}")
    check(
        "T1b UI 不绕过门面直连 workspace/store|layout",
        not offenders,
        "无越权 import" if not offenders else "; ".join(offenders[:5]),
    )

    # TECH-05-C §P0-3 起新增一个**产品内**消费者：工作空间状态组件
    # （挂在 /dashboard 上）。本条的目的不是"只允许固件页"，而是
    # **不允许绕过门面**或散落多处各读一份状态 —— 因此消费者必须逐个登记。
    allowed = {
        str(SRC / "workspace" / "runtime.ts"),
        str(SRC / "views" / "DevWorkspaceHarness.vue"),
        str(SRC / "components" / "WorkspaceStatus.vue"),
    }
    importers: list[str] = []
    for path in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"""from\s+['"][^'"]*workspace/runtime['"]""", text) and str(path) not in allowed:
            importers.append(str(path.relative_to(SRC)))
    check(
        "T1c workspace/runtime 的消费者只有已登记的两处（固件页 + 工作空间状态组件）",
        not importers,
        "无额外消费者" if not importers else "; ".join(importers),
    )


def t1_runtime(ws: CDPWebSocket) -> None:
    r = ev(ws, r"""
(() => {
  const W = window.__pwWorkspace;
  if (!W) return { missing: 'window.__pwWorkspace' };
  const need = ['getCurrent','getApps','getLayout','updateStatus','windowEvent',
                'saveLayoutSnapshot','loadLayoutSnapshot','clearLayoutSnapshot',
                'listTemplates','createTemplate','saveTemplate','loadTemplate','prepareWorkspace'];
  const missing = need.filter(k => typeof W[k] !== 'function');
  const apps = W.getApps();
  const cur = W.getCurrent();
  const tpl = W.listTemplates();
  const frozen = Object.isFrozen(apps) && Object.isFrozen(cur) && Object.isFrozen(tpl)
                 && (apps.length === 0 || Object.isFrozen(apps[0]));
  // 写穿测试：改拿到的副本，真身必须纹丝不动
  const before = apps.map(a => a.status).join(',');
  let pushThrew = false;
  try { apps.push({ appId: 'hack', name: 'x', status: 'running' }); } catch (e) { pushThrew = true; }
  try { if (apps[0]) apps[0].status = 'HACKED'; } catch (e) { /* frozen 下静默 */ }
  const after = W.getApps().map(a => a.status).join(',');
  const tplBefore = tpl.length;
  try { if (tpl[0]) tpl[0].name = 'HACKED'; } catch (e) { /* noop */ }
  const tplNameAfter = W.listTemplates()[0] ? W.listTemplates()[0].name : null;
  return { missing, frozen, pushThrew, before, after, tplBefore,
           tplMutated: tplNameAfter === 'HACKED',
           layoutShape: W.getLayout() ? Object.keys(W.getLayout()).sort().join('+') : null };
})()
""", timeout=15)
    ok = (
        not r.get("missing")
        and r.get("frozen") is True
        and r.get("pushThrew") is True
        and r.get("before") == r.get("after")
        and r.get("tplMutated") is False
    )
    check("T1d 门面方法齐全 + 返回值冻结克隆（写不穿真身）", ok, json.dumps(r, ensure_ascii=False))


# ---------------------------------------------------------------- T2


def t2_templates(ws: CDPWebSocket) -> None:
    name = f"T2-模板-{int(time.time()) % 100000}"
    pre = ev(ws, r"""
(async () => {
  const W = window.__pwWorkspace;
  const before = W.listTemplates().length;
  const tpl = W.createTemplate({ name: %s, goal: 'T2 目标', apps: [
    { appId: 't2-a', name: '应用A' }, { appId: 't2-b', name: '应用B' }] });
  const after = W.listTemplates().length;
  const back = W.getTemplate(tpl.id);
  return { before, after, tplId: tpl.id, name: tpl.name, goal: tpl.goal,
           apps: tpl.apps.map(a => a.appId + ':' + a.name).join(','),
           hasSnap: !!tpl.layoutSnapshot,
           snapEntries: tpl.layoutSnapshot ? tpl.layoutSnapshot.entries.length : 0,
           readBack: back ? { name: back.name, goal: back.goal, n: back.apps.length } : null };
})()
""" % json.dumps(name), timeout=20)
    created_ok = (
        pre.get("after") == pre.get("before", 0) + 1
        and pre.get("readBack", {}).get("name") == name
        and pre.get("readBack", {}).get("goal") == "T2 目标"
        and pre.get("readBack", {}).get("n") == 2
    )
    check("T2a 模板 create → 按 id 读回（字段完整）", created_ok, json.dumps(pre, ensure_ascii=False))

    # 模板能被 prepareWorkspace 真正用起来（深绑定：应用状态由模板决定）
    use = ev(ws, r"""
(async () => {
  const W = window.__pwWorkspace;
  const r = await W.prepareWorkspace(%s, {});
  const apps = W.getApps();
  return { ok: r.ok, templateId: r.templateId, n: apps.length,
           ids: apps.map(a => a.appId).sort().join(','),
           steps: r.steps.map(s => s.step).join('>'),
           stepsOk: r.steps.every(s => s.ok) };
})()
""" % json.dumps(pre.get("tplId")), timeout=25)
    ok = (
        use.get("ok") is True
        and use.get("templateId") == pre.get("tplId")
        and use.get("n") == 2
        and use.get("ids") == "t2-a,t2-b"
        and use.get("steps") == "read-workspace>read-layout-snapshot>sync-app-status>commit"
        and use.get("stepsOk") is True
    )
    check("T2b 新模板可被 prepareWorkspace 使用（流水线四步有序）", ok, json.dumps(use, ensure_ascii=False))

    # 对照组（无持久化）：整页 reload 后自定义模板必须消失、种子模板必须回来
    ws.call("Page.navigate", {"url": ws._tech02_base + "/dev/workspace"}, timeout=15)
    wait_for(ws, "!!(window.__pwWorkspace && document.querySelector('[data-wwr-canvas]'))", timeout=25)
    after_reload = ev(ws, r"""
(() => {
  const W = window.__pwWorkspace;
  const tpls = W.listTemplates();
  return { n: tpls.length, names: tpls.map(t => t.name).join(','),
           customGone: !tpls.some(t => t.name === %s) };
})()
""" % json.dumps(name), timeout=15)
    ok = (
        after_reload.get("customGone") is True      # 自定义模板随内存消失（无数据库）
        and after_reload.get("n", 0) >= 3           # 种子模板回来了
    )
    check("T2c 对照组：reload 后自定义模板消失、种子回来（证明零持久化）", ok,
          json.dumps(after_reload, ensure_ascii=False))


# ---------------------------------------------------------------- T3


def t3_snapshot(ws: CDPWebSocket, base: str) -> None:
    go_harness(ws, base)
    r = ev(ws, r"""
(async () => {
  const T = window.__t2, W = T.W();
  const geomA = T.measure();
  document.querySelector('[data-wwr-save-layout]').click();   // 真实点击
  await T.frame();
  const snaps = W.listLayoutSnapshots();
  const snap = snaps[snaps.length - 1];
  const layoutAfterSave = W.getLayout();
  const drag = await T.dragFirst(150, 96);                    // 真实指针拖拽
  const geomB = T.measure();
  if (snap) W.loadLayoutSnapshot(snap.snapshotId);            // 恢复
  await T.frame();
  const geomC = T.measure();
  const layoutAfterLoad = W.getLayout();
  const cleared = W.clearLayoutSnapshot();
  await T.frame();
  const afterClear = { type: (W.getLayout() || {}).type, n: W.listLayoutSnapshots().length };
  return { geomA, geomB, geomC, drag,
           snapId: snap ? snap.snapshotId : null,
           snapEntries: snap ? snap.entries.length : 0,
           layoutAfterSave, layoutAfterLoad, cleared, afterClear };
})()
""", timeout=30)

    a, b, c = r.get("geomA", []), r.get("geomB", []), r.get("geomC", [])
    key = lambda g: {e["appId"]: (e["x"], e["y"]) for e in g}
    ka, kb, kc = key(a), key(b), key(c)
    # 移动必须真的发生（否则"恢复成功"无区分度）
    moved = any(ka.get(k) != kb.get(k) for k in ka)
    # 恢复必须回到 A（2px 容差）
    restored = bool(ka) and all(
        kb and abs(kc.get(k, (9e9, 9e9))[0] - v[0]) <= 2 and abs(kc.get(k, (9e9, 9e9))[1] - v[1]) <= 2
        for k, v in ka.items()
    )
    ok = (
        r.get("snapId") is not None
        and r.get("snapEntries") == len(a)
        and moved
        and restored
        and r.get("layoutAfterSave", {}).get("type") == "manual"
        and r.get("layoutAfterLoad", {}).get("type") == "manual"
        and r.get("afterClear", {}).get("type") == "auto"
        and r.get("afterClear", {}).get("n") == 0
    )
    check("T3 Layout Snapshot：save → 拖拽移动 → restore 回原几何 → clear 回落 auto", ok,
          json.dumps({"snap": r.get("snapId"), "entries": r.get("snapEntries"),
                      "A": ka, "B": kb, "C": kc, "moved": moved, "restored": restored,
                      "layoutAfterSave": r.get("layoutAfterSave"),
                      "afterClear": r.get("afterClear")}, ensure_ascii=False))


# ---------------------------------------------------------------- T4


def t4_window_event(ws: CDPWebSocket, base: str) -> None:
    go_harness(ws, base)
    r = ev(ws, r"""
(async () => {
  const T = window.__t2, W = T.W();
  const appId = W.getApps()[0].appId;
  const wid = 'win-' + appId;
  // 起点：waiting（先把状态摆到"能被 open 改变"的位置）
  document.querySelector(`[data-wwr-st-waiting="${appId}"]`).click();
  await T.frame();
  const s0 = { store: (W.getApps().find(a => a.appId === appId) || {}).status, badge: T.badge(appId) };

  document.querySelector(`[data-wwr-open="${appId}"]`).click();      // open
  await T.frame();
  const app1 = W.getApps().find(a => a.appId === appId) || {};
  const s1 = { store: app1.status, badge: T.badge(appId), windowId: app1.windowId,
               layoutNode: app1.layoutNode, event: (W.lastWindowEvent() || {}).event };

  document.querySelector(`[data-wwr-focus="${appId}"]`).click();     // focus
  await T.frame();
  const s2 = { focused: W.focusedWindowId(), event: (W.lastWindowEvent() || {}).event,
               barText: (document.querySelector('[data-wwr-last-event]') || {}).textContent || '' };

  document.querySelector(`[data-wwr-close="${appId}"]`).click();     // close
  await T.frame();
  const app2 = W.getApps().find(a => a.appId === appId) || {};
  const s3 = { store: app2.status, badge: T.badge(appId), windowId: app2.windowId ?? null,
               layoutNode: app2.layoutNode ?? null, focused: W.focusedWindowId(),
               event: (W.lastWindowEvent() || {}).event };

  // 对照组：未匹配的 windowId 不得改动任何 app 状态
  const statusesBefore = W.getApps().map(a => a.appId + '=' + a.status).join(',');
  const unmatched = W.windowEvent({ windowId: 'win-does-not-exist', event: 'open' });
  const statusesAfter = W.getApps().map(a => a.appId + '=' + a.status).join(',');
  return { appId, s0, s1, s2, s3, unmatched: unmatched === null,
           noMutation: statusesBefore === statusesAfter };
})()
""", timeout=30)
    ok = (
        r.get("s0", {}).get("store") == "waiting"
        and r.get("s1", {}).get("store") == "running"
        and r.get("s1", {}).get("badge") == "running"          # UI 真的跟着变了
        and r.get("s1", {}).get("windowId") == f"win-{r.get('appId')}"
        and r.get("s1", {}).get("layoutNode") == f"node-{r.get('appId')}"
        and r.get("s2", {}).get("focused") == f"win-{r.get('appId')}"
        and r.get("s2", {}).get("event") == "focus"
        and "focus" in r.get("s2", {}).get("barText", "")
        and r.get("s3", {}).get("store") == "closed"
        and r.get("s3", {}).get("badge") == "closed"
        and r.get("s3", {}).get("windowId") is None
        and r.get("s3", {}).get("focused") is None
        and r.get("s3", {}).get("event") == "close"
        and r.get("unmatched") is True and r.get("noMutation") is True
    )
    check("T4 windowEvent open/close/focus 真改 UI（含未匹配对照组）", ok, json.dumps(r, ensure_ascii=False))


# ---------------------------------------------------------------- T5


def t5_s2_no_rerender(ws: CDPWebSocket, base: str) -> None:
    go_harness(ws, base)
    r = ev(ws, r"""
(async () => {
  const T = window.__t2, W = T.W();
  const canvasEl = T.canvas();
  const logEl = document.querySelector('[data-wwr-log]');
  const appId = W.getApps()[0].appId;
  // 先把状态摆到"能被 running 改变"的位置（否则 statusChanged 无区分度）
  document.querySelector(`[data-wwr-st-waiting="${appId}"]`).click();
  // 把日志喂到**真的可滚动**：用第 3 个 app 反复点 waiting（状态不变，但每次都会发通知写日志）
  const fillerId = W.getApps()[2].appId;
  const filler = document.querySelector(`[data-wwr-st-waiting="${fillerId}"]`);
  for (let i = 0; i < 30; i++) filler.click();
  await T.frame();
  const statusBefore = (W.getApps().find(a => a.appId === appId) || {}).status;
  const fillerAfter = (W.getApps().find(a => a.appId === fillerId) || {}).status;

  const winEls = [...canvasEl.querySelectorAll('[data-app-id]')];
  logEl.scrollTop = 30;                      // 制造一个 scrollTop 状态
  await T.frame();
  const refsBefore = winEls.map(el => el);
  const scrollBefore = logEl.scrollTop;
  const scrollable = logEl.scrollHeight > logEl.clientHeight + 10;

  // 被测操作：状态更新（S2 要求"不整页重绘"）
  document.querySelector(`[data-wwr-st-running="${appId}"]`).click();
  await T.frame();
  const s2 = {
    statusBefore, fillerAfter, scrollBefore, scrollable,
    sameCanvas: T.canvas() === canvasEl,
    sameNodes: [...T.canvas().querySelectorAll('[data-app-id]')].every((el, i) => el === refsBefore[i]),
    scrollKept: logEl.scrollTop === scrollBefore,
    statusChanged: (W.getApps().find(a => a.appId === appId) || {}).status === 'running',
  };

  // 对照组：换模板（appId 全变）→ 节点身份**必须**变化，证明探针有区分度
  const other = W.listTemplates().find(t => t.id !== 'tpl-seed-dev');
  await W.prepareWorkspace(other.id, {});
  await T.frame();
  const ctrl = {
    nodesChanged: ![...T.canvas().querySelectorAll('[data-app-id]')].every((el, i) => el === refsBefore[i]),
    countChanged: T.canvas().querySelectorAll('[data-app-id]').length !== refsBefore.length,
  };

  // 控制组之后复位，便于人工复核
  await W.prepareWorkspace('tpl-seed-dev', {});
  await T.frame();
  return { s2, ctrl, otherTpl: other.id };
})()
""", timeout=40)
    s2 = r.get("s2", {})
    ctrl = r.get("ctrl", {})
    ok = (
        s2.get("statusBefore") == "waiting"      # 起点摆在会被改变的位置
        and s2.get("statusChanged") is True      # 变化真的发生了（否则断言无意义）
        and s2.get("fillerAfter") == "waiting"   # 造日志的点击没把状态改坏
        and s2.get("scrollable") is True         # scrollTop 判据有区分度的前提
        and s2.get("scrollBefore", 0) >= 20
        and s2.get("sameCanvas") is True
        and s2.get("sameNodes") is True          # 节点身份保持 = 没有 remount
        and s2.get("scrollKept") is True
        and ctrl.get("nodesChanged") is True     # 对照组：会变的节点确实会变
        and ctrl.get("countChanged") is True
    )
    check("T5 S2 状态更新不整页重绘（节点身份 + 对照组）", ok, json.dumps(r, ensure_ascii=False))


# ---------------------------------------------------------------- T6


def t6_responsive(ws: CDPWebSocket, base: str) -> None:
    go_harness(ws, base)
    per_size = []
    for w, h, mode in ((1920, 1080, "wide"), (1366, 768, "mid"), (900, 700, "narrow")):
        ws.call("Emulation.setDeviceMetricsOverride",
                {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": False}, timeout=10)
        ev(ws, "window.__t2.frame()", timeout=10)
        r = ev(ws, r"""
(() => {
  const T = window.__t2;
  const root = document.querySelector('[data-wwr-harness]');
  const side = document.querySelector('.dwh-side');
  const stage = document.querySelector('.dwh-stage');
  const canvas = T.canvas();
  const sr = side.getBoundingClientRect(), tr = stage.getBoundingClientRect();
  const cr = canvas.getBoundingClientRect();
  const wins = [...canvas.querySelectorAll('[data-app-id]')].map(el => {
    const r = el.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height) };
  });
  return {
    vw: window.innerWidth,
    sideBySide: tr.left >= sr.right - 2,
    stacked: tr.top >= sr.bottom - 2,
    sideW: Math.round(sr.width), stageW: Math.round(tr.width),
    canvasW: Math.round(cr.width), canvasH: Math.round(cr.height),
    overflow: root.scrollWidth - root.clientWidth,
    winCount: wins.length,
    minWinW: wins.length ? Math.min(...wins.map(x => x.w)) : 0,
    minWinH: wins.length ? Math.min(...wins.map(x => x.h)) : 0,
  };
})()
""", timeout=15)
        r["mode"] = mode
        r["want"] = (w, h)
        per_size.append(r)

    ok = True
    detail = []
    for r in per_size:
        o = r.get("overflow", 99)
        common = (
            r.get("sideW", 0) > 40
            and r.get("stageW", 0) > 100
            and r.get("canvasW", 0) > 100
            and r.get("canvasH", 0) > 100
            and r.get("winCount") == 3
            and r.get("minWinW", 0) > 60
            and r.get("minWinH", 0) > 40
            and o <= 2
        )
        if r["mode"] in ("wide", "mid"):
            good = common and r.get("sideBySide") is True
        else:
            good = common and r.get("stacked") is True
        ok = ok and good
        detail.append(f"{r['mode']}({r['want'][0]}x{r['want'][1]}):"
                      f"{'ok' if good else 'BREAK'} ovf={o} side={r.get('sideBySide')} "
                      f"stack={r.get('stacked')} sideW={r.get('sideW')} stageW={r.get('stageW')} "
                      f"canvas={r.get('canvasW')}x{r.get('canvasH')} wins={r.get('winCount')}")
    ws.call("Emulation.clearDeviceMetricsOverride", timeout=10)
    check("T6 响应式 1920/1366/900 布局不破（含断点堆叠判据）", ok, " | ".join(detail))


# ---------------------------------------------------------------- 主流程

TESTS = [
    ("T1 静态（种子私有 / 无越权 import）", lambda ws, base: t1_static()),
    ("T1 动态（门面齐全 / 冻结克隆）", lambda ws, base: t1_runtime(ws)),
    ("T2 模板 create→read→reload", lambda ws, base: t2_templates(ws)),
    ("T3 Layout Snapshot save/move/restore", lambda ws, base: t3_snapshot(ws, base)),
    ("T4 windowEvent 同步 UI", lambda ws, base: t4_window_event(ws, base)),
    ("T5 S2 不整页重绘", lambda ws, base: t5_s2_no_rerender(ws, base)),
    ("T6 响应式三档", lambda ws, base: t6_responsive(ws, base)),
]


def main() -> int:
    if not DIST.exists():
        print(f"FATAL ui/dist 不存在：{DIST}（先 `npm run build`）")
        return 2
    # 最终产物门禁：dist 必须不早于 src（防"改了源码没构建"）
    newest_src = max((p.stat().st_mtime for p in SRC.rglob('*') if p.is_file()), default=0)
    if (DIST / "index.html").stat().st_mtime < newest_src:
        print("FATAL ui/dist 早于 ui/src —— 请先 `npm run build`（验收必须跑在最终产物上）")
        return 2

    edge = find_edge()
    port, srv = start_server()
    base = f"http://127.0.0.1:{port}"
    dbg_port = free_port()
    profile = tempfile.mkdtemp(prefix="pw-ws-verify-")
    cmd = [
        edge, "--headless=new", "--disable-gpu", "--no-first-run",
        "--no-default-browser-check", f"--user-data-dir={profile}",
        f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
        "--window-size=1600,1000", "about:blank",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        ws_url = None
        for _ in range(60):
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
        setattr(ws, "_tech02_base", base)  # 供 T2 reload 用
        ws.call("Page.navigate", {"url": f"{base}/dev/workspace"}, timeout=15)
        wait_for(ws, "!!(window.__pwWorkspace && document.querySelector('[data-wwr-canvas]'))")
        print(f"=== TECH-02 验收（Edge headless + CDP，产物 {DIST}）===")

        for name, fn in TESTS:
            try:
                fn(ws, base)
            except Exception:  # 单个用例失败不连坐
                tb = traceback.format_exc().strip().splitlines()
                check(name, False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        if ws is not None:
            ws.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)  # 收尾零残留

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== 汇总 {passed}/{total} ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
