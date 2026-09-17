#!/usr/bin/env python3
"""TECH-06-A 验收 · AI 模型真实连接完善（模型管理中心从"展示态"到"真实态"）。

## 审计前提（详见 `docs/tech/TECH-06-A-audit.md`）

链路本来就是真的（`registry.check()` → `ai_list_models` → sidecar → 真实 HTTP），
问题出在**归约层**：

| 现状 | 问题 |
|------|------|
| `entryStatusOf()` 把 `lastError` 一律压成 `unavailable` | **「离线」与「连接失败」被糊成一个词「不可用」** |
| `ModelListEntry` 不透出 `lastError` / `needsSecret` | UI 拿不到"为什么是这个状态"的证据 |
| `AgentAdapter.testConnection` 不探测 | 三类连接（API / 本地 / Agent）**缺一类** |
| `coreModelIo.listRemoteModels` 无 core 时 `return []` | 会被判成"连通，0 个模型" → **假绿** |

## 本轮判据

**验收要求只有一句：证明 UI 显示状态 == Registry 真实状态。**

于是判据分三层，各有各的治法：
- **静态**（T1~T8）抓"自己又造一份状态词表 / 偷偷加后端命令 / 破了 UI 冻结"；
- **Node 直驱**（①~⑤）把 `status.ts` 真编译后在 Node 里**穷举 288 种事实组合**，
  抓"映射逻辑其实反了"，并且**每条否定断言都配对照组**；
- **动态**（R1~R4）跑**最终 dist 产物**，其中 R2/R3 会**注入真实模型并触发真实探测**，
  证明"DOM == Registry"这条断言**不是空转**（否则本环境模型列表为空，断言恒真）。

## 反"假通过"（本环境是真考验）

headless 里没有 Tauri 后端 → `providers` 为空、模型列表为空，
"DOM 状态 == Registry 状态"天然空转。所以：
- R1 的 detail **显式标注**是否空转；
- R2/R3 用 `registry.add()` + `registry.registerProvider()` 造出真实模型，再 `probe()` 触发**真实失败** ——
  这条同时证明"修掉了假绿"（修复前探测会返回 `ok:true`，页面会显示"已连接"）；
- ① 的 288 组合里，**`entryStatus !== 'ready'` 一律不得为 `connected`** —— 这是"不许假绿灯"的形式化。

## 不做的事

不验模型市场 / 自动下载 / Agent 执行（本轮明确禁止）；
不验模型清单持久化（审计 §四已登记为**本轮不做**，刷新后为空是已知现状）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
UI = ROOT / "ui"
SRC = UI / "src"
DIST = UI / "dist"
TSC = UI / "node_modules" / "typescript" / "lib" / "tsc.js"

# ---------------------------------------------------------------- 复用 TECH-02 基建

_spec = importlib.util.spec_from_file_location("pw_tech02_infra", TOOLS / "verify_tech02_workspace.py")
assert _spec and _spec.loader
_t02 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_t02)

CDPWebSocket = _t02.CDPWebSocket
find_edge = _t02.find_edge
free_port = _t02.free_port
start_server = _t02.start_server
ev = _t02.ev
wait_for = _t02.wait_for

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def read_src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    """去注释后再做"禁止标识符"扫描 —— 注释里提到某个词不算违规。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\{\s*/\*.*?\*/\s*\}", "", text, flags=re.S)
    text = re.sub(r"(?m)^\s*//[^\n]*", "", text)
    text = re.sub(r"(?m)//[^\n]*", "", text)
    text = re.sub(r"(?m)^\s*\*[^\n]*", "", text)
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    return text


def node() -> str:
    """找 node.exe —— **不硬编码盘符/用户名**（门禁 A020/A021 会判违规）。"""
    cands: list[str] = []
    env_node = os.environ.get("NODE_EXE")
    if env_node:
        cands.append(env_node)
    home = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    versions = Path(home) / ".workbuddy" / "binaries" / "node" / "versions"
    if versions.is_dir():
        cands += [str(v / "node.exe") for v in sorted(versions.iterdir(), reverse=True)]
    pf = os.environ.get("ProgramFiles")
    if pf:
        cands.append(str(Path(pf) / "nodejs" / "node.exe"))
    which = shutil.which("node")
    if which:
        cands.append(which)
    for cand in cands:
        if cand and Path(cand).exists():
            return str(cand)
    raise RuntimeError("找不到 node.exe")


# ---------------------------------------------------------------- 路径常量

STATUS = "ai/model/status.ts"
REGISTRY = "ai/model/registry.ts"
PROVIDER = "ai/model/provider.ts"
PORTS = "ai/model/ports.ts"
PAGE = "views/ModelsView.vue"
PAUDIT = "views/SettingsView.vue"

# 后端既有命令（用于"零新增命令"断言）
COMMANDS_RS = "core/src/api/commands.rs"
# Agent 探测允许使用的**既有**命令
AGENT_CMDS = ("'agents_list'", "'agent_health'")
# TECH-05-D 冻结的模型域键基线（本轮不得增删）
MODEL_DOMAIN_KEYS = {"ui.ai.provider", "ui.ai.model", "ui.ai.apiBase"}
# TECH-05-D 冻结的 store 键基线
STORE_KEYS = {"ui.ai.width", "ui.ai.collapsed", "ui.ai.provider", "ui.ai.model", "ui.ai.mode"}


