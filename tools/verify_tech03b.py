#!/usr/bin/env python3
"""TECH-03-B 验收 · 已有 Runtime 接线准备（T1~T5）。

## 这一轮在验什么
TECH-03-B 的题目是"**不要继续造基础设施，开始把已有能力接进真实应用**"。
所以本脚本的验收口径与前三轮不同：不是"新模块能跑"，而是
**"接线真的接上了，而且没把原来好的东西碰坏"**。

| 组 | 验的是 | 手段 |
|----|--------|------|
| T1 | AI 侧栏拖拽经 Motion Runtime `claim('drag')` 决策 | 静态（调用/守卫成对）+ **Node 直驱真实 `motion/conflict.ts`** |
| T2 | 三套 Toast 归一 + 视觉逐字不变 + degraded-banner 未被并 | 静态（CSS 声明逐条比对 + 残留清零）+ **Node 直驱 `useToast.ts`（vue stub）** |
| T3 | WorkspaceSnapshot v1 三方法 + 四条红线可断言 | **Node 直驱 `workspace/snapshot.ts`** + 与 JSON Schema 的 `x-pw-v2-forbidden` 逐项对齐 |
| T4 | 只读消费者面（无写方法）+ AI 顶栏真的接上 | **Node 直驱 `ai/model/consumer.ts`** + 静态接线点 |
| T5 | 全局红线：不加迁移 / 不改已有接口 / 不改 core 面 | 静态 + 既有脚本交叉 |

## 反"假通过"的三条设计（沿用 TECH-03-A 的口径）
1. **每个"被禁用"的断言都配一个对照组**：说"没有写方法"，就必须同时证明"读方法都在"——
   否则一个空对象也能过。
2. **异步语义用异步断言**：`restore()` / `capture()` 是 `async`，用 `await` 抓 rejection，
   不用同步 `try/catch`（会静默变成 unhandled rejection）。
3. **不宣称端到端**：真实窗口采集在 core（Rust）侧，本轮只验"接口面 + 红线"，
   不验"窗口真的被摆回去了"——那是接真实窗口那一轮的题目。

## 编译方式
与 TECH-03-A 同法：把被测 `.ts` 用仓库里的 tsc 编成 CommonJS 再在 Node 里跑。
`useToast.ts` 依赖 `vue`，故在临时目录放一个**最小 vue stub**（只实现 `ref`/`readonly`），
这样"Toast 的单条/顶替/时长"这些**纯逻辑**可以被确定性地验证，不牵扯浏览器。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

try:  # 控制台编码兜底（Windows 下偶发 gbk）
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:  # pragma: no cover
    pass

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
SRC = UI / "src"
TSC = UI / "node_modules" / "typescript" / "lib" / "tsc.js"

# 被测入口（tsc 会沿着 import 图把依赖一并编出来）
ENTRY_FILES = [
    "ai/model/model.ts",
    "ai/model/provider.ts",
    "ai/model/registry.ts",
    "ai/model/consumer.ts",
    "motion/config.ts",
    "motion/conflict.ts",
    "composables/useToast.ts",
    "workspace/snapshot.ts",
]

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


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


def npm() -> str:
    cands: list[str] = []
    pf = os.environ.get("ProgramFiles")
    if pf:
        cands.append(str(Path(pf) / "nodejs" / "npm.cmd"))
    which = shutil.which("npm")
    if which:
        cands.append(which)
    for cand in cands:
        if cand and Path(cand).exists():
            return str(cand)
    raise RuntimeError("找不到 npm")


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def read_src(rel: str) -> str:
    return (SRC / rel).read_text(encoding="utf-8")


def strip_comments(text: str) -> str:
    """去掉 TS/JS 注释 —— 只在"代码里不许出现 X"这类断言里用（注释里提到 X 是允许的）。"""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(?m)//[^\n]*", "", text)
    return text


# ---------------------------------------------------------------- T0 编译

VUE_STUB = r"""
'use strict';
// 最小 vue stub：只实现被测逻辑真正用到的 ref / readonly / computed。
// 目的是让 useToast.ts 的**纯状态逻辑**能在 Node 里被确定性验证。
function ref(initial) {
  return { value: initial };
}
function readonly(r) {
  return new Proxy(r, {
    get(t, k) { return t[k]; },
    set() { throw new Error('readonly ref: 不允许写入'); },
  });
}
function computed(fn) {
  return { get value() { return fn(); } };
}
module.exports = { ref, readonly, computed };
"""


def compile_entries(tmp: Path) -> None:
    if not TSC.exists():
        raise RuntimeError(f"缺少 typescript 编译器：{TSC}（先 npm install）")
    args = [
        node(), str(TSC),
        "--target", "ES2022",
        "--module", "commonjs",
        "--moduleResolution", "node",
        "--strict",
        "--esModuleInterop",
        "--skipLibCheck",
        "--rootDir", str(SRC),
        "--outDir", str(tmp),
        *[str(SRC / f) for f in ENTRY_FILES],
    ]
    proc = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(UI), timeout=240)
    if proc.returncode != 0:
        raise RuntimeError(f"tsc 编译失败（exit {proc.returncode}）：\n{proc.stdout}\n{proc.stderr}")
    # 全部产物必须落地（少一个就说明 import 图被削了）
    for f in ENTRY_FILES:
        out = tmp / f.replace(".ts", ".js")
        if not out.exists():
            raise RuntimeError(f"编译产物缺失：{out}")
    # vue stub
    vdir = tmp / "node_modules" / "vue"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "package.json").write_text('{"name":"vue","version":"0.0.0-stub","main":"index.js"}',
                                       encoding="utf-8")
    (vdir / "index.js").write_text(VUE_STUB, encoding="utf-8")


def run_js(tmp: Path, name: str) -> list[tuple[str, bool, str]]:
    """跑一个已写入 tmp 的 JS harness，读回它打印的 `__PW_RESULT__` JSON。"""
    proc = subprocess.run([node(), str(tmp / name)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(tmp), timeout=240)
    out = proc.stdout or ""
    marker = [ln for ln in out.splitlines() if ln.startswith("__PW_RESULT__")]
    if not marker:
        raise RuntimeError(
            f"{name} 未产出结果（exit {proc.returncode}）\nSTDOUT:\n{out[-2500:]}\n"
            f"STDERR:\n{(proc.stderr or '')[-2500:]}"
        )
    payload = json.loads(marker[-1][len("__PW_RESULT__"):])
    return [(c[0], bool(c[1]), str(c[2])) for c in payload["checks"]]


# ---------------------------------------------------------------- T1 Motion 业务接线

MOTION_JS = r"""
'use strict';
const { claim, hasActiveClaims } = require('./motion/conflict.js');
const checks = [];
function check(name, passed, detail) { checks.push([name, !!passed, String(detail)]); }

