#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 层单元测试（阶段5）

覆盖三条线：
  1. **红线 V2 隔离**（最重要）—— 咨询模式必须拿不到任何用户数据
  2. Provider 抽象 —— 注册表完整性、占位 Provider 必须诚实抛错
  3. 凭据安全（红线 V1）—— 掩码不泄露明文
  4. 提示词渲染 —— 变量替换与漏传暴露

运行：python tools/test_ai.py

注：本文件内的 sk-* 字样全部是**测试用假密钥（fake key）**，不是真实凭据。
门禁 tools/gate.py 的 check_secrets 对 tools/ 目录下的测试语境假值有窄口径豁免
（见 V1x 记账行），此处显式登记以免后人误判。
"""

from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 只加仓库根 —— `ai` 是正规包（其内部一律用绝对导入 `from ai.xxx import`），
# 这样测试与 sidecar 加载到的是**同一批模块对象**。
# 以往踩过的坑：把 `ai/providers` 也塞进 sys.path，会让 `base` 被加载两次，
# `except ProviderError` 抓不到真正抛出的那个类。
sys.path.insert(0, ROOT)

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  [FAIL] {name} {detail}")


def section(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 60 - len(title)))


def main() -> int:
    # ---------------------------------------------------------------- 导入
    section("导入与注册表")
    try:
        from ai.context import (  # noqa: PLC0415
            MODE_CONSULT,
            MODE_WORKSPACE,
            ContextSource,
            assemble,
            permission_scope,
        )
        from ai.credentials import CredentialStore  # noqa: PLC0415
        from ai.prompt_renderer import render, unresolved  # noqa: PLC0415
        from ai.providers import registry  # noqa: PLC0415
        from ai.providers.base import ProviderConfig, ProviderError  # noqa: PLC0415

        check("ai 模块可导入", True)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        check("ai 模块可导入", False, str(e))
        return 1

    # 08 §1 要求六个 Provider
    expected = {"openai", "deepseek", "compatible", "ollama", "lmstudio", "web-ai", "user-agent"}
    have = set(registry.PROVIDERS.keys())
    check(
        "注册表覆盖 08 §1 的 Provider 集合",
        expected.issubset(have),
        f"缺：{expected - have}" if expected - have else "",
    )
    # 其中前四个必须已实现（enabled=True）
    for pid in ("openai", "deepseek", "compatible", "ollama", "lmstudio"):
        meta = registry.PROVIDERS.get(pid)
        check(f"{pid} 已启用", bool(meta and meta.enabled))
    # 占位必须标记未启用
    for pid in ("web-ai", "user-agent"):
        meta = registry.PROVIDERS.get(pid)
        check(f"{pid} 标记为未实现（enabled=False）", bool(meta and not meta.enabled))

    # ---------------------------------------------------------------- 红线 V2
    section("红线 V2：双模式隔离（核心）")

    secret_source = ContextSource(
        mode_name="AI开发模式",
        mode_apps=["VSCode", "Chrome"],
        project_dir="D:/projects/secret-project",
        learning_goal="掌握 Rust 异步",
        profile_skills=["Python", "Rust"],
    )

    # 咨询模式：无论传什么上下文素材，都必须产出零用户数据
    consult = assemble(MODE_CONSULT, secret_source)
    leaked = [
        token
        for token in (
            "AI开发模式",
            "VSCode",
            "Chrome",
            "secret-project",
            "掌握 Rust 异步",
            "Python",
            "Rust",
        )
        if token in consult.system_prompt
    ]
    check(
        "consult 模式提示词不含任何用户数据",
        not leaked,
        f"泄露：{leaked}",
    )
    check("consult 模式 used_scopes 为空", consult.used_scopes == [])
    check(
        "consult 模式权限范围为 0",
        permission_scope(MODE_CONSULT, {"mode": True, "project": True}) == [],
    )

    # 工作助手模式：传了就要用上（证明不是"两边都空"的假隔离）
    ws = assemble(MODE_WORKSPACE, secret_source)
    check(
        "workspace 模式**确实**注入了上下文（对照组）",
        "AI开发模式" in ws.system_prompt and "secret-project" in ws.system_prompt,
        f"实际：{ws.system_prompt[:120]}",
    )
    check("workspace 模式 used_scopes 非空", len(ws.used_scopes) > 0)

    # 开关生效：关掉 project 就不该出现项目路径
    ws_off = assemble(MODE_WORKSPACE, secret_source, enabled={"project": False})
    check(
        "workspace 模式尊重来源开关（关 project → 无路径）",
        "secret-project" not in ws_off.system_prompt,
    )

    # ---------------------------------------------------------------- Provider 抽象
    section("Provider 抽象")

    # 占位 Provider 必须抛错，不得静默返回空
    from ai.providers.base import Message  # noqa: PLC0415

    for pid in ("web-ai", "user-agent"):
        impl = registry.PROVIDERS[pid].impl
        try:
            list(impl.chat([Message(role="user", content="hi")], config=ProviderConfig()))
            check(f"{pid}.chat() 必须抛错而不是返回空", False, "静默返回了")
        except ProviderError as e:
            check(f"{pid}.chat() 诚实抛错", "not_implemented" in e.code)

    # 未知 provider 必须抛 KeyError（不静默兜底）
    try:
        registry.get("no-such-provider")
        check("未知 Provider 抛错", False, "未抛错")
    except KeyError:
        check("未知 Provider 抛错", True)

    # 未配置 key 时，云端 Provider 必须报 no_api_key（08 §7 降级表第一行）
    from ai.credentials import store as cred_store  # noqa: PLC0415

    cs = cred_store()
    cs.delete("pw/openai/default")  # 确保干净
    from ai.service import ChatRequest, prepare  # noqa: PLC0415

    try:
        prepare(ChatRequest(provider="openai", messages=[{"role": "user", "content": "hi"}]))
        check("未配置 key 时报 no_api_key", False, "未抛错")
    except ProviderError as e:
        check("未配置 key 时报 no_api_key", e.code == "no_api_key", f"实际 code={e.code}")

    # ---------------------------------------------------------------- 红线 V1
    section("红线 V1：凭据掩码不泄露明文")

    secret = "sk-fake-dummy-abcdefghijklmnopqrstuvwxyz123456"  # 测试用假密钥，非凭据
    masked = CredentialStore.mask(secret)
    check("掩码不含完整密钥", secret not in masked, f"masked={masked}")
    check("掩码保留头尾便于识别", masked.startswith("sk-") and masked.endswith("3456"), masked)
    check("短密钥全遮蔽", CredentialStore.mask("abc123") == "******")

    # ---------------------------------------------------------------- 提示词
    section("提示词渲染")

    prompts = ["consult_default", "study_assistant", "dev_assistant"]
    for name in prompts:
        try:
            text = render(name, {"context": "测试上下文"})
            check(f"模板 {name} 可加载", len(text) > 0)
        except Exception as e:  # noqa: BLE001
            check(f"模板 {name} 可加载", False, str(e))

    # 未提供变量时原样保留（暴露漏传），不静默变空
    out = render("study_assistant", {})
    check("未传变量时原样保留 {{context}}", "{{context}}" in out)

    # 提供了就替换
    out2 = render("study_assistant", {"context": "CTX-MARKER"})
    check("传变量后替换成功", "CTX-MARKER" in out2 and "{{context}}" not in out2)

    # 非法模板名（目录穿越）必须拒绝
    from ai.prompt_renderer import TemplateError  # noqa: PLC0415

    try:
        render("../../etc/passwd", {})
        check("拒绝目录穿越的模板名", False, "未拒绝")
    except TemplateError:
        check("拒绝目录穿越的模板名", True)
    except Exception as e:  # noqa: BLE001
        check("拒绝目录穿越的模板名", False, f"抛了非预期异常：{e}")

    # ---------------------------------------------------------------- 汇总
    print("\n" + "=" * 68)
    print(f"结果：PASS={PASSED}  FAIL={FAILED}")
    if FAILURES:
        print("\n失败明细：")
        for f in FAILURES:
            print(f"  - {f}")
    return 0 if FAILED == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
