# TECH-05-B · 原型 UI 接入真实应用 · 迁移方案

> 日期：2026-09-16 · 性质：**只出方案，零代码修改**（按停止条件：方案交付即停，不做大规模重构）
> 目标：把 `personal-workspace-ui/index.html` 已定稿的 UI 设计体系，迁移到真实 Tauri + Vue3 应用 `ui/` 中
> 证据口径：所有结论标注 `文件:行号`，来自本轮实测；**不引用未读过的文件**

---

## 零、三条结论先行

1. **Token 层不是"搬运"，是"补齐"** —— **脚本实测 18/18 项语义色值逐字节一致**（仅比浅色 `:root` 块，见下表）：

   | token | 原型 | 真实 | token | 原型 | 真实 |
   |-------|------|------|-------|------|------|
   | `--bg-app` | `#ebedf1` | `#ebedf1` ✅ | `--text-1` | `#14171c` | `#14171c` ✅ |
   | `--bg-canvas` | `#f4f5f8` | `#f4f5f8` ✅ | `--text-2` | `#565e6e` | `#565e6e` ✅ |
   | `--surface-1` | `#ffffff` | `#ffffff` ✅ | `--text-3` | `#737b8a` | `#737b8a` ✅ |
   | `--surface-2` | `#f8f9fb` | `#f8f9fb` ✅ | `--text-4` | `#9ba2af` | `#9ba2af` ✅ |
   | `--surface-3` | `#f1f3f6` | `#f1f3f6` ✅ | `--brand-50` | `#eff3fd` | `#eff3fd` ✅ |
   | `--border-subtle` | `#edeff3` | `#edeff3` ✅ | `--brand-500` | `#4a6bdc` | `#4a6bdc` ✅ |
   | `--border` | `#e1e4ea` | `#e1e4ea` ✅ | `--brand-600` | `#3a57c4` | `#3a57c4` ✅ |
   | `--border-strong` | `#cdd2dc` | `#cdd2dc` ✅ | `--success/--warning/--danger` | `#2e9c6e`/`#c08a1e`/`#ce4a3f` | 同 ✅ |

   **真实应用的 `tokens.css` 本就是按原型设计派生的**（TECH-01 Design Token Runtime，Foundation → Semantic 分层）。
   所以要做的**只有**：把原型有、真实缺的那部分语义 token **补进现有 `tokens.css`**（沿用现有分层），**不改名、不改值、不新建变量系统**。
2. **真实应用缺的是「共享组件层」** —— `ui/src/components/` 只有 8 个**业务**组件（AiSidebar / NavSide / TopBar / StatusBar / ModeBar / WidgetCard / ToastHost / PluginFrame），
   **没有任何通用 primitive 组件**；各视图在 scoped style 里**各写各的**（`DeviceView` / `LifeView` / `ProjectView` **三处各自定义了 `.card`**，`danger`/`row`/`plain`/`muted`/`small` 反复重写）。
   原型的 §5 PRIMITIVES（70 个类）正是这个缺失层 → **迁移它就是"建立第一套统一组件层"**，不是"创建第二套"。
3. **四项必须由你裁决，不能默认（三个系统冲突 + 一个后端缺口）** ——
   Motion 时长体系（原型 25 个 scene token vs 真实 6 档，后者已冻结）、
   Toast 行为（原型 2200ms/最多 2 条 vs 真实 4000ms/单条，后者已验收）、
   页面命名（原型 `HomeView` vs 真实 `/dashboard`，后者被 `verify_stage1.py` 钉死）、
   档案 avatar（后端无字段，你已指定"不自行加库字段"）。详见 §五。

---

## 一、迁移的第一原则（写进每次改动前）

| 原则 | 落地判据 |
|------|---------|
| **不重新设计 UI** | 实现形态以原型 `index.html` 为准；分歧时以 `docs/ui-handoff/*` 六份交接文档为准（`HANDOFF.md:3-5` 已声明其权威性） |
| **不新增产品概念** | 用户可见文案只出现原型已有词汇（工作空间/模式/软件/档案…）；`registry`/`canonical`/`adapter` 禁止进 UI 文本（`ui-forbidden.md:35`） |
| **不新建三件套** | 不新建 token 系统 / 不新建状态中心 / 不新建动画体系 |
| **真实数据优先** | 已存在的 Runtime/Core 一律优先接入；mock 只用于"无后端字段"的占位，且必须**显式标注** |
| **复用 > 新造** | 新页面必须消费 §三 的共享组件层，不得再写一套 `xx-card` |

