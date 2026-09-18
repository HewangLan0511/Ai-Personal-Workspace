#!/usr/bin/env python3
"""TECH-05-C 验收 · 首批三个 P0 落地（来源唯一性 + 禁止项）。

## 这一轮在验什么
TECH-05-C 的任务是把原型里已经定稿的三块 UI **落到真实应用**：

| P0 | 页面 | 落点 | 必须证明的一件事 |
|----|------|------|------------------|
| P0-1 | 模型管理中心 | `/models`（`ModelsView.vue`） | 显示用的"当前模型"与 AI 请求用的"当前模型"是**同一份** |
| P0-2 | 个人档案 | `/profile`（`ProfileView.vue`） | 仍走**既有** Profile 能力；头像不碰 DB schema |
| P0-3 | 工作空间状态 | `/dashboard`（`WorkspaceStatus.vue`） | 状态只有一个来源 `workspaceRuntime`；零真实控制 |

## 四组的判据（对应任务书"至少验证"四条）
- **T1** ModelsView 使用 ModelRegistry（不是自建清单 / 不是 localStorage / 不是第二份投影）
- **T2** Profile 使用既有 Profile capability（`profileApi` + store；两套结构各自独立；头像走已登记 config 键）
- **T3** workspace 状态来自 `workspaceRuntime`（不绕过门面直连 store/layout；零执行入口）
- **T4** 无第二套 token / 组件 / 动画体系（token 声明文件仍只有那两个；原语层只消费不定义；@keyframes 声明全局仍只 1 处）

## 为什么"静态 + 动态"两遍
静态能证明"接的是哪条线"，但证明不了"线上真有电"：
- 静态：import 图 / 禁止标识符 / 登记表 —— 抓"绕过门面自己造一份"；
- 动态（Edge headless + CDP，跑**最终 dist 产物**）：
  ① `window.__pwModels.registry === window.__pwAiModel.registry`（**对象同一性**：
     模型管理页取数的那份 Registry 与 AI 侧栏取数的那份是同一个，不靠"两边都写着 canonical"）；
  ② 页面 DOM 的当前模型 key == 该 Registry 的 `getDefault()`（显示 == 取数）；
  ③ 模型管理页的当前模型 label == AI 侧栏的当前模型 label（两个组件、同一个投影函数）；
  ④ 模型卡片计数文案 == `registry.list().length`（列表是投影，不是写死的）；
  ⑤ `/dashboard` 上目标/模式文案 == `workspaceRuntime.getCurrent()`；
     `snapshot.status().recovery.executable === false`（零真实恢复）；
  ⑥ S2：切路由后**壳层节点身份保持**，而**页面节点身份必须变化**（对照组），
     且 `window` 上的引导标记未重置（证明没有整页 reload）。

## 反"假通过"
- 空数据环境（headless 里没有 Tauri 后端）会让"两边都是空字符串"的断言变成空转 ——
  因此 ② 之外**必须**有 ①（对象同一性，与数据无关）兜底，并在 detail 里显式标注是否空转；
- ⑥ 自带反向对照（页面节点**必须**换新），否则"什么都没变"也能骗过节点身份断言。

## 不做的事
不重跑 TECH-02/03/04 的题目，只验本轮新增面；`verify_tech02_workspace.py` 的
T1c 消费者白名单已登记新组件（`WorkspaceStatus.vue`），由该脚本自己去守。
"""

from __future__ import annotations

import importlib.util
import json
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
DIST = ROOT / "ui" / "dist"
SRC = ROOT / "ui" / "src"

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


# ================================================================ T1 P0-1

MODELS = "views/ModelsView.vue"


