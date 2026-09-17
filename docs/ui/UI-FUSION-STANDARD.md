# UI-FUSION-STANDARD — personal-workspace-ui 原型 → 真实应用融合标准（TECH-07-C）

> 版本：v1（Phase C1）
> 事实来源：原型 `personal-workspace-ui/`（tokens.css / design-system.md / motion-system.md / index.html）
> 消费方：真实应用 `ui/`（Vue 3 + Tauri）
> 本文档是 UI 融合的唯一标准。所有后续 Phase（C2/C3、F0-F5）的页面融合必须遵守本文档；冲突时以本文档 + 原型为准。

---

## 一、页面映射（原型页 → 真实路由）

| 原型页面 | 原型状态入口 | 真实路由 | 融合状态 | 说明 |
|---|---|---|---|---|
| 工作台（Run） | index.html 整页 | `#/run` | **C1 本阶段**：UI 壳完成，数据经 `workspace/runtime` | 唯一整页级新增；顶栏/状态条/主舞台/软件栏/minimap/AI 侧栏入口 |
| 模型中心 | UI-06 | `#/models` | ✅ 已融合（TECH-05-C） | 不进主导航，入口在设置→AI 与模型 |
| AI 助手侧栏 | index.html 右栏 | `#/ai` + Run 页 AI 侧栏入口 | ✅ 已融合；C1 在 Run 页补入口（ai.toggleCollapsed） | Run 页内通过 AI 抽屉/侧栏复用，不复制页面 |
| 个人档案 | UI-04 | `#/profile` | ✅ 已融合 | — |
| 工作空间状态 | index.html 状态条 | Run 页 run-status 条 | **C1 本阶段**：只读 facts 投影（模式/布局/窗口/降级） | 降级警告按 R-2 口径展示 |
| 工作模式真实运行 | index.html 主舞台 | Run 页 run-stage | **C1 本阶段**：窗口矩形投影（只读）；编排/布局按钮可见但 disabled | 窗口控制属 C3，不在 C1 放开 |
| Dashboard/软件/学习/项目/模式/布局/生活/设备/插件/设置 | — | 既有路由 | ✅ 已有，不在本阶段改动 | 遵守"不修改已验收模块逻辑" |

---

## 二、Token 对应（原型 tokens.css → 真实 styles/tokens.css）

**原则：单一 Token 体系。** 真实应用只允许消费 `ui/src/styles/tokens.css`（+ motion-tokens.css、primitives.css 原语）。原型独有的 Token **不得**在组件里新建平行定义，只允许按 TECH-05-C 先例**并入真实 Semantic 层**后引用。

### 2.1 两边同名、直接可用的 Token（核心子集）

| 类别 | Token |
|---|---|
| 窗口层 | `--bg-app` `--bg-canvas` `--bg-sunken`（C1 新并入） |
| 内容层 | `--surface-1` `--surface-2` `--surface-3` `--surface-hover` `--surface-overlay` `--scrim` |
| 描边 | `--border-subtle` `--border` `--border-strong` |
| 主色 | `--brand-50` `--brand-500` `--brand-600` `--brand-contrast` |
| 状态 | `--success` `--success-soft` `--warning` `--warning-soft` `--danger` `--danger-soft` |
| 文本 | `--text-1` `--text-2` `--text-3` `--text-4` `--text-on-brand` |

### 2.2 原型独有、暂未并入真实 Semantic 层（禁止组件内私造）

| 原型 Token | 原型用途 | 融合处理 |
|---|---|---|
| `--app-tint-1..6` / `--app-ink-1..6` | 应用图标兜底配色 | 需要时成对并入 Semantic 层（禁止散落组件） |
| `--brand-100..400` / `--brand-700` | 主色中间梯度 | 同上，整段梯度一起并入 |
| `--success-text` / `--warning-text` / `--danger-text` / `--info(-soft)` | 状态文字色（对比度保证） | 同上 |
| `--surface-inset` / `--bg-app-hover` / `--border-focus` / `--text-inverse` | 凹陷内衬 / hover / 焦点环 | 同上 |
| `--fs-*` `--lh-*` `--ls-*` `--fw-*` `--font-*` | 排版标度 | 排版融合时（F 阶段）整组并入，不零散挑用 |
| `--space-*` `--r-*` `--shadow-*` `--pad-*` `--gap-*` | 间距/圆角/阴影标度 | 真实应用已有等价约定（pw-* 原语）；仅当原型值与真实值冲突时，以**原型值**为准整段对齐 |
| `--mt-*`（原型 tokens.css 内） | 动效标度 | 真实应用已有 `motion-tokens.css` 承接，**不在 tokens.css 重复定义** |
| `--topbar-h` `--titlebar-h` `--sidebar-w` `--ai-panel-w` `--appbar-h` `--content-max` `--panel-inset` | 布局尺寸 | Run 页布局标尺对齐时整组并入 |
| `--z-toast/tip/drawer/modal` | 浮层层级 | 引入浮层时整组并入 |