---

## 二、页面映射

### 2.1 总表

> 命名建议：**保留现有路由与文件名**（理由见 §2.3），在**文档层**登记"原型名 ↔ 真实名"对照。

| 原型页面 | 原型路由 | Vue 目标 | 处置 | 依据 |
|---------|---------|---------|:----:|------|
| 首页工作台 | `#/home` | `ui/src/views/DashboardView.vue`（路由 `/dashboard`） | **就地改造** | 已有真实组件网格；缺 Hero/MiniMap/最近使用/工作空间卡 |
| AI 助手 | `#/ai` | `ui/src/views/AiView.vue`（路由 `/ai`） | **就地落地**（现为占位） | 文件已存在但仅 7 行；真实聊天在 `components/AiSidebar.vue` |
| 模型中心 | `#/models` | **`ui/src/views/ModelsView.vue`（新建）** + 路由 `/models` | **新建** | 真实应用**无此页面**（`router/index.ts` 无 `/models`） |
| 档案编辑 | `#/profile` | `ui/src/views/ProfileView.vue` | **就地改造** | 已有 26KB 真实页（含 skills/projects/timeline/suggestions）；补 UI-08 编辑卡与头像 |
| 工作模式（沉浸态） | `#/run` | `ui/src/views/ModeView.vue`（路由 `/mode`） | **就地改造** | 已有真实模式应用 + 进度流水线；补 UI-05-B 状态栏与窗口画布视觉 |
| 工作空间列表 | `#/workspaces` | `ui/src/views/LayoutView.vue`（路由 `/layout`） | **就地改造** | 已有布局列表 + `lv-canvas` 百分比画布（原型 MiniMap 的真实对应物） |
| 设置 | `#/settings` | `ui/src/views/SettingsView.vue` | **就地改造** | 已有真实配置；补左分类 subnav + 「AI 与模型」分类 |
| 软件 | `#/apps` | `ui/src/views/SoftwareView.vue` | **就地改造**（视觉） | 已有 610 行真实实现 |
| 学习 | `#/learn` | `ui/src/views/LearningView.vue` | 就地改造（视觉） | 已有 770 行真实实现 |
| 项目 | `#/project` | `ui/src/views/ProjectView.vue` | 就地改造（视觉） | 已有 334 行 |
| 生活 | `#/life` | `ui/src/views/LifeView.vue` | 就地改造（视觉） | 已有 323 行 |
| 设备 | `#/device` | `ui/src/views/DeviceView.vue` | 就地改造（视觉） | 已有 221 行 |
| 插件 | `#/plugins` | `ui/src/views/PluginsView.vue` | 就地改造（视觉） | 已有 414 行 |
| 创建工作空间向导 | `#/create` | 归入 `ModeView.vue` 的向导（已存在 `openWizard`） | **不新建页面** | 真实应用用 wizard 而非独立页；避免新增产品概念 |
| 开发态工具页 ×4 | `#/showcase` `#/guard` `#/skinlab` `#/spec` | **不迁移** | 不迁移 | 真实应用无对应路由，且 `ui-forbidden.md:9` 禁"空态页/占位页" |

**需新建的页面：只有 1 个 —— `ModelsView.vue`。** 其余全部是"就地改造"。

### 2.2 三类处置的判据

**① 直接改造（7 页）**：文件与路由已存在、数据已接真实接口，缺的是**原型视觉与交互形态**。
→ 改造时**只动模板与样式，不动数据调用**。

**② 需新建（1 页）**：`ModelsView.vue`。原型 UI-06 已定稿（`ui-06-report.md` 10/10）、Runtime 已就绪（TECH-03-A/04），
真实应用**既无路由也无视图**（`ui/src/router/index.ts` 全文无 `models`）。
→ 新建时**禁止**重建模型状态：唯一来源是 `ui/src/ai/model/registry.ts`，UI 只经 `ai/model/bridge.ts` 取数。

**③ 可复用组件（关键）**：

