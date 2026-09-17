# TECH-03-B · 已有 Runtime 接线准备

> 日期：2026-09-15 · 状态：**已交付，验收 81/81**
> 验收工具：`tools/verify_tech03b.py`（tsc 编译被测模块 → Node 直跑 T1~T4 + 静态全局红线 T5）
> 回归：门禁 `--stage 9 --build` FAIL=0 WARN=0 PASS=30 · 六套既有验收脚本全绿
> 前置：TECH-01（Motion）/ TECH-02（Workspace Runtime）/ TECH-03-A（Model Registry）

## 零、一句话

这一轮**不造新设施**，只做四件事：把 AI 侧栏拖拽的决策权交给 Motion Runtime、
把三套各写各的 Toast 收成一个出口、为"接真实窗口"把快照接口定死（但一行窗口控制都不写）、
把 AI 顶栏的"当前模型"接到 Model Registry 上（只读）。

四条硬边界（全部在代码里可断言，不只在文档里承诺）：
**不破坏 UI · 不增加数据库迁移 · 不改变已有接口 · 全量回归。**

---

## 一、架构说明

### 1.1 四条接线各自的位置

```
                        ┌──────────────────────────── UI 层 ────────────────────────────┐
                        │                                                                │
  TECH-01 Motion ───────┤  AiSidebar.vue ──── claim(el,'drag') ──► motion/conflict.ts      │
                        │      │                  ▲ 唯一授权来源（isPrimary 守卫）        │
                        │      │                                                          │
  TECH-03-B §二 Toast ──┤      └─ 短提示 ─────► composables/useToast.ts ──► ToastHost.vue │
                        │                            （单条 + 4000ms + 变体只进数据）      │
                        │                                                                │
  TECH-03-B §四 Model ──┤  AiSidebar.vue「当前模型」◄── composables/useCurrentModel.ts     │
                        │                                └── ai/model/consumer.ts（只读面）│
                        │                                        └── ai/model/registry.ts │
                        │                                                                │
  TECH-03-B §三 Snapshot┤  workspace/snapshot.ts（零 import，未被任何页面 import）        │
                        │      capture() / restore() / validate()  ← 未来接 core 的接口面  │
                        └────────────────────────────────────────────────────────────────┘
```

### 1.2 任务一：Motion 成为拖拽的唯一来源

接线前，AI 侧栏宽度拖拽是"自己说了算"：`mousedown` 起监听、`mousemove` 直接改宽度。
一旦别的 Motion 也在同一元素上跑（例如 Cinema 接管、system 级动作），两边会同时改尺寸——
谁最后写入谁生效，**没有仲裁**。

现在把"谁有权拖"这件事收回 Motion Runtime：

| 环节 | 接线前 | 接线后 |
|------|--------|--------|
| 起拖 | 直接 `addEventListener` | 先 `claim(el, 'drag', onSuperseded)`；**拿不到 `isPrimary` 就本次不启动**，并把声明退掉 |
| 拖动中 | 每帧改宽度 | 每帧先问 `if (!dragClaim?.isPrimary) return` |
| 被顶掉 | 无感知，继续改宽度 | `onSuperseded` 立即 `endResize()`，声明与监听一起收 |
| 收尾 | 拆监听 | 拆监听 **+** `release()`（两件事必须成对，否则留下"幽灵 Primary"） |

**关键：这不新增任何动画。** `claim()` 是一个纯决策器，它不产生过渡、不写样式。
验收里 `T1d` 直接断言 AiSidebar 代码中不存在 `transition` / `animation` / `@keyframes` / `transform`
——"不改变视觉"是被机器验的，不是被口头保证的。

可观测性：`motion/runtime.ts` 的 debug 句柄（`window.__pwMotion`）补出了 `hasActiveClaims`，
这样"拖拽确实挂在 Motion 上"可以被外部探针看到，而不是读源码猜。

### 1.3 任务二：Toast 收成一个出口

接线前是**三套并行实现**：