# ================================================================ Node 直驱（纯函数穷举）

NODE_JS = r"""
'use strict';
const S = require('./ai/model/status.js');
const checks = [];
function check(n, p, d) { checks.push([n, !!p, String(d)]); }
const J = (x) => JSON.stringify(x);

const ES = ['ready', 'unchecked', 'unavailable', 'disabled'];
const ERRS = ['', 'local_model_down', 'unreachable', 'auth_failed', 'timeout',
              'rate_limit', 'bad_response', 'not_implemented', 'no_api_key'];
const OFFLINE = S.OFFLINE_CODES;

/* ---------------- ① 穷举：288 种事实组合，决定性属性必须成立 ---------------- */
let total = 0;
const violations = [];
const errOf = {};
for (const enabled of [true, false])
  for (const es of ES)
    for (const needs of [true, false])
      for (const has of [true, false])
        for (const err of ERRS) {
          total++;
          const f = { enabled, entryStatus: es, needsSecret: needs, hasSecret: has, lastError: err };
          const d = S.displayStatusOf(f);
          if (!S.DISPLAY_STATUSES.includes(d)) violations.push([f, d, '词表外']);
          // (a) 反假绿：不是 ready 就永远不许是 connected
          if (es !== 'ready' && d === 'connected') violations.push([f, d, 'FAKE_GREEN']);
          // (b) 未开放 / 已停用 → offline
          if ((!enabled || es === 'disabled') && d !== 'offline') violations.push([f, d, '应离线']);
          // (c) 缺前提（要密钥但没有，且已启用未停用）→ unconfigured
          if (enabled && es !== 'disabled' && needs && !has && d !== 'unconfigured')
            violations.push([f, d, '应未配置']);
          // (d) 真探测通过 → connected（只在 enabled + ready + 凭据齐时）
          if (enabled && es === 'ready' && (!needs || has) && d !== 'connected')
            violations.push([f, d, '应已连接']);
        }
check('① 归约穷举 ' + total + ' 种事实组合：全部落在词表内且 4 条决定性属性无一违例',
      violations.length === 0,
      violations.length ? J(violations.slice(0, 3)) : ('0 违例 / ' + total + ' 组合'));

/* ①b 五个显示态全部可达（没有死状态 —— 死状态说明判据写不到那条路） */
const reach = new Set();
for (const enabled of [true, false])
  for (const es of ES)
    for (const needs of [true, false])
      for (const has of [true, false])
        for (const err of ERRS)
          reach.add(S.displayStatusOf({ enabled, entryStatus: es, needsSecret: needs, hasSecret: has, lastError: err }));
const missing = S.DISPLAY_STATUSES.filter((s) => !reach.has(s));
check('①b 五个显示态全部可达（含 TECH-06-A 要求的 已连接/未配置/连接失败/离线）',
      missing.length === 0, missing.length ? ('不可达：' + J(missing)) : J([...reach].sort()));

/* ①c 反假绿（单独成条，便于审计一眼看到）：非 ready 的 216 种组合里零 connected */
let nonReady = 0, fakeGreen = 0;
for (const enabled of [true, false])
  for (const es of ES)
    for (const needs of [true, false])
      for (const has of [true, false])
        for (const err of ERRS) {
          if (es === 'ready') continue;
          nonReady++;
          if (S.displayStatusOf({ enabled, entryStatus: es, needsSecret: needs, hasSecret: has, lastError: err }) === 'connected')
            fakeGreen++;
        }
check('①c **反假绿**：从未探测通过的状态一律不得显示「已连接」',
      fakeGreen === 0 && nonReady > 0,
      J({ 非ready组合: nonReady, 假绿次数: fakeGreen }));

/* ---------------- ② 「离线」与「连接失败」必须可区分（+ 反向对照） ---------------- */
const base = { enabled: true, entryStatus: 'unavailable', needsSecret: true, hasSecret: true };
const down = S.displayStatusOf({ ...base, lastError: 'local_model_down' });
const netDown = S.displayStatusOf({ ...base, lastError: 'unreachable' });
const authBad = S.displayStatusOf({ ...base, lastError: 'auth_failed' });
const toSlow = S.displayStatusOf({ ...base, lastError: 'timeout' });
check('② 同一个失败状态，「离线」与「连接失败」按失败码分流（不再糊成「不可用」）',
      down === 'offline' && netDown === 'offline' && authBad === 'failed' && toSlow === 'failed',
      J({ local_model_down: down, unreachable: netDown, auth_failed: authBad, timeout: toSlow }));

/* ②b 对照组：其它事实完全相同，只把失败码从"离线类"换成"失败类" —— 结果必须变 */
const sameFacts = (err) => ({ enabled: true, entryStatus: 'unavailable', needsSecret: true, hasSecret: true, lastError: err });
check('②b 对照组：仅改失败码即可改变结论（证明 ② 不是"反正都一个词"）',
      S.displayStatusOf(sameFacts('unreachable')) !== S.displayStatusOf(sameFacts('rate_limit')),
      J({ unreachable: S.displayStatusOf(sameFacts('unreachable')),
          rate_limit: S.displayStatusOf(sameFacts('rate_limit')) }));

/* ---------------- ③ 「未配置」是缺前提，不是失败（+ 反向对照） ---------------- */
const noKey = S.displayStatusOf({ enabled: true, entryStatus: 'unavailable', needsSecret: true, hasSecret: false, lastError: 'no_api_key' });
const hasKey = S.displayStatusOf({ enabled: true, entryStatus: 'unavailable', needsSecret: true, hasSecret: true, lastError: 'no_api_key' });
check('③ 需要密钥却没配 → 「未配置」（不是「连接失败」，因为压根没发请求）',
      noKey === 'unconfigured', J({ display: noKey }));

/* ③b 对照组：同一个失败码，配了密钥之后就不再是「未配置」—— 证明判据真的看了 hasSecret */
check('③b 对照组：同一失败码，配齐凭据后结论立刻改变（证明 ③ 真的读了 hasSecret）',
      hasKey !== 'unconfigured' && noKey !== hasKey, J({ 无凭据: noKey, 有凭据: hasKey }));

/* ③c 本地模型不需要密钥 → 永远不该出现「未配置」 */
const localOk = S.displayStatusOf({ enabled: true, entryStatus: 'unchecked', needsSecret: false, hasSecret: false, lastError: '' });
check('③c 本地模型（不需要密钥）不会被判成「未配置」',
      localOk !== 'unconfigured', J({ display: localOk }));

/* ---------------- ④ 探测结论文案：没发请求 ≠ 连接失败 ---------------- */
const notProbed = S.probeConclusionOf({ ok: false, probed: false, code: 'not_implemented', message: '尚未注册该 Agent', modelCount: 0, ms: 3 });
const failed = S.probeConclusionOf({ ok: false, probed: true, code: 'auth_failed', message: '401', modelCount: 0, ms: 12 });
const okRes = S.probeConclusionOf({ ok: true, probed: true, code: 'ok', message: '', modelCount: 3, ms: 20 });
check('④ 未发起探测时不得显示「失败」或「已连接」（短路 ≠ 连不上）',
      notProbed.indexOf('未发起探测') === 0
      && notProbed.indexOf('已连接') < 0
      && notProbed.indexOf('失败') < 0,
      notProbed);
check('④b 对照组：真探测过才允许出现「已连接」/「探测失败」',
      okRes.indexOf('已连接') === 0 && failed.indexOf('探测失败') === 0,
      J({ ok: okRes, failed: failed }));

/* ---------------- ⑤ 词表映射到既有 3 个 dot 类（不引入新样式） ---------------- */
const dots = [...new Set(Object.values(S.DISPLAY_STATUS_META).map((m) => m.dot))].sort();
check('⑤ 显示态只映射到既有 dot 类 ok/wait/off（UI 冻结：不新增样式类）',
      dots.length <= 3 && dots.every((d) => ['ok', 'wait', 'off'].includes(d)),
      J(dots));

const texts = S.DISPLAY_STATUSES.map((s) => S.DISPLAY_STATUS_META[s].text);
check('⑤b 四个要求的状态词在文案表里齐备（已连接 / 未配置 / 连接失败 / 离线）',
      ['已连接', '未配置', '连接失败', '离线'].every((t) => texts.includes(t)),
      J(texts));

/* ---------------- ⑥ 连接类型展示名与页面同源 ---------------- */
check('⑥ 连接类型展示名收拢在领域层（api/local/agent 三档）',
      S.CONNECTION_TYPE_LABEL.api === 'API 模型'
      && S.CONNECTION_TYPE_LABEL.local === '本地模型'
      && S.CONNECTION_TYPE_LABEL.agent === '个人Agent',
      J(S.CONNECTION_TYPE_LABEL));

console.log('__PW_RESULT__' + JSON.stringify({ checks }));
"""


