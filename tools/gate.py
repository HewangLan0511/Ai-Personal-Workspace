#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Personal Workspace · 阶段门禁自动检查脚本
==========================================

监制归属：肉编器001号
用途：对开发 Agent 的交付做机器可复现的静态核查，产出 FAIL / WARN / PASS。

用法：
    python tools/gate.py                          # 默认检查当前基线（阶段0 + 通用卫生）
    python tools/gate.py --stage 1                # 检查阶段1的结构门禁
    python tools/gate.py --stage 4 --build        # 附带编译门禁（慢）
    python tools/gate.py --stage all --json out.json
    python tools/gate.py --list                   # 列出各阶段要求

退出码：
    0 = 通过（无 FAIL）
    1 = 不通过（存在 FAIL）
    2 = 脚本自身错误

判定口径见 docs/reviews/SUPERVISOR.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# ---------------------------------------------------------------- 基础定义

FAIL, WARN, PASS, INFO = "FAIL", "WARN", "PASS", "INFO"

SKIP_DIRS = {
    "node_modules", "target", "dist", "build", ".git", ".workbuddy",
    "__pycache__", ".venv", "venv", ".idea", ".vscode-test", "coverage",
    ".next", "out", "tmp", "temp",
}

SOURCE_EXTS = {".rs", ".ts", ".tsx", ".vue", ".js", ".mjs", ".cjs", ".py", ".toml", ".json", ".sql"}
DOC_EXTS = {".md", ".txt"}

# 扫描用扩展名（代码类，做卫生/安全扫描）
CODE_EXTS = {".rs", ".ts", ".tsx", ".vue", ".js", ".mjs", ".cjs", ".py"}

# 扫描豁免：监制工具与 CI 脚本本身含正则是字面量描述和 print 输出，不应被当作违规。
# 这是必要的自豁免——否则门禁脚本会永远把自己的检测模式定义判为违规。
SCAN_EXEMPT_PREFIXES = ("tools/",)
SCAN_EXEMPT_FILES = {"gate.py"}


def is_exempt(path_str: str) -> bool:
    if any(path_str.startswith(p) for p in SCAN_EXEMPT_PREFIXES):
        return True
    return Path(path_str).name in SCAN_EXEMPT_FILES


@dataclass
class Finding:
    level: str
    code: str
    message: str
    path: str = ""
    line: int = 0

    def render(self) -> str:
        loc = ""
        if self.path:
            loc = f"  @ {self.path}"
            if self.line:
                loc += f":{self.line}"
        return f"[{self.level}] {self.code} — {self.message}{loc}"


@dataclass
class Report:
    root: str = ""
    stage: str = ""
    findings: list[Finding] = field(default_factory=list)
    checks_run: int = 0
    checks_skipped: list[str] = field(default_factory=list)

    def add(self, level: str, code: str, message: str, path: str = "", line: int = 0):
        # 去重：同一条规则在同一位置命中多次只记一次，避免多模式重叠造成重复报告
        key = (level, code, path, line, message)
        for f in self.findings:
            if (f.level, f.code, f.path, f.line, f.message) == key:
                return
        self.findings.append(Finding(level, code, message, path, line))  # type: ignore[arg-type]
        self.checks_run += 1

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)

    @property
    def ok(self) -> bool:
        return self.count(FAIL) == 0


# ---------------------------------------------------------------- 阶段要求定义