def t1_models_registry() -> None:
    raw = read_src(MODELS)
    code = strip_comments(raw)

    # T1a 取的是**共享单例**，不是自己 new 一个
    from_bridge = set(re.findall(r"import\s*\{([^}]*)\}\s*from\s*'@/ai/model/bridge'", code, re.S))
    names: set[str] = set()
    for block in from_bridge:
        names |= {n.strip() for n in block.split(",") if n.strip()}
    need = {"getSharedRegistry", "ensureHydrated", "syncSelection"}
    check("T1a 模型管理页从 bridge 取**共享** Registry（getSharedRegistry / ensureHydrated / syncSelection）",
          need <= names, json.dumps(sorted(names), ensure_ascii=False))

    # T1b 当前模型用**同一个投影函数**（与 AI 侧栏一致），不另写一份
    uses_resolve = bool(re.search(r"import\s*\{[^}]*resolveCurrentModel[^}]*\}\s*from\s*'@/ai/model/consumer'", code, re.S))
    sidebar = read_src("components/AiSidebar.vue")
    composable = read_src("composables/useCurrentModel.ts")
    same_projection = ("resolveCurrentModel" in composable) and ("getSharedRegistry" in composable)
    check("T1b 「当前模型」走与 AI 侧栏**同一个** resolveCurrentModel 投影（非第二份逻辑）",
          uses_resolve and same_projection,
          json.dumps({"页面用 resolveCurrentModel": uses_resolve, "侧栏链路同源": same_projection},
                     ensure_ascii=False))

    # T1c 不存在第二份模型清单 / 不把清单写进 localStorage
    forbidden = {
        "MODELS 常量表": re.search(r"(?m)^\s*(?:const|let|var)\s+MODELS\b", code) is not None,
        "aiModel": "aiModel" in code,
        "localStorage": "localStorage" in code,
        "sessionStorage": "sessionStorage" in code,
    }
    hits = [k for k, v in forbidden.items() if v]
    check("T1c 无第二份模型清单（不定义 MODELS / 不碰 localStorage）", not hits,
          "未见 MODELS/aiModel/localStorage" if not hits else "; ".join(hits))

    # T1d 列表确实来自 registry.list()（而不是字面量数组）
    list_ok = bool(re.search(r"models\.value\s*=\s*registry\.list\(\)", code))
    prov_ok = bool(re.search(r"providers\.value\s*=\s*registry\.listProviders\(\)", code))
    sub_ok = bool(re.search(r"registry\.subscribe\(", code))
    check("T1d 列表/Provider 由 registry.list() / listProviders() 投影，并订阅变更后重取",
          list_ok and prov_ok and sub_ok,
          json.dumps({"list()": list_ok, "listProviders()": prov_ok, "subscribe()": sub_ok}, ensure_ascii=False))

    # T1e 写口收敛：切换走 bridge.syncSelection / 设默认走 registry.setDefault
    switch_ok = bool(re.search(r"await\s+syncSelection\(", code))
    default_ok = bool(re.search(r"await\s+registry\.setDefault\(", code))
    check("T1e 写 canonical 只经 syncSelection / registry.setDefault（与 AI 侧栏同一写口）",
          switch_ok and default_ok,
          json.dumps({"syncSelection": switch_ok, "setDefault": default_ok}, ensure_ascii=False))

    # T1f 路由与入口登记
    router = read_src("router/index.ts")
    route_ok = bool(re.search(r"path:\s*'/models'", router)) and "/views/ModelsView.vue" in router
    settings = read_src("views/SettingsView.vue")
    entry_ok = "/models" in settings
    check("T1f `/models` 路由存在，且设置页有入口（模型管理页不进主导航）", route_ok and entry_ok,
          json.dumps({"路由": route_ok, "设置页入口": entry_ok}, ensure_ascii=False))


# ================================================================ T2 P0-2