def compile_entries(tmp: Path) -> None:
    if not TSC.exists():
        raise RuntimeError(f"缺少 typescript 编译器：{TSC}（先 npm install）")
    args = [
        node(), str(TSC),
        "--target", "ES2022", "--module", "commonjs", "--moduleResolution", "node",
        "--strict", "--esModuleInterop", "--skipLibCheck",
        "--rootDir", str(SRC), "--outDir", str(tmp),
        str(SRC / STATUS),
    ]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(UI), timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"tsc 编译失败（exit {proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    if not (tmp / STATUS.replace(".ts", ".js")).exists():
        raise RuntimeError("编译产物缺失：status.js")


def run_js(tmp: Path) -> None:
    (tmp / "__probe.js").write_text(NODE_JS, encoding="utf-8")
    proc = subprocess.run([node(), str(tmp / "__probe.js")], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(tmp), timeout=240)
    out = proc.stdout or ""
    marker = [ln for ln in out.splitlines() if ln.startswith("__PW_RESULT__")]
    if not marker:
        raise RuntimeError(
            f"Node 探针未产出结果（exit {proc.returncode}）\nSTDOUT:\n{out[-2000:]}\n"
            f"STDERR:\n{(proc.stderr or '')[-2000:]}"
        )
    payload = json.loads(marker[-1][len("__PW_RESULT__"):])
    for name, ok, detail in payload["checks"]:
        check(name, ok, detail)