STAGES: dict[str, dict] = {
    "0": {
        "name": "指令集与标准（已交付）",
        "required": [
            "docs/agent-dev/AGENTS.md",
            "docs/agent-dev/01-项目上下文.md",
            "docs/agent-dev/02-架构与目录规范.md",
            "docs/agent-dev/03-数据契约与接口规范.md",
            "docs/agent-dev/13-验收清单与禁止事项.md",
        ],
        "optional_note": "源计划书 txt 建议归档至 docs/source/ 以备追溯",
    },
    "1": {
        "name": "基础桌面框架",
        "required": [
            "core/Cargo.toml",
            "core/tauri.conf.json",
            "core/migrations",          # 契约 3.1：迁移脚本放 core/migrations/
            "database/schema.sql",
            "ui/package.json",
            "config/app.toml",
            "system/service.py",
            "docs/adr/ADR-001-窗口控制与进程启动实现语言.md",
        ],
        "requires_structure": [
            "core/src/state", "core/src/db", "core/src/event_bus",
            "ui/src/views", "ui/src/widgets", "ui/src/components",
            "ui/src/stores", "ui/src/api", "modules", "plugins",
        ],
    },
    "2": {
        "name": "软件管理系统",
        # ADR-001：进程启动 = Rust。原 required 里的 system/win/process.py
        # 会逼开发者去建一个"违反 ADR-001"的文件（条例自相矛盾），已移除。
        "required": ["core/src/app_manager"],
    },
    "3": {
        "name": "窗口管理系统",
        "required": ["config/layouts"],
        "requires_structure": ["core/src/window_manager"],
        # ADR-001 已定稿为 Rust，不再保留"若为 Python 实现则改 system/win/window.py"的歧义出口。
    },
    "4": {
        "name": "工作模式引擎（核心）",
        "required": ["core/src/scheduler", "config/layouts", "config/modes"],
        "core_critical": True,
    },
    "5": {
        "name": "AI 助手系统",
        "required": ["ai/providers", "ai/prompt"],
        "requires_files_glob": {
            "ai/providers": ["*.py"],
        },
    },
    "6": {
        "name": "学习成长模块",
        "required": ["modules/learning"],
    },
    "7": {
        "name": "个人数字档案",
        "required": ["modules/profile"],
    },
    "8": {
        "name": "生活中心与设备中心",
        "required": ["modules/life", "modules/device"],
    },
    "9": {
        "name": "插件系统与桌面小组件",
        "required": ["plugins"],
        "requires_files_glob": {"plugins": ["manifest.json"]},
    },
}

# 通用基线要求（任何阶段都应满足）——交接设施缺失即视为项目不可接手
BASELINE_REQUIRED = [
    "docs/agent-dev",
    "docs/reviews",
    "HANDOFF.md",
    "AGENTS.md",
    "tools/gate.py",
]


# ---------------------------------------------------------------- 扫描工具

def iter_files(root: Path, exts: set[str]):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            p = Path(dirpath) / name
            if p.suffix.lower() in exts:
                yield p


def read_text(p: Path) -> str | None:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(p)


# ---------------------------------------------------------------- 检查项

def check_structure(root: Path, stage: str, r: Report):
    """结构门禁：必需产物是否存在"""
    for b in BASELINE_REQUIRED:
        if (root / b).exists():
            r.add(PASS, "S000", f"基线目录存在：{b}")
        else:
            r.add(FAIL, "S001", f"基线目录缺失：{b}")

    spec = STAGES.get(stage)
    if not spec:
        r.checks_skipped.append(f"未知阶段 {stage}，跳过阶段结构检查")
        return

    for item in spec.get("required", []):
        p = root / item
        if p.exists():
            r.add(PASS, "S100", f"[阶段{stage}] 存在：{item}")
        else:
            r.add(FAIL, "S101", f"[阶段{stage}] 缺失必需产物：{item}")

    for item in spec.get("requires_structure", []):
        if (root / item).is_dir():
            r.add(PASS, "S110", f"[阶段{stage}] 目录结构到位：{item}")
        else:
            r.add(WARN, "S111", f"[阶段{stage}] 目录未创建：{item}")

    for base, patterns in (spec.get("requires_files_glob") or {}).items():
        bp = root / base
        if not bp.is_dir():
            continue
        found = any(
            any(fp.match(pat) for fp in bp.glob("*") if fp.is_file())
            for pat in patterns
        )
        if found:
            r.add(PASS, "S120", f"[阶段{stage}] {base} 下存在 {patterns} 文件")
        else:
            r.add(FAIL, "S121", f"[阶段{stage}] {base} 下缺少 {patterns} 文件")