| 位置 | 类名 | 形态 | 时长 | 本地状态 |
|------|------|------|------|----------|
| ModeView | `.mv-toast` | 固定底部居中 | 4000ms | `ref` + `setTimeout` |
| SoftwareView | `.apps-toast` | 固定底部居中（**声明与上者完全相同**） | 4000ms | `ref` + `setTimeout` |
| SettingsView | `.saved-toast` | 内联小字 | 无 | `ref` |

三套的规则迟早漂移，且没有任何一处能被别的模块复用（例如服务层想发提示，只能自己再造一套）。

现在只有一个来源：

```
调用方 ── toast.success / error / info(msg) ──► useToast.ts（单条 + 4000ms + 序号）
                                                    │
                                                    └─► ToastHost.vue（全应用唯一渲染者）
```

**视觉契约：变体只进数据，暂不进样式。** 这是本轮最要紧的一个决定。
`success/error/info` 会如实写进 `state.variant`，并作为 `data-variant` 挂到宿主元素上，
但 CSS 里**没有任何**按变体着色的规则——所以三个页面的提示**像素级不变**。
验收 `T2c` 把 canonical 的 10 条声明逐条与接线前的值比对（`position:fixed` / `bottom:24px` /
`left:50%` / `transform:translateX(-50%)` / `--panel` 底 / `--border` 边 / 8px 圆角 /
`8px 14px` 内边距 / `--shadow` / `z-index:60`），`T2d` 断言 CSS 中不存在 `[data-variant]` 规则。

**degraded-banner 刻意不并入。** 它看起来也是"底部一条提示"，但语义完全不同：
Toast 是"我刚做了一件事的结果"（瞬时、可丢），banner 是"系统当前处于降级状态"（持续、不可丢）。
把持续状态塞进 4 秒就消失的组件里是语义降级。验收 `T2e` 同时断言"规则仍在"且"没被并入 toast"。

### 1.4 任务三：快照接口定死，但一行窗口控制都不写

WorkspaceSnapshot v1 的契约（`docs/contracts/workspace-snapshot.v1.schema.json`）在 PW-INTEGRATION-003
已经冻结，本轮补的是**前端侧的接口面**：`capture()` / `restore()` / `validate()`。

未来真实窗口控制需要四件东西，本轮确认结构上已支持、不需要再改结构：

| 字段 | 含义 | 本轮状态 |
|------|------|----------|
| `hwnd` | 句柄 | 已定稿，**volatile**（只在 `source.runId` 期间有效） |
| `pid` | 进程 id | 已定稿 |
| `rectPx` / `rectNorm` | 绝对像素 + 归一化 | 已定稿，归一化由 `deriveNormRect` 单点换算 |
| `zIndex` | Z 序（越大越靠前） | 已定稿，恢复计划按它升序重排 |

四条红线做成了**可断言的数据**，而不是文档里的一句承诺：

```ts
RestorePlan.guardrails = {
  killsProcesses: false,          // 不杀进程
  launchesApps: false,            // 不启动软件
  writesDatabase: false,          // 不改数据库
  touchesUnmanagedWindows: false, // 不碰未登记窗口
}
```

再加两道"不假装"：

- **没有探针就不产出快照**。`capture()` 在探针未接线时返回 `ok:false / dryRun:true /
  degraded:['probe-not-wired']`，**不编一份看起来像样的假数据**——那会让下游误以为恢复链已通。
- **`restore()` 只算不做**。每一步都带 `executable: false`，计划里含"要把软件重新拉起来"的动作时
  只登记 `skip` + `requiresUserConfirm: true`。

**hwnd 跨运行期失效**这条语义被单独验：`runId` 不匹配时，计划里**每一步**都降级为 `skip`
（而不是假装能按旧句柄恢复）；配了对照组证明 `runId` 相同时确实会产出 `place-window`。

### 1.5 任务四：模型只读消费者

TECH-03-A 把 `ModelRegistry` 立成了"模型管理的唯一读写口"，但刻意**零接线**——
于是 canonical（用户到底在用哪个模型）在 UI 上**没有第二双眼睛看得到**。

本轮补上**只读的那一半**，并且把"只读"做成类型层面的约束：

