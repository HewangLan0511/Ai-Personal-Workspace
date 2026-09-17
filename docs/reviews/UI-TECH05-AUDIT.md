# UI-TECH05-AUDIT · UI 架构审计（TECH-05 阶段一）

> 日期：2026-09-16 · 性质：**只读审计，零代码修改**
> 范围：`personal-workspace-ui/`（UI 设计定稿）↔ `ui/`（真实 Vue 应用）↔ `core/`（Rust）↔ `ai/`（Python sidecar）↔ Runtime 模块
> 证据口径：所有结论标注 `文件:行号`，均来自本轮实际读码；验收基线为**本轮实跑**结果。

---

## 零、结论先行（10 秒版）

1. **工作区里有两套 UI，不是一套。** `personal-workspace-ui/index.html`（5535 行单文件原型，UI-02~UI-08 定稿）是**视觉与交互标准**；
   `ui/src/views/*.vue`（Tauri+Vue3）是**真实应用**，功能已接 core，但**视觉与原型不是同一套设计**。
   两套的类名零交集（原型 `ws-home`/`ai-dock`/`stage-grid`/`model-grid`… 在 `ui/src` 中**出现 0 次**）。
2. **"接入"的落点是真实应用**，不是原型——原型是独立 HTML，没有 Tauri 通道，无法承载真实数据。
   因此 TECH-05 的每个 P0 都是："把原型第 N 版的设计，在 `ui/` 里用真实数据实现出来"。
3. **三个 P0 的可行性差别很大**：
   - **模型管理中心**：真实应用**根本没有这个页面**（`ui/src/router/index.ts` 无 `/models`；无 models 视图）。设计（UI-06）+ Runtime（TECH-03-A/04）**都已就绪**，缺的是页面本身 → **工作量最实**。
   - **个人档案**：真实应用**已有功能页**（`ProfileView.vue`，26KB，接 `profileService` 的 22 个命令），但**缺头像**（`profile_basic` 表无 avatar 列，全仓零 avatar）→ **一处真实后端缺口**。
   - **工作空间状态**：真实应用的窗口能力（`layout_apply`/`windows_place`）**比原型更完整**，缺的是原型 UI-05-B 那套"状态栏三态 chip"的展示层 → **纯前端展示层工作**（符合"禁止实现真实窗口控制"）。
4. **P0 之前有一件事必须先定**（§二）：原型 CSS 要不要"抽取 + 适配"进 `ui/src/styles`？
   这决定了是"按原型标准改造现有组件"还是"新增一套组件"——后者正是 TECH-05 明令禁止的"创建第二套组件体系"。
5. **UI 验收基线本轮实跑全绿**（§七）：15 套脚本 + 96 条用例，其中 `verify_ui05p0` 在**批量连跑**时偶发 1 例失败，
   单跑 3 次均 7/7 —— 判定为**测试基础设施时序问题**，不是产品缺陷（已登记，见 §八 R1）。

---

## 一、审计范围与方法

### 1.1 读了什么（全部实际打开）

| 类别 | 文件 | 规模 |
|------|------|------|
| UI 设计载体 | `personal-workspace-ui/index.html` | 5535 行 |
| | `personal-workspace-ui/tokens.css` | 359 行 |
| UI 规范 | `design-system.md` / `motion-system.md` / `skin-system.md` / `default-skin.md` | 832 / 966 / 375 / 213 行 |
| UI 交接（6 份，**当前权威**） | `docs/ui-handoff/`：ui-overview / ui-components / ui-pages / ui-interaction / ui-responsive / ui-forbidden | — |
| UI 阶段报告（12 份） | `ui-02` ~ `ui-08`（含 04-a/b/c/c-p0、05-p0/b/snap） | — |
| UI 验收脚本（15 套） | `verify_*.py`（Edge 无头 + CDP） | — |
| 真实应用 | `ui/src/`：router / views(15) / components(8) / api(12) / stores(7) / workspace(4) / motion(10) / ai/model(8) / widgets(9) | — |
| 后端契约 | `core/src/db/config.rs` / `database/schema.sql` / `core/src/api/commands.rs`（121 条命令） | — |

### 1.2 本轮**没有**做什么

未修改任何产品代码；未新增路由/组件/样式；未跑 `verify_ui*` 以外的改动性操作。
唯一"执行"是**只读验收**（§七），用于建立基线。

---

## 二、关键前提：两套 UI 的关系（**这是本审计最重要的发现**）

### 2.1 事实对照