def check_housekeeping(root: Path, r: Report):
    """工程卫生：构建产物 / 数据库文件不得入库。
    已被 .gitignore 覆盖的目录不算违规——本地开发必然存在这些产物。
    """
    ignored = load_gitignore(root)
    bad_names = {"node_modules", "target", ".venv", "venv", "__pycache__"}
    for d in bad_names:
        hits = [p for p in root.rglob(d) if p.is_dir()]
        if hits:
            # 只报顶层直接存在（不算子目录里的）
            top = [h for h in hits if len(h.relative_to(root).parts) <= 2]
            flagged_top = [h for h in top if not is_ignored(h, root, ignored)]
            flagged_deep = [
                h for h in hits
                if not is_ignored(h, root, ignored) and (h not in top)
            ]
            if flagged_top:
                r.add(
                    FAIL,
                    "H001",
                    f"未被 .gitignore 覆盖的构建/依赖产物目录（应加入 .gitignore 或删除）："
                    f"{rel(root, flagged_top[0])}",
                )
            if flagged_deep:
                r.add(
                    WARN,
                    "H002",
                    f"存在未被忽略的构建产物目录（较深）：{rel(root, flagged_deep[0])}",
                )

    for p in iter_files(root, {".db", ".sqlite", ".sqlite3"}):
        if is_ignored(p, root, ignored):
            continue
        r.add(FAIL, "H010", "数据库文件混入仓库", rel(root, p))

    for p in iter_files(root, {".log", ".tmp"}):
        if is_ignored(p, root, ignored):
            continue
        r.add(WARN, "H011", "临时/日志文件混入仓库", rel(root, p))

    gi = root / ".gitignore"
    if not gi.exists():
        r.add(WARN, "H020", "缺少 .gitignore")
    else:
        content = read_text(gi) or ""
        for need in ("node_modules", "target", "dist", ".db"):
            if need not in content:
                r.add(WARN, "H021", f".gitignore 未忽略：{need}")


def load_gitignore(root: Path) -> list[str]:
    """极简 .gitignore 解析：只取纯目录模式（以 / 结尾）。不做完整 gitignore 语法支持。"""
    gi = root / ".gitignore"
    if not gi.exists():
        return []
    content = read_text(gi) or ""
    out: list[str] = []
    for line in content.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("!"):  # 否定模式暂不支持
            continue
        out.append(s.rstrip("/"))
    return out


def is_ignored(path: Path, root: Path, patterns: list[str]) -> bool:
    """粗略判断：路径中任一段匹配某个模式即视为已忽略。"""
    try:
        rel_parts = path.relative_to(root).parts
    except ValueError:
        return False
    for pat in patterns:
        if not pat or pat.startswith("*"):
            continue
        if pat in rel_parts:
            return True
        if rel_parts[-1] == pat:
            return True
    return False


SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "疑似 OpenAI/DeepSeek 明文密钥 sk-..."),
    (re.compile(r"\b(?:api[_-]?key|apikey|secret|token|password|passwd|pwd)\s*[:=]\s*[\"'][^\"'\s{}$]{12,}[\"']", re.I),
     "疑似硬编码密钥/口令"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9\-\._~\+/]{20,}"), "疑似硬编码 Bearer Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "疑似 AWS Access Key"),
]


def check_secrets(root: Path, r: Report):
    """安全门禁 V1：明文密钥"""
    for p in iter_files(root, CODE_EXTS | {".json", ".toml", ".yaml", ".yml", ".env"}):
        path_str = rel(root, p)
        if path_str.endswith(".env.example"):
            continue
        text = read_text(p)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("//", "#", "*")):
                continue
            for pat, desc in SECRET_PATTERNS:
                m = pat.search(line)
                if not m:
                    continue
                # 排除明显的占位符
                placeholder = re.search(
                    r"(YOUR_|xxx+|xxx|TODO|PLACEHOLDER|<.*?>|\$\{|process\.env|os\.environ|keyring|credential)",
                    m.group(0), re.I)
                if placeholder:
                    continue
                r.add(FAIL, "V1", f"{desc}：{m.group(0)[:40]}", path_str, i)