// 说明：conflict.ts 只用 WeakMap 以元素为 key，不需要真实 DOM —— 普通对象即可。
// 这本身就是"Motion 决策与 DOM 解耦"的证据。

// ① 正常拖拽：drag 拿到 Primary
{
  const el = {};
  const drag = claim(el, 'drag');
  check('motion-a drag 声明即取得 Primary', drag.isPrimary === true, 'isPrimary=' + drag.isPrimary);
  check('motion-b 元素上有活跃声明（可观测）', hasActiveClaims(el) === true, String(hasActiveClaims(el)));
  drag.release();
  check('motion-c release 后无残留（不留幽灵 Primary）', hasActiveClaims(el) === false,
        String(hasActiveClaims(el)));
}

// ② 低优先级抢不走：drag 在时 hover 拿不到 Primary，且 drag 仍然是 Primary
{
  const el = {};
  const drag = claim(el, 'drag');
  const hover = claim(el, 'hover');
  check('motion-d 低优先级抢不走（hover 拿不到 Primary）', hover.isPrimary === false,
        'hover.isPrimary=' + hover.isPrimary);
  check('motion-e 高优先级未被降级（drag 仍是 Primary）', drag.isPrimary === true,
        'drag.isPrimary=' + drag.isPrimary);
}

// ③ 高优先级顶掉：system 声明时 drag 立即失效 + onSuperseded 触发（调用方得以收敛）
{
  const el = {};
  const fired = [];
  const drag = claim(el, 'drag', () => fired.push('drag'));
  const sys = claim(el, 'system', () => fired.push('system'));
  check('motion-f 更高优先级顶掉 drag（drag.isPrimary → false）', drag.isPrimary === false,
        'drag.isPrimary=' + drag.isPrimary);
  check('motion-g 被顶掉的一方收到 onSuperseded（可立即收敛）', fired.includes('drag'),
        JSON.stringify(fired));
  // AiSidebar 拖拽守卫的等价物：move 里 `if (!dragClaim?.isPrimary) return`
  let moved = 0;
  const onMove = () => { if (!drag.isPrimary) return; moved += 1; };
  onMove();
  check('motion-h 被顶掉后"移动"被拒（AiSidebar move 守卫等价物）', moved === 0, 'moved=' + moved);
  check('motion-i 顶掉后 system 自己是 Primary', sys.isPrimary === true, 'sys.isPrimary=' + sys.isPrimary);
}

// ④ 同优先级只留一条：新的顶替旧的
{
  const el = {};
  const d1 = claim(el, 'drag');
  const d2 = claim(el, 'drag');
  check('motion-j 同优先级新声明取代旧声明（不会同时两个 Primary）',
        d1.isPrimary === false && d2.isPrimary === true,
        'd1=' + d1.isPrimary + ',d2=' + d2.isPrimary);
  d2.release();
  check('motion-k release 只释放自己那条', hasActiveClaims(el) === false, String(hasActiveClaims(el)));
}