### 2.3 引用规则

1. 组件 `<style>` 内**禁止硬编码色值/字号/间距**（verify 门禁会扫描 hex）。
2. 原型中出现而真实缺失的 Token：先在 `ui/src/styles/tokens.css` Semantic 层按 TECH-05-C 先例补齐（含暗色映射），再在组件引用。
3. 暗色主题：每个并入的亮色 Token 必须同时给出 `[data-theme='dark']` 映射，禁止只在亮色定义。

---

## 三、Component 对应（原型组件 → 真实原语/组件）

| 原型构件 | 真实对应 | 说明 |
|---|---|---|
| `.pw-btn` `.pw-card` `.pw-chip` `.pw-t-page` `.pw-dot--ok/wait/off` `.pw-scrim` `.pw-drawer` | `ui/src/components/ui/primitives.css` 同名原语 | **直接复用**，禁止在页面里重写第二套按钮/卡片样式 |
| 顶栏（返回/标题/分段控件） | Run 页 `.run-head`（C1） | 分段控件用 pw-btn 组合，禁用态用原生 disabled + `--text-4` |
| 状态条（task chips / layout / mode） | Run 页 `.run-status`（C1） | chip 用 pw-chip；降级警告用 `--warning` 系 |
| 主舞台（窗口矩形投影） | Run 页 `.run-stage`（C1） | 画布底 `--bg-canvas`、凹陷编排区 `--bg-sunken`；矩形边框 `--border-strong`、填充 `--surface-3` |
| 软件栏 + minimap | Run 页 `.run-foot`（C1） | minimap 与主舞台共用同一 windows facts 投影（单一事实来源，不各自拉数据） |
| AI 侧栏 | 复用 `#/ai`（useAiStore.toggleCollapsed） | 不复制 AI 页面内容 |
| 动效 | `motion-tokens.css`（--mt-*） | 时长/缓动只引用 Token；Run 页当前仅用 hover/entrance 级微动效 |

---

## 四、数据接入边界（Runtime Adapter）

1. **唯一通道**：页面/组件数据只允许来自 `@/workspace/runtime`（`workspaceAdapter.facts.*` / `workspaceAdapter.actions.*`），**禁止 import `@/api`**。
2. `@/api` 只允许出现在 `ui/src/workspace/runtime/` 内部（facts.ts / actions.ts）。
3. 命令白名单：`ALLOWED_COMMANDS` = modes_list / modes_current / mode_progress / layouts_list / monitors_list / windows_list / mode_apply / mode_cancel / mode_exit（全部为**已存在**命令，C1 不新增命令）。
4. 命令黑名单：`FORBIDDEN_COMMANDS` = windows_place / windows_activate / windows_find / windows_rect / layout_apply / mode_restore / modes_capture_current / apps_launch —— 窗口控制与恢复属 C3+，adapter 边界层直接拒绝。
5. 模式开关：`ADAPTER_MODE` C1 固定 `observe`；actions 在非 actuate 模式抛 `ActionBlockedError`。

---

## 五、禁止项（红线，验收门禁依据）

1. **禁止第二套 CSS 体系**：不新建组件级 token 文件；不在 `<style>` 写 hex/px 硬编码视觉值（布局 px 允许）。
2. **禁止绕过 adapter**：Run 页（及后续融合页）不得 import `@/api`、不得直连 store|layout 领域层。
3. **禁止修改视觉 Token 体系**：只允许"整段并入"缺失 Token，禁止改名/改义/改已有值。
4. **禁止降低交互复杂度**：原型分段控件/浮层/minimap 交互一律保留结构，C1 用 disabled 表达"能力未放开"，不删不简化。
5. **禁止复制 AI 页面**：侧栏入口复用现有 AI store/页面。
6. **禁止新增命令/迁移**：C1 数据全部来自已有命令聚合。
7. **禁止伪造数据**：所有投影来自 facts 快照真实返回；拉取失败必须显式展示降级（failures → 警告 chip），不得静默兜底假数据。

---

## 六、C1 验收对照（verify_tech07c.py 检查项）

| 检查 | 判据 |
|---|---|
| 原型视觉 Token 被引用 | `--bg-sunken` 已在真实 tokens.css Semantic 层定义（亮/暗），且 RunView 引用 |
| 无第二套 CSS 体系 | RunView 无 hex 硬编码；styles 目录仅 base/tokens/motion-tokens；组件样式只引用 token/pw-* |
| `/run` 路由存在 | router/index.ts 含 `path: '/run'` → RunView.vue |
| adapter 边界存在 | workspace/runtime 四文件在；ALLOWED/FORBIDDEN 清单齐；actions 不触碰黑名单命令 |
| UI 不直连 core | RunView.vue 无 `@/api`、无 tauri invoke import；**新融合页**一律如此（存量已验收视图的既有 @/api 引用不在 C1 红线内，C1 不改它们） |