# ================================================================ T1 状态词表唯一出处

def t1_single_vocabulary() -> None:
    status = read_src(STATUS)
    page = strip_comments(read_src(PAGE))

    # T1a 词表与归约函数只定义在领域层一处
    definers = []
    for p in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        t = strip_comments(p.read_text(encoding="utf-8"))
        if re.search(r"(export\s+)?const\s+DISPLAY_STATUSES\s*=", t) or \
           re.search(r"(export\s+)?function\s+displayStatusOf\s*\(", t):
            definers.append(p.relative_to(SRC).as_posix())
    check("T1a 显示状态词表与归约函数**唯一定义**在 ai/model/status.ts（不出现第二套）",
          definers == [STATUS] and "DISPLAY_STATUSES" in status,
          json.dumps(definers, ensure_ascii=False))

    # T1b 页面不再自带一份状态映射表（旧的 STATUS_LABEL 已删除）
    legacy = re.search(r"const\s+STATUS_LABEL\s*[:=]", page)
    check("T1b 页面不再自带状态映射表（旧 `STATUS_LABEL` 已移除，状态一律取领域层）",
          legacy is None, "页面无 STATUS_LABEL" if legacy is None else "仍存在 STATUS_LABEL")

    # T1c 页面确实调用领域层归约（而不是"删了旧的、换了个地方写"）
    check("T1c 页面通过 displayStatusOf 取状态（唯一判据的**消费方**，不是实现方）",
          "displayStatusOf(" in page and "DISPLAY_STATUS_META" in page,
          "页面消费领域层判据")

    # T1d 页面不得就地写 `lastError ? … : …` 之类的第二套判断
    inline = re.findall(r"lastError\s*\?", page)
    check("T1d 页面零 `lastError ? …` 就地三元（不允许绕过归约函数自己判）",
          not inline, json.dumps({"就地判据": inline}, ensure_ascii=False))


# ================================================================ T2 列表投影透出证据

def t2_entry_exposes_evidence() -> None:
    reg = strip_comments(read_src(REGISTRY))
    m = re.search(r"export interface ModelListEntry\s*\{[\s\S]*?\n\}", reg)
    body = m.group(0) if m else ""
    fields = {k: (k in body) for k in ("needsSecret", "lastError", "lastCheck")}
    check("T2a ModelListEntry 透出「为什么是这个状态」的证据（needsSecret / lastError / lastCheck）",
          all(fields.values()), json.dumps(fields, ensure_ascii=False))

    lm = re.search(r"(?m)^  list\(opts[\s\S]*?\n  \}", reg)
    lbody = lm.group(0) if lm else ""
    filled = {k: (f"{k}:" in lbody) for k in ("needsSecret", "lastError", "lastCheck")}
    check("T2b list() 真的把这三项**填进投影**（不是只声明了字段）",
          all(filled.values()), json.dumps(filled, ensure_ascii=False))

    # T2c 凭据需求取自 L0（ProviderDescriptor），不是页面自己查表
    check("T2c 凭据需求取自 L0 能力真相（`getProvider(...).needsKey`），页面不再自查 Provider 表",
          "getProvider(p.provider)" in lbody and "needsKey" in lbody,
          "needsKey ← L0")


# ================================================================ T3 三类连接都能检测

def t3_three_probe_kinds() -> None:
    prov = strip_comments(read_src(PROVIDER))
    ports = strip_comments(read_src(PORTS))

    # T3a 端口新增可选的 agentHealth（不实现时可回退，不假装）
    check("T3a ModelIo 新增**可选** agentHealth 端口（不实现时如实回退，不假装探测过）",
          "agentHealth?" in prov or "agentHealth(" in prov,
          "agentHealth 端口在位")

    # T3b AgentAdapter 真的去探测（不再恒 not_implemented）
    am = re.search(r"class AgentAdapter[\s\S]*?\n\}", prov)
    abody = am.group(0) if am else ""
    check("T3b AgentAdapter 真的走 `io.agentHealth()` 探测（不再**恒**返回 not_implemented）",
          "io.agentHealth" in abody and "notFound" in abody,
          "Agent 走真实健康探测")

    # T3c 两条诚实底线：无端口 / 未注册 → **末位实参 probed=false**（不能被显示成"连接失败"）。
    # 注意：`probed` 是 `result()` 的**第 7 个位置参数**（见 provider.ts:`function result(`），
    # 源码里没有名为 `probed` 的标识符，所以只能按**位置**断言 —— 数词不算证据，顺序才算。
    def _probed_arg(seg: str):
        m = re.search(r"return result\(([^;]*?)\)", seg)
        if not m:
            return None
        args = [a.strip() for a in m.group(1).split(",")]
        return args[-1] if args else None

    _kv = "const { value, ms }"
    no_port = _probed_arg(abody[: abody.find(_kv)]) if _kv in abody else None
    nf_at = abody.find("value.notFound")
    not_found = _probed_arg(abody[nf_at:]) if nf_at >= 0 else None
    check("T3c Agent 无端口 / 未注册时末位 `probed=false`（缺前提 ≠ 连接失败）",
          no_port == "false" and not_found == "false",
          json.dumps({"无端口分支_probed": no_port, "未注册分支_probed": not_found},
                     ensure_ascii=False))

    # T3d 三类适配器齐备（api / local / agent）
    kinds = {k: (k in prov) for k in ("class CloudApiAdapter", "class LocalRuntimeAdapter", "class AgentAdapter")}
    check("T3d 三类连接（API / 本地 / Agent）适配器齐备",
          all(kinds.values()), json.dumps(kinds, ensure_ascii=False))

    # T3e Agent 探测只用既有命令
    used = set(re.findall(r"invokeCore<[^>]*>\('([a-z_]+)'|invokeCore\('([a-z_]+)'", ports))
    used_flat = {a or b for a, b in used}
    check("T3e Agent 探测**复用既有命令**（agents_list + agent_health），零新增后端能力",
          {"agents_list", "agent_health"} <= used_flat,
          json.dumps(sorted(used_flat), ensure_ascii=False))

    # T3f 这些命令确实已在 core 侧存在（不是画饼）
    cmds = set(re.findall(r"pub (?:async )?fn (\w+)", read(COMMANDS_RS)))
    missing = sorted(c for c in ("agents_list", "agent_health") if c not in cmds)
    check("T3f 所用命令在 core 侧**确实存在**（本轮零新增命令）",
          not missing, "都在 commands.rs" if not missing else "缺失：" + ", ".join(missing))


