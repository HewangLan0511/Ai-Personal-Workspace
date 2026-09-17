#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PW-INTEGRATION-003 Contract Freeze —— 契约静态验证门禁。

性质：**静态**（不启浏览器、不连 core、不碰数据库）。只校验
`docs/contracts/` 下的 schema 与 fixture，属于「本轮允许的静态验证工具」。

为什么要有它（而不是只写文档）：
    文档里的「v1 边界」是**承诺**，不是**判据**。本脚本把承诺变成可执行门禁 ——
    任何往 v1 里偷塞 v2 字段（历史快照 / 多版本 / 跨重启 hwnd 永久身份）的改动，
    都会在这里变红；任何把明文密钥写进契约的改动，同样变红（红线 V1）。

约定：
    * fixture 顶层以 `_` 开头的键是**测试元数据**（`_fixture` / `_expectedFailure`），
      校验前剥离，不参与契约校验。
    * 反向 fixture（预期失败）用 `_expectedFailure` 声明**必须出现的错误签名**；
      只要有一条错误包含该签名即判通过 —— 这样"门禁真的会拦"是被证明的，
      而不是靠肉眼相信。

用法：
    python tools/verify_contracts.py            # 跑全部 fixture
    python tools/verify_contracts.py -v         # 额外打印每条错误
退出码：0 = 全部符合预期；1 = 有 fixture 与预期不符；2 = 环境/路径问题。
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTRACTS = os.path.join(ROOT, "docs", "contracts")
FIXTURES = os.path.join(CONTRACTS, "fixtures")
SNAPSHOT_SCHEMA = os.path.join(CONTRACTS, "workspace-snapshot.v1.schema.json")

# 归一化坐标一致性容差：像素取整 + 归一化保留 4 位小数 ⇒ 0.02 足够宽，又拦得住 0.4 级别的写错
NORM_TOL = 0.02

# 明文密钥键名特征（红线 V1：只进系统凭据库，契约/配置/日志都不得出现明文）
SECRET_KEY_RE = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|credential|bearer|private[_-]?key|sk-)",
    re.IGNORECASE,
)

META_KEYS = {"title", "note", "contractVersion", "configKey", "writer"}

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


# --------------------------------------------------------------------------- #
# 校验器（JSON Schema draft-07 的**子集**，够用且无第三方依赖）
# --------------------------------------------------------------------------- #

def _resolve_ref(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError(f"不支持的 $ref：{ref}")
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate_node(schema: dict, value, path: str, errors: list[str], root: dict) -> None:
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        validate_node(_resolve_ref(schema["$ref"], root), value, path, errors, root)
        return

    declared = schema.get("type")
    if declared is not None:
        types = declared if isinstance(declared, list) else [declared]
        if not _type_ok(value, types):
            errors.append(f"type:{'/'.join(types)} @ {path}")
            return

    if "const" in schema and value != schema["const"]:
        errors.append(f"const:{schema['const']} @ {path}")

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"enum:{','.join(str(v) for v in schema['enum'])} @ {path}")

    if isinstance(value, bool):
        pass  # bool 是 int 的子类，数值约束对 bool 无意义
    elif isinstance(value, (int, float)):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"minimum:{schema['minimum']} @ {path}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"maximum:{schema['maximum']} @ {path}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"exclusiveMinimum:{schema['exclusiveMinimum']} @ {path}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"minLength:{schema['minLength']} @ {path}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"maxLength:{schema['maxLength']} @ {path}")
        if "pattern" in schema and not re.match(schema["pattern"], value):
            errors.append(f"pattern:{schema['pattern']} @ {path}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"minItems:{schema['minItems']} @ {path}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"maxItems:{schema['maxItems']} @ {path}")
        if "items" in schema:
            for i, item in enumerate(value):
                validate_node(schema["items"], item, f"{path}[{i}]", errors, root)

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"required:{key} @ {path}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"unexpected-key:{key} @ {path}")
        for key, sub in props.items():
            if key in value:
                validate_node(sub, value[key], f"{path}.{key}", errors, root)