def t2_profile_capability() -> None:
    raw = read_src("views/ProfileView.vue")
    code = strip_comments(raw)

    # T2a 仍接既有 Profile 能力
    api_ok = "profileApi" in code and bool(re.search(r"from\s*'@/api/profileService'", code))
    store_ok = "useProfileStore" in code and bool(re.search(r"from\s*'@/stores/profile'", code))
    check("T2a 个人档案仍走既有 Profile 能力（profileService + useProfileStore）",
          api_ok and store_ok, json.dumps({"profileApi": api_ok, "profileStore": store_ok}, ensure_ascii=False))

    # T2b 两套结构各自独立：基础字段（profile_basic）与扩展块（技能/项目/时间线）分属不同调用
    ext_calls = {
        "技能": "profileApi.skillAdd" in code and "skillRemove" in code,
        "项目经历": "profileApi.projectAdd" in code and "projectRemove" in code,
        "时间线": "profileApi.timelineAdd" in code and "timelineRemove" in code,
    }
    basic_ok = store_ok and "saveBasic" in code
    check("T2b `profile.fields`（基础字段）与 `profileExts`（技能/项目/时间线）仍是两套独立结构",
          basic_ok and all(ext_calls.values()),
          json.dumps({"基础字段→saveBasic": basic_ok, **ext_calls}, ensure_ascii=False))

    # T2c 头像**不改 DB schema**：走已登记的 config 键
    AVATAR_KEY = "profile.avatar"
    key_ok = f"'{AVATAR_KEY}'" in code
    cfg_ok = "configApi" in code and bool(re.search(r"configApi\.put\(\s*AVATAR_KEY", code)) \
        and bool(re.search(r"configApi\.get<string>\(\s*AVATAR_KEY", code))
    check("T2c 头像读写走**既有 config 通道**（configApi.get/put，键 profile.avatar）",
          key_ok and cfg_ok, json.dumps({"键名": key_ok, "get/put": cfg_ok}, ensure_ascii=False))

    # T2c2 core 侧三处登记齐备（否则 ConfigService::set 会 bail）
    config_rs = read("core/src/db/config.rs")
    in_keys = f'"{AVATAR_KEY}"' in config_rs
    tail_type = config_rs.split("fn expected_type")[-1].split("fn type_ok")[0]
    tail_default = config_rs.split("fn default_for")[-1]
    in_type = bool(re.search(r'"%s"' % re.escape(AVATAR_KEY), tail_type))
    in_default = bool(re.search(r'"%s"\s*=>' % re.escape(AVATAR_KEY), tail_default))
    check("T2c2 core 三处登记齐备（KEYS / expected_type / default_for）",
          in_keys and in_type and in_default,
          json.dumps({"KEYS": in_keys, "expected_type": in_type, "default_for": in_default},
                     ensure_ascii=False))

    # T2c3 未新增数据库迁移（头像不是 schema 变更）
    migs = sorted(p.name for p in (ROOT / "core" / "migrations").glob("*.sql"))
    check("T2c3 未新增数据库迁移（头像不改 schema）",
          bool(migs) and migs[-1] == "0008_plugin_audit.sql",
          json.dumps({"count": len(migs), "last": migs[-1] if migs else None}, ensure_ascii=False))

    # T2d 既有交互保留：编辑 / 取消（Esc）/ 保存 / 标签 / 头像选择面
    interactions = {
        "编辑开关": "editingBasic" in code,
        "Esc 取消": "Escape" in code and "keydown" in code,
        "保存": "saveBasic" in code,
        "兴趣标签": "interests" in code or "tags" in code,
        "头像选择面": "avatarOpen" in code and "avatarDraft" in code,
        "Toast 反馈": "toast." in code,
    }
    check("T2d 既有交互保留（编辑/取消(Esc)/保存/标签/头像面/Toast）",
          all(interactions.values()), json.dumps(interactions, ensure_ascii=False))

    # T2e 原语层复用（不是又写一套 .card）
    prims = all(f"Pw{c}" in code for c in ("Button", "Card", "Chip", "Drawer"))
    check("T2e 复用共享原语（PwButton/PwCard/PwChip/PwDrawer），不另写一套卡/抽屉",
          prims, "四个原语均被引入" if prims else "缺原语")


# ================================================================ T3 P0-3

WS_STATUS = "components/WorkspaceStatus.vue"