| 维度 | A 套：设计定稿原型 | B 套：真实应用 |
|------|-------------------|---------------|
| 位置 | `personal-workspace-ui/index.html` | `ui/`（Vue3 + Tauri） |
| 形态 | 单文件 HTML + 内联 CSS + 单 `<script>` | 组件化 SFC + 构建 |
| 数据 | 全内存 `state` mock（`index.html:1485`） | 真实 core 命令（121 条） |
| 路由 | hash：`#/home` `#/models` `#/run` …（`ui-overview.md` §3，共 **18** 条） | vue-router：**12** 条产品路由 + 2 条 dev-only（`ui/src/router/index.ts`） |
| 视觉 | 三层「窗口即纸面」+ `tokens.css` 单一来源 | `ui/src/styles/base.css`（14KB）+ `tokens.css`（4.6KB），**另一套** |
| 页面完成度 | 高（Hero/MiniMap/窗口编排画布/模型中心/档案编辑卡） | 中（功能可用，视觉朴素；AI 页是占位骨架） |
| 验收 | `verify_ui*.py` 15 套（测 **`index.html`**） | 无 UI 视觉验收（只有 `verify_tech02_workspace` 等行为验收） |

**类名交集为零**（实测）：`ws-home` / `home-split` / `ai-dock` / `dock-rail` / `widget-col` / `stage-grid` / `win-role` / `badge-emoji` / `model-grid` / `pick-grid` / `minimap` / `profileEditor` 在 `ui/src` 中均为 **0 个文件命中**。

### 2.2 三个必须先厘清的问题

| # | 问题 | 为什么必须先定 |
|---|------|---------------|
| **Q1** | **原型的 CSS 是否"抽取 + 适配"进 `ui/src/styles`？** | `HANDOFF.md` §1 明确建议"原型的 CSS 就是组件库初稿，抽取+适配，不要看截图重写"；但 TECH-05 又禁止"创建第二套组件体系"。**只有"抽取进现有体系"同时满足两条**；若新开一套 CSS 就是违规 |
| **Q2** | **原型（`index.html`）本轮是否保持冻结？** | 15 套 `verify_ui*.py` 测的是 `index.html`。若它冻结，UI 验收基线天然稳定；若允许改，验收脚本必须同步 |
| **Q3** | **"接入"的验收标准是"原型能跑"还是"Vue 应用行为达标"？** | 决定验收脚本要不要新增一套"测真实应用"的 UI 脚本 |

> ⚠️ **本节的 Q1 直接决定阶段二/三的做法**。我的读码结论是：**唯一不违规的路径 = 把原型 CSS 抽取进 `ui/src/styles` 并让现有组件向它靠**（而非并列新体系）。
> 但这条需要你确认——因为它的工作量远大于"给现有页面补数据"。

### 2.3 与此前审计的衔接

`docs/reviews/PW-INTEGRATION-002-preflight.md` §8 曾把 8 个 Vue 视图列为**"等待 UI Skill 的冻结区"**（LearningView / NavSide / ModeView / ProfileView / LifeView / DashboardView / 独立 AI 页 / 滚动容器）。
现在 UI-02~UI-08 已交付 → **冻结解除**，这正是 TECH-05 存在的理由。
该 preflight 的 §3.2（AI canonical 落 core config）**已由 TECH-04 落地**（L1 键 `ai.provider.current`/`ai.model.current`，`core/src/db/config.rs:106-107`）。

---

## 三、页面清单（核心交付）

> 判据说明：**① 当前数据来源** = 设计标准里这一页靠什么数据活着；**② mock 位置** = 原型中硬编码的 `state`/常量行号；**③ 未来真实接口** = 真实应用里对应的服务/命令/Runtime；**④ 是否已有 Runtime 支撑** = ✅ 已就绪 / ⚠️ 部分 / ❌ 无。
> **真实应用现状** = B 套里这一页今天长什么样。

### 3.0 总表