```
ModelRegistry（可读写）
     │  只投影读方法
     ▼
createModelReadOnly() ──► { current(), list(), providers(), hasCredential(), subscribe() }  ← Object.freeze
     │
     ▼
AiSidebar.vue「当前模型：GPT-5」  ← 纯展示，不可点、不可改
```

消费者拿到的对象上**根本没有** `setCanonical` / `add` / `update` / `remove` / `setDefault` /
`check` / `setCredential`——所以"消费者不会偷偷改模型"不是靠自觉，是靠拿不到方法。
验收 `t4-b` 用 `MUTATOR_NAMES` 逐项断言一个写方法都没漏出来，`t4-c` 作为对照组断言读方法齐备
（否则一个空对象也能过），`t4-m` 断言调用只读面后 Registry 的 canonical 与 revision 都没变。

顶栏的状态归约（`resolveCurrentModel`）覆盖四种真实情形，每一种都**如实显示、不静默兜底**：

| 情形 | 顶栏显示 | 为什么不兜底 |
|------|----------|--------------|
| 从未设置 | `未配置` | 不假装有模型 |
| 正常 | `模型名` + Provider 标签 | — |
| canonical 有值但模型被删 | `模型名` + 角标`已失效` | 静默回退成"未配置"会掩盖"用户选的东西没了" |
| 写入没落到 L1 | 角标`待同步` | 不谎报"已落库到契约键" |
| core 不可达、走本地缓存 | 角标`离线` | 离线态必须可见 |

**不连真实 API**：本层不调 `check()`、不建 `createModelsApi`、不写 config、不碰凭据（`T4d` 静态断言）。
`useCurrentModel.ts` 只做两件只读的事：`hydrate()`（读 L0 + 读 canonical）与订阅刷新。

---

## 二、文件变更

### 新增（6 个）

| 文件 | 行数 | 作用 |
|------|------|------|
| `ui/src/composables/useToast.ts` | 146 | 统一 Toast Service：`toast.success/error/info/show/dismiss/subscribe` |
| `ui/src/components/ToastHost.vue` | 27 | **全应用唯一**的 toast 渲染者（`data-pw-toast` / `:data-variant`） |
| `ui/src/workspace/snapshot.ts` | 907 | WorkspaceSnapshot v1 接口面：`capture` / `restore` / `validate`（零 import） |
| `ui/src/ai/model/consumer.ts` | 192 | 模型只读消费者面（`ModelReadOnly` + `MUTATOR_NAMES`） |
| `ui/src/composables/useCurrentModel.ts` | 115 | 单例 Registry + 只读投影（懒启动、失败不抛给 UI） |
| `tools/verify_tech03b.py` | 1001 | 本轮验收脚本（81 项） |

### 修改（8 个）

| 文件 | 改动 | 边界说明 |
|------|------|----------|
| `ui/src/components/AiSidebar.vue` | 拖拽走 `claim('drag')`（§一）；顶部加只读「当前模型」（§四） | 视觉零变化；无新增动效 |
| `ui/src/motion/runtime.ts` | debug 句柄补出 `hasActiveClaims` | 只加可观测性，不改行为 |
| `ui/src/App.vue` | 挂载 `<ToastHost />` | 单点出口 |
| `ui/src/styles/base.css` | 加 `.toast-canonical`（10 条声明逐字取自旧实现）+ `.ai-canonical`；**删** `.saved-toast` | canonical 像素级不变；`degraded-banner` 未动 |
| `ui/src/views/ModeView.vue` | 19 处提示改走统一服务；删本地 `toast`/`toastTimer`/`.mv-toast` | 文案与时长不变 |
| `ui/src/views/SoftwareView.vue` | 13 处提示改走统一服务；删本地实现/`.apps-toast` | 同上 |
| `ui/src/views/SettingsView.vue` | 5 处提示改走统一服务；删 `flash()`/`keyMessage`/`.saved-toast` | 同上（本轮最高优先目标） |
| `tools/verify_model_registry.py` | **T6b 判据升级**：`零接线` → `接线点白名单 + 白名单内不得写`（新增 T6b2） | 见 §四 · 限制 6 |

