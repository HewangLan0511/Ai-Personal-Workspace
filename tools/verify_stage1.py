#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段1 验收自动核验：把 04「验收标准」里*需要真跑*的项变成机器可判。

覆盖（04-阶段指令-基础框架.md §验收标准）：
  1 应用能启动        启动 release 可执行文件，枚举窗口标题
  2 启动速度          < 3s（进程启动 → 窗口可见）
  2b 顶栏控件         04 §2 要求 [设置][最小化] 都在（R-06 回归）
  3 页面切换          用系统自带 Edge 无头模式逐个渲染 9 条路由，检查页面标识 + 导航齐全
  4 配置持久化        经 core HTTP 改 ui.theme → 重启 → 值仍在
  5 sidecar           sidecar 端口被写入 config，且 /health 返回 200
  6 数据库            首次启动自动建库 + migration，config 表存在
  8 ★ Widget 动态布局  Edge CDP **真实点击**（`--widget-probe`）：
                      A 点击 0→3→10 次 ⇒ 尺寸 small→medium→large，并核对次数落库到收敛；
                      B 调序锁定 ⇒ 锁定态点 5 次次数涨而尺寸冻结，解冻后按次数重算

不覆盖：
  7 构建              由 `npm run tauri build` 产出安装包（本脚本只校验 exe 存在）

已知边界（REVIEW-006 F-2 / L-026，勿误读为"主路径已验证"）：
  第 3/8 项在**浏览器**里跑，浏览器无 Tauri 容器 ⇒ 生效的是 configService 的
  **localStorage 降级层**（core 内部 HTTP API 不发 CORS 头，跨源 fetch 被拦）。
  即：本脚本验证的是「交互逻辑 + 降级持久化」；**invoke 主路径无运行时断言**。

用法：
  python tools/verify_stage1.py --exe core/target/release/personal-workspace-core.exe
  python tools/verify_stage1.py            # 自动在 core/target/release 下找
  python tools/verify_stage1.py --routes-url http://localhost:5173 --widget-probe

设计说明：本脚本**只读**数据库（验收需要核对落库结果），不写用户数据；
写入只通过 core 自己的 HTTP 接口，避免绕过「单一写入者」。
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
WINDOW_TITLE = "Personal Workspace"
STARTUP_BUDGET_MS = 3000

# ---------------------------------------------------------------- Win32 窗口枚举
if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
else:  # pragma: no cover
    _user32 = None
    _EnumProc = None