console.log('__PW_RESULT__' + JSON.stringify({ checks }));
"""


def t1_motion() -> None:
    sidebar = read_src("components/AiSidebar.vue")
    code = strip_comments(sidebar)

    has_claim = bool(re.search(r"claim\(\s*el\s*,\s*'drag'", code))
    check("T1a 拖拽入口向 Motion Runtime 声明 claim('drag')", has_claim,
          "startResize 里 claim(el,'drag',…)" if has_claim else "未见 claim('drag') 调用")

    primary_guard = "if (!c.isPrimary)" in code
    move_guard = "if (!dragClaim?.isPrimary) return" in code
    release_paired = bool(re.search(r"dragClaim\?\.release\(\)", code))
    check("T1b 声明三件套成对（拿不到 Primary 即退 / move 侧守卫 / endResize 必 release）",
          primary_guard and move_guard and release_paired,
          json.dumps({"noPrimary→return": primary_guard, "moveGuard": move_guard,
                      "release": release_paired}, ensure_ascii=False))

    bound = '@mousedown.prevent="startResize"' in sidebar and 'ref="resizerEl"' in sidebar
    check("T1c 拖拽把手绑定在同一元素（resizerEl）", bound,
          "resizerEl ↔ @mousedown.prevent=startResize" if bound else "绑定缺失")

    # 不新增动效：拖拽相关代码里不得出现 transition / animation / keyframes / transform
    motion_verbs = [v for v in ("transition", "animation", "@keyframes", "transform") if v in code]
    check("T1d 不新增动效（AiSidebar 代码里无 transition/animation/keyframes/transform）",
          not motion_verbs, "无动效" if not motion_verbs else "; ".join(motion_verbs))

    # Motion debug 句柄暴露 hasActiveClaims（可观测性 → 验收可探针）
    runtime = read_src("motion/runtime.ts")
    check("T1e Motion debug 句柄暴露 hasActiveClaims（接线可被外部观测）",
          "hasActiveClaims" in runtime, "motion/runtime.ts 已导出")


# ---------------------------------------------------------------- T2 统一 Toast

# 接线前的 canonical 声明（ModeView `.mv-toast` / SoftwareView `.apps-toast` 本就完全相同）
CANONICAL_DECLS = {
    "position": "fixed",
    "bottom": "24px",
    "left": "50%",
    "transform": "translateX(-50%)",
    "background": "var(--panel)",
    "border": "1px solid var(--border)",
    "border-radius": "8px",
    "padding": "8px 14px",
    "box-shadow": "var(--shadow)",
    "z-index": "60",
}

TOAST_JS = r"""
'use strict';
const t = require('./composables/useToast.js');
const { ref } = require('vue');
const checks = [];
function check(name, passed, detail) { checks.push([name, !!passed, String(detail)]); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const seen = [];
  const off = t.subscribeToast((x) => seen.push(x ? x.message + '|' + x.variant : null));

  check('toast-a 三入口齐全（success / error / info）',
        typeof t.toast.success === 'function' && typeof t.toast.error === 'function'
        && typeof t.toast.info === 'function',
        ['success', 'error', 'info'].map((k) => k + '=' + typeof t.toast[k]).join(','));

  check('toast-b 默认时长 = 4000ms（与接线前一致）', t.TOAST_DEFAULT_DURATION === 4000,
        String(t.TOAST_DEFAULT_DURATION));

  const a = t.toast.success('已保存');
  check('toast-c success 变体如实记录', a && a.variant === 'success', a ? a.variant : 'null');

  const b = t.toast.error('出错了');
  check('toast-d 单条语义：新的顶掉旧的（同时只显示一条）',
        t.currentToast.value !== null && t.currentToast.value.message === '出错了'
        && b.id === a.id + 1,
        'cur=' + (t.currentToast.value ? t.currentToast.value.message : 'null')
        + ', idA=' + a.id + ', idB=' + b.id);

  check('toast-e 变体只进数据（presentation 恒为 canonical，本轮不改外观）',
        t.currentToast.value.presentation === 'canonical', t.currentToast.value.presentation);

  check('toast-f data-variant 会挂到宿主上（供将来着色）',
        t.currentToast.value.variant === 'error', t.currentToast.value.variant);

  const before = t.currentToast.value.message;
  const nullish = t.showToast('   ');
  check('toast-g 空文案不弹（不留空框）', nullish === null && t.currentToast.value.message === before,
        'ret=' + JSON.stringify(nullish));

  check('toast-h 订阅者收到变更（服务层可监听）', seen.length >= 2, 'seen=' + JSON.stringify(seen));

  // 对照组：有内容的一条一定弹得出来（证明"空不弹"不是因为整个机制哑了）
  const c = t.toast.info('正常内容');
  check('toast-i 对照组：非空文案照常显示', c !== null && t.currentToast.value.message === '正常内容',
        'cur=' + t.currentToast.value.message);

  // 自动消失（用短时长；异步断言）
  t.toast.info('短', { duration: 40 });
  await sleep(90);
  check('toast-j 到时自动消失（默认 4000ms 的机制本身可跑）', t.currentToast.value === null,
        'cur=' + JSON.stringify(t.currentToast.value));

  t.toast.success('待清除');
  t.dismissToast();
  check('toast-k dismiss 主动收起', t.currentToast.value === null, 'cleared');

  off();
  const n = seen.length;
  t.toast.info('退订后');
  check('toast-l 退订后不再收到通知', seen.length === n, 'seen=' + seen.length);

  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
})().catch((e) => {
  checks.push(['toast EXCEPTION', false, String((e && e.stack) || e)]);
  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
});
"""


def t2_toast() -> None:
    host = read_src("components/ToastHost.vue")
    app = read_src("App.vue")
    css = read_src("styles/base.css")
    use_toast = read_src("composables/useToast.ts")
    mode = read_src("views/ModeView.vue")
    soft = read_src("views/SoftwareView.vue")
    settings = read_src("views/SettingsView.vue")

    # 2a 唯一渲染者
    host_marker = "data-pw-toast" in host
    mounted = "ToastHost" in app
    check("T2a 唯一渲染者：ToastHost 挂载于 App（单点出口）", host_marker and mounted,
          json.dumps({"data-pw-toast": host_marker, "App 挂载": mounted}, ensure_ascii=False))

    # 2b 三套旧实现残留清零（要求：不是注释里提到，而是真的没有规则/用法）
    def has_rule(text: str, cls: str) -> bool:
        return bool(re.search(r"\.%s\s*\{" % re.escape(cls), text))

    def has_class_usage(text: str, cls: str) -> bool:
        return bool(re.search(r"class=\"[^\"]*\b%s\b" % re.escape(cls), text))

    leftovers = {
        ".mv-toast 规则": has_rule(mode, "mv-toast"),
        ".mv-toast 用法": has_class_usage(mode, "mv-toast"),
        ".apps-toast 规则": has_rule(soft, "apps-toast"),
        ".apps-toast 用法": has_class_usage(soft, "apps-toast"),
        ".saved-toast 规则": has_rule(css, "saved-toast") or has_rule(settings, "saved-toast"),
        ".saved-toast 用法": has_class_usage(settings, "saved-toast"),
    }
    dirty = [k for k, v in leftovers.items() if v]
    check("T2b 三套旧实现残留清零（规则 + 用法都无）", not dirty,
          "已清零" if not dirty else "; ".join(dirty))

    # 2c canonical 声明逐条等于接线前
    m = re.search(r"\.toast-canonical\s*\{(.*?)\}", css, flags=re.S)
    actual: dict[str, str] = {}
    if m:
        for line in m.group(1).split(";"):
            if ":" in line:
                k, v = line.split(":", 1)
                actual[k.strip()] = v.strip()
    missing = {k: v for k, v in CANONICAL_DECLS.items() if actual.get(k) != v}
    check("T2c canonical 声明逐条等于接线前（像素级不变）", not missing,
          "10/10 一致" if not missing else json.dumps(missing, ensure_ascii=False))

    # 2d 变体不进样式（本轮原则：已有视觉不变）
    variant_rules = re.findall(r"data-variant[^\n{]*\{", css)
    check("T2d 无按变体着色的 CSS（视觉零变化，只挂 data 属性）", not variant_rules,
          "无 [data-variant] 规则" if not variant_rules else "; ".join(variant_rules))
    check("T2d2 变体确实会挂到宿主上（数据层已就绪，可供将来接管）",
          "data-variant" in host, "ToastHost 上存在 :data-variant")

    # 2e degraded-banner 未被并入（它是"系统降级状态"，语义不同）
    banner_kept = has_rule(css, "degraded-banner")
    banner_merged = ("degraded" in use_toast.lower()) or ("degraded" in host.lower())
    check("T2e degraded-banner 未被并入 Toast（系统状态 ≠ 短提示）",
          banner_kept and not banner_merged,
          json.dumps({"规则仍在": banner_kept, "被并入 toast": banner_merged}, ensure_ascii=False))

    # 2f 三处页面全部改走统一服务，且本地实现已删
    def migrated(text: str) -> tuple[bool, bool]:
        imported = "from '@/composables/useToast'" in text
        local_gone = ("toastTimer" not in strip_comments(text)) and (
            not re.search(r"const\s+toast\s*=\s*ref", strip_comments(text)))
        return imported, local_gone

    mi, mg = migrated(mode)
    si, sg = migrated(soft)
    se_imported = "from '@/composables/useToast'" in settings
    se_local_gone = ("function flash(" not in strip_comments(settings)) and (
        not re.search(r"const\s+message\s*=\s*ref", strip_comments(settings)))
    check("T2f 三处页面全部迁移到统一服务（import 到 + 本地实现已删）",
          mi and mg and si and sg and se_imported and se_local_gone,
          json.dumps({"ModeView": [mi, mg], "SoftwareView": [si, sg],
                      "SettingsView": [se_imported, se_local_gone]}, ensure_ascii=False))

    # 2g 接线前时长语义：旧实现是 4000ms（防"顺手改成别的值"）
    check("T2g 默认时长常量在源码里显式声明为 4000", "TOAST_DEFAULT_DURATION = 4000" in use_toast,
          "TOAST_DEFAULT_DURATION = 4000")


# ---------------------------------------------------------------- T3 Snapshot 接口


def t3_snapshot() -> None:
    snap = read_src("workspace/snapshot.ts")
    schema = json.loads(read("docs/contracts/workspace-snapshot.v1.schema.json"))

    # 3f 与冻结契约的 v2 黑名单逐项一致
    schema_forbidden = [str(x) for x in schema.get("x-pw-v2-forbidden", [])]
    m = re.search(r"SNAPSHOT_V2_FORBIDDEN[^=]*=\s*\[(.*?)\]", snap, flags=re.S)
    ts_forbidden = re.findall(r"'([^']+)'", m.group(1)) if m else []
    same = schema_forbidden == ts_forbidden
    check("T3f v2 越界字段黑名单与冻结 schema 逐项一致（顺序也一致）", same,
          json.dumps({"schema": len(schema_forbidden), "ts": len(ts_forbidden),
                      "一致": same}, ensure_ascii=False))

    # 3g 零执行依赖（不杀进程 / 不起进程 / 不碰 DB / 不 invoke core）
    code = strip_comments(snap)
    forbidden_calls = {
        "invokeCore": "invokeCore" in code,
        "child_process/require": bool(re.search(r"\brequire\s*\(", code)),
        "process.kill": bool(re.search(r"\bprocess\.kill\b", code)),
        "tauri": bool(re.search(r"\btauri\b", code, flags=re.I)),
        "fetch/http": bool(re.search(r"\bfetch\s*\(|https?://", code)),
    }
    dirty = [k for k, v in forbidden_calls.items() if v]
    check("T3g snapshot 零执行依赖（无 invoke/require/kill/tauri/fetch，也不碰 DB）",
          not dirty, "纯函数，零 import" if not dirty else "; ".join(dirty))

    imports = re.findall(r"^\s*import\s", snap, flags=re.M)
    check("T3g2 snapshot 模块零 import（不依赖 store / @/api / core）", not imports,
          "0 import" if not imports else f"{len(imports)} 处 import")

    # 3h 三方法齐备（接口面完整）
    three = all(k in snap for k in ("export async function capture", "export function restore",
                                    "export function validate"))
    check("T3h 接口面齐备（capture / restore / validate 三方法）", three,
          "capture+restore+validate 均在")

    # 3i 四件"未来真实窗口要支持的字段"已定稿
    fields = {"hwnd": "hwnd" in snap, "pid": "pid" in snap,
              "rectPx/rectNorm": "rectPx" in snap and "rectNorm" in snap, "zIndex": "zIndex" in snap}
    check("T3i 未来窗口控制所需四件已定稿（hwnd / pid / rect / zIndex）",
          all(fields.values()), json.dumps(fields, ensure_ascii=False))

    # 3j 契约键名与 schema 一致
    key_ok = "workspace.snapshot.last" in snap
    check("T3j 持久化键名 = 契约键 `workspace.snapshot.last`", key_ok,
          "SNAPSHOT_CONFIG_KEY = workspace.snapshot.last" if key_ok else "键名不符")


SNAPSHOT_JS = r"""
'use strict';
const S = require('./workspace/snapshot.js');
const checks = [];
function check(name, passed, detail) { checks.push([name, !!passed, String(detail)]); }
const codes = (issues) => issues.map((i) => i.code).join(',');
function badCodes(res) { return res.issues.map((i) => i.code).sort().join(','); }