# ================================================================ T4 零新增后端能力

def t4_no_new_backend() -> None:
    ports = strip_comments(read_src(PORTS))
    existing = set(re.findall(r"pub (?:async )?fn (\w+)", read(COMMANDS_RS)))
    used = {a or b for a, b in re.findall(r"invokeCore<[^>]*>\('([a-z_]+)'|invokeCore\('([a-z_]+)'", ports)}
    unknown = sorted(c for c in used if c not in existing)
    check("T4a 端口层调用的 core 命令全部是既有命令（零新增）",
          not unknown, json.dumps({"使用": sorted(used), "不存在": unknown}, ensure_ascii=False))

    # T4b 核心探测路径仍是 ai_list_models（没有另起一条后端通道）
    check("T4b API / 本地探测仍走既有 `ai_list_models`（未另起后端通道）",
          "'ai_list_models'" in ports, "ai_list_models 在位")


# ================================================================ T5 修掉假绿

def t5_no_fake_green() -> None:
    ports = strip_comments(read_src(PORTS))
    m = re.search(r"async listRemoteModels\(providerId, opts\)[\s\S]*?\n    \},", ports)
    body = m.group(0) if m else ""

    no_core = re.search(r"!inTauri\(\)[\s\S]{0,300}?\}", body)
    seg = no_core.group(0) if no_core else ""
    check("T5a 无 core 环境下 `listRemoteModels` **抛错**而不是返回 `[]`（修掉「拿不到 → 已连接」的假绿）",
          "throw" in seg and "return []" not in seg,
          "无 core → 抛错（归类 unreachable）" if "throw" in seg else "仍返回 []")

    check("T5b 抛出的错误文本可被归类为 `unreachable`（与 classifyProbeError 的码表同源）",
          "unreachable" in seg.lower(), "错误文本含 unreachable")

    # T5c 对照：真在 Tauri 里仍然返回列表（没有把探测整体禁掉）
    check("T5c 对照组：Tauri 环境下仍然如实返回模型列表（不是「一律抛错」）",
          "invokeCore<{ models?: string[] }>('ai_list_models'" in body,
          "Tauri 分支仍在")


# ================================================================ T6 UI 冻结

def t6_ui_frozen() -> None:
    page = read_src(PAGE)
    css_page = strip_comments(page)

    # T6a 页面不定义自定义属性（不新增 token）
    decl = re.findall(r"(?m)^\s*(--[A-Za-z0-9_-]+)\s*:", page)
    check("T6a AI 模型页零自定义属性定义（未新增第二套 Token）",
          not decl, json.dumps(decl, ensure_ascii=False))

    # T6b 页面样式只用 token（无裸色值）
    naked = re.findall(r"(?<![-\w])(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))", css_page)
    check("T6b 页面样式零裸色值（颜色一律走 token）",
          not naked, json.dumps(sorted(set(naked))[:5], ensure_ascii=False))

    # T6c 复用共享原语
    prims = sorted(set(re.findall(r"components/ui/(Pw\w+)\.vue", page)))
    check("T6c 复用共享原语（PwButton / PwCard / PwChip / PwDrawer）",
          {"PwButton", "PwCard", "PwChip"} <= set(prims), json.dumps(prims, ensure_ascii=False))

    # T6d 未新增独立 Toast 体系
    check("T6d 未新增独立提示条体系（仍用共享 toast）",
          "useToast" in page and "ToastHost" not in page, "复用共享 toast")


# ================================================================ T7 零新增存储真值

