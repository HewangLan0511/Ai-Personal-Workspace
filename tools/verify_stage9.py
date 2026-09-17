#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段9 验收自动核验：把 12「验收标准」11 项做成机器可判。

覆盖（docs/agent-dev/12-阶段指令-插件与小组件.md §验收标准）：

| # | 验收项 | 本脚本怎么判 |
|---|--------|--------------|
| 1 | 零改动扩展 ★ | 复制 plugins/examples 两插件进插件根（**core 零改动**）→ discover 发现 → 安装 → 网关 data.set/get 读写通 → 卸载 |
| 2 | 权限拦截 | 用 pomodoro（无 net:http）调 net.http → 403 plugin_permission_denied + plugin_audit 留 denied 行 |
| 3 | 权限展示 | /api/v1/plugins 返回的 permissions 与 manifest 声明一致（安装即授权） |
| 4 | 崩溃隔离 | plugin/crash 上报 → 审计 error + PLUGIN_ERROR 语义；随后 /health 仍 200（主程序无恙） |
| 5 | 卸载清理 | 卸载后 plugins/<id>/ 目录消失；DB 的 plugins/plugin_permissions 无行；plugin_audit **保留** |
| 6 | 加载超时 | iframe 10s ready 定时器在 UI 宿主层（无 HTTP 判据）—— 如实声明：机器判 manifest 校验拒绝坏包，真实超时人工核验 |
| 7 | 小组件独立 | toggle → status open=true（真实独立窗口创建）；置顶/最小化仍显示：人工核对 |
| 8 | 小组件性能 | CPU<1% 无法在脚本生命周期内可靠判 —— 人工核对（如实声明） |
| 9 | 小组件持久化 | 关闭窗口 → config widget.desktop.config 落盘边界；重启保持：读回值比对 |
| 10 | 外部 Agent | 脚本内起 mock Agent（health+invoke）→ 注册/健康检查/调用通；无权限 action → 403；mode.switch 无 confirm → 400（**不测 confirm=true 全路径**，避免真实切模式的窗口副作用，人工核） |
| 11 | 生活中心迁移 | core 无插件特判（`plugin_id ==` 零命中）+ music 示例演示 system:media 通道；生活中心能力仍在 core（阶段8 交付口径），整体插件化非本阶段强判 |

## 边界如实声明（红线 V6）

 - **pwplugin:// 自定义协议**：Tauri 进程内协议，无 HTTP 判据 —— 由 cargo test
   `plugins::tests::serve_file_blocks_traversal`（路径守卫单测）+ 人工 GUI 核验。
 - **ZIP 导入**：sidecar /plugin/import（zip-slip 防护）→ core install 全链路实测。
 - **事件到 webview**：接线级证据（PLUGIN_LOADED / PLUGIN_ERROR /
   PLUGIN_PERMISSION_DENIED 已在 core publish；webview 侧经既有 eventBridge）。
 - **WebSocket Agent**：契约如实"预留、未实现"（transport 仅 http），不测。

用法：
  python tools/verify_stage9.py
  python tools/verify_stage9.py --exe core/target/release/personal-workspace-core.exe
  python tools/verify_stage9.py --keep

前置：先 `cargo build --release`。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")