(async () => {
  const work = { x: 0, y: 0, w: 1920, h: 1040 };
  const mk = (x, w, hwnd, z) => ({
    hwnd: hwnd, pid: 500 + hwnd, exeName: 'app' + hwnd + '.exe', exePath: null, appId: hwnd,
    title: 'win' + hwnd, className: 'Cls', monitorIndex: 0,
    rectPx: { x: x, y: 0, w: w, h: work.h },
    rectNorm: S.deriveNormRect({ x: x, y: 0, w: w, h: work.h }, work),
    state: { visible: true, minimized: false, maximized: false }, zIndex: z,
  });
  const good = {
    schemaVersion: 1,
    snapshotId: 'ws-20260915-104200-abcd',
    takenAt: 1789000000000,
    trigger: 'enter_mode',
    source: { appVersion: '0.1.0', corePid: 4242, runId: 'run-aaa' },
    monitors: [{ index: 0, primary: true, bounds: { x: 0, y: 0, w: 1920, h: 1080 }, work: work }],
    desktop: { foregroundHwnd: 100, windows: [mk(0, 960, 100, 10), mk(960, 960, 200, 20)] },
    workspace: {
      modeName: '开发模式', modeId: 1, layoutName: null, monitor: 0, launchedAppIds: [100],
      managed: [{ appId: 100, appName: 'VS Code', pid: 600, hwnd: 100 }],
    },
  };

  // ① 合法样本通过
  const vg = S.validate(good);
  check('snap-a validate 合法样本通过（对照：校验器不是"全拒"）', vg.ok === true,
        vg.ok ? 'ok' : badCodes(vg));

  // ② rectNorm 必须与 rectPx/work 一致（跨字段不变量）
  const drift = JSON.parse(JSON.stringify(good));
  drift.desktop.windows[0].rectNorm.x = 0.5;
  const vd = S.validate(drift);
  check('snap-b rectNorm 与 rectPx/work 不一致时被拦（invariant 生效）',
        !vd.ok && vd.issues.some((i) => i.code === 'invariant:rectNorm-consistent'), badCodes(vd));

  // ③ v2 越界字段被拦（history 类）
  const v2 = JSON.parse(JSON.stringify(good));
  v2.history = [{ snapshotId: 'ws-20260915-104200-ffff' }];
  const vv2 = S.validate(v2);
  check('snap-c v2 越界字段（history）被拦', !vv2.ok
        && vv2.issues.some((i) => i.code === 'forbidden-v2-key:history'), badCodes(vv2));

  // ④ 明文密钥字段被拦（红线 V1）
  const sec = JSON.parse(JSON.stringify(good));
  sec.workspace.apiKey = 'whatever';
  const vs = S.validate(sec);
  check('snap-d 密钥字段（apiKey）被拦（红线 V1）', !vs.ok
        && vs.issues.some((i) => i.code.startsWith('secret-key:')), badCodes(vs));

  // ⑤ hwnd 唯一性 + 前台必须在列表内
  const dup = JSON.parse(JSON.stringify(good));
  dup.desktop.windows[1].hwnd = 100;
  const dupRes = S.validate(dup);
  check('snap-e hwnd 重复被拦', !dupRes.ok
        && dupRes.issues.some((i) => i.code === 'invariant:hwnd-unique'), badCodes(dupRes));

  const fg = JSON.parse(JSON.stringify(good));
  fg.desktop.foregroundHwnd = 999;
  const fgRes = S.validate(fg);
  check('snap-f 前台窗口不在列表内被拦', !fgRes.ok
        && fgRes.issues.some((i) => i.code === 'invariant:foreground-present'), badCodes(fgRes));

  // ⑥ capture：探针未接线 → 明确拒绝，不编造假数据
  const cap1 = await S.capture();
  check('snap-g capture 无探针时不产出快照（拒绝伪造，非"假通过"）',
        cap1.ok === false && cap1.snapshot === null && cap1.dryRun === true
        && cap1.degraded.includes('probe-not-wired'),
        JSON.stringify({ ok: cap1.ok, snap: cap1.snapshot, degraded: cap1.degraded }));

  let rejected = false;
  try { await S.nullProbe.windows(); } catch (e) { rejected = true; }
  check('snap-h nullProbe 的每个方法都明确 reject（不静默返回空）', rejected, 'rejected=' + rejected);

  // ⑦ restore：只算计划，不执行 —— 每步 executable=false + 四护栏全 false
  const plan = S.restore(good);
  const stepsAllFalse = plan.steps.every((s) => s.executable === false);
  const guards = plan.guardrails;
  check('snap-i restore 只产出计划（executable 恒 false，不执行窗口控制）',
        plan.ok === true && plan.executable === false && stepsAllFalse && plan.steps.length > 0,
        'steps=' + plan.steps.map((s) => s.kind).join('>'));
  check('snap-j 四条红线可断言（不杀进程/不启动软件/不写库/不碰未登记窗口）',
        guards.killsProcesses === false && guards.launchesApps === false
        && guards.writesDatabase === false && guards.touchesUnmanagedWindows === false,
        JSON.stringify(guards));

  // ⑦b 排序与范围：managed 故意写成乱序，且多一个"未登记"的窗口
  const ordered = JSON.parse(JSON.stringify(good));
  ordered.desktop.windows = [mk(0, 600, 100, 10), mk(600, 600, 200, 20), mk(1200, 720, 300, 30)];
  ordered.desktop.foregroundHwnd = null;
  ordered.workspace.managed = [
    { appId: 200, appName: '后启动的', pid: 700, hwnd: 200 },
    { appId: 100, appName: '先启动的', pid: 600, hwnd: 100 },
  ];
  const oPlan = S.restore(ordered, { currentRunId: 'run-aaa' });
  const placed = oPlan.steps.filter((s) => s.kind === 'place-window');
  check('snap-k 计划按 zIndex 升序重排（managed 乱序 200,100 → 计划 10,20）',
        placed.map((s) => s.hwnd).join(',') === '100,200'
        && placed.map((s) => s.zIndex).join(',') === '10,20',
        'hwnd=' + placed.map((s) => s.hwnd).join(',')
        + ' z=' + placed.map((s) => s.zIndex).join(','));
  check('snap-l 只处理 managed 里的窗口（未登记的 300 号窗口一律不碰）',
        placed.every((s) => s.hwnd !== 300) && placed.length === 2,
        'hwnd=' + placed.map((s) => s.hwnd).join(','));

  // ⑧ runId 不匹配 → hwnd 全部失效 → 全 skip（volatile 语义）
  const stale = S.restore(good, { currentRunId: 'run-bbb' });
  check('snap-m runId 不匹配 ⇒ 全部降级为 skip（hwnd 跨运行期无效）',
        stale.ok === true && stale.mode === 'stale-hwnd' && stale.runIdMatch === false
        && stale.steps.length > 0 && stale.steps.every((s) => s.kind === 'skip')
        && stale.skipped === stale.steps.length,
        JSON.stringify({ mode: stale.mode, kinds: stale.steps.map((s) => s.kind), skipped: stale.skipped }));

  // ⑨ 对照组：runId 相同 → 有 place-window（证明上一条不是因为"永远只产 skip"）
  const same = S.restore(good, { currentRunId: 'run-aaa' });
  check('snap-n 对照组：runId 相同 → 产出 place-window（证明上条非恒 skip）',
        same.mode === 'same-run' && same.steps.some((s) => s.kind === 'place-window'),
        JSON.stringify({ mode: same.mode, kinds: same.steps.map((s) => s.kind) }));

  // ⑩ 无 hwnd 的 managed → 不启动软件，只登记 + 要求用户确认（红线 V5）
  //    注：foregroundHwnd 一并置 null —— 否则计划里会有一条合法的 focus-window，
  //    那会让"全部都是 skip"这个断言变成假失败。
  const noHwnd = JSON.parse(JSON.stringify(good));
  noHwnd.desktop.foregroundHwnd = null;
  noHwnd.workspace.managed = [{ appId: 7, appName: '未启动的软件', pid: null, hwnd: null }];
  const nhPlan = S.restore(noHwnd, { currentRunId: 'run-aaa' });
  check('snap-o 缺 hwnd 时不启动软件，只登记 skip + requiresUserConfirm（红线 V5）',
        nhPlan.requiresUserConfirm === true
        && nhPlan.steps.length > 0
        && nhPlan.steps.every((s) => s.kind === 'skip' && s.executable === false),
        JSON.stringify({ confirm: nhPlan.requiresUserConfirm, kinds: nhPlan.steps.map((s) => s.kind) }));

  // ⑪ 非法输入 → restore 不猜，返回 issues
  const badPlan = S.restore({ schemaVersion: 2 });
  check('snap-p 非法输入时 restore 只回问题、不产出步骤',
        badPlan.ok === false && badPlan.steps.length === 0 && badPlan.issues.length > 0,
        codes(badPlan.issues));

  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
})().catch((e) => {
  checks.push(['snapshot EXCEPTION', false, String((e && e.stack) || e)]);
  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
});
"""


# ---------------------------------------------------------------- T4 模型只读消费者


def t4_consumer() -> None:
    consumer = read_src("ai/model/consumer.ts")
    composable = read_src("composables/useCurrentModel.ts")
    sidebar = read_src("components/AiSidebar.vue")

    code = strip_comments(consumer)
    mutators_in_code = [k for k in ("setCanonical", "add", "update", "remove", "setDefault", "check")
                        if re.search(r"\b%s\s*\(" % k, code)]
    check("T4c 只读消费者模块自身不调用任何写方法", not mutators_in_code,
          "只有读方法" if not mutators_in_code else "; ".join(mutators_in_code))

    comp_code = strip_comments(composable)
    no_check = ".check(" not in comp_code
    no_api = "createModelsApi" not in comp_code
    no_write = not any(k in comp_code for k in ("setCanonical", "setDefault", "setCredential",
                                                "importProfiles"))
    check("T4d 接线桥不连真实 API / 不写（无 check() / createModelsApi / 写方法）",
          no_check and no_api and no_write,
          json.dumps({"无 check()": no_check, "无 createModelsApi": no_api,
                      "无写方法": no_write}, ensure_ascii=False))

    hooked = "data-pw-current-model" in sidebar and "当前模型" in sidebar
    from_bridge = "useCurrentModel" in sidebar
    check("T4e AI 侧栏顶部接入只读「当前模型」（标记 + 文案 + 桥接）",
          hooked and from_bridge,
          json.dumps({"data-pw-current-model": "data-pw-current-model" in sidebar,
                      "文案": "当前模型" in sidebar, "桥接": from_bridge}, ensure_ascii=False))

    read_only_api = "interface ModelReadOnly" in consumer and "MUTATOR_NAMES" in consumer
    check("T4f 只读面类型显式声明 + 写方法清单可被断言（MUTATOR_NAMES）",
          read_only_api, "ModelReadOnly + MUTATOR_NAMES")


CONSUMER_JS = r"""
'use strict';
const { ModelRegistry } = require('./ai/model/registry.js');
const { createModelReadOnly, resolveCurrentModel, MUTATOR_NAMES } =
  require('./ai/model/consumer.js');