def t7_no_new_storage() -> None:
    store = read_src("stores/ai.ts")
    found = set(re.findall(r"'(ui\.ai\.[A-Za-z]+)'", store))
    check("T7a AI store 的 localStorage 键与基线逐项一致（不增不减）",
          found == STORE_KEYS,
          json.dumps({"count": len(found), "差异": sorted(found ^ STORE_KEYS)}, ensure_ascii=False))

    model_keys: set[str] = set()
    others: list[str] = []
    for p in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.vue")):
        rel = p.relative_to(SRC).as_posix()
        ks = set(re.findall(r"'(ui\.ai\.[A-Za-z]+)'", p.read_text(encoding="utf-8")))
        if not ks:
            continue
        if rel == "stores/ai.ts":
            continue
        if rel.startswith("ai/model/"):
            model_keys |= ks
            continue
        others += [f"{rel}:{k}" for k in sorted(ks)]
    check("T7b 模型域键集合与 TECH-05-D 冻结基线一致（本轮未新增存储键）",
          model_keys == MODEL_DOMAIN_KEYS and not others,
          json.dumps({"模型域": sorted(model_keys), "基线": sorted(MODEL_DOMAIN_KEYS),
                      "越界": sorted(set(others))}, ensure_ascii=False))


# ================================================================ T8 零新增页面/路由

def t8_no_new_page() -> None:
    router = read_src("router/index.ts")
    routes = re.findall(r"path:\s*'([^']*)'", router)
    baseline_routes = ['/', '/dashboard', '/software', '/ai', '/learning', '/project', '/mode', '/layout',
                       '/profile', '/life', '/device', '/plugins', '/settings', '/models',
                       '/dev/motion', '/dev/workspace']
    views = sorted(p.name for p in (SRC / "views").glob("*.vue"))
    baseline_views = ["AiView.vue", "DashboardView.vue", "DesktopWidgetView.vue", "DevMotionHarness.vue",
                      "DevWorkspaceHarness.vue", "DeviceView.vue", "LayoutView.vue", "LearningView.vue",
                      "LifeView.vue", "ModeView.vue", "ModelsView.vue", "PluginsView.vue", "ProfileView.vue",
                      "ProjectView.vue", "SettingsView.vue", "SoftwareView.vue"]
    check("T8 本轮**零新增页面 / 路由**（只把既有 /models 的状态语义改真）",
          routes == baseline_routes and views == baseline_views,
          json.dumps({"路由差异": sorted(set(routes) ^ set(baseline_routes)),
                      "视图差异": sorted(set(views) ^ set(baseline_views))}, ensure_ascii=False))

    # T8b 密钥面仍然只有一处（设置页），模型页不输入密钥
    page = strip_comments(read_src(PAGE))
    check("T8b 模型页仍不输入密钥（密钥面只有「设置 → AI」一处，无第二处存密钥的地方）",
          "ai_set_credential" not in page, "页面零凭据写入")


# ================================================================ 动态（最终产物）

PROBE_READY = r"""
(() => {
  const M = window.__pwModels;
  return {
    has: !!M,
    hasStatuses: !!(M && typeof M.statuses === 'function'),
    hasProbe: !!(M && typeof M.probe === 'function'),
    hasStatusOf: !!(M && typeof M.statusOf === 'function'),
    models: document.querySelectorAll('[data-pw-model-id]').length,
    truth: M && M.statuses ? M.statuses() : [],
    dom: Array.prototype.map.call(
      document.querySelectorAll('[data-pw-model-id]'),
      (el) => ({
        id: el.getAttribute('data-pw-model-id'),
        status: el.getAttribute('data-pw-model-status'),
        entryStatus: el.getAttribute('data-pw-model-entry-status'),
        text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200),
      })
    ),
  };
})()
"""

# 注入两个**真实**模型并触发**真实**探测。
#
# 关键：本环境没有 core，`listRemoteModels` 会抛错 → 本地模型探测必须**如实失败**（离线）。
# 三个易踩的点，都在这里处理掉了：
#  1. Provider id **不能以 `_` 开头** —— `deriveModelId()` 会拼出 `_x:y`，
#     而 `validateModelProfile()` 要求 id 形如 `^[A-Za-z0-9]...`，会被 `bad_id` 整单拒绝。
#  2. `add()` 会抛（凭据/校验/重复）—— 必须在页内 try/catch，否则整组验收被一个异常带走。
#  3. 前缀过滤要用 `t6a-local:` / `t6a-api:` 全前缀，避免误伤。
PROBE_INJECT_AND_PROBE = r"""
(async () => {
  const M = window.__pwModels;
  const r = M.registry;
  const PROV = [
    { id: 't6a-local', label: 'T6A 本地桩', connectionType: 'local',
      defaultEndpoint: 'http://127.0.0.1:59999', defaultModel: 't6a-model',
      needsKey: false, enabled: true, note: '验收注入', capabilities: ['chat'] },
    { id: 't6a-api', label: 'T6A API 桩', connectionType: 'api',
      defaultEndpoint: 'https://example.invalid/v1', defaultModel: 't6a-api-model',
      needsKey: true, enabled: true, note: '验收注入', capabilities: ['chat'] },
  ];
  const errors = [];
  for (const p of PROV) {
    try { r.providers.registerProvider(p); } catch (e) { errors.push(['register', p.id, String(e && e.message || e)]); }
  }
  const before = M.statuses().length;
  for (const p of PROV) {
    try { r.add({ provider: p.id, model: p.defaultModel }); }
    catch (e) { errors.push(['add', p.id, String(e && e.message || e)]); }
  }
  const added = M.statuses().filter((s) => s.id.indexOf('t6a-') === 0);
  const localId = (added.find((s) => s.id.indexOf('t6a-local:') === 0) || {}).id || null;
  const apiId = (added.find((s) => s.id.indexOf('t6a-api:') === 0) || {}).id || null;
  if (!localId) return { before, added, localId, apiId, errors, probe: null };
  let probe = null;
  try { probe = await M.probe(localId); }
  catch (e) { errors.push(['probe', localId, String(e && e.message || e)]); }
  return { before, added, localId, apiId, errors, probe };
})()
"""

