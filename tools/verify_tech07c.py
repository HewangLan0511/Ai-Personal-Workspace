#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TECH-07-C Phase C1 验收脚本
============================
按任务要求验证五项：
  1. 原型视觉 token 被引用（--bg-sunken 在真实 tokens.css Semantic 层定义 + RunView 引用）
  2. 无第二套 CSS 体系（RunView 无硬编码色值；styles 目录无新增 token 文件）
  3. /run 路由存在（router 注册 RunView）
  4. adapter 边界存在（workspace/runtime 齐备；FORBIDDEN_COMMANDS 不被 facts/actions 触碰）
  5. UI 没有直接调用 core（RunView 零 @/api / tauri invoke；@/api 实际 import 只出现在 workspace/runtime）

范围说明：
  - "UI 不直连 core" 只约束 TECH-07-C 之后的**新融合面**（C1 = RunView 及后续融合页）。
    存量已验收视图（LayoutView / SettingsView 等）的 @/api 引用是既有架构，不在 C1 红线内
    （C1 原则：不修改已有已验收模块逻辑）。
  - 扫描命令/导入前先剥离注释，避免把「说明性文字」误判为真实调用。

用法：python tools/verify_tech07c.py
退出码：0 = 全绿；1 = 存在红灯。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
RUNTIME = UI / "src" / "workspace" / "runtime"
RUNVIEW = UI / "src" / "views" / "RunView.vue"
ROUTER = UI / "src" / "router" / "index.ts"
TOKENS = UI / "src" / "styles" / "tokens.css"
STYLES = UI / "src" / "styles"

results: list[tuple[bool, str, str]] = []  # (ok, check_id, detail)