### 未改（明确不动）

`core/**`（Rust）· `database/**` · `ai/**`（Python sidecar）· `core/migrations/**`（仍止于 `0008`）·
`ui/src/stores/ai.ts`（既有 AI 链路一行未改）· `ui/src/workspace/{store,layout,runtime}.ts`。

---

## 三、验收结果

### 3.1 本轮验收脚本：`tools/verify_tech03b.py` — **81/81 PASS**

手段：把被测 `.ts` 用仓库里的 tsc 编成 CommonJS 再在 Node 里**直跑真实模块**
（`useToast.ts` 依赖 `vue`，故在临时目录放一个只实现 `ref`/`readonly` 的最小 stub——
这样"单条/顶替/时长"这些纯逻辑可以被确定性验证，不牵扯浏览器）。

| 组 | 项数 | 代表断言 |
|----|------|----------|
| T0 编译 | 1 | 8 个入口文件全部编译落地 |
| T1 Motion | 5 静态 + 11 Node | 拖拽守卫三件套成对；**真实 `conflict.ts`** 驱动：低优先级抢不走、高优先级顶掉后移动被拒、同优先级只留一条 |
| T2 Toast | 7 静态 + 12 Node | canonical 10 条声明逐条一致；三套残留清零；无 `[data-variant]` 着色；`degraded-banner` 未被并；单条顶替 / 空文案不弹 / 40ms 自动消失 |
| T3 Snapshot | 6 静态 + 16 Node | v2 黑名单与 schema 逐项一致；零执行依赖；`capture` 无探针拒绝伪造；`restore` 全步 `executable:false` + 四护栏 false；`runId` 不匹配全 `skip` |
| T4 只读消费者 | 4 静态 + 13 Node | 只读面冻结且写方法零泄漏（配读方法齐备对照组）；四态归约（未配置/正常/已失效/待同步/离线）；调用后 registry 状态不变 |
| T5 全局红线 | 5 | 迁移仍止于 0008；L1 键仍未登记；既有 AI store 对外面 12/12；本轮新增面全在 UI/工具层；typecheck 通过 |

**修掉的两处"假失败"（脚本自身缺陷，非产品缺陷）**：`snap-k` 的 fixture 只有 1 个 managed 窗口，
导致"排序"断言无从验证；`snap-o` 的 fixture 自相矛盾（`managed` 说软件没跑、`foregroundHwnd` 却指向在跑的窗口），
于是计划里多出一条**合法的** `focus-window`。两处都改为构造自洽 fixture 后通过——
按既有口径，**脚本红但产品对 ⇒ 改脚本**，不能为了"绿"去放松产品断言。

### 3.2 全量回归（六套既有验收 + 门禁）

| 项 | 命令 | 结果 |
|----|------|------|
| 门禁（含编译） | `python tools/gate.py --stage 9 --build` | **FAIL=0 WARN=0 PASS=30**（`B100 cargo check` / `B110 前端 typecheck` 均过） |
| 契约 | `tools/verify_contracts.py` | **6/6** 符合预期 |
| TECH-01 Motion/Skin/Tokens | `tools/verify_tech01.py` | **9/9** |
| Skin Engine | `tools/verify_skin_engine.py` | **12/12** |
| TECH-02 Workspace Runtime | `tools/verify_tech02_workspace.py` | **11/11** |
| TECH-03-A Model Registry | `tools/verify_model_registry.py` | **32/32**（含整仓 `vue-tsc + vite build`） |
| 性能基线 | `tools/perf_tech01_22.py` | 12 场景 **error 行 0**；所有场景 `longtask.count=0`（含 `S8_toast`、`S3a_drag_ai_sidebar`） |

### 3.3 四条硬边界的机器证据