| # | 页面 | 原型路由 | 原型 mock 位置 | 未来真实接口 | Runtime 支撑 | 真实应用现状 |
|:-:|------|---------|---------------|-------------|:-----------:|-------------|
| 1 | 首页 | `#/home` | `WS:1455` `RECENT:1222` `HOME_SECTIONS:1215` `WIDGETS:1207` | `appsService` / `learningService` / `lifeService` / `workspaceRuntime` | ⚠️ | `DashboardView.vue`（仅组件网格，2.6KB） |
| 2 | AI 页面 | `#/ai` | `aiSessions:1511` `aiSession:1521` | `stores/ai.ts` + `ai_chat` + 事件流 | ✅ | `AiView.vue`（**占位骨架**，6 行）+ `AiSidebar.vue`（真实聊天） |
| 3 | **模型管理** | `#/models` | `models:1503` `currentModel:1508` `modelBack:1509` | `ai/model/registry.ts` + L1 canonical 键 + `ai_info`/`ai_list_models` | ✅ | **不存在**（无路由、无视图） |
| 4 | 工作空间 | `#/workspaces` `#/run` `#/create` | `WS:1455` `run:1492` `wfModes:1495` | `workspaceRuntime` + `modeService` + `layoutService` | ✅ | `ModeView.vue`(33KB) + `LayoutView.vue`(7.6KB)，功能真实 |
| 5 | **个人档案** | `#/profile` | `profile:1529` `profileExts:1543` | `profileService`（22 条 `profile_*` 命令） | ✅ | `ProfileView.vue`(26KB)，功能真实；**缺 avatar** |
| 6 | 学习系统 | `#/learn` | `learnGoal:1523` | `learningService`（15 条 `learning_*`） | ✅ | `LearningView.vue`(22KB)，功能真实 |
| 7 | 生活区域 | `#/life` | `lifeSlots:1552` `LIFE_SLOT_DEFS:3684` | `lifeService`（9 条 `life_*`）+ 插件系统 | ✅ | `LifeView.vue`(11.9KB)，功能真实 |
| 8 | 设置 | `#/settings` | `devMode:1558` `theme:1559` | `configService` + `stores/settings` + `ai_set_credential` | ✅ | `SettingsView.vue`(7.6KB)，功能真实（**表单风格，非原型设计**） |
| 9 | 软件 | `#/apps` | `APPS:1185` `GROUPS:2677` | `appsService`（14 条 `apps_*`） | ✅ | `SoftwareView.vue`(17KB) |
| 10 | 设备 | `#/device` | `DEVICES`（原型内联） | `deviceService`（4 条 `device_*`） | ✅ | `DeviceView.vue`(7.9KB) |
| 11 | 插件 | `#/plugins` | `PLUGINS:3806` `MARKET:3816` | `pluginService`（18 条 `plugin_*`） | ✅ | `PluginsView.vue`(12.5KB) |
| 12 | 项目 | `#/project` | 原型内联 | `learningService`(project 段) + `modeService` | ✅ | `ProjectView.vue`(9.5KB) |

**一句话**：**真实应用不缺数据接口**（121 条 core 命令 + 9 个 service + 4 个 Runtime 模块），
**缺的是"原型那套视觉与交互"**；唯一例外是 **模型管理页（连页面都没有）** 和 **档案头像（连后端字段都没有）**。

---

### 3.1 首页 `#/home`

| 项 | 内容 |
|----|------|
| **当前数据来源** | 全内存 mock：工作空间列表 `WS`、最近使用 `RECENT`、模块开关 `HOME_SECTIONS`、组件区 `WIDGETS` |
| **mock 数据位置** | `index.html:1455`（WS，含 `layout:[{app,x,y,w,h}]` 百分比几何）、`:1222`（RECENT）、`:1215`（HOME_SECTIONS）、`:1207`（WIDGETS） |
| **未来真实接口** | 工作空间卡片 → `workspaceRuntime` / `modeService.list()`；最近使用 → `appsService.list()` + `apps_running`；MiniMap → 原型的 `layout` ↔ `core` 的 `Layout.slots`（`window_manager/apply.rs:20-42`）；组件区 → 现有 `widgets/`（9 个组件）+ `stores/widgets` |
| **Runtime 支撑** | ⚠️ **部分**：组件区、apps、learning、life 都有真实接口；但**没有"工作空间卡片网格 + MiniMap"对应的 Runtime 读模型**（`workspace/store.ts` 有 `WorkspaceRuntime`，但无"列表 + 使用次数 + 尺寸档"） |
| **真实应用现状** | `DashboardView.vue`（84 行）= 组件网格 + 组件管理面板。**没有 Hero、没有 MiniMap、没有工作空间卡片、没有最近使用** |
| **设计标准** | `ui-pages.md` §首页；`design-system.md` §8 P0-1；`HANDOFF.md` 阶段1 |
| **缺口性质** | **展示层重建**（数据大多已有）＋ 一个新读模型（工作空间列表视图） |

### 3.2 AI 页面 `#/ai`

| 项 | 内容 |
|----|------|
| **当前数据来源** | 内存 mock 会话列表 `aiSessions`、当前会话 `aiSession`、模式 `aiTab` |
| **mock 数据位置** | `index.html:1511-1520`（4 条会话，含 `mode:'chat'|'ws'` 与消息数组）、`:1521` |
| **未来真实接口** | `stores/ai.ts`（消息流/流式/中断）+ `ai_chat` + 事件桥（`AI_STREAM_CHUNK`/`AI_RESPONSE`）+ `ai/model/bridge.ts`（当前模型） |
| **Runtime 支撑** | ✅ **完整**：AI store、事件流、Model Registry、canonical 全部就绪 |
| **真实应用现状** | `AiView.vue` = **7 行 / 366 字节的占位骨架**（"阶段5 交付…"文案）。真实聊天能力全在 `components/AiSidebar.vue`（全局侧栏） |
| **设计标准** | `ui-pages.md` §AI 助手页；原型 `ROUTES.ai`（含聊天/工作空间助手双 tab + 历史会话列表 + 模型 chip） |
| **缺口性质** | **页面缺失**（能力已有，页面没建）。⚠️ 注意 preflight §4 已登记"独立 AI 页与 AiSidebar 是否共享会话"是**需先定契约**项 |
| **TECH-05 定位** | **P1**（后续接入）：接「当前模型 / Provider / 会话状态」 |