def http_json(
    url: str,
    method: str = "GET",
    body=None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    # 本机直连 core：绕过 http_proxy 等环境代理（沙箱代理无法回连宿主 loopback）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"ok": False, "error": {"code": "transport", "message": str(e)}}


def data_of(resp):
    st, body = resp
    if not body:
        return None
    d = body.get("data")
    return d if body.get("ok") is True else None


def err_of(resp) -> str:
    st, body = resp
    try:
        return str((body or {}).get("error", {}).get("message", ""))
    except Exception:
        return ""


def read_config_map(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {k: v for k, v in con.execute("SELECT key, value FROM config").fetchall()}
    except Exception:  # noqa: BLE001
        return {}
    finally:
        con.close()


def db_query(db_path: Path, sql: str):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def db_tables(db_path: Path) -> list[str]:
    return [r[0] for r in db_query(db_path, "SELECT name FROM sqlite_master WHERE type='table'")]


def wait_port(db_path: Path, old_port: str, timeout_s: float = 40.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        port = read_config_map(db_path).get("runtime.http_port", "")
        if port and str(port) != str(old_port):
            return str(port)
        time.sleep(0.3)
    return ""


def wait_sidecar(db_path: Path, old: str, timeout_s: float = 60.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        port = read_config_map(db_path).get("runtime.sidecar_port", "")
        if port and str(port) != str(old):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    if r.status == 200:
                        return str(port)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)
    return ""


def start_app(exe: Path, data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PW_DATA_DIR"] = str(data_dir)
    env["PW_SIDECAR_FORCE_DEV"] = "1"  # 钉死 sidecar 到当前源码（防旧快照）
    return subprocess.Popen(
        [str(exe)], cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_app(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()


# ---------------------------------------------------------------- mock Agent

class MockAgentHandler(BaseHTTPRequestHandler):
    """最小 mock 外部 Agent：/health 与 /invoke（回显 action）。"""

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"ok": False})

    def do_POST(self) -> None:
        if self.path == "/invoke":
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw.decode())
            except Exception:
                body = {}
            self._send(200, {"ok": True, "data": {"echo": body.get("action")}})
        else:
            self._send(404, {"ok": False})


def start_mock_agent() -> tuple[ThreadingHTTPServer, int]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), MockAgentHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


# ---------------------------------------------------------------- zip 造包

def make_plugin_zip(path: Path, plugin_id: str, name: str, perms: list) -> None:
    manifest = {
        "pluginId": plugin_id,
        "name": name,
        "version": "1.0.0",
        "author": "verify9",
        "description": "verify9 造包",
        "entry": "index.html",
        "permissions": perms,
        "ui": {"type": "widget", "size": "small", "route": "index.html"},
        "minAppVersion": "0.1.0",
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        zf.writestr("index.html", "<html><body>zip ok</body></html>")


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="阶段9 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    exe = (
        Path(args.exe)
        if args.exe
        else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    )
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `python tools/rust.py build --release`。")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify9-"))
    db_path = data_dir / "workspace.db"
    plugins_root = data_dir / "plugins"  # core 默认插件根 = <data_dir>/plugins

    core: subprocess.Popen | None = None
    mock_srv = None
    base = ""

    print(f"[verify9] exe = {exe}")
    print(f"[verify9] data dir = {data_dir}")

    def api(path: str, method: str = "GET", body=None, timeout: float = 30.0, headers=None):
        return http_json(base + path, method, body, timeout, headers)

    try:
        # ---------------------------------------------------------- 起 core + mock Agent
        print("\n启动 core（release）与 mock Agent ...")
        core = start_app(exe, data_dir)
        port = wait_port(db_path, "")
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port")
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            st, _ = http_json(base + "/health", timeout=3)
            if st == 200:
                break
            time.sleep(0.3)
        sc_port = wait_sidecar(db_path, "")
        print(f"  core http = {base}")
        check("前置：core 存活 + sidecar /health 可用", bool(sc_port),
              f"sidecar port={sc_port or '（未就绪）'}")
        mock_srv, mock_port = start_mock_agent()
        mock_url = f"http://127.0.0.1:{mock_port}"
        print(f"  mock agent = {mock_url}")

        # ---------------------------------------------------------- 前置：契约 v11
        # 注（TECH-04 §一）：契约版本在 TECH-04 升到 v12（登记 canonical 的 L1 键，
        # 无表结构变更）。本断言的**意图**是"迁移 0008 已生效 ⇒ 契约版本至少 v11"，
        # 故改用 `>=` 表达该意图，而不是钉死等于某个后续会继续增长的常量。
        st_v, b_v = api("/api/v1/config/schema_version")
        check("前置：契约版本 ≥ v11（迁移 0008 生效）", (data_of((st_v, b_v)) or 0) >= 11,
              f"schema_version={data_of((st_v, b_v))}")
        check("前置：plugin_audit 表已建（0008）", "plugin_audit" in db_tables(db_path))

        cfg_ext, b_ext = api("/api/v1/config/agents.external")
        cfg_en, b_en = api("/api/v1/config/widget.desktop.enabled")
        check("前置：新配置键默认值（agents.external='[]' / widget.desktop.enabled=false）",
              data_of((cfg_ext, b_ext)) == "[]" and data_of((cfg_en, b_en)) is False,
              f"agents.external={data_of((cfg_ext, b_ext))!r} (raw={json.dumps(b_ext, ensure_ascii=False)[:160]}) "
              f"enabled={data_of((cfg_en, b_en))!r} (raw={json.dumps(b_en, ensure_ascii=False)[:160]})")

        # ======================================================== 验收 1 零改动扩展
        print("\n--- 验收项 1：零改动扩展 ★（示例插件拷入 → 发现 → 安装 → 能力调用）" + "-" * 12)
        src = REPO_ROOT / "plugins" / "examples"
        for pid in ("com.example.pomodoro", "com.example.music"):
            shutil.copytree(src / pid, plugins_root / pid)
        st_d, b_d = api("/api/v1/plugins/discover")
        got_d = data_of((st_d, b_d)) or []
        got_ids = {(p.get("manifest") or {}).get("pluginId") for p in got_d}
        check("1a 拷贝即发现（discover 不落库，manifest 完整可解析）",
              st_d == 200 and {"com.example.pomodoro", "com.example.music"} <= got_ids,
              f"discovered={[p.get('manifest', {}).get('pluginId') if p.get('valid') else ('INVALID:' + str(p.get('errors'))) for p in got_d]}")

        st_i, b_i = api("/api/v1/plugins/install", "POST", {"sourceDir": str(plugins_root / "com.example.pomodoro")})
        inst = data_of((st_i, b_i)) or {}
        check("1b 安装成功（返回 manifest 公开形态）",
              st_i == 200 and inst.get("installed") is True
              and (inst.get("plugin") or {}).get("pluginId") == "com.example.pomodoro",
              f"status={st_i} err={err_of((st_i, b_i))!r}")

        st_e, b_e = api("/api/v1/plugins/enabled", "POST", {"pluginId": "com.example.pomodoro", "enabled": True})
        st_l0, b_l0 = api("/api/v1/plugins")
        rows_now = data_of((st_l0, b_l0)) or []
        pom_now = next((r for r in rows_now if r.get("pluginId") == "com.example.pomodoro"), {})
        check("1c 启用成功且列表状态翻转",
              st_e == 200 and pom_now.get("enabled") is True,
              f"status={st_e} err={err_of((st_e, b_e))!r} enabled={pom_now.get('enabled')}")

        # 网关：data.set / data.get 往返（data:own 已授权）
        st_s, b_s = api("/api/v1/plugin/api", "POST", {
            "pluginId": "com.example.pomodoro", "api": "data", "method": "set",
            "payload": {"key": "cycles", "value": 3},
        })
        ok_s = st_s == 200 and (data_of((st_s, b_s)) or {}).get("saved") is True
        st_g, b_g = api("/api/v1/plugin/api", "POST", {
            "pluginId": "com.example.pomodoro", "api": "data", "method": "get",
            "payload": {"key": "cycles"},
        })
        got_val = (data_of((st_g, b_g)) or {}).get("value")
        check("1d 网关能力调用往返（data.set → data.get 回读 3）",
              ok_s and st_g == 200 and got_val == 3,
              f"set={ok_s} value={got_val!r} err={err_of((st_s, b_s))!r}/{err_of((st_g, b_g))!r}")

        # 落点隔离断言：文件在 plugins/<id>/data/ 下
        data_file = plugins_root / "com.example.pomodoro" / "data" / "cycles.json"
        check("1e 数据隔离落点正确（plugins/<id>/data/cycles.json）", data_file.exists(),
              f"path={data_file}")

        # zip 导入链路（sidecar 解包 → core 安装）
        zip_path = data_dir / "ext.zip"
        make_plugin_zip(zip_path, "com.verify.zipped", "压缩包插件", ["data:own"])
        st_z, b_z = api("/api/v1/plugins/import", "POST", {"zipPath": str(zip_path)})
        z = data_of((st_z, b_z)) or {}
        check("1f zip 导入（sidecar 解包 → core 安装）",
              st_z == 200 and (z.get("plugin") or {}).get("pluginId") == "com.verify.zipped",
              f"status={st_z} err={err_of((st_z, b_z))!r}")

        # 非法 manifest 拒装
        bad_dir = plugins_root / "com.bad.plugin"
        (bad_dir / "main").mkdir(parents=True, exist_ok=True)
        (bad_dir / "manifest.json").write_text('{"pluginId":"com.bad.plugin","name":"x"}', encoding="utf-8")
        st_bad, _ = api("/api/v1/plugins/install", "POST", {"sourceDir": str(bad_dir)})
        check("1g 坏 manifest 拒装（缺 entry/version）", st_bad == 400, f"status={st_bad}")

        # ======================================================== 验收 3 权限展示
        print("\n--- 验收项 3：权限展示（安装即授权，清单与 manifest 一致）" + "-" * 12)
        st_l, b_l = api("/api/v1/plugins")
        rows = data_of((st_l, b_l)) or []
        pom = next((r for r in rows if r.get("pluginId") == "com.example.pomodoro"), {})
        perms = [p.get("permission") for p in pom.get("permissions", [])]
        check("3 插件列表返回完整权限清单（= manifest 声明）",
              set(perms) == {"data:own", "ui:widget"}, f"permissions={perms}")

        # ======================================================== 验收 2 权限拦截
        print("\n--- 验收项 2：权限拦截（未声明 → 403 + 审计 denied + 事件）" + "-" * 12)
        st_deny, b_deny = api("/api/v1/plugin/api", "POST", {
            "pluginId": "com.example.pomodoro", "api": "net", "method": "http",
            "payload": {"url": "http://api.example.com/x"},
        })
        denied_rows = db_query(
            db_path,
            "SELECT outcome FROM plugin_audit WHERE plugin_id='com.example.pomodoro' AND outcome='denied'",
        )
        check("2 未授权能力被拦（403 plugin_permission_denied + 审计 denied）",
              st_deny == 403 and len(denied_rows) >= 1,
              f"status={st_deny} err={err_of((st_deny, b_deny))!r} denied_rows={len(denied_rows)}")

        # ======================================================== 验收 4 崩溃隔离
        print("\n--- 验收项 4：崩溃隔离（上报崩溃 → 审计 + 主程序无恙）" + "-" * 12)
        st_c, _ = api("/api/v1/plugin/crash", "POST", {"pluginId": "com.example.pomodoro", "reason": "boom"})
        err_rows = db_query(
            db_path,
            "SELECT outcome FROM plugin_audit WHERE plugin_id='com.example.pomodoro' AND action='plugin.crash'",
        )
        st_h, _ = api("/health", timeout=5)
        check("4 崩溃上报写审计且主程序存活（/health 仍 200）",
              st_c == 200 and len(err_rows) >= 1 and st_h == 200,
              f"crash={st_c} audit={len(err_rows)} health={st_h}")

        # ======================================================== 验收 5 卸载清理
        print("\n--- 验收项 5：卸载清理（目录没了 + 表无残留 + 审计保留）" + "-" * 12)
        # 先给 zipped 插件留审计
        api("/api/v1/plugin/api", "POST", {
            "pluginId": "com.verify.zipped", "api": "data", "method": "set",
            "payload": {"key": "k", "value": 1},
        })
        st_u, _ = api("/api/v1/plugins/uninstall", "POST", {"pluginId": "com.verify.zipped"})
        left_dirs = [p.name for p in plugins_root.iterdir() if p.name == "com.verify.zipped"]
        db_plugins = db_query(db_path, "SELECT COUNT(*) FROM plugins WHERE plugin_id='com.verify.zipped'")
        db_perms = db_query(db_path, "SELECT COUNT(*) FROM plugin_permissions WHERE plugin_id='com.verify.zipped'")
        db_audit = db_query(db_path, "SELECT COUNT(*) FROM plugin_audit WHERE plugin_id='com.verify.zipped'")
        check("5 卸载：目录删除 + plugins/plugin_permissions 无行 + audit 保留",
              st_u == 200 and not left_dirs and db_plugins[0][0] == 0 and db_perms[0][0] == 0 and db_audit[0][0] >= 1,
              f"dir={left_dirs} plugins={db_plugins[0][0]} perms={db_perms[0][0]} audit={db_audit[0][0]}")

        # ======================================================== 验收 7/9 小组件
        print("\n--- 验收项 7/9：小组件（独立窗口 + 边界持久化）" + "-" * 12)
        st_t, b_t = api("/api/v1/desktop-widget/toggle", "POST")
        st_s1, b_s1 = api("/api/v1/desktop-widget/status")
        s1 = data_of((st_s1, b_s1)) or {}
        check("7a 小组件可开（真实独立窗口创建，open=true）",
              st_t == 200 and s1.get("open") is True and s1.get("enabled") is True,
              f"toggle={st_t} err={err_of((st_t, b_t))!r} status={s1}")

        st_bd, b_bd = api("/api/v1/desktop-widget/bounds", "POST", {"x": 222.0, "y": 333.0, "w": 400.0, "h": 560.0})
        cfg2 = read_config_map(db_path).get("widget.desktop.config", "")
        try:
            cfg2_j = json.loads(cfg2)
            if isinstance(cfg2_j, str):  # config 存的是 JSON 字符串，需解两层
                cfg2_j = json.loads(cfg2_j)
        except Exception:
            cfg2_j = {}
        check("9a 边界持久化（config 落盘 x=222 y=333）",
              st_bd == 200 and cfg2_j.get("x") == 222 and cfg2_j.get("y") == 333,
              f"status={st_bd} err={err_of((st_bd, b_bd))!r} config={cfg2[:120]!r}")

        st_t2, _ = api("/api/v1/desktop-widget/toggle", "POST")
        st_s2, b_s2 = api("/api/v1/desktop-widget/status")
        s2 = data_of((st_s2, b_s2)) or {}
        check("7b 小组件可关（open=false，enabled 同步 false）",
              st_t2 == 200 and s2.get("open") is False and s2.get("enabled") is False,
              f"status={s2}")

        # ======================================================== 验收 10 外部 Agent
        print("\n--- 验收项 10：外部 Agent（mock 通信 + 权限 + 逐次确认）" + "-" * 12)
        st_gw0, _ = api("/api/v1/agent/gateway", "POST", {"action": "mode.read", "payload": {}})
        check("10a 无身份（缺 X-Agent-Name）→ 401", st_gw0 == 401, f"status={st_gw0}")

        st_gw1, _ = api("/api/v1/agent/gateway", "POST", {"action": "mode.read", "payload": {}},
                        headers={"X-Agent-Name": "Ghost"})
        check("10b 未注册 Agent → 401", st_gw1 == 401, f"status={st_gw1}")

        st_reg, b_reg = api("/api/v1/agents", "PUT", [
            {"name": "MockBot", "url": mock_url, "transport": "http",
             "permissions": ["mode:read", "project:read", "mode:switch"], "timeoutMs": 5000},
        ])
        check("10c 注册 mock Agent（校验通过）",
              st_reg == 200 and (data_of((st_reg, b_reg)) or {}).get("count") == 1,
              f"status={st_reg}")

        st_h2, b_h2 = api("/api/v1/agent/health", "POST", {"name": "MockBot"})
        check("10d 健康检查通（core → Agent）",
              st_h2 == 200 and (data_of((st_h2, b_h2)) or {}).get("healthy") is True,
              f"status={st_h2}")

        st_inv, b_inv = api("/api/v1/agent/invoke", "POST",
                            {"name": "MockBot", "action": "hello", "payload": {"a": 1}})
        # invoke 返回 {status, body:{ok,data:{echo}}} —— mock Agent 的原始信封
        inv = data_of((st_inv, b_inv)) or {}
        echo = ((inv.get("body") or {}).get("data") or {}).get("echo")
        check("10e 调用 mock Agent（POST /invoke 回显）",
              st_inv == 200 and echo == "hello",
              f"status={st_inv} err={err_of((st_inv, b_inv))!r} echo={echo!r}")

        st_p, _ = api("/api/v1/agent/gateway", "POST", {"action": "profile.read", "payload": {}},
                      headers={"X-Agent-Name": "MockBot"})
        check("10f 无权限 action → 403（profile:read 未授予）", st_p == 403, f"status={st_p}")

        st_mr, b_mr = api("/api/v1/agent/gateway", "POST", {"action": "mode.read", "payload": {}},
                          headers={"X-Agent-Name": "MockBot"})
        mr = data_of((st_mr, b_mr)) or {}
        check("10g 有权限 action 通（mode.read 返回 current+modes）",
              st_mr == 200 and "current" in mr and "modes" in mr, f"status={st_mr}")

        st_ms, _ = api("/api/v1/agent/gateway", "POST",
                       {"action": "mode.switch", "payload": {"modeName": "whatever"}},
                       headers={"X-Agent-Name": "MockBot"})
        check("10h mode.switch 缺逐次确认 → 400（红线）", st_ms == 400, f"status={st_ms}")

        agent_audit = db_query(db_path, "SELECT COUNT(*) FROM plugin_audit WHERE plugin_id='agent:MockBot'")
        check("10i Agent 调用全部入审计（plugin_audit, plugin_id=agent:MockBot）",
              agent_audit[0][0] >= 4, f"audit_rows={agent_audit[0][0]}")

        st_badagent, _ = api("/api/v1/agents", "PUT", [
            {"name": "Bad", "url": "https://localhost:1", "transport": "http"},
        ])
        check("10j https url 拒收（无 TLS 能力，如实拒绝）", st_badagent == 400, f"status={st_badagent}")

        # ======================================================== 验收 6/8/11 + 声明
        print("\n--- 验收项 6/8/11：如实声明与静态判据" + "-" * 12)
        core_src = REPO_ROOT / "core" / "src"
        special_case = 0
        for py in core_src.rglob("*.rs"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            special_case += text.count('plugin_id == "')
        check("11 core 无插件特判（`plugin_id == \"` 零命中）", special_case == 0,
              f"hits={special_case}")

        print("\n  [如实声明] 验收项 6（iframe 10s 加载超时）：判据在 UI 宿主层（PluginFrame），")
        print("             机器只判坏 manifest 拒装（1g 已过）；真实超时人工核验。")
        print("  [如实声明] 验收项 8（小组件 CPU<1%）：需长周期采样，人工核验。")
        print("  [如实声明] 验收项 7（最小化主窗口后仍置顶显示）与 10（confirm=true 全路径切换）：")
        print("             会与真实桌面交互，机器不强测，人工核验（红线 V6）。")
        print("  [如实声明] pwplugin:// 协议与 WebSocket Agent：分别由单测（serve_file 路径守卫）")
        print("             与契约（预留未实现）覆盖。")

        return summarize()

    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] {exc}")
        return 2
    finally:
        stop_app(core)
        if mock_srv:
            mock_srv.shutdown()
        if args.keep:
            print(f"\n[verify9] 保留现场：{data_dir}")
        else:
            shutil.rmtree(data_dir, ignore_errors=True)


def summarize() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n===== verify_stage9：{passed}/{total} =====")
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL {name}  {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