HYGIENE_PATTERNS = [
    (re.compile(r"\bconsole\.(log|debug)\s*\("), "调试输出 console.log 残留", WARN),
    (re.compile(r"\bdebugger\b"), "debugger 残留", FAIL),
    (re.compile(r"\bdbg!\s*\("), "Rust dbg! 残留", FAIL),
    (re.compile(r"\beprintln!\s*\("), "Rust eprintln! 残留", WARN),
    (re.compile(r"^\s*print\s*\(", re.M), "Python print 残留（脚本入口除外）", WARN),
    (re.compile(r"\bTODO\b|\bFIXME\b|\bXXX\b"), "TODO/FIXME 残留", WARN),
]


def _is_cli_script(p: Path, path_str: str) -> bool:
    """CLI 入口 / 构建脚本：stdout 就是它们的用户界面，print 属正常输出而非调试残留。

    先例：`service.py --announce` 靠 stdout 首行传端口（这就是它的对外协议），
    `build_sidecar.py` 是构建脚本，进度必须打到终端。
    """
    if p.name in {"service.py", "main.py", "cli.py", "__main__.py"}:
        return True
    if p.name.startswith(_BUILD_SCRIPT_PREFIXES) or p.name.startswith("build_"):
        return True
    return "/scripts/" in path_str or path_str.startswith("tools/")


def check_hygiene(root: Path, r: Report):
    """代码卫生"""
    for p in iter_files(root, CODE_EXTS):
        path_str = rel(root, p)
        if is_exempt(path_str):
            continue
        text = read_text(p)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for pat, desc, level in HYGIENE_PATTERNS:
                if pat.search(line):
                    if desc.startswith("Python print") and _is_cli_script(p, path_str):
                        continue
                    r.add(level, "Q001", desc, path_str, i)


# ui / modules 层不得直连数据库（须走 api 封装层）
DB_ACCESS_PATTERN = re.compile(
    r"(rusqlite|sqlx|tauri-plugin-sql|better-sqlite3|node-sqlite3|sql\.js|"
    r"from\s+sqlite3\s+import|import\s+sqlite3|require\(\s*[\"']sqlite3)", re.I)

# 插件层：出现 sqlite 相关字样即视为越权（插件必须走宿主 Data API）
PLUGIN_DB_PATTERN = re.compile(r"(sqlite|rusqlite|sqlx|lowdb|better-sqlite3)", re.I)


def check_architecture(root: Path, r: Report):
    """架构门禁：UI / 插件越权访问数据库"""
    for p in iter_files(root, CODE_EXTS):
        path_str = rel(root, p)
        text = read_text(p)
        if text is None:
            continue
        is_ui = path_str.startswith("ui/") or "/ui/" in path_str
        is_plugin = path_str.startswith("plugins/")
        is_module = path_str.startswith("modules/")

        if is_ui or is_plugin or is_module:
            where = "UI 层" if is_ui else ("插件" if is_plugin else "modules 模块")
            pat = PLUGIN_DB_PATTERN if is_plugin else DB_ACCESS_PATTERN
            for i, line in enumerate(text.splitlines(), 1):
                if stripped_comment(line):
                    continue
                if pat.search(line):
                    r.add(FAIL, "V7", f"{where}直接访问数据库（违反单一写入者原则）", path_str, i)

        # core 不得引用具体插件
        if path_str.startswith("core/") and path_str.endswith(".rs"):
            for i, line in enumerate(text.splitlines(), 1):
                if stripped_comment(line):
                    continue
                if re.search(r"(include_str!|include_bytes!)\(\s*[\"'][^\"']*plugins/", line):
                    r.add(FAIL, "A010", "core 直接硬编码引用具体插件资源", path_str, i)

        # 硬编码绝对路径
        for i, line in enumerate(text.splitlines(), 1):
            if stripped_comment(line):
                continue
            if re.search(r"[\"'][A-Za-z]:\\\\?Users\\\\?[^\"']+[\"']", line):
                r.add(FAIL, "A020", "硬编码用户绝对路径", path_str, i)
            elif re.search(r"[\"']['\"]?C:\\\\?Program Files", line):
                r.add(FAIL, "A021", "硬编码 Program Files 路径", path_str, i)