| 原型构造 | 真实应用已有对应物 | 复用方式 |
|---------|------------------|---------|
| `.minimap`（窗口排布缩略） | `LayoutView.vue` 的 `.lv-canvas` + `.lv-slot`（百分比 rect） | **升级视觉**，不重写逻辑 |
| `.ws-card` 的 slots 缩略 | `ModeView.vue` 的 `.mode-card__slots`（`slotsOf(layout)`） | 同上 |
| `#runStatus` 状态栏 | `components/StatusBar.vue`（15 行）+ ModeView 的进度面板 | 扩展现有组件，不新建 |
| `.ai-dock` / `.dock-rail` / `.dock-panel` | `components/AiSidebar.vue` + `.ai-sidebar`/`.ai-rail`（`base.css:380-430`） | **就地改样式** |
| `toast()` / `#toastHost` | `composables/useToast.ts` + `components/ToastHost.vue`（TECH-03-B） | 复用，**只补视觉**（行为冲突见 §五 D2） |
| `.chip` 家族 | `base.css:585` 的 `.ai-tag`（仅局部） | 提升为共享组件 |
| `.avatar` | 无 | 新增（且后端无字段，见 §五 D4） |

### 2.3 为什么建议**不**改文件名/路由（重要）

你的示例里写了 `HomeView.vue` / `WorkspaceView.vue`。实测**重命名会打挂既有验收**：

| 被钉住的点 | 位置 | 影响 |
|-----------|------|------|
| `/dashboard` 路由 + "Dashboard" 文案 | `tools/verify_stage1.py:122` `:133` `:462` `:598` | 改路由 ⇒ `verify_stage1` 直接红 |
| `/dashboard` 点击锚点 | `tools/perf_tech01_22.py:286` `:317` | 改路由 ⇒ 性能基线跑不到页面 |
| `/mode` 点击锚点 | `tools/perf_tech01_22.py:327` | 同上 |
| `ui/src/views/LayoutView.vue` 必须存在 | `tools/gate.py:167` | 删/改名 ⇒ **门禁 FAIL** |
| `/ai` `/learning` `/project` `/profile` `/life` `/device` | `tools/verify_stage1.py:133` | 改路由 ⇒ 导航断言红 |

而你的第三阶段要求"必须通过 `verify_ui*` / `verify_tech*` / `build`"。
**结论：采用「文件名与路由不变，页面内部按原型改造」**——视觉标准通过"页面长什么样"实现，而不是通过文件名实现。
（若你坚持改名，必须同批更新上表 6 处脚本，那本身属"改验收判据"，需单独记账。）

---

## 三、Token 迁移方案

### 3.1 分层目标（**不新建变量系统**）

```
原型（唯一设计来源）              →   ui/src/styles/（现有分层，就地补齐）
─────────────────────────────────────────────────────────────────────────
tokens.css  色/字/距/圆角/阴影/几何  →   tokens.css      【补齐缺口】Foundation 不动，Semantic 加缺项
tokens.css  MOTION TOKENS（25 个）   →   motion-tokens.css 【不搬】改用映射表（§3.4）
index.html §3 TYPOGRAPHY（13 类）    →   components.css   【新增】t-* 排版类
index.html §4 APP SHELL（113 行）    →   base.css / layout.css 【就地升级】三层结构
index.html §5 PRIMITIVES（70 类）    →   components.css   【新增】共享组件层
index.html §6 ICON & MINIMAP（25类） →   components.css   【新增】
index.html §7~§9 页面专用            →   各 views/*.vue   【就地改造】
index.html §10* 响应式（4 段）        →   layout.css       【新增】+ 现有 JS 状态机
```

**形成的链路**（符合你要求的"设计token → Vue变量 → 组件样式"）：

```
设计 token（原型 tokens.css）
   ↓  补齐为
Vue 变量（ui/src/styles/tokens.css： --f-* Foundation → 语义层）
   ↓  只消费语义层
组件样式（components.css 的 .pw-card / .pw-chip / …）
   ↓  scoped 只放"这一页独有的" 
页面样式（views/*.vue）
```

**三条硬禁令的具体含义**：

| 禁令 | 本方案如何满足 |
|------|--------------|
| 禁止复制整套 CSS | 原型内联 CSS 共 **1079 行**（`index.html:1-1079`）。**不整体拷贝**：只抽取 §3/§5/§6 作为组件层，§4 升级现有 shell，§7~§9 按页就地改。§1 TOKENS 与 §1.5 MOTION **不拷** |
| 禁止创建第二套变量系统 | 变量**只增不改**地进 `tokens.css`；`motion-tokens.css` **只读不动**；不新开 `theme.css`/`vars.css` |
| 禁止第二套组件体系 | 只建 **1 个** 共享组件层（`components.css` + `components/ui/`），并把现有页面的重复 primitive（3 处 `.card`）**逐步迁到它上面**，不并列保留 |

### 3.2 色/尺寸 token 差异表（实测）

**命名空间：真实应用用 `--f-*`（Foundation）+ 语义名，原型用语义名 —— 语义名两边一致，这是迁移的最大便利。**