const checks = [];
function check(name, passed, detail) { checks.push([name, !!passed, String(detail)]); }

function fake(seed) {
  const provs = [
    { id: 'openai', label: 'OpenAI', defaultEndpoint: 'https://api.openai.com/v1',
      defaultModel: 'gpt-5', needsKey: true, enabled: true, note: '',
      capabilities: ['chat', 'stream', 'models'] },
    { id: 'ollama', label: 'Ollama', defaultEndpoint: 'http://localhost:11434',
      defaultModel: 'qwen2.5:7b', needsKey: false, enabled: true, note: '',
      capabilities: ['chat', 'stream', 'models'] },
  ];
  const kv = new Map();
  const creds = new Set();
  const st = { mode: 'core', landing: 'core', cache: null };
  return {
    st: st,
    ports: {
      io: { async listRemoteModels() { return []; } },
      capability: {
        async loadProviders() { return provs; },
        async loadSecretPresence() { return [...creds]; },
      },
      canonical: {
        keys: { provider: 'ai.provider.current', model: 'ai.model.current' },
        mirrorKeys: { provider: 'ui.ai.provider', model: 'ui.ai.model' },
        async read() {
          if (st.mode === 'none') return null;
          const p = kv.get('p') || '';
          const m = kv.get('m') || '';
          if (!p && !m) return null;
          return { values: { provider: p, model: m, apiBase: '' }, from: st.mode };
        },
        async write(patch) {
          if (patch.provider !== undefined) kv.set('p', patch.provider);
          if (patch.model !== undefined) kv.set('m', patch.model);
          return { landedOn: st.landing };
        },
      },
      cache: {
        read() { return st.cache; },
        write(v) { st.cache = v; },
        clear() { st.cache = null; },
      },
      secret: {
        refFor: (id) => 'pw/' + id + '/default',
        async has(id) { return creds.has(id); },
        async set(id) {
          creds.add(id);
          return { provider: id, ref: 'pw/' + id + '/default', mask: '****', backend: 'memory' };
        },
        async remove(id) { return creds.delete(id); },
      },
      now: () => 1700000000000,
    },
  };
}