def stripped_comment(line: str) -> bool:
    s = line.strip()
    return s.startswith(("//", "#", "*", "/*"))


# ADR-001 合规扫描：进程启动 / 窗口控制 = Rust。
# REVIEW-002 R-03 复盘：原检查点（见 docs/adr/ADR-001 与 system/README.md）只点名
# `win32*` 与 `pywin32`，于是 `subprocess.Popen` 这类**等价实现**直接从缝里漏了过去。
# 该检查把口径收窄到"能力"而非"库名"。
PY_PROCESS_LAUNCH_PATTERN = re.compile(
    r"(subprocess\.(Popen|run|call|check_output|check_call)\s*\(|"
    r"os\.(startfile|system|spawnl|spawnle|spawnv|spawnve|execv|execve)\s*\(|"
    r"\bwin32process\b|\bwin32gui\b|\bwin32api\b|"
    r"\bShellExecute\w*\b|\bCreateProcess\w*\b)",
    re.I,
)

# sidecar 的"构建脚本"允许调用 subprocess 驱动 PyInstaller —— 它不是 runtime 能力。
_BUILD_SCRIPT_PREFIXES = ("build_", "_build", "make_")


def check_adr001(root: Path, r: Report):
    """ADR-001 合规：`system/`（sidecar runtime）不得出现窗口/进程控制实现。"""
    sysdir = root / "system"
    if not sysdir.is_dir():
        r.checks_skipped.append("ADR-001 合规扫描（无 system/）")
        return

    for p in iter_files(sysdir, {".py"}):
        path_str = rel(root, p)
        if p.name.startswith(_BUILD_SCRIPT_PREFIXES):
            r.add(PASS, "A030", f"ADR-001：{path_str} 属构建脚本，豁免", path_str)
            continue
        text = read_text(p)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if stripped_comment(line):
                continue
            if PY_PROCESS_LAUNCH_PATTERN.search(line):
                r.add(
                    FAIL,
                    "A031",
                    "ADR-001 违规：sidecar 出现进程启动/窗口控制实现（该能力归 Rust core）",
                    path_str,
                    i,
                )


# ---------------------------------------------------------------- 接线检查
# REVIEW-003 复盘：**"文件存在 ≠ 功能存在"**。
# `ui/src/utils/logger.ts` 与 `stores/widgets.ts::autoSize()` 都被结构门禁判为 PASS，
# 但前者全项目零 import、后者零调用 —— 纯静态结构检查查不出"孤儿代码"。
# 该检查对工具类模块做"被引用性"验证：没人 import 的模块 = 未接线。

_ORPHAN_SCAN_DIRS = ("ui/src/utils", "ui/src/composables")


def _import_pattern(stem: str) -> "re.Pattern[str]":
    esc = re.escape(stem)
    return re.compile(
        rf"""(?:from|import)\s*\(?\s*['"][^'"]*/{esc}['"]"""
        rf"""|(?:from|import)\s*\(?\s*['"]\.\.?/{esc}['"]"""
        rf"""|import\s*\(\s*['"][^'"]*/{esc}['"]\s*\)""",
        re.I,
    )