def find_windows(title_substr: str) -> list[tuple[int, str]]:
    """枚举可见顶层窗口，返回标题包含 substr 的 (hwnd, title)。"""
    if _user32 is None:
        return []
    hits: list[tuple[int, str]] = []

    def _cb(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            _user32.GetWindowTextW(hwnd, buf, length + 1)
            if title_substr in buf.value:
                hits.append((int(hwnd), buf.value))
        return True

    _user32.EnumWindows(_EnumProc(_cb), 0)
    return hits


# ---------------------------------------------------------------- 工具
def http_json(url: str, method: str = "GET", body=None, timeout: float = 5.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, {"error": str(e)}


# ---------------------------------------------------------------- 路由渲染核验
# 验收项 3「点 7 个导航项都能正常切换，无白屏」需要真实浏览器。
# 这里用系统自带的 Edge 无头模式逐个渲染路由并检查页面标识，
# 避免引入 Playwright 之类的重型依赖（不下载 Chromium，不污染环境）。
# 路径不写死：从环境变量推导安装根目录，再回退 PATH 查找（跨盘符/跨版本可用）。
_EDGE_SUBPATHS = (
    ("Microsoft", "Edge", "Application", "msedge.exe"),
    ("Microsoft", "Edge Beta", "Application", "msedge.exe"),
    ("Microsoft", "Edge Dev", "Application", "msedge.exe"),
)

ROUTES: tuple[tuple[str, str], ...] = (
    ("/dashboard", "Dashboard"),
    ("/ai", "AI 助手"),
    ("/learning", "学习成长"),
    ("/project", "项目管理"),
    ("/profile", "个人数字档案"),
    ("/life", "生活中心"),
    ("/device", "设备中心"),
    ("/plugins", "插件"),
    ("/settings", "设置"),
)

NAV_ROUTES = ("/dashboard", "/ai", "/learning", "/project", "/profile", "/life", "/device")


def _install_roots() -> list[Path]:
    """从环境变量推导软件安装根目录（避开硬编码盘符路径）。"""
    roots: list[Path] = []
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if base:
            p = Path(base)
            if p not in roots:
                roots.append(p)
    return roots


def find_edge() -> str | None:
    for root in _install_roots():
        for rel in _EDGE_SUBPATHS:
            cand = root.joinpath(*rel)
            if cand.exists():
                return str(cand)
    return shutil.which("msedge")


def render_dom(edge: str, url: str, profile_dir: Path, timeout_s: float = 90.0) -> str:
    """用 Edge 无头模式渲染 URL 并 dump DOM。"""
    proc = subprocess.run(
        [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            f"--user-data-dir={profile_dir}",
            "--virtual-time-budget=5000",
            "--dump-dom",
            url,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
    )
    return proc.stdout or ""


def check_routes(base_url: str) -> list[tuple[str, bool, str]]:
    out: list[tuple[str, bool, str]] = []
    edge = find_edge()
    if edge is None:
        out.append(("3 页面切换（无白屏）", False, "未找到 Edge，无法无头渲染"))
        return out

    profile_dir = Path(tempfile.mkdtemp(prefix="pw-edge-profile-"))
    try:
        for route, marker in ROUTES:
            url = base_url.rstrip("/") + route
            try:
                dom = render_dom(edge, url, profile_dir)
            except Exception as e:
                out.append((f"3 {route}", False, f"渲染异常：{e}"))
                continue
            has_marker = marker in dom
            # 导航存在性：检查 7 个导航项 href 是否都在。
            # 注意不能用 `class="nav-item` 计数 —— RouterLink 激活态会把 class 列表
            # 重排成 `router-link-active router-link-exact-active nav-item`，
            # 于是"当前页那条"不匹配前缀，计数恒为 6（本脚本第一版就栽在这）。
            missing = [r for r in NAV_ROUTES if f'href="{r}"' not in dom]
            has_nav = not missing
            app_filled = 'id="app"' in dom and len(dom) > 1500
            ok = has_marker and has_nav and app_filled
            out.append(
                (
                    f"3 {route} 渲染（标识 {marker!r}）",
                    ok,
                    f"marker={has_marker} nav={'齐全' if has_nav else f'缺 {missing}'} dom_len={len(dom)}",
                )
            )
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)
    return out


# ---------------------------------------------------------------- ★ 验收项 8 探针
# 「Widget 动态布局」是 04 §3 的 ★ 核心项，前两轮审核连漏两次（见 REVIEW-003 / M-4），
# 原因之一就是它被写成"需人工交互"。这里用 Edge 的 DevTools Protocol（CDP）
# 真实点击卡片，把"使用次数 → 尺寸变化"变成机器可判。
#
# 为什么是 CDP 而不是再多装个 Playwright：本机刻意不引入重型浏览器依赖；
# CDP 只要一个 WebSocket 客户端，标准库 socket 手搓即可（下面 WSClient）。


class WSClient:
    """最小 WebSocket 客户端（仅满足 CDP 的文本帧收发，不实现扩展/压缩）。"""

    def __init__(self, url: str, timeout: float = 15.0):
        m = re.match(r"^ws://([^/:]+):(\d+)(/.*)$", url)
        if not m:
            raise ValueError(f"非法 ws 地址：{url}")
        host, port, path = m.group(1), int(m.group(2)), m.group(3)
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(
            (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        while b"\r\n\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("WS 握手期间连接被关闭")
            self.buf += chunk
        head, _, rest = self.buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError("WS 握手失败：" + head.decode("utf-8", "replace")[:200])
        self.buf = rest
        self._id = 0

    def _recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("WS 连接已关闭")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes = b"") -> None:
        header = bytearray([0x80 | opcode])
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += n.to_bytes(2, "big")
        else:
            header.append(0x80 | 127)
            header += n.to_bytes(8, "big")
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        b0, b1 = self._recv_exact(2)
        opcode = b0 & 0x0F
        n = b1 & 0x7F
        if n == 126:
            n = int.from_bytes(self._recv_exact(2), "big")
        elif n == 127:
            n = int.from_bytes(self._recv_exact(8), "big")
        mask = self._recv_exact(4) if b1 & 0x80 else b""
        payload = self._recv_exact(n) if n else b""
        if mask:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    def call(self, method: str, params: dict | None = None, timeout: float = 90.0):
        self._id += 1
        mid = self._id
        self._send_frame(0x1, json.dumps({"id": mid, "method": method, "params": params or {}}).encode())
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.sock.settimeout(max(1.0, deadline - time.time()))
            opcode, payload = self._recv_frame()
            if opcode == 0x9:  # ping → 必须回 pong，否则对端会断开
                self._send_frame(0xA, payload)
                continue
            if opcode == 0x8:
                raise RuntimeError("CDP 对端主动关闭连接")
            if opcode != 0x1:
                continue
            msg = json.loads(payload.decode("utf-8"))
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"CDP {method} 报错：{msg['error']}")
                return msg.get("result")
        raise TimeoutError(f"CDP {method} 超时")

    def close(self) -> None:
        try:
            self._send_frame(0x8)
        except Exception:
            pass
        try:
            self.sock.close()
        except Exception:
            pass


# 在页面里真实点击「天气」卡片：3 次应升到 medium、10 次应升到 large。
# 尺寸阈值来自 ui/src/stores/widgets.ts 的 sizeFor()（≥3 medium / ≥10 large）。
_WIDGET_PROBE_JS = r"""
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const cards = () => [...document.querySelectorAll('.widget-card')];
  const titleOf = (c) => (c && c.querySelector('.widget-title') ? c.querySelector('.widget-title').textContent : '');
  const cardOf = (name) => cards().find((c) => titleOf(c).includes(name)) || null;
  const sizeOf = (c) => (c ? ['small', 'medium', 'large'].find((s) => c.classList.contains('size-' + s)) : null);
  const useOf = (c) => (c ? ((c.querySelector('.widget-usage') || {}).textContent || '').trim() : null);
  const btnOf = (c, label) => (c ? [...c.querySelectorAll('.widget-actions button')]
      .find((b) => (b.getAttribute('title') || '').includes(label)) : null);

  const clickBody = async (name, n) => {
    for (let i = 0; i < n; i++) {
      const c = cardOf(name);
      const body = c && c.querySelector('.widget-body');
      if (!body) return '第 ' + i + ' 次点击时找不到 ' + name + ' 的 .widget-body';
      body.click();
      await sleep(220);
    }
    return null;
  };

  // 等首次渲染（前端有 load 态）
  let card = null;
  for (let i = 0; i < 60 && !card; i++) { card = cardOf('天气'); if (!card) await sleep(250); }
  if (!card) return { error: '未找到「天气」卡片（组件可能没渲染）', cardCount: cards().length };

  // ---------- 阶段 A：点击 → 次数 → 尺寸 ----------
  const steps = [{ use: useOf(cardOf('天气')), size: sizeOf(cardOf('天气')) }];
  const e1 = await clickBody('天气', 3);
  steps.push({ use: useOf(cardOf('天气')), size: sizeOf(cardOf('天气')) });
  const e2 = await clickBody('天气', 7);
  steps.push({ use: useOf(cardOf('天气')), size: sizeOf(cardOf('天气')) });

  // 持久化是异步的（put → fetch 失败 → 降级 localStorage），而且每次点击都会各发一次写，
  // 完成顺序不保证 —— 所以不能"读到非空就算过"（会读到早期那次的旧快照，值偏小）。
  // 正确判据：**最终值收敛到点击次数**。这里轮询到 weather === 10 为止。
  const want = 10;
  const observed = [];
  let persisted = null;
  try {
    for (let i = 0; i < 100; i++) {
      persisted = localStorage.getItem('pw.config.ui.dashboard.usage');
      if (persisted && observed[observed.length - 1] !== persisted) observed.push(persisted);
      if (persisted) { try { if (JSON.parse(persisted).weather === want) break; } catch (e) { /* 半截 JSON，继续等 */ } }
      await sleep(200);
    }
  } catch (e) { persisted = 'N/A'; }

  // ---------- 阶段 B：调序锁定半支（04 验收项 8 的第二子要求）----------
  // 断言必须有**区分度**：选一个当前 size=small 的低频卡片（设备状态，priority=20）——
  //   ① 点「上移」⇒ layout_locked=true，尺寸不应立刻变；
  //   ② 锁定态下再点 5 次 ⇒ 次数涨到 5（若未锁定按 sizeFor 应变 medium），尺寸必须**仍是 small**；
  //   ③ 点「恢复自动布局」解冻 ⇒ 按 usage 重算，尺寸必须**变成 medium**。
  // 若只在已是大卡的 Widget 上断言"尺寸不变"，锁没锁都不会变，等于没有断言。
  const T = '设备状态';
  const b0 = cardOf(T);
  const lock = { target: T };
  if (!b0) {
    lock.error = '找不到「' + T + '」卡片';
  } else {
    lock.startSize = sizeOf(b0);
    lock.startUse = useOf(b0);
    const upBtn = btnOf(b0, '上移');
    if (!upBtn) {
      lock.error = '找不到「上移」按钮';
    } else {
      upBtn.click();
      await sleep(400);
      // 注意：落库比"眼皮底下"慢。浏览器降级路径下每笔 put 都会先发一次注定失败的
      // fetch（core HTTP 无 CORS 头）再落 localStorage，而 moveUp 串行发两笔
      // （widgets 数组 + layout_locked），前面还可能排着阶段 A 的写。
      // 所以这里的预算要放宽 —— 早先 8s 就判不出来，白白误报了一次。
      let lockVal = null;
      for (let i = 0; i < 120; i++) {
        lockVal = localStorage.getItem('pw.config.ui.dashboard.layout_locked');
        if (lockVal === 'true') break;
        await sleep(250);
      }
      lock.persistedLock = lockVal;
      lock.bannerShown = /已按手动布局固定/.test(document.body.innerText || '');
      lock.sizeAfterLock = sizeOf(cardOf(T));
      lock.clickErr = await clickBody(T, 5);
      lock.useAfterLockClicks = useOf(cardOf(T));
      lock.sizeAfterLockClicks = sizeOf(cardOf(T));

      const unlockBtn = [...document.querySelectorAll('button')]
          .find((b) => (b.textContent || '').includes('恢复自动布局'));
      if (!unlockBtn) {
        lock.error2 = '找不到「恢复自动布局」按钮（未能证明"解冻"出口可用）';
      } else {
        unlockBtn.click();
        await sleep(600);
        lock.sizeAfterUnlock = sizeOf(cardOf(T));
        let lockVal2 = null;
        for (let i = 0; i < 30; i++) {
          lockVal2 = localStorage.getItem('pw.config.ui.dashboard.layout_locked');
          if (lockVal2 === 'false') break;
          await sleep(200);
        }
        lock.persistedUnlock = lockVal2;
      }
    }
  }

  return {
    steps: steps,
    clickErrors: [e1, e2].filter(Boolean),
    persistedUsage: persisted,
    observedPersisted: observed,
    lock: lock,
  };
})()
"""


def probe_widget_layout(base_url: str, timeout_s: float = 120.0) -> tuple[bool, str]:
    """驱动 Edge（CDP）真实点击 Widget，核验 ★ 验收项 8：使用次数 → 尺寸变化。

    产出判据（全部机器可判）：
      1. 卡片使用次数随点击递增（0 → 3 → 10）；
      2. 尺寸按 sizeFor 阈值变化（small → medium → large）；
      3. 使用次数已持久化（浏览器直开走 localStorage 降级，见 client.ts 注释）。
    """
    edge = find_edge()
    if edge is None:
        return False, "未找到 Edge，无法做交互核验"

    debug_port = _free_port()
    profile_dir = Path(tempfile.mkdtemp(prefix="pw-edge-cdp-"))
    url = base_url.rstrip("/") + "/dashboard"
    proc = subprocess.Popen(
        [
            edge,
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={debug_port}",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ws: WSClient | None = None
    try:
        ws_url = None
        deadline = time.time() + 30
        while time.time() < deadline and ws_url is None:
            for target in _json_list(debug_port):
                if target.get("type") == "page" and str(target.get("url", "")).startswith(base_url.rstrip("/")):
                    ws_url = target.get("webSocketDebuggerUrl")
                    break
            if ws_url is None:
                time.sleep(0.4)
        if ws_url is None:
            return False, "30s 内未拿到 CDP page target"

        ws = WSClient(ws_url)
        # vite dev 下页面在我们连上之后常有一次整体重载（HMR 首帧），会把执行上下文打掉。
        # 重试到页面稳定为止；「Execution context was destroyed」属预期抖动，不是缺陷。
        res = None
        last_err: Exception | None = None
        for attempt in range(6):
            try:
                res = ws.call(
                    "Runtime.evaluate",
                    {"expression": _WIDGET_PROBE_JS, "awaitPromise": True, "returnByValue": True},
                    timeout=timeout_s,
                )
                break
            except Exception as e:  # noqa: BLE001 —— 重试是这里的正解
                last_err = e
                time.sleep(1.0 + attempt * 0.5)
        if res is None:
            return False, f"探针重试 6 次仍失败：{last_err}"
        value = (res or {}).get("result", {}).get("value")
        if not value:
            return False, f"CDP 未返回结果：{json.dumps(res, ensure_ascii=False)[:300]}"
        if value.get("error"):
            return False, f"{value['error']}（页面上共有 {value.get('cardCount')} 张卡片）"

        steps = value.get("steps") or []
        if len(steps) != 3:
            return False, f"点击步骤不完整：{json.dumps(value, ensure_ascii=False)[:300]}"
        uses = [s.get("use") for s in steps]
        sizes = [s.get("size") for s in steps]
        want_sizes = ["small", "medium", "large"]
        ok_a = sizes == want_sizes and [int(u) for u in uses if u and u.isdigit()] == [0, 3, 10]

        persisted = value.get("persistedUsage")
        want_usage = 10
        try:
            persist_ok = json.loads(persisted or "{}").get("weather") == want_usage
        except Exception:
            persist_ok = False
        ok_a = ok_a and persist_ok

        # ---- 阶段 B：调序锁定半支（04 验收项 8 的第二子要求，REVIEW-006 F-1 补验）----
        lock = value.get("lock") or {}
        lock_err = lock.get("error") or lock.get("error2")
        # 关键判据是"有区分度"的那两条：锁定态下次数涨而尺寸不动；解冻后尺寸按次数重算。
        ok_b = (
            not lock_err
            and lock.get("startSize") == "small"
            and lock.get("persistedLock") == "true"
            and lock.get("bannerShown") is True
            and lock.get("sizeAfterLock") == "small"
            and lock.get("useAfterLockClicks") == "5"
            and lock.get("sizeAfterLockClicks") == "small"
            and lock.get("sizeAfterUnlock") == "medium"
            and lock.get("persistedUnlock") == "false"
        )

        detail = (
            f"A｜点击序列 use={uses} size={sizes}（期望 {want_sizes}）；"
            f"最终落库={persisted!r}（期望 weather={want_usage}）；"
            f"落库值演变={value.get('observedPersisted')}；clickErrors={value.get('clickErrors')} || "
            f"B｜调序锁定({lock.get('target')}): 起始 size={lock.get('startSize')} → "
            f"锁后={lock.get('persistedLock')}/banner={lock.get('bannerShown')}/size={lock.get('sizeAfterLock')} → "
            f"锁定态点5次 use={lock.get('useAfterLockClicks')} size={lock.get('sizeAfterLockClicks')}（应仍 small）→ "
            f"解冻后 size={lock.get('sizeAfterUnlock')}（应 medium）/lock={lock.get('persistedUnlock')}"
            + (f"；错误={lock_err}" if lock_err else "")
        )
        return (ok_a and ok_b), detail
    except Exception as e:
        return False, f"探针异常：{e}"
    finally:
        if ws:
            ws.close()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(profile_dir, ignore_errors=True)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _json_list(port: int) -> list[dict]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return []


def check_topbar(base_url: str) -> tuple[bool, str]:
    """04 §2 顶栏必须含 `[设置] [最小化]` 两个控件。

    为什么单列一条：R-06 的失败形态是「**Rust 命令在、UI 按钮没接**」——
    功能实际不可用，但"看代码/看命令列表"都会以为做完了（L-020）。
    故这里直接对渲染结果断言，让"按钮被拔掉"这件事无法静默通过。
    """
    edge = find_edge()
    if edge is None:
        return False, "未找到 Edge，无法无头渲染"
    profile_dir = Path(tempfile.mkdtemp(prefix="pw-edge-topbar-"))
    try:
        dom = render_dom(edge, base_url.rstrip("/") + "/dashboard", profile_dir)
    except Exception as e:
        return False, f"渲染异常：{e}"
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    has_settings = "设置" in dom
    has_minimize = "最小化" in dom
    ok = has_settings and has_minimize
    return ok, f"顶栏控件：设置={has_settings} 最小化={has_minimize}（浏览器环境下最小化按钮应为 disabled）"


def list_sidecar_pids() -> set[str]:
    """列出名为 service.exe 的进程 PID（sidecar 的产物名）。"""
    if sys.platform != "win32":
        return set()
    out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True).stdout
    text = out.decode("gbk", errors="replace")
    pids: set[str] = set()
    for line in text.splitlines():
        cells = [c.strip().strip('"') for c in line.split(",")]
        if len(cells) >= 2 and cells[0].lower() == "service.exe":
            pids.add(cells[1])
    return pids


def kill_sidecar(baseline: set[str]) -> str:
    """杀掉本次运行新起的 sidecar 进程（只动 baseline 之外的新 PID，不误伤他人）。"""
    targets = list_sidecar_pids() - baseline
    for pid in targets:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    return f"killed pids={sorted(targets)}" if targets else "未找到新起的 sidecar 进程"


def read_config_map(db_path: Path) -> dict[str, str]:
    """只读方式取 config 表全部 KV。"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT key, value FROM config").fetchall()
        return {k: v for k, v in rows}
    finally:
        con.close()


def wait_for_config(
    db_path: Path, keys: tuple[str, ...], timeout_s: float = 20.0
) -> dict[str, str]:
    """轮询等待指定配置键全部落库。

    为什么必须轮询：sidecar 是 PyInstaller 单文件，启动时要先自解包（1~3s），
    端口 announce 之后才会写进 config。若在窗口出现的那一刻只读一次库里快照，
    必然读到"sidecar_port 还没写"的过期状态 —— 这是核验脚本自身的坑。
    """
    deadline = time.time() + timeout_s
    cfg: dict[str, str] = {}
    while time.time() < deadline:
        if db_path.exists():
            try:
                cfg = read_config_map(db_path)
            except Exception:
                cfg = {}
            if all(cfg.get(k) not in (None, "null") for k in keys):
                return cfg
        time.sleep(0.3)
    return cfg


class Launcher:
    """启动/关闭被测应用，并可测量「进程启动 → 窗口可见」耗时。"""

    def __init__(self, exe: Path, data_dir: Path):
        self.exe = exe
        self.data_dir = data_dir
        self.proc: subprocess.Popen | None = None
        self.startup_ms: int | None = None

    def start(self, wait_window: bool = True, timeout_s: float = 20.0) -> None:
        env = dict(os.environ)
        env["PW_DATA_DIR"] = str(self.data_dir)
        env["RUST_LOG"] = env.get("RUST_LOG", "info")
        t0 = time.perf_counter()
        self.proc = subprocess.Popen(
            [str(self.exe)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if not wait_window:
            return
        deadline = t0 + timeout_s
        while time.perf_counter() < deadline:
            if find_windows(WINDOW_TITLE):
                self.startup_ms = int((time.perf_counter() - t0) * 1000)
                return
            if self.proc.poll() is not None:
                out = self.proc.stdout.read() if self.proc.stdout else ""
                raise RuntimeError(f"应用提前退出（code={self.proc.returncode}）：\n{out[-2000:]}")
            time.sleep(0.02)
        raise TimeoutError(f"{timeout_s}s 内未出现标题含 {WINDOW_TITLE!r} 的窗口")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="阶段1 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--data-dir", help="数据目录（默认临时目录，避免污染 %APPDATA%）")
    ap.add_argument("--keep", action="store_true", help="保留临时数据目录以便排查")
    ap.add_argument(
        "--routes-url",
        help="前端地址（如 http://localhost:5173）。给了就额外核验验收项 3（各路由渲染无白屏）",
    )
    ap.add_argument(
        "--widget-probe",
        action="store_true",
        help="额外核验 ★ 验收项 8：用 Edge CDP 真实点击 Widget，验证使用次数→尺寸变化（需配合 --routes-url）",
    )
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `npm run tauri build`（或 cargo build --release）。")
        return 2

    data_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="pw-verify-"))
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "workspace.db"
    print(f"[verify] exe      = {exe}")
    print(f"[verify] data dir = {data_dir}")

    results: list[tuple[str, bool, str]] = []
    app = Launcher(exe, data_dir)
    baseline_sidecar_pids = list_sidecar_pids()
    try:
        # ---- 验收 1 + 2：启动 & 启动耗时 ----
        app.start(wait_window=True)
        ok1 = app.startup_ms is not None
        results.append(("1 应用能启动（窗口出现）", ok1, f"窗口标题含 {WINDOW_TITLE!r}"))
        ok2 = (app.startup_ms or 10**9) < STARTUP_BUDGET_MS
        results.append(
            ("2 启动速度 < 3s", ok2, f"{app.startup_ms} ms（预算 {STARTUP_BUDGET_MS} ms）")
        )

        # ---- 验收 6：数据库自动建库 ----
        # core 的 HTTP 端口是启动早期写的；sidecar 端口要等 sidecar 解包 + announce，故一起轮询。
        cfg = wait_for_config(db_path, ("runtime.http_port", "runtime.sidecar_port"), timeout_s=25.0)
        db_ok = db_path.exists() and bool(cfg)
        if db_ok:
            detail6 = (
                f"config 表 {len(cfg)} 行；schema_version={cfg.get('schema_version')}；"
                f"db.migration_version={cfg.get('db.migration_version')}"
            )
        else:
            detail6 = f"{db_path.name} 或 config 表为空"
        results.append(("6 首次启动自动建库 + migration + 种子", db_ok, detail6))

        # ---- 验收 5：sidecar 端口落库 + /health ----
        core_port = cfg.get("runtime.http_port")
        side_port = cfg.get("runtime.sidecar_port")
        detail5 = f"core port={core_port}, sidecar port={side_port}"
        ok5 = False
        if side_port and side_port != "null":
            for _ in range(25):
                st, _body = http_json(f"http://127.0.0.1:{side_port}/health", timeout=2)
                if st == 200:
                    ok5 = True
                    break
                time.sleep(0.4)
            detail5 += f" → /health {'200' if ok5 else '未就绪'}"
        else:
            detail5 += " → runtime.sidecar_port 未落库"
        results.append(("5a sidecar 拉起 + /health 200", ok5, detail5))

        # ---- 验收 5（后半）：杀掉 sidecar，主界面仍可用 ----
        killed = kill_sidecar(baseline_sidecar_pids)
        time.sleep(2.0)
        alive = False
        if core_port:
            st, _b = http_json(f"http://127.0.0.1:{core_port}/health", timeout=3)
            alive = st == 200
        window_alive = bool(find_windows(WINDOW_TITLE))
        results.append(
            (
                "5b 杀掉 sidecar 后主界面仍可用（降级）",
                alive and window_alive,
                f"killed={killed}；core /health={'200' if alive else '不可达'}；窗口{'仍在' if window_alive else '已消失'}",
            )
        )

        # ---- 验收 4（前半）：经 core HTTP 改配置 ----
        theme_before = None
        if core_port:
            st, body = http_json(f"http://127.0.0.1:{core_port}/api/v1/config/ui.theme", timeout=3)
            theme_before = (body or {}).get("data")
            st2, body2 = http_json(
                f"http://127.0.0.1:{core_port}/api/v1/config/ui.theme",
                method="PUT",
                body="dark",
                timeout=3,
            )
            # PUT 返回 { ok, data: oldValue }
            put_ok = st2 == 200 and (body2 or {}).get("ok") is True
            results.append(
                (
                    "4a 配置写入（HTTP PUT ui.theme=dark）",
                    put_ok,
                    f"原值={theme_before!r} → {json.dumps(body2, ensure_ascii=False)}",
                )
            )
        else:
            results.append(("4a 配置写入（HTTP PUT ui.theme=dark）", False, "runtime.http_port 未落库"))

        # ---- 验收 4（后半）：重启后仍在 ----
        app.stop()
        time.sleep(1.0)
        cfg_after = read_config_map(db_path) if db_path.exists() else {}
        persisted = cfg_after.get("ui.theme") in ('"dark"', "dark")
        results.append(
            ("4b 重启后主题仍为 dark（持久化）", persisted, f"库中 ui.theme={cfg_after.get('ui.theme')!r}")
        )

        # 冷启动再测一次耗时（第二轮，磁盘缓存已热）
        app2 = Launcher(exe, data_dir)
        try:
            app2.start(wait_window=True)
            results.append(("1b 二次启动（热态）窗口仍出现", True, f"{app2.startup_ms} ms"))
        finally:
            app2.stop()
    except Exception as e:
        results.append(("执行异常", False, str(e)))
    finally:
        app.stop()
        # sidecar 是主程序的子进程，TerminateProcess 主程序不会连带结束它 —— 显式清理。
        kill_sidecar(baseline_sidecar_pids)
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify] 数据目录已保留：{data_dir}")

    if args.routes_url:
        print(f"[verify] 路由渲染核验中（Edge 无头）… base={args.routes_url}")
        results.extend(check_routes(args.routes_url))
        ok_top, detail_top = check_topbar(args.routes_url)
        results.append(("2b 顶栏含 [设置][最小化]（04 §2 / R-06 回归）", ok_top, detail_top))

    if args.widget_probe:
        if not args.routes_url:
            results.append(("8 ★ Widget 动态布局", False, "--widget-probe 需要同时给 --routes-url"))
        else:
            print("[verify] ★ Widget 动态布局核验中（Edge CDP 真实点击）…")
            ok8, detail8 = probe_widget_layout(args.routes_url)
            results.append(("8 ★ Widget 动态布局（点击→次数→尺寸）", ok8, detail8))

    print("\n" + "=" * 60)
    print("阶段1 验收核验结果")
    print("=" * 60)
    all_ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}\n      {detail}")
        all_ok = all_ok and passed
    print("=" * 60)
    if args.routes_url:
        print("验收项 3 已由 Edge 无头渲染核验（见上方 3 /xxx 各项）。")
    else:
        print("验收项 3（页面切换）需浏览器渲染，请带 --routes-url 重跑，或手工：")
        print("    npm --prefix ui run dev   然后逐个点击左侧导航项")
    print("验收项 7（出安装包）见 `npm run tauri build` 输出。")
    if args.widget_probe:
        print("验收项 8（★ Widget 动态布局）已由 Edge CDP 真实点击核验（见上方）。")
    else:
        print("验收项 8（★ Widget 动态布局）未核验：加 --widget-probe 自动点击，或人工反复点同一 Widget。")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