def t3_workspace_status() -> None:
    raw = read_src(WS_STATUS)
    code = strip_comments(raw)

    # T3a 只 import 门面，不绕过它直连 store/layout
    facade_ok = bool(re.search(r"from\s*'@/workspace/runtime'", code))
    bypass = re.findall(r"from\s*'[^']*workspace/(?:store|layout)[^']*'", code)
    check("T3a 状态组件只经 workspaceRuntime 门面（不 import workspace/store|layout）",
          facade_ok and not bypass,
          "只经门面" if (facade_ok and not bypass) else f"facade={facade_ok} bypass={bypass}")

    # T3b 用到的门面方法齐全（覆盖"当前目标 / 应用状态 / 布局 / 模板 / 恢复可用性"）
    methods = ["getCurrent", "getApps", "getLayout", "updateStatus",
               "listTemplates", "saveTemplate", "prepareWorkspace", "subscribe", "snapshot.status"]
    missing = [m for m in methods if m not in code]
    check("T3b 门面方法齐备（读状态/改应用状态/模板/恢复可用性）", not missing,
          "九个入口齐备" if not missing else "缺：" + ", ".join(missing))

    # T3c 零真实控制（禁止项逐条）
    forbidden = ["launchApp", "startApp", "killProcess", "terminateProcess", "ShellExecute",
                 "moveWindow", "setWindowPos", "resizeWindow", "exec(", "spawn("]
    hits = [i for i in forbidden if i in code]
    check("T3c 零真实控制（不启动软件 / 不杀进程 / 不动窗口）", not hits,
          "无执行入口" if not hits else "; ".join(hits))

    # T3d 恢复能力如实显示（只读，不画假的"已恢复"）
    ro_ok = bool(re.search(r"workspaceRuntime\.snapshot\.status\(\)", code))
    exec_true = "executable: true" in code or "executable:true" in code
    check("T3d 恢复可用性只读展示（snapshot.status()），且不把 executable 写成 true",
          ro_ok and not exec_true, json.dumps({"status()": ro_ok, "写死true": exec_true}, ensure_ascii=False))

    # T3e 真的挂在真实工作台首页（不是固件页）
    dash = read_src("views/DashboardView.vue")
    mounted = "WorkspaceStatus" in dash and bool(re.search(r"<WorkspaceStatus\s*/?>", dash))
    check("T3e 已挂在真实工作台首页 /dashboard（DashboardView 渲染它）", mounted,
          "DashboardView 内含 <WorkspaceStatus />" if mounted else "未挂载")


# ================================================================ T4 禁止项