| 类别 | 原型有 | 真实已有 | 处置 |
|------|-------|---------|------|
| 窗口底 | `--bg-app` `--bg-app-hover` `--bg-canvas` `--bg-sunken` | `--bg-app` `--bg-canvas`（缺 2） | **补** `--bg-app-hover` `--bg-sunken` |
| 内容层 | `--surface-1/2/3` `--surface-hover` `--surface-inset` | `--surface-1/2/3`（缺 2） | **补** `--surface-hover` `--surface-inset` |
| 浮层 | `--surface-overlay` `--scrim` | 无 | **补**（Drawer/Modal 必需） |
| 描边 | `--border-subtle` `--border` `--border-strong` `--border-focus` | 前 3 个有（缺 focus） | **补** `--border-focus` |
| 主色 | `--brand-50/100/200/300/400/500/600/700` `--brand-contrast` | 只有 `50/500/600` | **补** 100/200/300/400/700 + contrast |
| 语义 | `--success/-soft/-text` `--warning/-soft/-text` `--danger/-soft/-text` `--info/-soft` | 只有 `--success/warning/danger` 单值 | **补** soft/text 变体 |
| 文本 | `--text-1..4` `--text-inverse` `--text-on-brand` | `--text-1..4`（缺 2） | **补** 2 个 |
| 应用图标 | `--app-tint-1..6` `--app-ink-1..6` | 无 | **补** 12 个（原型 §6 视觉签名依赖） |
| 字体 | `--font-ui` `--font-display` `--font-mono` | 只有 `--f-font-ui` | **补** display/mono + 语义别名 |
| 字级 | `--fs-display/page/section/card/body/body-sm/caption/label/num-lg` + `--lh-*` + `--ls-*` | 无 | **补**（原型 §3 排版类依赖） |
| 间距 | `--space-1..16`（含 64）+ `--gap-*` `--pad-*` | `--f-space-1..9`（4..48） | **补** 语义别名 `--space-N: var(--f-space-M)`，缺的补新 Foundation |
| 圆角 | `--r-xs/sm/md/lg/xl/2xl/full` | `--f-radius-1..5` + `--radius-controls/card/panel/container` | **补** 语义别名映射到既有 `--f-radius-*`（**不新增 Foundation 值**） |
| 阴影 | `--shadow-xs/sm/md/lg/inset`（5） | `--shadow-card` `--shadow-floating`（2） | **补** xs/sm 与 lg/inset，`--shadow-card` 保持沿用 |
| 几何 | `--titlebar-h` `--sidebar-w` `--sidebar-w-mini` `--topbar-h` `--appbar-h` `--ai-panel-w` `--content-max` `--panel-inset` `--z-*` | 无（硬编码在 `base.css:65`） | **补**（把 `44px`/`auto`/`28px` 硬编码提为变量） |

> ⚠️ **补 token = 只增不删不改**。现有 `--shadow-card` / `--radius-card` / Legacy 桥接（`--bg`/`--panel`/`--accent`，`tokens.css:97-105`）**全部保留**，
> 否则 `base.css` 里 300+ 处消费点会一起断。Legacy 桥接按原计划"存量兼容、新代码禁用"。

### 3.3 组件样式（§5 PRIMITIVES，70 类）的归属

原型 §5 是**组件库初稿**（`HANDOFF.md:29-33` 明确要求"抽取 + 适配，不要看截图重写"）。按"是否已有真实实现"分三类：

| 组 | 原型类 | 归属 |
|----|-------|------|
| **A. 全新增**（真实无对应） | `.card` `--lg/--ghost/--dashed/--flat/--hoverable`、`.chip` `--brand/--outline/--removable`、`.btn` 家族 7 个、`.icon-btn`、`.input`/`.field`/`.search`/`.select`、`.seg`/`.switch`/`.checkbox`/`.radio`、`.badge` 家族、`.avatar` `-grid` `-pick`、`.progress`/`.thin`、`.tile`、`.drawer` 系列、`.modal` 系列、`.scrim`、`.row-item`、`.empty`、`.skel`/`.spinner`、`.tabs`、`.tip`、`.illus`/`.ill` | `components.css`（新增） |
| **B. 就地升级**（已有实现，改成原型的样式/结构） | `.toast-host`/`.toast` → `ToastHost.vue`；`.ai-*`（dock/chat/perm）→ `AiSidebar.vue`；`.shell`/`.titlebar`/`.sidebar`/`.view` → `base.css` | 各组件 scoped + `base.css` |
| **C. 页面专用**（不进共享层） | `.hero`/`.ws-card`/`.ws-grid`/`.nowplaying`/`.stage*`/`.win*`/`.run-status`/`.wf-*`/`.model-*`/`.life-*`/`.timeline`/`.pick*`/`.wizard` | 各 `views/*.vue` scoped |