def check_orphans(root: Path, r: Report):
    """接线门禁：utils/ 与 composables/ 下的模块必须被别处引用。"""
    targets: list[Path] = []
    for d in _ORPHAN_SCAN_DIRS:
        dd = root / d
        if dd.is_dir():
            targets.extend(sorted(p for p in dd.rglob("*.ts") if p.is_file()))
    if not targets:
        r.checks_skipped.append("接线检查（无 ui/src/utils 或 composables）")
        return

    # 语料：ui/src 下所有可能的引用者
    corpus: dict[str, str] = {}
    src = root / "ui" / "src"
    if src.is_dir():
        for p in iter_files(src, {".ts", ".tsx", ".vue", ".mjs", ".js"}):
            t = read_text(p)
            if t is not None:
                corpus[rel(root, p)] = t

    for p in targets:
        rp = rel(root, p)
        # 排除 index.ts（桶文件常为入口，允许无引用者）
        if p.stem == "index":
            r.add(PASS, "W102", f"{rp} 为桶文件（index），跳过引用检查", rp)
            continue
        pat = _import_pattern(p.stem)
        hit = next((owner for owner, text in corpus.items() if owner != rp and pat.search(text)), None)
        if hit:
            r.add(PASS, "W100", f"{rp} 已被 {hit} 引用（接线到位）", rp)
        else:
            r.add(WARN, "W101", f"{rp} 未被任何模块引用（疑似死代码 / 未接线）", rp)


DRIFT_PATTERNS = [
    (re.compile(r"\bunwrap\(\)"), "Rust unwrap() 使用（确认不在错误路径上再放行）", WARN),
    (re.compile(r"\bpanic!\s*\("), "panic! 使用", WARN),
    (re.compile(r"\.expect\(\s*[\"']"), "expect() 使用", WARN),
    (re.compile(r"shell\s*=\s*True"), "shell=True（命令注入风险）", FAIL),
    (re.compile(r"\bshell=True\b"), "shell=True（命令注入风险）", FAIL),
]


def check_drift(root: Path, r: Report):
    """风险用法扫描"""
    for p in iter_files(root, CODE_EXTS):
        path_str = rel(root, p)
        if is_exempt(path_str):
            continue
        text = read_text(p)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if stripped_comment(line):
                continue
            for pat, desc, level in DRIFT_PATTERNS:
                if pat.search(line):
                    r.add(level, "R001", desc, path_str, i)


def check_build(root: Path, r: Report):
    """编译门禁（可选，--build）。

    REVIEW-002 复盘：原实现不区分「工具链缺失」与「编译失败」——
    机器上没装 cargo 时 `run_cmd` 返回 127，被当作 `B101 cargo check 失败` 上报，
    于是"编译门禁 1 FAIL"既可能是真编译错误、也可能只是工具链没装，**信号不可信**。
    现分离为：工具链缺失 → WARN(B102) + 记入 skipped；真失败 → FAIL(B101)。
    """
    cargo_toml = root / "core" / "Cargo.toml"
    if cargo_toml.exists():
        if shutil.which("cargo") is None:
            r.add(WARN, "B102", "未检测到 cargo（Rust 工具链缺失），编译未验证 —— 见遗留项 L-004")
            r.checks_skipped.append("cargo check（Rust 工具链缺失）")
        else:
            rc, out = run_cmd(["cargo", "check", "--quiet"], root / "core")
            if rc == 0:
                r.add(PASS, "B100", "cargo check 通过")
            elif rc == 127:
                r.add(WARN, "B102", "cargo 不可用，编译未验证 —— 见遗留项 L-004")
                r.checks_skipped.append("cargo check（Rust 工具链缺失）")
            else:
                r.add(FAIL, "B101", f"cargo check 失败：{out.strip().splitlines()[-1] if out.strip() else '未知错误'}")
    else:
        r.checks_skipped.append("cargo check（无 core/Cargo.toml）")

    pkg = root / "ui" / "package.json"
    if pkg.exists():
        data = json.loads(read_text(pkg) or "{}")
        scripts = data.get("scripts", {})
        if "typecheck" not in scripts:
            r.add(WARN, "B112", "ui/package.json 缺少 typecheck 脚本（无法自动验证类型）")
        elif shutil.which("npm") is None:
            r.add(WARN, "B113", "未检测到 npm，前端 typecheck 未验证")
            r.checks_skipped.append("前端 typecheck（npm 缺失）")
        else:
            rc, out = run_cmd(["npm", "run", "typecheck", "--silent"], root / "ui")
            if rc == 0:
                r.add(PASS, "B110", "前端 typecheck 通过")
            elif rc == 127:
                r.add(WARN, "B113", "npm 不可用，前端 typecheck 未验证")
                r.checks_skipped.append("前端 typecheck（npm 缺失）")
            else:
                r.add(FAIL, "B111", f"前端 typecheck 失败：{out.strip().splitlines()[-1] if out.strip() else '未知错误'}")
    else:
        r.checks_skipped.append("前端 typecheck（无 ui/package.json）")