def t4_no_second_system() -> None:
    # T4a token 声明文件仍只有两个（没有第二套 token 体系）
    decl_files: dict[str, int] = {}
    for p in list(SRC.rglob("*.css")) + list(SRC.rglob("*.vue")):
        text = p.read_text(encoding="utf-8")
        n = len(re.findall(r"(?m)^\s*(--[A-Za-z0-9_-]+)\s*:", text))
        if n:
            decl_files[p.relative_to(SRC).as_posix()] = n
    expected = {"styles/tokens.css", "styles/motion-tokens.css"}
    check("T4a 自定义属性声明文件仍只有 tokens.css + motion-tokens.css（未新增第二套 token）",
          set(decl_files) == expected,
          json.dumps(decl_files, ensure_ascii=False))

    # T4b 补齐的语义值写在**同一个** tokens.css 里（不是另起炉灶）
    tokens = read_src("styles/tokens.css")
    added = ["--surface-overlay", "--surface-hover", "--success-soft",
             "--warning-soft", "--danger-soft", "--scrim"]
    missing = [t for t in added if t not in tokens]
    check("T4b 本轮补齐的语义值落在同一个 tokens.css（同层补充，非第二套）",
          not missing, "六个语义值均在 tokens.css" if not missing else "缺：" + ", ".join(missing))

    # T4c 原语层只**消费** token，不定义
    prim_files = ["components/ui/primitives.css"] + [
        f"components/ui/Pw{c}.vue" for c in ("Button", "Card", "Chip", "Drawer")]
    defines = []
    for rel in prim_files:
        text = read_src(rel)
        if re.search(r"(?m)^\s*--[A-Za-z0-9_-]+\s*:", text):
            defines.append(rel)
    # 用到的 var(--x) 必须都能找到定义
    #
    # ⚠️ 2026-09-18 修工具缺陷：原先用 `^\s*(--x)\s*:`（**行首锚定**）收集定义，
    # 而 tokens.css 的排版标度段是「一行多声明」（`--fs-page: 20px;  --lh-page: 28px; …`），
    # 于是 --lh-* / --ls-* 全家被判成"未定义"——这是**假阴性**，也掩盖了
    # "这些 token 其实没人在用"。改为不锚行首、先剥注释，只要求"某处有 `--x:` 声明"。
    defined: set[str] = set()
    for p in list(SRC.rglob("*.css")) + list(SRC.rglob("*.vue")):
        text = re.sub(r"/\*.*?\*/", "", p.read_text(encoding="utf-8"), flags=re.S)
        defined |= set(re.findall(r"(--[A-Za-z0-9_-]+)\s*:", text))
    used: set[str] = set()
    for rel in prim_files:
        used |= set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", read_src(rel)))
    undefined = sorted(used - defined)
    check("T4c 原语层只消费 token（零自定义属性定义）且引用的变量都有定义",
          not defines and not undefined,
          json.dumps({"自定义定义": defines, "未定义引用": undefined}, ensure_ascii=False) if (defines or undefined)
          else f"消费 {len(used)} 个变量，全部有定义")

    # T4d 动画体系：@keyframes **声明**全局仍只 1 处（base.css 的 ai-blink）
    kf_re = re.compile(r"@keyframes\s+[A-Za-z_-]")
    kf = sorted(str(p.relative_to(SRC)).replace("\\", "/")
                for p in SRC.rglob("*")
                if p.suffix in (".css", ".vue") and p.is_file() and kf_re.search(p.read_text(encoding="utf-8")))
    check("T4d 未新增动画体系（@keyframes 声明全局仅 base.css 一处）",
          kf == ["styles/base.css"], json.dumps(kf, ensure_ascii=False))

    # T4e 原语层由 main.ts 统一引入（一处入口，不散落各页）
    main_ts = read_src("main.ts")
    imp = "./components/ui/primitives.css" in main_ts
    check("T4e 原语层经 main.ts 单点引入（不散落到各页面各自 import）", imp,
          "main.ts 已引入 primitives.css" if imp else "未引入")

    # T4f 原语层**无孤儿类**（"无冗余垃圾"口径的机器守护）
    #
    # 判据：primitives.css 里定义的每个 `.pw-*` 选择器都必须被**消费**，消费只有三种形态 ——
    #   ① 字面引用：某处 `class="pw-x"`；
    #   ② 组件动态拼接：`variant`/`size` prop → `` `pw-btn--${v}` ``（拼出来也是消费）；
    #   ③ Vue 过渡类：`<Transition name="pw-fade">` 由 Vue 自动生成 `-enter-from` 等后缀。
    # 不在这三类里的 = 无人消费的半成品 —— 本期实测删掉了 `pw-empty` / `pw-seg` /
    # `pw-card--dashed` 三个（原先"预留"但零消费方），本条从此守着它不再长回来。
    body = re.sub(r"/\*.*?\*/", "", read_src("components/ui/primitives.css"), flags=re.S)
    defined = set(re.findall(r"\.(pw-[A-Za-z0-9_-]+)", body))

    literal: set[str] = set()
    dynamic_prefix: set[str] = set()
    transition_names: set[str] = set()
    for p in list(SRC.rglob("*.vue")) + list(SRC.rglob("*.ts")):
        if p.name == "primitives.css":
            continue
        text = p.read_text(encoding="utf-8")
        literal |= set(re.findall(r"\b(pw-[A-Za-z0-9_-]+)\b", text))
        # 动态拼接前缀：`pw-btn--${...}` / `pw-dot--${...}`
        dynamic_prefix |= set(re.findall(r"`(pw-[A-Za-z0-9-]+)--\$\{", text))
        transition_names |= set(re.findall(r"""name="(pw-[A-Za-z0-9-]+)\"""", text))

    composed = {c for c in defined if any(c.startswith(p + "--") for p in dynamic_prefix)}
    transitional = {c for c in defined if any(c.startswith(n + "-") for n in transition_names)}
    orphans = sorted(defined - literal - composed - transitional)
    check("T4f 原语层无孤儿类（每个 .pw-* 都有消费方：字面 / 组件拼接 / 过渡类）",
          not orphans,
          f"{len(defined)} 个类全部有消费方（字面 {len(literal & defined)} / 拼接 {len(composed)} / 过渡 {len(transitional)}）"
          if not orphans else "无人消费：" + ", ".join(orphans))