### 3.3 模型管理 `#/models` ★ P0-1

| 项 | 内容 |
|----|------|
| **当前数据来源** | 内存 mock 模型数组（3 条）+ `currentModel` |
| **mock 数据位置** | `index.html:1503-1507`（`state.models[] = {id,name,ptype,provider/addr+mname/agent+channel,status,latency,note}`）、`:1508`（currentModel）、`:1509`（modelBack 来源记忆） |
| **未来真实接口** | `ui/src/ai/model/registry.ts`（唯一读写口）+ `model.ts`（`ModelProfile` 实体）+ L1 canonical 键 `ai.provider.current`/`ai.model.current` + `ai_info`/`ai_list_models`/`ai_set_credential` |
| **Runtime 支撑** | ✅ **完整且已验收**：TECH-03-A（Registry/Provider/Ports）+ TECH-04（canonical 落 L1，`verify_tech04.py` 44/44） |
| **真实应用现状** | **页面不存在**。`ui/src/router/index.ts` 无 `/models`；全仓只有 `AiSidebar.vue` 引用 `useCurrentModel`（顶栏只读显示） |
| **设计标准** | `ui-06-report.md`（10/10 验收）；`ui-pages.md` §模型管理页 |
| **字段映射（原型 → 真实）** | `ptype` → `connection.type`（`api|local|agent`，**枚举完全一致**）；`provider`(展示名) → `providerLabel()`；`status:connected|local|unset` → `status.{enabled,available}`；`latency`(演示) → **contract 无此项**（`status.lastCheck` 存在但不是延迟值 → 需扩展位 `metadata.extras` 或新字段）；`addr/mname` → `connection.endpoint`/`model` |
| **缺口性质** | **页面缺失 + 1 个展示字段待定（延迟）**。数据面 100% 就绪 |
| **⚠️ 已知冲突** | `SettingsView.vue` 写 `settings.data.defaultProvider`（键 `defaultProvider`），与 canonical `ai.provider.current` **是两个"默认 Provider"事实** —— 接线时必须收敛（preflight §3.4 已判定"任何页面不得自行持久化 provider/model"） |

### 3.4 工作空间（列表 + 工作模式）`#/workspaces` `#/run` `#/create` ★ P0-3

| 项 | 内容 |
|----|------|
| **当前数据来源** | `WS`（工作空间 + layout 几何）、`state.run`（tab/layoutMode/goal/modeId/appState）、`wfModes`（2 个模式模板） |
| **mock 数据位置** | `index.html:1455-1466`（WS）、`:1492-1493`（run）、`:1495-1498`（wfModes） |
| **未来真实接口** | `workspaceRuntime`（`ui/src/workspace/runtime.ts` 门面）+ `workspace/store.ts`（`WorkspaceApp.status: running|waiting|closed`）+ `modeService`（`modes_*` 15 条）+ `layoutService`（`layout_apply`/`windows_place`） |
| **Runtime 支撑** | ✅ **完整**（且比原型更强）：`store.ts` 有 `AppStatus` 三态、`windowId`、`layoutNode`、`applyWindowEvent`；`runtime.ts` 新增 `snapshot` 命名空间 + `getRecoveryStatus()` 三视图（TECH-04 §二） |
| **真实应用现状** | `ModeView.vue`(33KB) = 真实模式管理（应用真实、进模式有进度流水线、布局槽位编辑器）；`LayoutView.vue`(7.6KB) = 真实布局应用（`layout_apply`） |
| **设计标准** | `ui-05-b-report.md`（9/9）；`ui-pages.md` §工作空间 / §工作模式 |
| **字段映射** | `state.run.appState` → `WorkspaceApp.status`；`state.run.goal` → **无后端字段**（登记为产品项）；`state.run.modeId` → `modes_current`；`state.run.customLayout` → `customLayout{ws,mode,rects}` ↔ `Layout.slots` |
| **缺口性质** | **展示层**（把三态 chip / 状态栏 / 应用状态点做出来）+ **1 个待定字段（工作目标）** |
| **TECH-05 约束** | **禁止实现真实窗口控制**，只做**状态同步**。注意：`layoutService` 里 `place`/`activate` **已经存在**（真实窗口控制），本轮不新增、不扩大其调用面 |
| **唯一替换点（原型自己标好的）** | `appStatusOf` —— 原型 UI-05-B 报告 §五.1 明确"派生逻辑 `appStatusOf` 是唯一替换点，已收敛" |
| **数据"说谎"风险** | 原型 UI-05-B §五.1 自陈："用户把 VS Code 点成已关闭但窗口还在舞台"。接真实 `WorkspaceApp.status` 后此问题**自然消失** |