### 3.4 Motion：**不搬**，只出映射表（关键决策）

原型 `tokens.css:250-316` 定义了 **25 个逐场景 duration**（`--mt-dur-press/hover/drag/reorder/drop/highlight/scene-out/scene-in/window/toast-in/toast-out/ctx/drawer/modal-bg/modal/ai/ai-out/nav/nav-out/dwell/perm/entrance/entrance-ws/entrance-2/ambient`）。

真实应用 `motion-tokens.css:31-37` 是**刻意的 6 档**（`instant/quick/base/panel/scene/cinematic`）+ Skin 通道 + Guard，**已在 TECH-01 / Skin Engine 验收通过**（`verify_tech01` 9/9、`verify_skin_engine` 12/12）。

> **决策：不把 25 个 scene token 搬进 `motion-tokens.css`。**
> 理由：① 你的禁令"不新建动画体系"；② 真实应用已有 Skin 通道机制（原型没有），两套并存会让 Skin 失效；③ 25 个 token 的语义已被 6 档覆盖。

**映射表（写进文档，供实现时查表，不落 CSS）**：

| 原型 token | 值 | → 真实 token | 值 | 说明 |
|-----------|----|-------------|----|------|
| `--mt-dur-press` | 80ms | `--mt-dur-quick` | 120ms | 按下；真实已有 `--mt-press-scale` |
| `--mt-dur-hover` | 140ms | `--mt-dur-quick` | 120ms | hover |
| `--mt-dur-drag` / `-reorder` / `-drop` | 100/160/160 | `--mt-dur-quick` / `-base` | 120/180 | 拖拽过程**禁止过渡**，此项仅用于落位 |
| `--mt-dur-highlight` | 460ms | `--mt-dur-scene` | 320ms | ⚠️ 值不同，见下 |
| `--mt-dur-scene-out` + `-in` | 80+140 | `--mt-dur-scene` | 320ms | 页面进出（真实是单值） |
| `--mt-dur-window` | 200ms | `--mt-dur-base` | 180ms | Cinema 窗口落位 |
| `--mt-dur-toast-in` / `-out` | 180/120 | `--mt-dur-base` / `-quick` | 180/120 | **完全一致** |
| `--mt-dur-ctx` | 100ms | `--mt-dur-quick` | 120ms | 右键菜单 |
| `--mt-dur-drawer` | 240ms | `--mt-dur-panel` | 240ms | **完全一致** |
| `--mt-dur-modal-bg` / `-modal` | 140/180 | `--mt-dur-quick` / `-base` | 120/180 | 弹窗 |
| `--mt-dur-ai` / `-ai-out` | 260/200 | `--mt-dur-panel` / `-base` | 240/180 | AI dock 开合 |
| `--mt-dur-nav` / `-nav-out` | 260/200 | `--mt-dur-panel` / `-base` | 240/180 | 侧栏折叠 |
| `--mt-dur-perm` | 140ms | `--mt-dur-quick` | 120ms | 权限条 |
| `--mt-dur-entrance*` | 200/220/180 | `--mt-dur-base` | 180ms | 首入 |
| `--mt-stagger` | 24ms | `--mt-stagger` | 24ms | **完全一致** |
| `--mt-dur-dwell` | 320ms | ⚠️ **无对应** | — | 折叠停顿；真实侧栏折叠由 `motion/` 的 JS 管理，需查现实现 |
| `--mt-dur-ambient` | 600ms | ⚠️ **无对应** | — | 仅 loading 循环；真实用 `--mt-dur-cinematic: 560ms` 或 `.pw-motion-essential` |
| `--mt-cinema-interactive-gate` | 240ms | `--mt-interactive-gate` | 240ms | **完全一致** |

**两处值不一致需你注意**：`--mt-dur-highlight`（460 vs 320）与 3 个"无对应"项。
处置建议：**以真实应用的 token 值为准**（它已过 Skin/性能验收），把差异登记进 `docs/tech/` 的差异表，**不为了对齐数字而改冻结区**。

---

## 四、组件拆分规划（只定结构，不实现）

### 4.1 目标目录