# ================================================================ 动态（最终产物）

PROBE_MODELS = r"""
(() => {
  const M = window.__pwModels, A = window.__pwAiModel;
  const card = document.querySelector('[data-pw-models-current]');
  const side = document.querySelector('[data-pw-current-model] .ai-canonical-val');
  const cnt = document.querySelector('[data-pw-models-count]');
  if (!M || !card) return { error: 'missing __pwModels / [data-pw-models-current]' };
  const need = ['list','listProviders','getDefault','subscribe','setDefault','add','remove','check','hydrate'];
  const dft = M.registry.getDefault();
  return {
    missing: need.filter(k => typeof M.registry[k] !== 'function'),
    domKey: card.getAttribute('data-current-key') || '',
    domLabel: card.getAttribute('data-current-label') || '',
    fnKey: M.current(),
    dftKey: dft && dft.model ? (dft.provider + '::' + dft.model) : '',
    sameRegistry: !!A && A.registry === M.registry,
    modelCount: M.registry.list().length,
    countText: cnt ? cnt.textContent.trim() : null,
    sidebarLabel: side ? side.textContent.trim() : null,
  };
})()
"""

PROBE_DASH = r"""
(() => {
  const W = window.__pwWorkspace;
  const sec = document.querySelector('[data-pw-workspace-status]');
  if (!W || !sec) return { error: 'missing __pwWorkspace / [data-pw-workspace-status]' };
  const cur = W.getCurrent();
  const txt = (s) => { const e = document.querySelector(s); return e ? e.textContent.trim() : null; };
  const st = W.snapshot.status();
  return {
    goalText: txt('[data-pw-ws-goal]'),
    expectGoal: (cur && cur.goal) ? cur.goal : '未设置工作目标',
    modeText: txt('[data-pw-ws-mode]'),
    expectMode: (cur && cur.mode) ? cur.mode : '未设置',
    layoutText: txt('[data-pw-ws-layout]'),
    hasBar: !!document.querySelector('[data-pw-ws-bar]'),
    recoveryText: txt('[data-pw-ws-recovery]'),
    executable: st && st.recovery ? st.recovery.executable : 'MISSING',
    tplCount: W.listTemplates().length,
    domTplCards: document.querySelectorAll('[data-pw-ws-templates] .ws-tpl').length,
    apps: W.getApps().length,
  };
})()
"""

PROBE_SHELL_MARK = r"""
(() => {
  window.__pwShellBoot = 'tech05c-probe';
  let i = 0; const seq = () => ++i;
  const main = document.querySelector('.app-main');
  const side = document.querySelector('[data-pw-current-model]');
  const page = main ? main.firstElementChild : null;
  const put = (el) => { if (!el) return null; const id = seq(); el.__pwMark = id; return id; };
  window.__pwShellProbe = { main: put(main), side: put(side), page: put(page) };
  return { ...window.__pwShellProbe, hasPage: !!page, hasSide: !!side, hasMain: !!main };
})()
"""

# SPA 导航：点**真实** RouterLink（`a[href]`），不是 Page.navigate ——
# Page.navigate 是整页加载，问"壳层是否被重建"没有意义（新窗口天然全新）。
PROBE_CLICK = r"""
(() => {
  const sel = '%s';
  const a = document.querySelector(sel);
  if (!a) return { clicked: false, sel };
  a.click();
  return { clicked: true, sel };
})()
"""

PROBE_SHELL_READ = r"""
(() => {
  const p = window.__pwShellProbe || {};
  const num = (x) => typeof x === 'number';
  const main = document.querySelector('.app-main');
  const side = document.querySelector('[data-pw-current-model]');
  const page = main ? main.firstElementChild : null;
  return {
    boot: window.__pwShellBoot || null,
    marksPresent: num(p.main) && num(p.side) && num(p.page),
    mainSame: num(p.main) && !!main && main.__pwMark === p.main,
    sideSame: num(p.side) && !!side && side.__pwMark === p.side,
    // 对照组：页面节点**必须**换新（否则"什么都没变"也能骗过上面两条）
    pageChanged: num(p.page) && !!page && page.__pwMark !== p.page,
    path: location.pathname,
  };
})()
"""