### 3.5 个人档案 `#/profile` ★ P0-2

| 项 | 内容 |
|----|------|
| **当前数据来源** | 内存 mock `state.profile.fields[]`（7 个字段）+ `profileExts`（3 个扩展块） |
| **mock 数据位置** | `index.html:1529-1541`（fields，含 `{id,label,value,editable,type}`）、`:1543-1550`（profileExts） |
| **未来真实接口** | `profileService`：`basicGet`/`basicSave`、`skills`、`projects`、`timeline`、`suggestions`（**22 条 `profile_*` 命令**）+ `stores/profile.ts` |
| **Runtime 支撑** | ✅ **完整**（含 AI 建议确认流：`profile_suggestions_confirm/ignore/reject_kind`） |
| **真实应用现状** | `ProfileView.vue`(26KB)：真实基础信息（含首次引导 3 字段）、技能树、项目经历、成长时间线、待确认建议面板 |
| **设计标准** | `ui-07-report.md`(5/5) + `ui-08-report.md`(9/9)；`ui-pages.md` §个人档案页 |
| **字段映射（**关键**）** | `nickname` → `basic.name` ✅ ／ `signature` → `basic.motto` ✅ ／ `tags` → `basic.interests[]` ✅ ／ `tagline`(方向) → `basic.direction` ✅ ／ **`avatar` → ❌ 无对应后端字段** |
| **❌ 真实后端缺口** | `profile_basic` 表只有 `name, direction, interests, motto, updated_at`（`database/schema.sql:116-123`），**无 avatar 列**；全仓 `avatar` 关键字在 backend + `profileService.ts` + `stores/profile.ts` 中**命中 0 次** |
| **avatar 语义（原型已定义）** | `''`=首字母头像 ／ emoji=预设 ／ 未来 `custom:<引用>`=上传。**原型已把三种语义定死**，只缺落地位置 |
| **缺口性质** | **1 处真实后端缺口**（avatar）+ **展示层改造**（原型的编辑卡/头像 picker/签名计数/标签推荐） |
| **UI-08 交互约束** | 必须保持：**原位展开编辑卡**（不跳页）、`#profileEditor` 壳节点恒在、进入编辑态整体快照 `backup`、Esc 优先级（弹层 > 编辑卡）、标签增删只重写 `#tagEditor` |

### 3.6 学习系统 `#/learn`

| 项 | 内容 |
|----|------|
| **当前数据来源** | 内存 mock `state.learnGoal`（1 个目标） |
| **mock 数据位置** | `index.html:1523`（`{name,type,level,time}`） |
| **未来真实接口** | `learningService`（`learning_goals_list`/`goal_add`/`goal_update`、`learning_nodes_*` 路线、`learning_updates_*`、`learning_ai_suggest`）+ `stores/learning.ts` |
| **Runtime 支撑** | ✅ **完整**（15 条命令，含 AI 重新规划） |
| **真实应用现状** | `LearningView.vue`(22KB)，功能真实（目标 + 路线节点 + 进度 + AI 建议） |
| **缺口性质** | 展示层（原型的目标大卡 / 路线 timeline 三态） |
| **TECH-05 定位** | **P1**：接「学习目标 / 进度数据」 |

### 3.7 生活区域 `#/life`

| 项 | 内容 |
|----|------|
| **当前数据来源** | 内存 mock：槽位顺序 `lifeSlots` + 槽位定义 `LIFE_SLOT_DEFS`（7 个槽，`body()` 内联假数据：天气 28°、播放"夜空中最亮的星"、微信 3 条） |
| **mock 数据位置** | `index.html:1552-1557`（lifeSlots）、`:3684-3720`（LIFE_SLOT_DEFS，含 usage/weather/message/music/calendar） |
| **未来真实接口** | `lifeService`（`life_weather`/`life_media_now`/`life_media_control`/`life_usage_today`/`life_usage_week`/`life_social_overview`/`life_social_config_*`）+ 插件系统（`plugin_api`） |
| **Runtime 支撑** | ✅ **完整**（阶段8 sidecar 交付天气/音乐 SMTC/社交概览） |
| **真实应用现状** | `LifeView.vue`(11.9KB)：天气 / 正在播放 / 消息概览 / 屏幕使用时间 四张卡，真实数据 |
| **缺口性质** | 展示层（原型是"插件槽位网格 + 来源标注 + 管理抽屉"）+ **1 个待定契约**：preflight §4 判定"life 区域容纳插件卡片用哪套机制（复用 dashboard widget 还是 life 专属 slot）**需先定 contract**" |
| **TECH-05 定位** | **P1**：建立插件数据接口 |