```
ui/src/components/
  ui/                 ← 新增：共享 primitive（原型 §5 的落地形态）
    PwCard.vue  PwButton.vue  PwChip.vue  PwInput.vue  PwField.vue
    PwSeg.vue   PwSwitch.vue  PwCheckbox.vue  PwBadge.vue  PwAvatar.vue
    PwProgress.vue  PwTimeline.vue  PwEmpty.vue  PwSkeleton.vue  PwSpinner.vue
    PwDrawer.vue  PwModal.vue  PwRowItem.vue  PwTabs.vue  PwAppIcon.vue
    PwMinimap.vue
  (既有 8 个业务组件保持原名原位)
ui/src/styles/
  tokens.css        【补缺】
  motion-tokens.css 【冻结，不动】
  base.css          【升级 shell】
  components.css    ← 新增：primitives 的类实现
  layout.css        ← 新增：响应式档位（或并入 base.css）
```

### 4.2 你点名的 10 个组件：现状与处置

| 组件 | 原型类 | 真实现状（实测） | 处置 | 依赖 |
|------|-------|----------------|:----:|------|
| **Card** | `.card` + 5 变体 | **不存在**；`DeviceView`/`LifeView`/`ProjectView` **各写一个 `.card`** | **新增** | tokens |
| **Chip** | `.chip` + 3 变体 | 仅 `base.css:585` `.ai-tag`（局部） | **新增**（`ai-tag` 迁上去） | tokens |
| **Drawer** | `.drawer` + head/body/foot + `.scrim` | **不存在**（PW-INTEGRATION-002 §6.2 已判"真缺失"） | **新增** | Motion `overlay` claim |
| **Toast** | `.toast` + `#toastHost` | **已有** `ToastHost.vue` + `useToast.ts` | **复用**（⚠️ 行为冲突见 §五 D2） | — |
| **Window** | `.win` + `win-bar`/`win-body`/`.rz-*`/`win-size`/`.carried` | **不存在**（ModeView 只做布局槽位编辑器，无窗口画布） | **新增**（**只做展示**，不接真实窗口控制） | workspaceRuntime |
| **Workspace Stage** | `.stage` + `.stage-grid` + `.snap-ghost` | **不存在**；`LayoutView.lv-canvas` 是**只读画布**（最近似物） | **升级 `lv-canvas`** + 新增 stage 容器 | workspaceRuntime |
| **AI Sidebar** | `.ai-dock` + `.dock-rail` + `.dock-panel` | **已有** `AiSidebar.vue`（298 行）+ `base.css:380-717` | **就地改样式** | `stores/ai` |
| **Profile Editor** | `#profileEditor` + `.avatar-grid`/`.avatar-pick` | **不存在**（`ProfileView` 是表单式编辑） | **新增**（UI-08 结构） | `profileService`（avatar 缺字段） |
| **Model Card** | `.model-card` + `.model-grid` + `.mc-foot` | **不存在**（连页面都没有） | **新增**（P0-1） | `ai/model/bridge.ts` |
| **Minimap** | `.minimap` | **不存在**；`lv-canvas`+`lv-slot` 与 `mode-card__slots` 是数据等价物 | **新增组件 + 复用数据** | `layoutService` / `modeService` |

### 4.3 可选新增（原型有、你未点名，但被上述组件依赖）

`PwButton`（`.btn` 7 变体，每页都在手写 `<button>`）、`PwInput`/`PwField`（`.input`/`.field`）、`PwSeg`（`.seg`，设置/布局模式切换）、`PwSwitch`/`PwCheckbox`、`PwProgress`/`PwBadge`、`PwEmpty`/`PwSkeleton`/`PwSpinner`（三态成对，`design-system.md:761` 硬要求）、`PwAppIcon`（`.app` + `tint1..6`，`APPS` 已存在于真实应用软-ware库）。

### 4.4 明确**不做**的

- 不引入表格组件（`ui-forbidden.md:10` 禁表格化 CRUD）
- 不引入第三方 UI 库（等于第二套组件体系）
- 不把 `AiSidebar` 拆成多个组件（它是冻结的接线点，`verify_model_registry` T6b 白名单盯着）
- **不提前实现任何组件的"功能"** —— 本阶段只确定结构与归属

---

## 五、必须由你裁决的 4 件事（**不自行决定**）