PROBE_AFTER = r"""
(() => {
  const M = window.__pwModels;
  const truth = M.statuses();
  const pick = (pref) => truth.find((s) => s.id.indexOf(pref) === 0) || null;
  const domOf = (id) => {
    const el = document.querySelector('[data-pw-model-id="' + id + '"]');
    return el ? {
      status: el.getAttribute('data-pw-model-status'),
      entryStatus: el.getAttribute('data-pw-model-entry-status'),
      text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
    } : null;
  };
  // 全部模型：DOM 与 Registry 逐项对齐
  const mismatches = [];
  for (const t of truth) {
    const d = domOf(t.id);
    if (!d) { mismatches.push([t.id, 'DOM 缺该模型']); continue; }
    if (d.status !== t.display) mismatches.push([t.id, d.status, t.display]);
  }
  const local = pick('t6a-local:');
  const api = pick('t6a-api:');
  return {
    count: truth.length,
    mismatches,
    local, api,
    localDom: local ? domOf(local.id) : null,
    apiDom: api ? domOf(api.id) : null,
  };
})()
"""

PROBE_MATRIX = r"""
(() => {
  const M = window.__pwModels;
  const f = (enabled, es, needs, has, err) =>
    M.statusOf({ enabled, entryStatus: es, needsSecret: needs, hasSecret: has, lastError: err });
  return {
    ready: f(true, 'ready', true, true, ''),
    unconfigured: f(true, 'unchecked', true, false, ''),
    offline: f(true, 'unavailable', true, true, 'local_model_down'),
    failed: f(true, 'unavailable', true, true, 'auth_failed'),
    // 反假绿：没探测过且从没 ready → 不许 connected
    fakeGreen: f(true, 'unchecked', true, true, ''),
    notEnabled: f(false, 'ready', false, false, ''),
  };
})()
"""

N_R1 = "R1 /models 真实渲染：状态句柄齐备，且 **DOM 显示状态 == Registry 真实状态**（逐项）"
N_R2 = "R2 **反假绿（端到端）**：注入真实模型 → 真实探测 → 如实报「离线」，而不是假的「已连接」"
N_R3 = "R3 **未配置 ≠ 连接失败**：注入 API 模型且无凭据 → 显示「未配置」"
N_R4 = "R4 出厂包里的归约函数行为正确（4 个语义词齐备 + 反假绿）"