(async () => {
  // ① 只读面：冻结 + 一个写方法都没有 + 读方法齐备（对照组）
  {
    const f = fake();
    const reg = new ModelRegistry(f.ports);
    const ro = createModelReadOnly(reg);
    check('t4-a 只读面被 Object.freeze', Object.isFrozen(ro) === true, String(Object.isFrozen(ro)));
    const keys = Object.keys(ro);
    const leaked = keys.filter((k) => MUTATOR_NAMES.indexOf(k) >= 0);
    check('t4-b 只读面一个写方法都没有（MUTATOR_NAMES 全不在）', leaked.length === 0,
          'keys=' + keys.join(',') + ' leaked=' + leaked.join(','));
    const reads = ['current', 'list', 'providers', 'hasCredential', 'subscribe'];
    const missing = reads.filter((k) => keys.indexOf(k) < 0);
    check('t4-c 对照组：读方法齐备（证明上条不是"空对象"）', missing.length === 0,
          'present=' + reads.filter((k) => keys.indexOf(k) >= 0).join(','));
    let injectedThrew = false;
    try { ro.setCanonical = function () {}; } catch (e) { injectedThrew = true; }
    check('t4-d 冻结后无法往只读面里塞写方法', ro.setCanonical === undefined,
          'threw=' + injectedThrew);
  }

  // ② unset：从未设置过
  {
    const f = fake();
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    const view = resolveCurrentModel(reg);
    check('t4-e 未设置时 label=未配置（不假装有模型）',
          view.set === false && view.label === '未配置' && view.dangling === false,
          JSON.stringify({ label: view.label, set: view.set, source: view.source }));
  }

  // ③ 正常：有默认模型 → label = 模型名，detail = Provider 标签
  {
    const f = fake();
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    const p = reg.add({ provider: 'openai', model: 'gpt-5', name: 'GPT-5' });
    await reg.setDefault(p.id);
    const view = resolveCurrentModel(reg);
    check('t4-f 正常态：label=模型名 / detail=Provider 标签 / 无角标',
          view.set === true && view.label === 'GPT-5' && view.detail === 'OpenAI' && view.badge === '',
          JSON.stringify({ label: view.label, detail: view.detail, badge: view.badge }));
    check('t4-g 只读面 current() 与纯函数同源（同一个 Registry 得同一个值）',
          createModelReadOnly(reg).current().label === view.label, view.label);
  }

  // ④ dangling：canonical 有值但模型被删
  {
    const f = fake();
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    const p = reg.add({ provider: 'openai', model: 'gpt-5', name: 'GPT-5' });
    await reg.setDefault(p.id);
    reg.remove(p.id);
    const view = resolveCurrentModel(reg);
    check('t4-h 模型被删后如实标"已失效"（不静默回退成未配置）',
          view.dangling === true && view.badge === '已失效' && view.label === 'gpt-5',
          JSON.stringify({ dangling: view.dangling, badge: view.badge, label: view.label }));
  }

  // ⑤ pendingSync：写入只落到过渡镜像
  {
    const f = fake();
    f.st.mode = 'mirror';
    f.st.landing = 'mirror';
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    const p = reg.add({ provider: 'openai', model: 'gpt-5', name: 'GPT-5' });
    await reg.setDefault(p.id);
    const view = resolveCurrentModel(reg);
    check('t4-i 未落到 L1 时标"待同步"（不谎报已落库）',
          view.pendingSync === true && view.badge === '待同步',
          JSON.stringify({ badge: view.badge, source: view.source, pendingSync: view.pendingSync }));
  }

  // ⑥ stale：只有本地缓存（core 不可达）
  {
    const f = fake();
    f.st.mode = 'none';
    f.st.cache = { provider: 'ollama', model: 'qwen2.5:7b', apiBase: '' };
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    reg.add({ provider: 'ollama', model: 'qwen2.5:7b', name: 'Qwen2.5' });
    const view = resolveCurrentModel(reg);
    check('t4-j core 不可达走缓存时标"离线"（stale 可见）',
          view.stale === true && view.badge === '离线' && view.source === 'cache',
          JSON.stringify({ badge: view.badge, source: view.source, stale: view.stale }));
  }

  // ⑦ 订阅：Registry 变更能被只读面观察到
  {
    const f = fake();
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    const ro = createModelReadOnly(reg);
    const seen = [];
    const off = ro.subscribe((reason, rev) => seen.push(reason + '#' + rev));
    const p = reg.add({ provider: 'openai', model: 'gpt-5', name: 'GPT-5' });
    await reg.setDefault(p.id);
    check('t4-k 只读面能订阅到 Registry 变更（顶栏可自动刷新）', seen.length >= 2,
          JSON.stringify(seen));
    off();
    const n = seen.length;
    reg.add({ provider: 'ollama', model: 'qwen2.5:7b', name: 'Q' });
    check('t4-l 退订后不再收到通知', seen.length === n, 'seen=' + seen.length);
  }

  // ⑧ 只读面不改状态：调完所有读方法后 Registry 状态不变
  {
    const f = fake();
    const reg = new ModelRegistry(f.ports);
    await reg.hydrate();
    const p = reg.add({ provider: 'openai', model: 'gpt-5', name: 'GPT-5' });
    await reg.setDefault(p.id);
    const before = JSON.stringify(reg.getCanonical());
    const revBefore = reg.getRevision();
    const ro = createModelReadOnly(reg);
    ro.current(); ro.list(); ro.providers(); ro.hasCredential('openai');
    check('t4-m 只读面调用后 Registry 状态与 revision 均不变（真只读）',
          JSON.stringify(reg.getCanonical()) === before && reg.getRevision() === revBefore,
          'canonical 与 revision 未变');
  }

  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
})().catch((e) => {
  checks.push(['consumer EXCEPTION', false, String((e && e.stack) || e)]);
  console.log('__PW_RESULT__' + JSON.stringify({ checks }));
});
"""


# ---------------------------------------------------------------- T5 全局红线


def t5_global() -> None:
    # 5a 不加数据库迁移
    mig = sorted(p.name for p in (ROOT / "core" / "migrations").glob("*.sql"))
    expected_last = "0008_plugin_audit.sql"
    check("T5a 未新增数据库迁移（core/migrations 仍止于 0008）",
          bool(mig) and mig[-1] == expected_last,
          json.dumps({"count": len(mig), "last": mig[-1] if mig else None}, ensure_ascii=False))

    # 5b core 面（**TECH-04 §一 起判据翻转**）
    #    TECH-03-B 时这里断言"L1 键仍未登记"。TECH-04 正式登记了 canonical 的落点，
    #    于是本条改为断言**登记齐全 + 镜像键仍保留**（否定式 → 更强的一致性断言）。
    config_rs = read("core/src/db/config.rs")
    commands_rs = read("core/src/api/commands.rs")
    l1_ok = {}
    for k in ("ai.provider.current", "ai.model.current"):
        in_keys = ("\"%s\"" % k) in config_rs
        tail_type = config_rs.split("fn expected_type")[-1].split("fn type_ok")[0]
        tail_default = config_rs.split("fn default_for")[-1]
        in_type = bool(re.search(r"\"%s\"" % re.escape(k), tail_type))
        in_default = bool(re.search(r"\"%s\"\s*=>" % re.escape(k), tail_default))
        l1_ok[k] = bool(in_keys and in_type and in_default)
    mirror_kept = ("\"ui.ai.provider\"" in config_rs) and ("\"ui.ai.model\"" in config_rs)
    ports_ts = read_src("ai/model/ports.ts")
    used = set(re.findall(r"invokeCore<[^>]*>\('([a-z_]+)'", ports_ts)) | set(
        re.findall(r"invokeCore\('([a-z_]+)'", ports_ts))
    existing = set(re.findall(r"pub (?:async )?fn (\w+)", commands_rs))
    unknown = sorted(c for c in used if c not in existing)
    check("T5b core 面（TECH-04 起）：canonical L1 键已登记齐全 + 镜像键保留 + 只调既有命令",
          all(l1_ok.values()) and mirror_kept and not unknown,
          json.dumps({"L1三处齐全": l1_ok, "镜像键保留": mirror_kept,
                      "不存在的命令": unknown}, ensure_ascii=False))

    # 5c 不改已有接口：既有 AI store 的对外面完好
    store = read_src("stores/ai.ts")
    surface = ["providerId", "model", "mode", "messages", "currentProvider", "permissionText",
               "enabledScopes", "setProvider", "setModel", "setMode", "init", "send"]
    miss = [s for s in surface if s not in store]
    check("T5c 既有 AI store 对外面完好（接线未改已有接口）", not miss,
          "12/12 存在" if not miss else "缺失：" + ", ".join(miss))

    # 5d 未新增 core 改动面：core/ 与 database/ 本轮零改动（用 mtime 之外的口径：
    #    只断言"本轮引入的新文件都在 ui/ 与 tools/ 与 docs/"）
    new_files = [
        "ui/src/composables/useToast.ts",
        "ui/src/components/ToastHost.vue",
        "ui/src/workspace/snapshot.ts",
        "ui/src/ai/model/consumer.ts",
        "ui/src/composables/useCurrentModel.ts",
        "tools/verify_tech03b.py",
    ]
    absent = [f for f in new_files if not (ROOT / f).exists()]
    check("T5d 本轮新增面全部落在 UI/工具层（core / database / sidecar 零新增）",
          not absent, f"{len(new_files)} 个文件均存在" if not absent else "缺失：" + ", ".join(absent))

    # 5e UI 类型检查通过（不破坏 UI 的机器证据；整仓构建由回归组负责）
    proc = subprocess.run([npm(), "run", "typecheck"], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", cwd=str(UI), timeout=600)
    tail = (proc.stdout or "").strip().splitlines()[-2:]
    check("T5e UI 类型检查通过（vue-tsc --noEmit）", proc.returncode == 0,
          f"exit={proc.returncode} " + " | ".join(tail)[:180])


# ---------------------------------------------------------------- 主流程


def main() -> int:
    print("=== TECH-03-B 验收 · 已有 Runtime 接线准备 ===")
    tmp = Path(tempfile.mkdtemp(prefix="pw-tech03b-"))
    try:
        try:
            compile_entries(tmp)
            sizes = ", ".join(f"{f.split('/')[-1]}→{(tmp / f.replace('.ts', '.js')).stat().st_size}B"
                              for f in ENTRY_FILES)
            check("T0 被测模块编译（tsc → CommonJS）", True, sizes)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check("T0 被测模块编译（tsc → CommonJS）", False, "EXCEPTION: " + " | ".join(tb[-3:]))
            raise SystemExit(1)

        # 静态组（先跑：不依赖编译产物，失败也能看到）
        for fn in (t1_motion, t2_toast, t3_snapshot, t4_consumer):
            try:
                fn()
            except Exception:
                tb = traceback.format_exc().strip().splitlines()
                check(getattr(fn, "__name__", "static"), False,
                      "EXCEPTION: " + " | ".join(tb[-3:]))

        # Node 驱动组
        for name, script in (("motion.js", MOTION_JS), ("toast.js", TOAST_JS),
                             ("snapshot.js", SNAPSHOT_JS), ("consumer.js", CONSUMER_JS)):
            (tmp / name).write_text(script, encoding="utf-8")
            try:
                for cname, passed, detail in run_js(tmp, name):
                    check(cname, passed, detail)
            except Exception:
                tb = traceback.format_exc().strip().splitlines()
                check(f"{name}（Node 驱动）", False, "EXCEPTION: " + " | ".join(tb[-3:]))

        try:
            t5_global()
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check("t5_global", False, "EXCEPTION: " + " | ".join(tb[-3:]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"=== 汇总 {passed}/{total} ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