| # | 冲突/问题 | A 方案 | B 方案 | 我的建议 |
|---|----------|-------|-------|---------|
| **D1** | **Motion 值不一致**（`--mt-dur-highlight` 460 vs 320；`dwell`/`ambient` 无对应） | 改动 `motion-tokens.css` 对齐原型 | 以真实 token 为准，差异登记 | **B**（冻结区已过 Skin/性能验收，改它属"修改 Motion 基础规范"= 你的禁令 4） |
| **D2** | **Toast 行为**：原型 2200ms/最多 2 条/带 ico；真实 4000ms/单条/变体无色 | 按原型改行为 | 保持真实行为，只补视觉 | **需你定**：行为差异**用户可感知**（时长差 1.8s、能否同时两条）。改 = 动 TECH-03-B 已验收件；不改 = 视觉标准未 100% 落地 |
| **D3** | **页面命名**：是否按你的示例改 `HomeView.vue`/`WorkspaceView.vue` | 改名（须同批改 6 处验收脚本） | **保留现有命名**，文档层登记对照 | **B**（改名会打挂 `verify_stage1`/`perf`/`gate`，与"必须通过验收"矛盾） |
| **D4** | **档案 avatar**：后端无字段（`database/schema.sql:116-123` 无 avatar 列，全仓 0 命中） | config 键 `profile.avatar`（零迁移） | migration 加列（语义更正） | **A**（你明确"不要自行增加数据库字段"） |

> ✅ 你已明确的两条，本方案直接遵循：
> - **avatar 问题单独登记、不自行加库字段** → 见 D4，方案 A 明确"用 config 键，零迁移"。
> - **P0-1 禁止重新创建模型状态** → §六 已把唯一来源钉为 `registry.ts`。

---

## 六、第二阶段：P0 接入顺序

### P0-1 模型管理中心（`ModelsView.vue`）

| 项 | 内容 |
|----|------|
| **创建** | `ui/src/views/ModelsView.vue` + 路由 `/models`（**不进主导航**，入口 = 设置「AI 与模型」分类 + AI 页 `当前模型` chip — 与原型 `ui-06-report.md` 一致） |
| **真实来源** | `ui/src/ai/model/bridge.ts`（`getSharedRegistry` / `currentCanonical` / `subscribeCanonical` / `syncSelection`）→ 内部经 `registry.ts` 落 L1 canonical |
| **只读展示** | `useCurrentModel()`（已有，只读面） |
| **禁止** | ❌ 新建 model store / ❌ 新建状态中心 / ❌ 直接 import `ai/model/registry` 调写方法（`setCanonical` 等） |
| **⚠️ 必须同步改验收** | `tools/verify_model_registry.py` 的 **T6b 白名单**（`WIRING_ALLOWED`，`:636-641`）当前只含 3 个文件；新增 `views/ModelsView.vue` 会**直接判红** → **必须加白名单并同步 T6b2 的写方法检查** |
| **字段映射** | `ptype` ↔ `connection.type`；`name` ↔ `name`；`provider` 展示名 ↔ `providerLabel()`；`status: connected/local/unset` ↔ `status.{available,enabled}`；**`latency` 无契约字段**（→ `metadata.extras.latency` 或不做，见 D5） |
| **状态真实显示** | 用 `ai_info`（凭据是否有 key）+ `registry.current()`；**测试连接**按钮本轮只做"演示"还是真调 `check()` 需你定（原型是演示） |
| **冲突项（必须收敛）** | `SettingsView.vue` 的 `store.data.defaultProvider` 与 canonical `ai.provider.current` 是**两个"默认 Provider"事实** → 接线时**必须**让设置页改为读写 canonical（preflight §3.4） |

### P0-2 个人档案页（`ProfileView.vue`）

| 项 | 内容 |
|----|------|
| **迁移目标** | UI-08 交互（`ui-08-report.md`）：原位展开编辑卡 `#profileEditor`、昵称/签名/标签/头像四区、头像 picker drawer、签名 60 字计数、标签删加推荐、进入编辑整体快照 `backup` |
| **接入** | 已有：`profile_*` 22 条命令、`ProfileView.vue`、`profileService`、`stores/profile` |
| **profileField 契约** | 原型 `{id,label,value,editable,type}` ↔ 真实 `ProfileBasic {name,direction,interests[],motto,updatedAt}`：`nickname→name`、`signature→motto`、`tags→interests[]`、`tagline→direction` **全部已有映射** |
| **avatar** | **单独登记**（你已指定）：后端无字段 → 按 D4 用 config 键 `profile.avatar`；**不加库字段**。语义沿用原型：`''`=首字母 / emoji=预设 / 未来 `custom:<引用>`=上传 |
| **必须保持** | S2 局部 diff（`verify_ui08` 的 T1/T8 断言**壳节点 DOM 身份不变**）；Esc 优先级（弹层 > 编辑卡）；**取消 = 整体还原** |
| **不得破坏** | 现有首次引导（`isFirstUse` 3 字段表单）、技能树、项目经历、成长时间线、**AI 建议确认流**（`suggestion-panel`，含"永久拒绝此类"） |