def _type_ok(value, types: list[str]) -> bool:
    for t in types:
        if t == "object" and isinstance(value, dict):
            return True
        if t == "array" and isinstance(value, list):
            return True
        if t == "string" and isinstance(value, str):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "null" and value is None:
            return True
    return False


# --------------------------------------------------------------------------- #
# 全树扫描：v2 越界字段 + 明文密钥
# --------------------------------------------------------------------------- #

def scan_tree(node, path: str, forbidden: set[str], errors: list[str]) -> None:
    if isinstance(node, dict):
        for key, child in node.items():
            if key in forbidden:
                errors.append(f"forbidden-v2-key:{key} @ {path}")
            if SECRET_KEY_RE.search(str(key)):
                errors.append(f"secret-key:{key} @ {path}")
            scan_tree(child, f"{path}.{key}", forbidden, errors)
    elif isinstance(node, list):
        for i, child in enumerate(node):
            scan_tree(child, f"{path}[{i}]", forbidden, errors)


# --------------------------------------------------------------------------- #
# Snapshot 契约的不变量（schema 表达不了的跨字段约束）
# --------------------------------------------------------------------------- #

def snapshot_invariants(doc: dict, errors: list[str]) -> None:
    monitors = doc.get("monitors")
    if not isinstance(monitors, list):
        return
    idxs = [m.get("index") for m in monitors if isinstance(m, dict)]
    if sorted(i for i in idxs if isinstance(i, int)) != list(range(len(idxs))):
        errors.append("invariant:monitors-index @ $")
    if sum(1 for m in monitors if isinstance(m, dict) and m.get("primary")) != 1:
        errors.append("invariant:monitors-primary @ $")

    by_index = {m["index"]: m for m in monitors if isinstance(m, dict) and "index" in m}

    desktop = doc.get("desktop")
    windows = desktop.get("windows") if isinstance(desktop, dict) else None
    if not isinstance(windows, list):
        return

    seen_hwnd: set[int] = set()
    for i, w in enumerate(windows):
        if not isinstance(w, dict):
            continue
        wp = f"$.desktop.windows[{i}]"
        mi = w.get("monitorIndex")
        if mi not in by_index:
            errors.append(f"invariant:monitorIndex-exists @ {wp}")
            continue
        m = by_index[mi]
        work = m.get("work") or {}
        px, norm = w.get("rectPx"), w.get("rectNorm")
        if isinstance(px, dict) and isinstance(norm, dict) and work.get("w") and work.get("h"):
            exp = {
                "x": (px.get("x", 0) - work.get("x", 0)) / work["w"],
                "y": (px.get("y", 0) - work.get("y", 0)) / work["h"],
                "w": px.get("w", 0) / work["w"],
                "h": px.get("h", 0) / work["h"],
            }
            for k, want in exp.items():
                if abs(float(norm.get(k, 0)) - want) > NORM_TOL:
                    errors.append(f"invariant:rectNorm-consistent @ {wp}")
                    break
        hwnd = w.get("hwnd")
        if isinstance(hwnd, int):
            if hwnd in seen_hwnd:
                errors.append(f"invariant:hwnd-unique @ {wp}")
            seen_hwnd.add(hwnd)

    fg = desktop.get("foregroundHwnd")
    if fg is not None and fg not in seen_hwnd:
        errors.append("invariant:foreground-present @ $")

    ws = doc.get("workspace")
    if isinstance(ws, dict):
        if ws.get("monitor") not in by_index:
            errors.append("invariant:workspace-monitor @ $")
        for j, mgd in enumerate(ws.get("managed") or []):
            if isinstance(mgd, dict) and mgd.get("hwnd") is not None:
                if mgd["hwnd"] not in seen_hwnd:
                    errors.append(f"invariant:managed-subset @ $.workspace.managed[{j}]")


# --------------------------------------------------------------------------- #
# AI Provider 契约的层次不变量
# --------------------------------------------------------------------------- #