| 边界 | 证据 |
|------|------|
| **不破坏 UI** | 门禁 `B110` typecheck 过 + `verify_model_registry T6f` 整仓 `vue-tsc + vite build` 过 + `T2c` canonical 声明逐条不变 + `T1d` 无新增动效 + perf `longtask=0` |
| **不增加数据库迁移** | `T5a`：`core/migrations` 仍为 8 个、止于 `0008_plugin_audit.sql` |
| **不改变已有接口** | `T5c`：既有 AI store 对外面 12/12 完好；`verify_model_registry T6c`：既有 AI 链路符号 10/10 完好；`T5b`：未新增 config 键、未新增 core 命令 |
| **全量回归** | §3.2 表：六套脚本 + 门禁全绿 |

---

## 四、当前限制与下一阶段建议

### 限制 1：Toast 变体只进数据，还没进样式
`success/error/info` 现在只体现在 `data-variant` 上，外观三态同一套。这是**刻意的**——
本轮原则是"已有视觉不变"。真正着色应与 IP1 的浮层/反馈体系一起做（否则会变成第三套局部配色）。

### 限制 2：快照只有接口面，真实采集仍缺
`capture()` 恒 `dryRun`、`restore()` 恒 `executable:false`——因为窗口枚举在 core（Rust）侧（ADR-001），
本轮不碰。下一轮接真实窗口时：core 侧实现 `WindowProbe` 的对应能力 → `capture()` 一行不用改即可接通。

### 限制 3：`snapshot.ts` 暂未挂进 `workspaceRuntime` 门面
`workspace/snapshot.ts` 目前是**独立模块**，没有挂到 `workspaceRuntime.snapshot.*`。
原因是 `verify_tech02_workspace.py` 的 `T1c` 把 `workspace/runtime` 的消费者**白名单**限定为
`DevWorkspaceHarness` 一处；擅自挂上去会打破那条断言。
接真实窗口那一轮再挂，并同步更新那份白名单（挂的时候是**有意的**边界扩张，需要一起改）。

### 限制 4：canonical 的 L1 键仍未在 core 登记
`ai.provider.current` / `ai.model.current` 还没进 `core/src/db/config.rs` 的白名单，
所以写入会落到过渡镜像键 `ui.ai.provider` / `ui.ai.model`，顶栏角标会**长期显示"待同步"**。
这不是 bug，是迁移未完成——core 登记后 `ports.ts` 无需改动即自动切到 L1。

### 限制 5：只读接线还没驱动实际发送
顶栏现在**只显示** canonical，真正发请求仍走 `stores/ai.ts` 的 `providerId` / `model`。
所以当下存在"显示的值"与"实际发送的值"可能不一致的窗口期。
**不建议现在就直接替换**——需要同时具备两个前提才动手：
① L1 键在 core 登记（限制 4）；② 用户有一条可见的、改 canonical 的路径（设置页），
否则会出现"顶栏显示 A、发给 B"的更糟状态。
在满足这两个前提之前，"只显示不改行为"是更安全的中间态。

### 限制 6：`verify_model_registry.py T6b` 的判据被有意改写（需知会）
TECH-03-A 的 `T6b` 断言是"**零接线**（没有任何既有文件 import `ui/src/ai/model`）"。
TECH-03-B §四 明确要求把 AI 顶栏接到 ModelRegistry，两者直接冲突。
处置：把 `T6b` 从"零接线"升级为"**接线点白名单 + 白名单内不得出现写方法**"（并新增 `T6b2`），
白名单只放 `components/AiSidebar.vue` 与 `composables/useCurrentModel.ts`。
**这是对上一轮边界的显式扩张，不是静默放宽**——写在这里，避免下一个人以为 T6b 一直长这样。

### 下一阶段建议（按优先级）
1. **core 侧登记 L1 键**（`ai.provider.current` / `ai.model.current`）→ 消掉"待同步"常亮，为限制 5 铺路。
2. **设置页接管 canonical 写口** → 让用户能改"当前模型"，与顶栏只读显示形成闭环。
3. **core 实现窗口探针** → `capture()` 转 `dryRun:false`，接真实窗口控制（那时才动 `restore()` 的执行侧）。
4. **IP1 浮层统一** → Toast 变体着色 + degraded-banner 的视觉归属一起定，避免再造局部配色。