def check(ok: bool, cid: str, detail: str) -> None:
    results.append((ok, cid, detail))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(src: str) -> str:
    """剥掉 /* */ 块注释、// 行注释和 JSDoc 的 * 前缀行，只留真实代码。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    lines = []
    for ln in src.splitlines():
        s = ln.strip()
        if s.startswith("*") or s.startswith("//"):
            continue
        lines.append(ln)
    return "\n".join(lines)


# ---------------------------------------------------------------- 1. tokens
def check_tokens() -> None:
    try:
        css = read(TOKENS)
    except OSError as e:
        check(False, "T7C-1a", f"tokens.css 读取失败: {e}")
        return

    # 亮色定义（:root 块内）
    root_block = css.split("[data-theme", 1)[0]
    dark_block = css.split("[data-theme", 1)[1] if "[data-theme" in css else ""
    ok_light = "--bg-sunken:" in root_block
    ok_dark = "--bg-sunken:" in dark_block
    check(ok_light, "T7C-1a", f"--bg-sunken 亮色(:root)定义: {'OK' if ok_light else 'MISSING'}")
    check(ok_dark, "T7C-1b", f"--bg-sunken 暗色([data-theme='dark'])定义: {'OK' if ok_dark else 'MISSING'}")

    rv = read(RUNVIEW)
    ok_ref = "var(--bg-sunken" in rv
    check(ok_ref, "T7C-1c", f"RunView 引用 var(--bg-sunken): {'OK' if ok_ref else 'MISSING'}")


# ---------------------------------------------------- 2. 无第二套 CSS 体系
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def check_no_second_css() -> None:
    rv = read(RUNVIEW)
    hexes = [m.group(0) for m in HEX_RE.finditer(rv)]
    check(not hexes, "T7C-2a", f"RunView 硬编码色值: {'无' if not hexes else hexes[:5]}")

    # 自定义属性私造检测：RunView <style> 内不允许定义 --x:（消费 var() 可以）
    defined = re.findall(r"(--[\w-]+)\s*:", rv)
    check(not defined, "T7C-2b", f"RunView 私造 token: {'无' if not defined else defined[:5]}")

    files = sorted(p.name for p in STYLES.glob("*.css"))
    allowed = ["base.css", "motion-tokens.css", "tokens.css"]
    extra = [f for f in files if f not in allowed]
    check(not extra, "T7C-2c", f"styles 目录新增 token 文件: {'无' if not extra else extra}")


# ---------------------------------------------------------- 3. /run 路由
def check_route() -> None:
    r = read(ROUTER)
    has_path = re.search(r"path:\s*['\"]/run['\"]", r) is not None
    has_comp = "RunView.vue" in r
    check(has_path and has_comp, "T7C-3", f"/run 路由注册: path={'OK' if has_path else 'MISSING'} comp={'OK' if has_comp else 'MISSING'}")
    check(RUNVIEW.exists(), "T7C-3b", f"RunView.vue 存在: {'OK' if RUNVIEW.exists() else 'MISSING'}")


# ------------------------------------------------------ 4. adapter 边界
# C3 演进（2026-09-16）：windows_place 移入 ALLOWED（actuate 段，仅移动/缩放），
# FORBIDDEN 相应收窄并新增 windows_close / apps_terminate 明确禁区。本清单随之更新。
FORBIDDEN = [
    "windows_activate", "windows_find", "windows_rect",
    "layout_apply", "mode_restore", "modes_capture_current", "apps_launch",
    "windows_close", "apps_terminate",
]
ALLOWED = [
    "modes_list", "modes_current", "mode_progress", "layouts_list",
    "monitors_list", "windows_list", "apps_list", "windows_place",
    "mode_apply", "mode_cancel", "mode_exit",
]


def check_adapter() -> None:
    names = ["boundary.ts", "facts.ts", "actions.ts", "index.ts"]
    missing = [n for n in names if not (RUNTIME / n).exists()]
    check(not missing, "T7C-4a", f"workspace/runtime 四文件: {'齐备' if not missing else missing}")

    b = read(RUNTIME / "boundary.ts")
    ok_f = all(re.search(rf"['\"]{c}['\"]", b) for c in FORBIDDEN)
    ok_a = all(re.search(rf"['\"]{c}['\"]", b) for c in ALLOWED)
    check(ok_f, "T7C-4b", "boundary.ts FORBIDDEN_COMMANDS 清单: " + ("OK" if ok_f else "INCOMPLETE"))
    check(ok_a, "T7C-4c", "boundary.ts ALLOWED_COMMANDS 清单: " + ("OK" if ok_a else "INCOMPLETE"))

    # facts/actions/index 的【代码】不得出现任何黑名单命令（注释里的说明不算）
    leaks: list[str] = []
    for n in ["facts.ts", "actions.ts", "index.ts"]:
        t = strip_comments(read(RUNTIME / n))
        for c in FORBIDDEN:
            if c in t:
                leaks.append(f"{n}:{c}")
    check(not leaks, "T7C-4d", f"facts/actions 代码触碰黑名单命令: {'无' if not leaks else leaks}")

    # workspace 域内，runtime/ 之外的文件不得有真实的 @/api import（注释中的"零 @/api"声明不算）
    ws_dir = UI / "src" / "workspace"
    outside = sorted(
        str(p.relative_to(ws_dir))
        for p in ws_dir.rglob("*.ts")
        if RUNTIME not in p.parents
        and re.search(r"from\s+['\"]@/api", strip_comments(read(p)))
    )
    check(not outside, "T7C-4e", f"workspace 域内 runtime 之外真实 import @/api: {'无' if not outside else outside}")


# ------------------------------------------------ 5. UI 不直连 core
# 范围：TECH-07-C 的新融合面（C1 = RunView）。存量已验收视图的 @/api 引用
# 是既有架构（TECH-02 前即如此），不在 C1 红线内，也不允许为通过验收去改它们。
def check_ui_boundary() -> None:
    rv_code = strip_comments(read(RUNVIEW))
    bad = re.findall(r"from\s+['\"]@/api[^'\"]*['\"]", rv_code)
    check(not bad, "T7C-5a", f"RunView import @/api: {'无' if not bad else bad}")

    # 直连 tauri invoke 同样视为"直连 core"
    tauri = re.findall(r"from\s+['\"]@tauri-apps/api[^'\"]*['\"]", rv_code)
    check(not tauri, "T7C-5b", f"RunView 直连 tauri invoke: {'无' if not tauri else tauri}")

    imports = re.findall(r"from\s+['\"]([^'\"]+)['\"]", rv_code)
    ok_src = all(
        i.startswith(".") or i.startswith("@/") and (
            i.startswith("@/workspace/runtime") or i.startswith("@/stores/ai")
        )
        for i in imports
        if not i.startswith("vue")
    )
    check(ok_src, "T7C-5c", f"RunView import 白名单(vue/vue-router/workspace/runtime/stores/ai): {'OK' if ok_src else imports}")


def main() -> int:
    if not UI.exists():
        print(f"FATAL: ui 目录不存在: {UI}")
        return 1
    check_tokens()
    check_no_second_css()
    check_route()
    check_adapter()
    check_ui_boundary()

    print("=" * 64)
    print("TECH-07-C Phase C1 验收")
    print("=" * 64)
    failed = 0
    for ok, cid, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{mark}] {cid}  {detail}")
    print("-" * 64)
    total = len(results)
    print(f"{total - failed}/{total} 通过")
    if failed:
        print(f"红灯 {failed} 项 —— C1 验收不通过")
        return 1
    print("C1 验收全绿。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