def run_cmd(cmd: list[str], cwd: Path):
    try:
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           timeout=600, shell=(os.name == "nt"))
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"命令未找到：{cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "命令超时"
    except Exception as e:  # pragma: no cover
        return 99, str(e)


# ---------------------------------------------------------------- 输出

def print_report(r: Report):
    line = "=" * 68
    print(line)
    print(f"Personal Workspace · 阶段门禁报告")
    print(f"项目根目录：{r.root}")
    print(f"审核阶段  ：阶段 {r.stage} · {STAGES.get(r.stage, {}).get('name', '通用检查')}")
    print(line)

    for level in (FAIL, WARN, PASS, INFO):
        items = [f for f in r.findings if f.level == level]
        if not items:
            continue
        print()
        print(f"--- {level}（{len(items)}）{'-' * (50 - len(level))}")
        limit = 200 if level != PASS else 1000
        for f in items[:limit]:
            print("  " + f.render())
        if len(items) > limit:
            print(f"  ... 另有 {len(items) - limit} 条")

    print()
    print(line)
    verdict = "✅ 门禁通过" if r.ok else "❌ 门禁不通过"
    print(f"{verdict}   FAIL={r.count(FAIL)}  WARN={r.count(WARN)}  PASS={r.count(PASS)}")
    if r.checks_skipped:
        print("跳过：" + "；".join(r.checks_skipped))
    if not r.ok:
        print()
        print("不通过项需返工。判定口径见 docs/reviews/SUPERVISOR.md 第四章。")
    print(line)


def main():
    ap = argparse.ArgumentParser(description="Personal Workspace 阶段门禁检查")
    ap.add_argument("--root", default=".", help="项目根目录")
    ap.add_argument("--stage", default="0", help="阶段号 0-9，all=全部通用检查")
    ap.add_argument("--build", action="store_true", help="附带编译门禁（较慢）")
    ap.add_argument("--json", dest="json_out", help="输出 JSON 报告到文件")
    ap.add_argument("--list", action="store_true", help="列出各阶段要求")
    args = ap.parse_args()

    if args.list:
        for k in sorted(STAGES, key=lambda x: int(x)):
            spec = STAGES[k]
            print(f"阶段 {k} · {spec['name']}")
            for item in spec.get("required", []):
                print(f"    - 必需：{item}")
            for item in spec.get("requires_structure", []):
                print(f"    - 目录：{item}")
            print()
        return 0

    root = Path(args.root).resolve()
    if not root.exists():
        print(f"根目录不存在：{root}", file=sys.stderr)
        return 2

    r = Report(root=str(root), stage=args.stage)

    check_structure(root, args.stage, r)
    check_housekeeping(root, r)
    check_secrets(root, r)
    check_hygiene(root, r)
    check_architecture(root, r)
    check_adr001(root, r)
    check_orphans(root, r)
    check_drift(root, r)
    if args.build:
        check_build(root, r)
    else:
        r.checks_skipped.append("编译门禁（未加 --build）")

    print_report(r)

    if args.json_out:
        out = Path(args.json_out)
        payload = {
            "root": r.root, "stage": r.stage,
            "verdict": "PASS" if r.ok else "FAIL",
            "counts": {FAIL: r.count(FAIL), WARN: r.count(WARN), PASS: r.count(PASS)},
            "findings": [asdict(f) for f in r.findings],
            "skipped": r.checks_skipped,
        }
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON 报告已写入：{out}")

    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(main())