def provider_invariants(doc: dict, errors: list[str]) -> None:
    reg = doc.get("registry") or {}
    allowed = set(reg.get("enabledIds") or []) | {""}
    canon = doc.get("canonical") or {}
    if canon.get("provider") not in allowed:
        errors.append("invariant:canonical-enabled @ $.canonical")

    # 唯一事实来源只能有一个：除 canonical 外，任何块都不得声明自己写真相
    for block in ("cache", "suggestion", "headlessDefault"):
        b = doc.get(block)
        if isinstance(b, dict) and b.get("mayWriteTruth") is not False:
            errors.append(f"invariant:no-shadow-truth @ $.{block}")

    tr = doc.get("transport") or {}
    if tr.get("mayDecide") is not False:
        errors.append("invariant:no-transport-decide @ $.transport")

    order = doc.get("resolutionOrder") or []
    if "canonical" not in order or "suggestion" not in order or order.index("canonical") > order.index("suggestion"):
        errors.append("invariant:resolution-order @ $")


# --------------------------------------------------------------------------- #
# 驱动
# --------------------------------------------------------------------------- #

def strip_meta(doc):
    if isinstance(doc, dict):
        return {k: v for k, v in doc.items() if not k.startswith("_")}
    return doc


def check_snapshot(doc: dict, schema: dict) -> list[str]:
    errors: list[str] = []
    forbidden = set(schema.get("x-pw-v2-forbidden") or [])
    scan_tree(doc, "$", forbidden, errors)
    validate_node(schema, doc, "$", errors, schema)
    snapshot_invariants(doc, errors)
    return errors


def check_provider(doc: dict) -> list[str]:
    errors: list[str] = []
    scan_tree(doc, "$", set(), errors)
    required = ("contractVersion", "canonical", "cache", "suggestion", "headlessDefault",
                "transport", "registry", "resolutionOrder")
    for key in required:
        if key not in doc:
            errors.append(f"required:{key} @ $")
    provider_invariants(doc, errors)
    return errors


def main() -> int:
    if not os.path.isdir(FIXTURES):
        print(f"[env] fixture 目录不存在：{FIXTURES}")
        return 2
    try:
        with open(SNAPSHOT_SCHEMA, encoding="utf-8") as fh:
            snapshot_schema = json.load(fh)
    except OSError as exc:
        print(f"[env] 无法读取 schema：{exc}")
        return 2

    names = sorted(n for n in os.listdir(FIXTURES) if n.endswith(".json"))
    if not names:
        print("[env] 没有 fixture")
        return 2

    print("=" * 78)
    print("PW-INTEGRATION-003 Contract Freeze —— 契约静态门禁")
    print(f"schema : {os.path.relpath(SNAPSHOT_SCHEMA, ROOT)}")
    print(f"fixture: {os.path.relpath(FIXTURES, ROOT)}  （{len(names)} 个）")
    print("=" * 78)

    failed = 0
    for name in names:
        with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
            doc = json.load(fh)
        expected = doc.get("_expectedFailure")
        clean = strip_meta(doc)

        if "workspace-snapshot" in name:
            errors = check_snapshot(clean, snapshot_schema)
        elif "ai-provider" in name:
            errors = check_provider(clean)
        else:
            errors = ["unknown-fixture-kind @ $"]

        if expected:
            ok = any(expected in e for e in errors)
            kind = "反向"
            verdict = f"PASS  (门禁按预期拦截：{expected})" if ok else f"FAIL  (未拦截预期错误：{expected})"
        else:
            ok = not errors
            kind = "正向"
            verdict = "PASS  (0 error)" if ok else f"FAIL  ({len(errors)} error)"

        if not ok:
            failed += 1
        print(f"[{kind}] {name}\n        {verdict}")
        if errors and (VERBOSE or not ok):
            for e in errors[:8]:
                print(f"          - {e}")
            if len(errors) > 8:
                print(f"          ... 另有 {len(errors) - 8} 条")

    print("-" * 78)
    print(f"结果：{len(names) - failed}/{len(names)} 符合预期")
    print("=" * 78)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