def _r_models(ws: "CDPWebSocket", base: str) -> None:
    ws.call("Page.navigate", {"url": f"{base}/models"}, timeout=15)
    wait_for(ws, "!!(window.__pwModels && window.__pwModels.statuses)", timeout=30)
    ev(ws, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))", timeout=10)

    ready = ev(ws, PROBE_READY, timeout=20)
    if not isinstance(ready, dict) or not ready.get("has"):
        for nm in (N_R1, N_R2, N_R3, N_R4):
            check(nm, False, "探针未取到数据：" + json.dumps(ready, ensure_ascii=False))
        return

    handle_ok = ready["hasStatuses"] and ready["hasProbe"] and ready["hasStatusOf"]
    vacuous = ready["models"] == 0
    if vacuous:
        # 空环境：这条断言天然空转 —— **显式标注**，不假装它是有效证据（真正的证据在 R2）
        check(N_R1 + "（⚠ 空转：本环境无核心服务，模型列表为空；由 R2 注入真实模型补证）",
              handle_ok, json.dumps({"句柄齐备": handle_ok, "模型数": ready["models"],
                                      "空转": True}, ensure_ascii=False))
    else:
        bad = [(d["id"], d["status"]) for d in ready["dom"]
               if not any(t["id"] == d["id"] and t["display"] == d["status"] for t in ready["truth"])]
        check(N_R1, handle_ok and not bad,
              json.dumps({"句柄齐备": handle_ok, "模型数": ready["models"],
                          "不一致": bad}, ensure_ascii=False))

    # ---- R2/R3 注入真实模型 + 真实探测 ----
    inj = ev(ws, PROBE_INJECT_AND_PROBE, timeout=30)
    if not isinstance(inj, dict) or not inj.get("probe"):
        why = json.dumps(inj, ensure_ascii=False)
        check(N_R2, False, "注入/探测未产出结果：" + why)
        check(N_R3, False, "注入/探测未产出结果")
        return
    if inj.get("errors"):
        # 注入本身报错 → 证据链断了，如实标注（不静默放过）
        print("  · 注入期告警：" + json.dumps(inj["errors"], ensure_ascii=False))
    ev(ws, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))", timeout=10)
    after = ev(ws, PROBE_AFTER, timeout=20)
    if not isinstance(after, dict) or after.get("local") is None:
        check(N_R2, False, "读回失败：" + json.dumps(after, ensure_ascii=False))
        check(N_R3, False, "读回失败")
        return

    probe = inj["probe"]
    local = after["local"]
    # R2 核心：真探测 + 如实失败 + DOM 与 Registry 同源
    r2_ok = (
        probe.get("ok") is False                       # 修复前这里会是 True（假绿）
        and probe.get("probed") is True                # 真的发过请求
        and probe.get("code") in ("local_model_down", "unreachable")
        and local["display"] == "offline"
        and local["lastError"] in ("local_model_down", "unreachable")
        and after["localDom"] is not None
        and after["localDom"]["status"] == "offline"    # DOM == Registry
        and not after["mismatches"]
    )
    check(N_R2, r2_ok,
          json.dumps({"probe": probe, "registry": {"display": local["display"], "lastError": local["lastError"]},
                      "dom": after["localDom"], "逐项不一致": after["mismatches"]}, ensure_ascii=False))

    # R3：API 模型无凭据 → 未配置（不是连接失败）
    api = after["api"]
    r3_ok = (
        api is not None
        and api["needsSecret"] is True and api["hasSecret"] is False
        and api["display"] == "unconfigured"
        and after["apiDom"] is not None
        and after["apiDom"]["status"] == "unconfigured"
    )
    check(N_R3, r3_ok,
          json.dumps({"registry": api, "dom": after["apiDom"]}, ensure_ascii=False))

    # ---- R4 出厂包的归约函数 ----
    mx = ev(ws, PROBE_MATRIX, timeout=15)
    if not isinstance(mx, dict):
        check(N_R4, False, "读回失败：" + repr(mx))
        return
    r4_ok = (mx["ready"] == "connected" and mx["unconfigured"] == "unconfigured"
             and mx["offline"] == "offline" and mx["failed"] == "failed"
             and mx["fakeGreen"] != "connected" and mx["notEnabled"] == "offline")
    check(N_R4, r4_ok, json.dumps(mx, ensure_ascii=False))

    # 收尾：把注入的模型摘掉，避免影响后续（本进程随后即退出，但保持干净）
    ev(ws, """(() => {
      const r = window.__pwModels.registry;
      for (const id of (r.list() || []).map(e => e.id)) {
        if (id.indexOf('t6a-') === 0) r.remove(id);
      }
      for (const pid of ['t6a-local', 't6a-api']) r.providers.removeProvider(pid);
      return true;
    })()""", timeout=10)


DYNAMIC_GROUPS = (("R1~R4 模型管理中心（/models）", _r_models),)


def run_dynamic(ws: "CDPWebSocket") -> None:
    base = getattr(ws, "_tech06a_base")
    for label, fn in DYNAMIC_GROUPS:
        try:
            fn(ws, base)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check(f"{label} · 组异常", False, "EXCEPTION: " + " | ".join(tb[-3:]))


# ================================================================ 主流程

def main() -> int:
    print("=== TECH-06-A 验收 · AI 模型真实连接完善 ===")

    if not DIST.exists():
        print(f"FATAL ui/dist 不存在：{DIST}（先 `npm run build`）")
        return 2

    # ---- Node 直驱（纯函数穷举）
    tmp = Path(tempfile.mkdtemp(prefix="pw-tech06a-"))
    try:
        compile_entries(tmp)
        run_js(tmp)
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        check("①~⑥ Node 直驱（纯函数穷举）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # ---- 静态
    for fn in (t1_single_vocabulary, t2_entry_exposes_evidence, t3_three_probe_kinds,
               t4_no_new_backend, t5_no_fake_green, t6_ui_frozen, t7_no_new_storage,
               t8_no_new_page):
        try:
            fn()
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check(f"{fn.__name__} · 组异常", False, "EXCEPTION: " + " | ".join(tb[-3:]))

    # ---- 动态：Edge headless + CDP（最终产物）
    edge = None
    proc = None
    srv = None
    profile = None
    ws = None
    try:
        edge = find_edge()
        port, srv = start_server()
        base = f"http://127.0.0.1:{port}"
        dbg_port = free_port()
        profile = tempfile.mkdtemp(prefix="pw-tech06a-")
        cmd = [
            edge, "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-default-browser-check", f"--user-data-dir={profile}",
            f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
            "--window-size=1600,1000", "about:blank",
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
            check("R0 启动 Edge headless + CDP", False, "连不上 CDP")
        else:
            ws = CDPWebSocket(ws_url)
            ws.call("Page.enable")
            setattr(ws, "_tech06a_base", base)
            run_dynamic(ws)
    except Exception:
        tb = traceback.format_exc().strip().splitlines()
        check("R0 动态段（Edge headless + CDP）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        if srv is not None:
            srv.shutdown()
        if profile:
            shutil.rmtree(profile, ignore_errors=True)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== 汇总 {passed}/{total} ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