### 3.8 设置 `#/settings`

| 项 | 内容 |
|----|------|
| **当前数据来源** | `devMode`、`theme`、`playing`、`motion`、`navMini` 等内存开关 |
| **mock 数据位置** | `index.html:1558-1570`（devMode/theme/motion/navMini…） |
| **未来真实接口** | `configService`（`get_config`/`put_config`）+ `stores/settings` + `ai_set_credential`/`ai_delete_credential`/`ai_list_models` |
| **Runtime 支撑** | ✅ **完整**；Motion 三档（standard/reduced/off）与 Skin 由 `motion/runtime.ts`、`motion/skin.ts` 支撑 |
| **真实应用现状** | `SettingsView.vue`(7.6KB)：主题/自启/默认 Provider/数据目录/遥测 + **AI 凭据**（Key 掩码、模型拉取） |
| **缺口性质** | 展示层（原型是"左分类 subnav + 右行式控件"，真实是**单列表单**）+ **「AI 与模型」分类缺失**（原型 UI-06 要求设置里有"AI 与模型"分类作为模型管理的两个入口之一） |
| **⚠️ 冲突（同 §3.3）** | `defaultProvider` 与 canonical 并存 |

### 3.9 其余页面（简）

| 页面 | mock 位置 | 真实接口 | Runtime | 真实应用现状 |
|------|----------|---------|:-------:|-------------|
| 软件 `#/apps` | `APPS:1185` `GROUPS:2677` | `appsService`（14 命令） | ✅ | `SoftwareView.vue`(17KB)，真实（含扫描/启动/图标提取） |
| 设备 `#/device` | 原型内联 | `deviceService`（4 命令） | ✅ | `DeviceView.vue`(7.9KB)，真实（指标/进程/模式健康） |
| 插件 `#/plugins` | `PLUGINS:3806` `MARKET:3816` | `pluginService`（18 命令） | ✅ | `PluginsView.vue`(12.5KB)，真实（启停/权限/审计/Agent） |
| 项目 `#/project` | 原型内联 | `learningService`(project) + `modeService` | ✅ | `ProjectView.vue`(9.5KB)，真实 |

---

## 四、UI → 数据 → Runtime 映射总表

> 只列"需要接线"的域；已完全对齐的不重复。

| 域 | 原型（设计标准） | 原型 mock | 真实中间层（Adapter 候选） | 真实 Runtime / Core | 支撑 |
|----|----------------|----------|-------------------------|-------------------|:----:|
| **模型** | `#/models` + AI 页 chip + 设置分类 | `models:1503` `currentModel:1508` | `ai/model/bridge.ts`（**已存在，即 Model Registry 门面**） | `registry.ts` / `model.ts` / `provider.ts` + L1 canonical 键 | ✅ |
| **档案** | `#/profile` 展示态 + 编辑卡 | `profile:1529` `profileExts:1543` | **待建** profile adapter（现为 `profileService` 直连 store） | 22 条 `profile_*` | ✅（avatar ❌） |
| **工作空间** | `#/workspaces` `#/run` | `WS:1455` `run:1492` `wfModes:1495` | `workspace/runtime.ts`（**已是门面**，T1c 白名单） | `workspace/store.ts` + `layout.ts` + `snapshot.ts` | ✅ |
| **工作模式** | `#/run` 状态栏 + 模板区 | `wfModes:1495` `run.appState:1493` | `modeService` | 15 条 `modes_*` | ✅ |
| **学习** | `#/learn` | `learnGoal:1523` | **待建** learning adapter | 15 条 `learning_*` | ✅ |
| **生活** | `#/life` | `lifeSlots:1552` `LIFE_SLOT_DEFS:3684` | **待建** life adapter | 9 条 `life_*` + 插件系统 | ✅ |
| **首页** | `#/home` | `WS` `RECENT` `HOME_SECTIONS` `WIDGETS` | **待建** home adapter（聚合 4 域） | apps + learning + life + workspaceRuntime | ⚠️ |
| **设置** | `#/settings` | `devMode` `theme`… | `stores/settings` | `get_config`/`put_config` | ✅ |
| **UI 偏好** | 全局 | `theme:1559` `motion:1565` `navMini:1566` | `stores/nav` + `stores/settings` | config 键 `ui.*` | ✅ |

**门面已就绪的域**：`ai/model/bridge.ts`（模型）、`workspace/runtime.ts`（工作空间）—— 这两个正是 TECH-05 的 P0-1 / P0-3，**门面已存在**，只需在门面之上做页面。