### P0-3 工作空间状态页（`ModeView.vue` / `LayoutView.vue`）

| 项 | 内容 |
|----|------|
| **迁移目标** | UI-05-B：第二行状态栏 `#runStatus`（当前任务 + 应用三态 chip + 布局状态 + 模式 chip + 布局结构入口）、工作空间页模板区 `wf-row`、准备 overlay `run-prep` |
| **只接** | `workspaceRuntime`（门面）+ `snapshot` 读 API（`getRecoveryStatus()`） |
| **只展示** | ① 当前模式（`modes_current`）② 应用状态（`WorkspaceApp.status`）③ 布局状态（`getLayoutMeta()`）④ 恢复状态（`getRecoveryStatus().recovery`） |
| **❌ 禁止** | **真实窗口控制**（不调 `layout_apply` / `windows_place` / `windows_activate` —— 它们**已存在**，本轮不扩大调用面）；原型 `restore()` 执行侧**保持 `executable:false`** |
| **替换点** | 原型 UI-05-B 已自标唯一替换点 `appStatusOf` → 换真实 `WorkspaceApp.status`；三态 chip 的"说谎"问题（报告 §五.1）随之消失 |
| **⚠️ 必须同步改验收** | `tools/verify_tech02_workspace.py` 的 **T1c**（`:355-368`）当前只允许 `DevWorkspaceHarness.vue` import `workspace/runtime` → 页面消费会**直接判红** → **必须扩白名单并记账（这是有意的边界扩张）** |
| **另注意 T1b** | UI 不得绕过门面直接 import `workspace/store` / `workspace/layout`（`:349`）→ 新页面**必须**走 `runtime.ts` |

### P1（后续，本轮只登记）

AI 页接「当前模型 / Provider / 会话状态」（⚠️ preflight §4 已登记"与 AiSidebar 是否共享会话"**需先定契约**）；学习系统接目标与进度；生活插件数据接口（⚠️ 槽位机制**需先定契约**）。

---

## 七、第三阶段：验收要求（每完成一个页面）

1. **输出五项**：修改文件 / 数据流变化 / UI 变化 / 验收结果 / 风险。
2. **保持现有功能不丢失**：改造前先跑基线，改造后逐条复跑。
3. **禁止**：不新建 mock 数据源 / 不新建状态中心 / 不新建 token 系统 / 不新建动画体系。
4. **必须通过**：

| 类别 | 命令 | 基线（本轮实测） |
|------|------|----------------|
| UI 验收 | `verify_ui04b/04c/04cp0/05p0/05snap/05b/06/07/08` | **96 条用例全绿**（15 套，Edge 无头 + CDP） |
| TECH 验收 | `verify_contracts` / `verify_model_registry` / `verify_tech02_workspace` | 6/6 · 32/32 · 11/11 |
| 其他 TECH | `verify_tech04` / `verify_tech03b` / `verify_tech01` / `verify_skin_engine` | 44/44 · 81/81 · 9/9 · 12/12 |
| 门禁 | `gate.py --stage 9 --build` | FAIL=0 WARN=0 PASS=30 |
| 构建 | `npm run build`（+ `cargo test`） | 通过（86/86） |
| 性能 | `perf_tech01_22.py` | 12 场景 longtask 全 0 |

> **增量记账要求**：本方案已识别 **2 处验收白名单必须同步扩张**（P0-1 的 T6b、P0-3 的 T1c）。
> 按项目既有纪律，扩张必须**显式写进报告与台账**，不许静默放宽。
>
> **批跑注意**：UI 脚本批量连跑时 `verify_ui05p0` 曾偶发 1 例失败（单跑 3 次均 7/7，属 Edge 资源争抢）。
> 批跑时该脚本**单独再跑一次**；不删断言、不放松判据。

---

## 八、本轮停止声明

按停止条件，本方案交付后**停止**：

- ✅ 已输出：UI 迁移方案 · 页面映射 · CSS/token 映射 · 组件拆分方案
- ❌ **未做**：任何代码修改（无新增/修改文件，无路由变更，无样式变更，无组件实现）
- ⏭ 待你确认 §五 的 **D1~D4** 与 §二 的命名口径后，再进第二阶段实现

**本方案的全部结论均可按标注的 `文件:行号` 复核。**