N_R1 = "R1 模型管理页真实渲染，且挂的是真 Registry（9 个方法齐备）"
N_R2 = "R2 **同源证明**：模型管理页的 Registry === AI 侧栏的 Registry（对象同一性）"
N_R3 = "R3 显示 == 取数：当前模型卡 key == registry.getDefault() == __pwModels.current()"
N_R4 = "R4 跨组件一致：模型管理页的当前模型 label == AI 侧栏的当前模型 label（同一投影函数）"
N_R5 = "R5 列表是**投影**（计数文案 == registry.list().length，不是写死的）"
N_R6 = "R6 工作空间状态块在真实工作台首页渲染（状态栏 + 恢复可用性）"
N_R7 = "R7 状态文案来自 workspaceRuntime（目标/模式文案 == getCurrent()）"
N_R8 = "R8 模板卡数量 == listTemplates().length（模板网格是投影）"
N_R9 = "R9 **零真实恢复**：snapshot.status().recovery.executable === false（写死的红线）"
N_R10 = "R10 S2：路由切换后**壳层节点身份保持**且**页面节点换新**（对照）+ 未整页 reload"


def _r_models(ws: "CDPWebSocket", base: str) -> None:
    """动态组 ①：`/models` 的来源唯一性。"""
    ws.call("Page.navigate", {"url": f"{base}/models"}, timeout=15)
    wait_for(ws, "!!(window.__pwModels && document.querySelector('[data-pw-models-current]'))", timeout=30)
    wait_for(ws, "!!(window.__pwAiModel && document.querySelector('[data-pw-current-model]'))", timeout=30)
    m = ev(ws, PROBE_MODELS, timeout=20)
    if not isinstance(m, dict) or m.get("error"):
        for nm in (N_R1, N_R2, N_R3, N_R4, N_R5):
            check(nm, False, "探针未取到数据：" + json.dumps(m, ensure_ascii=False))
        return

    check(N_R1, not m["missing"],
          json.dumps({"缺方法": m["missing"], "模型数": m["modelCount"]}, ensure_ascii=False))

    # 对象同一性：与数据无关，**永不空转** —— 这是本组的主判据
    check(N_R2, m["sameRegistry"] is True,
          f"__pwModels.registry === __pwAiModel.registry : {m['sameRegistry']}")

    vacuous = m["dftKey"] == ""
    check(N_R3 + ("（⚠ 空转：本环境无 canonical，三项均为空串；由 R2 兜底）" if vacuous else ""),
          m["domKey"] == m["fnKey"] == m["dftKey"] and len(m["domLabel"]) > 0,
          json.dumps({"DOM": m["domKey"], "current()": m["fnKey"], "getDefault()": m["dftKey"],
                      "label": m["domLabel"], "空转": vacuous}, ensure_ascii=False))

    check(N_R4, m["sidebarLabel"] is not None and m["domLabel"] == m["sidebarLabel"],
          json.dumps({"管理页": m["domLabel"], "AI侧栏": m["sidebarLabel"]}, ensure_ascii=False))

    expect_count = f"{m['modelCount']} 个模型" if m["modelCount"] else "暂无模型"
    check(N_R5, m["countText"] == expect_count,
          json.dumps({"DOM文案": m["countText"], "期望": expect_count,
                      "空转": m["modelCount"] == 0}, ensure_ascii=False))