---

## 五、断点清单

### P0（阻塞 TECH-05 阶段二/三）

| # | 断点 | 位置 | 影响 |
|---|------|------|------|
| **B1** | **模型管理页不存在** | `ui/src/router/index.ts`（无 `/models`）+ 无 models 视图 | P0-1 无法"接线"，必须**新建页面** |
| **B2** | **档案无 avatar** | `database/schema.sql:116-123`（表无列）+ 后端零 avatar | P0-2 的头像功能无处落 |
| **B3** | **`defaultProvider` 与 canonical 双真相** | `stores/settings.ts`（`defaultProvider`）↔ `core/src/db/config.rs:106-107`（`ai.provider.current`） | 违反 preflight §3.4"任何页面不得自行持久化 provider/model"；接线后会"设置写 A、顶栏显示 B" |
| **B4** | **原型 CSS 是否可抽取进现有体系（Q1）未定** | `personal-workspace-ui/index.html` CSS ↔ `ui/src/styles/base.css` | 定不了就无法开始任何视觉改造 |

### P1（不阻塞 P0，但影响成品完整度）

| # | 断点 | 位置 | 影响 |
|---|------|------|------|
| B5 | 独立 AI 页是占位骨架 | `ui/src/views/AiView.vue`（7 行 / 366 字节） | 设计有页面、实现没有；且"与 AiSidebar 是否共享会话"**契约未定** |
| B6 | 设置缺「AI 与模型」分类 | `SettingsView.vue`（单列表单） | 模型管理的第 2 个入口缺失（原型要求双入口 + 来源记忆 `models-back`） |
| B7 | 首页缺工作空间卡片读模型 | `workspace/store.ts` 无"列表+使用次数+尺寸档" | MiniMap 与尺寸分档（l/m/s）无数据来源 |
| B8 | 工作目标（`run.goal`）无后端字段 | 全仓无对应 | 原型状态栏"当前任务"无可接字段 |
| B9 | life 槽位机制契约未定 | preflight §4 已登记 | 插件卡片用哪套机制未定 |
| B10 | 模型"延迟"无契约字段 | `model.ts` 的 `status` 只有 `enabled/available/lastCheck/lastError` | 原型的延迟 chip 只能进 `metadata.extras` |

### P2（登记，不在本轮）

| # | 断点 |
|---|------|
| B11 | 真实应用**没有 UI 视觉验收**（`verify_ui*.py` 只测原型 `index.html`）→ 阶段四"现有 UI 验收继续通过"只覆盖原型 |
| B12 | 原型 18 条路由 vs 真实应用 12 条产品路由，缺 `#/showcase` `#/guard` `#/skinlab` `#/spec`（开发态工具页） |

---

## 六、Runtime 支撑现状盘点

| Runtime | 位置 | 状态 | 本轮可复用 |
|---------|------|:----:|-----------|
| **Model Registry** | `ui/src/ai/model/`（8 文件：model/provider/registry/ports/selection/session/bridge/consumer） | ✅ TECH-03-A 验收 | **P0-1 直接用** |
| **Canonical L1** | `core/src/db/config.rs:106-107`（`ai.provider.current`/`ai.model.current`） | ✅ TECH-04 落地，schema v12 | **P0-1 直接用** |
| **Workspace Runtime** | `ui/src/workspace/`（store/layout/runtime/snapshot） | ✅ TECH-02 + TECH-04 §二 | **P0-3 直接用**（`snapshot` 门面：`executable` 恒 `false`） |
| **Motion Runtime** | `ui/src/motion/`（10 文件，含 conflict/interrupt/guards/cinema/viewTransition） | ✅ TECH-01 验收 | 可复用；**禁止新增动画体系** |
| **Skin Engine** | `ui/src/motion/skin.ts` + `styles/tokens.css` | ✅ 验收（12/12） | **冻结，不得触碰** |
| **Toast** | `ui/src/composables/useToast.ts` + `components/ToastHost.vue` | ✅ TECH-03-B 统一 | 直接用（**禁止另建**） |
| **Plugin Host** | `ui/src/plugin/pluginHost.ts` + `api/pluginService.ts` | ✅ 阶段9 验收 | P1 life 用 |
| **Core 命令** | `core/src/api/commands.rs`（**121 条**） | ✅ 全量 | 全部可用 |

**结论：Runtime 侧零缺口。** TECH-05 的全部工作都在**展示层 + Adapter 层**。

---

## 七、验收基线（本轮实跑）

### 7.1 UI 验收（15 套，`personal-workspace-ui/`，Edge 无头 + CDP）