def _r_dashboard(ws: "CDPWebSocket", base: str) -> None:
    """动态组 ②：`/dashboard` 上工作空间状态的来源。"""
    ws.call("Page.navigate", {"url": f"{base}/dashboard"}, timeout=15)
    wait_for(ws, "!!(window.__pwWorkspace && document.querySelector('[data-pw-workspace-status]'))", timeout=30)
    d = ev(ws, PROBE_DASH, timeout=20)
    if not isinstance(d, dict) or d.get("error"):
        for nm in (N_R6, N_R7, N_R8, N_R9):
            check(nm, False, "探针未取到数据：" + json.dumps(d, ensure_ascii=False))
        return

    check(N_R6, d["hasBar"] and bool(d["recoveryText"]),
          json.dumps({"状态栏": d["hasBar"], "恢复行": d["recoveryText"]}, ensure_ascii=False))

    check(N_R7, d["goalText"] == d["expectGoal"] and d["modeText"] == d["expectMode"],
          json.dumps({"goal": [d["goalText"], d["expectGoal"]], "mode": [d["modeText"], d["expectMode"]]},
                     ensure_ascii=False))

    check(N_R8, d["domTplCards"] == d["tplCount"],
          json.dumps({"DOM": d["domTplCards"], "runtime": d["tplCount"],
                      "空转": d["tplCount"] == 0}, ensure_ascii=False))

    check(N_R9, d["executable"] is False, f"executable = {d['executable']!r}")


def _r_shell(ws: "CDPWebSocket", base: str) -> None:
    """动态组 ③：S2 —— 路由切换不重建壳层。

    用**页内 SPA 导航**（点真实 RouterLink）。`Page.navigate` 是整页加载，
    拿它问"壳层是否被重建"是无效问题（新窗口里一切都是新的）。
    """
    ev(ws, PROBE_SHELL_MARK, timeout=10)
    click = ev(ws, PROBE_CLICK % '.app-nav a[href="/mode"]', timeout=10)
    if not (isinstance(click, dict) and click.get("clicked")):
        check(N_R10, False, f"找不到可点的导航链接：{json.dumps(click, ensure_ascii=False)}")
        return
    wait_for(ws, "location.pathname === '/mode'", timeout=30)
    wait_for(ws, "!!(document.querySelector('.app-main').firstElementChild)", timeout=15)
    ev(ws, "new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))", timeout=10)
    s = ev(ws, PROBE_SHELL_READ, timeout=15)
    ok_s2 = bool(s) and s.get("boot") == "tech05c-probe" and s.get("marksPresent") \
        and s.get("mainSame") and s.get("sideSame") and s.get("pageChanged")
    check(N_R10, ok_s2, json.dumps(s, ensure_ascii=False) if isinstance(s, dict) else repr(s))
    # 回到 /dashboard，方便人工/后续检查
    ev(ws, PROBE_CLICK % 'a[href="/dashboard"]', timeout=10)
    try:
        wait_for(ws, "location.pathname === '/dashboard'", timeout=20)
    except TimeoutError:
        pass


DYNAMIC_GROUPS = (
    ("R1~R5 模型管理页（/models）", _r_models),
    ("R6~R9 工作空间状态（/dashboard）", _r_dashboard),
    ("R10 S2 壳层不重建", _r_shell),
)


def run_dynamic(ws: "CDPWebSocket") -> None:
    base = getattr(ws, "_tech05c_base")
    for label, fn in DYNAMIC_GROUPS:
        # 单个动态组失败**不连坐**：后面两组照跑（否则报告只剩一句 TimeoutError）
        try:
            fn(ws, base)
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check(f"{label} · 组异常", False, "EXCEPTION: " + " | ".join(tb[-3:]))


# ================================================================ 主流程


def main() -> int:
    print("=== TECH-05-C 验收 · 首批三个 P0 ===")

    if not DIST.exists():
        print(f"FATAL ui/dist 不存在：{DIST}（先 `npm run build`）")
        return 2
    newest_src = max((p.stat().st_mtime for p in SRC.rglob("*") if p.is_file()), default=0)
    if (DIST / "index.html").stat().st_mtime < newest_src:
        print("FATAL ui/dist 早于 ui/src —— 请先 `npm run build`（验收必须跑在最终产物上）")
        return 2

    for fn in (t1_models_registry, t2_profile_capability, t3_workspace_status, t4_no_second_system):
        try:
            fn()
        except Exception:
            tb = traceback.format_exc().strip().splitlines()
            check(fn.__name__, False, "EXCEPTION: " + " | ".join(tb[-3:]))

    # 动态：Edge headless + CDP（最终产物）
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
        profile = tempfile.mkdtemp(prefix="pw-tech05c-")
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
            setattr(ws, "_tech05c_base", base)
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