| 脚本 | 结果 | 脚本 | 结果 |
|------|------|------|------|
| `verify_s2_local_diff` | 6/6 ✅ | `verify_ui05snap` | 6/6 ✅ |
| `verify_collapse_expand` | 7/7 ✅ | `verify_ui05b` | 9/9 ✅ |
| `verify_widget_dock` | 6/6 ✅ | `verify_ui06` | **10/10 ✅** |
| `verify_toast` | 4/4 ✅ | `verify_ui07` | 5/5 ✅ |
| `verify_win_front` | 4/4 ✅ | `verify_ui08` | 9/9 ✅ |
| `verify_ui04b` | 6/6 ✅ | `verify_skin_lab` | 5/5 ✅ |
| `verify_ui04c` | 6/6 ✅ | `verify_ui04cp0` | 6/6 ✅ |
| `verify_ui05p0` | **7/7 ✅**（批量连跑时曾 6/7，单跑 3 次均 7/7 → 偶发） | | |

**合计 96 条用例通过。** UI 基线**可用且可复跑**（本机 Edge 路径已确认存在）。

### 7.2 工程基线（沿用 TECH-04 收官结果）

`gate.py --stage 9 --build` FAIL=0 WARN=0 PASS=30 ／ `cargo test` 86/86 ／
`verify_tech04` 44/44 ／ `verify_tech03b` 81/81 ／ `verify_model_registry` 32/32 ／
`verify_contracts` 6/6 ／ `verify_tech01` 9/9 ／ `verify_skin_engine` 12/12 ／
`verify_tech02_workspace` 11/11 ／ `perf_tech01_22` 12 场景 longtask 全 0

---

## 八、风险与待裁决

### 8.1 风险

| # | 风险 | 等级 | 说明 |
|---|------|:----:|------|
| R1 | `verify_ui05p0` 批量连跑偶发失败 | 低 | 14 套脚本背靠背启动 Edge 无头实例抢资源；单跑稳定。**不删断言、不放松判据**，批跑时把该脚本独立跑一次 |
| R2 | 两套 CSS 并存会滑向"第二套组件体系" | **中** | 若不执行 Q1 的"抽取+适配"，很容易变成并列一套新样式 → **违规** |
| R3 | 真实应用无 UI 视觉验收 | 中 | 改造后无自动化视觉门禁，"改坏了"只能靠人眼 |
| R4 | 模型管理页从零建，易夹带"新组件" | 中 | 必须复用现有 `Button/Input/Chip/Card/Toast`，否则违反"禁止替换已有 UI 组件" |
| R5 | `defaultProvider` 双真相（B3） | **中** | 不收敛就会出现"显示 A 实发 B"回归——正是 TECH-04 刚消灭的问题 |
| R6 | 原型 route 与真实 route 命名不同 | 低 | 原型 `#/run`/`#/apps`/`#/workspaces` ↔ 真实 `/mode`/`/software`/`/layout`，映射需登记避免混乱 |
| R7 | "工作目标"无处可存（B8） | 低 | 可先用 config 键 `run.goal`（零迁移）或明确不做 |

### 8.2 待裁决（**等你的指令，本轮不动手**）

| # | 待决 | 选项 |
|---|------|------|
| **D1** | **原型 CSS 的处理方式**（=Q1，**最高优先级**） | ① 抽取进 `ui/src/styles`，现有组件向原型靠（合规，工作量大）／ ② 只做数据接线，视觉保持现状（工作量小，但 TECH-05 的"视觉标准"落不了地） |
| **D2** | **原型 `index.html` 本轮是否冻结**（=Q2） | 冻结 → UI 验收基线天然稳定；不冻结 → 验收脚本须同步 |
| **D3** | **"接入"的验收对象**（=Q3） | 原型跑通 / 真实应用行为达标 / 两者都要 |
| **D4** | 档案 avatar 落点（B2） | ① config 键 `profile.avatar`（零迁移）／ ② 迁移加列（语义更正） |
| **D5** | 模型"延迟"落点（B10） | ① 不显示（去掉该 chip）／ ② `metadata.extras.latency` |
| **D6** | P0 三项的**施工顺序** | 建议：模型管理（门面+设计都已就绪）→ 工作空间状态（纯展示层）→ 个人档案（含后端缺口） |

---

## 九、下一步

阶段一（本审计）**到此结束**，等你的下一步指令。

若继续，建议的**阶段二（UI Contract v1）**要定的是：
1. Adapter 层的**位置与命名**（`ui/src/api/adapters/` vs `ui/src/datasource/`）与"UI 不感知底层"的具体边界；
2. 每个域的 **Adapter 接口签名**（输入/输出类型一律取自现有 service/Runtime，不新造领域模型）；
3. Q1 的落地形态（Token 层如何抽取而不并列）；
4. 与现有 `verify_ui*.py` 的关系（复用/新增/不动）。
