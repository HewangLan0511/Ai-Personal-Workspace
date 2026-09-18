# UI-FUSION-REAL · prototype ↔ ui/ 只读对照与迁移映射（2026-09-17）

> 指令：UI-FUSION-REAL（唯一视觉源 = `personal-workspace-ui/`，技术实现适配设计）。
> 本表是 Phase 1 对照产物，也是后续逐页实施的依据。**零代码改动**（本阶段）。

## 一、结论（三条）

1. **数据面已经真实化，视觉面停留在"融合前"**：AiView / ModelsView / ProfileView 已用 Pw* 原语（TECH-05/06 融合）；RunView 的 run-head/run-status/run-stage 已按原型结构落地（TECH-07-C1~C7）。**Dashboard / Settings / NavSide / TopBar / Software / Mode 等仍是自有类 + 原生控件**，与原型视觉不是同一套。
2. **Shell 缺口**：正式壳层是 `TopBar(44px) + ModeBar + NavSide(平铺文字链接) + main + AiSidebar + StatusBar(28px)`；原型是 `sidebar(236px 分组导航+图标+底部设置/设备行) + content(page-head/page) + widget-col(仅首页) + ai-dock`。真实 token 中**没有** `--sidebar-w`/`--fs-*` 排版标度（尺寸硬编码在 base.css，字号收敛在 primitives 注释表）。
3. **导航缺口（用户硬性要求）**：当前侧栏 11 项平铺、无分组、无图标、**无设置入口**（设置只在 TopBar 有链接）。路由本身已齐（/settings、/models、/run 都存在），缺的是 IA 呈现层。

## 二、验收脚本 DOM 依赖（迁移不可破坏）

| 依赖 | 来源 | 约束 |
|---|---|---|
| `.app-nav a[href="/mode"]`、`a[href="/ai"]`、`a[href="/dashboard"]` | verify_tech05c/05d | 侧栏必须保留 `.app-nav` 类 + RouterLink 真实 href |
| 7 个 NAV_ROUTES href（/dashboard /ai /learning /project /profile /life /device） | verify_stage1 | 同上 |
| 页面文案标记："Dashboard""AI 助手""学习成长""项目管理""个人数字档案""生活中心""设备中心""插件""设置" | verify_stage1 ROUTES | 迁移后各页 DOM 必须仍含这些字符串 |
| `.widget-card`/`.widget-title`/`.widget-body`/`.widget-usage`/`.widget-actions button[title=上移]`、"恢复自动布局"、"已按手动布局固定"、`pw.config.ui.dashboard.usage/layout_locked` | verify_stage1 ★项8 | 首页必须继续经 WidgetCard 渲染组件（含天气/设备状态），组件管理入口保留 |
| `/dashboard` 上 WorkspaceStatus 文案 == `workspaceRuntime.getCurrent()` | verify_tech05c T3e | WorkspaceStatus 必须仍挂在首页 |
| RunView run-* 结构、S5 hash 基线（snapshot.ts/boundary 等 8 文件） | verify_tech07c1~c7 | RunView 只换视觉壳，runtime 结构与冻结域 hash 不动 |

## 三、页面级对照（prototype → 现状 → 迁移动作）

| Prototype | 现状 | 迁移动作 | 保留的真实能力 |
|---|---|---|---|
| 首页 `#/home`（greet 问候 + Hero 当前工作大卡 + grid-recent 最近使用 + home-split[我的工作空间 ws-card+minimap / 今天行动中心] + widget 侧挂列） | DashboardView：自有 dashboard-bar + WorkspaceStatus + widget 4 列网格 | **整体重建**为原型结构；"我的工作空间"区由 WorkspaceStatus（状态条+模板卡）承担；右侧列 = WidgetCard 组件区（组件管理/锁定横幅原样保留） | workspaceRuntime、widget store/usage/lock 全链、apps 真实图标与 launch |
| 侧边栏（NAV 分组：首页/工作[工作空间·软件]/学习/项目/生活/AI助手·设备·档案·插件 + nav-foot[设置+设备行]，图标+active 左竖条） | NavSide 平铺 11 项无图标无设置 | **重建**为原型分组+图标+设置底栏；删除"布局"项（原型 IA 无此项，路由保留） | 全部既有路由与 href 依赖、nav.collapsed 持久化（映射为原型 mini 态） |
| 设置 `#/settings`（set-layout：左 192px subnav 分组 + 右 set-body row-item 行式） | SettingsView 平铺单列表单 | **重建**为 set-layout；分类=外观/工作空间/AI 与模型/数据/关于（软件/插件暂无真实行，不造假） | 主题/自启/默认Provider/数据目录/遥测/AI凭据/Model Center 入口全部绑定原样迁移 |
| 工作空间 `#/workspaces`（page-head + 模式模板区 + ws-grid） | ModeView（mv-toolbar + mode-card，真实 apply/progress/exit） | 轻改：补 page-head 形态（保留 mv-* 类与全部逻辑） | 模式全链（C4/C5/C6 验收依赖） |
| 软件 `#/apps`（GROUPS 分组网格 + 右键菜单） | SoftwareView（apps-toolbar/apps-side，真实） | 轻改：补 page-head | 扫描/启动/移除全链 |
| 学习/项目/生活/设备/插件 | LearningView/ProjectView/LifeView/DeviceView/PluginsView（真实数据） | 轻改：补 page-head | 各域全链 |
| AI 助手 `#/ai`、模型中心 `#/models`、档案 `#/profile` | AiView/ModelsView/ProfileView（已用 Pw* 原语融合） | 本轮不动（已是原型视觉语言），仅核对 | session/service/bridge、registry、profile 契约 |
| Run `#/run` | RunView（C1~C7 完整 runtime） | **只换视觉壳不动 runtime**（原型 run-head/run-status/run-stage 结构已对齐，本轮仅核对视觉细节） | projection/ownership/drag/Esc/snap/offline/layout/snapshot 全部 |

## 四、Token 并入清单（整段并入 tokens.css，含暗色映射）

- 排版标度：`--fs/--lh/--ls`（display 26 / page 20 / section 15 / card 14 / body 14·13 / caption 12 / label 11 / num-lg 22）+ `--fw-regular/medium/semi` + `--font-display/--font-mono`
- Shell 布局：`--sidebar-w:236px`、`--sidebar-w-mini:64px`、`--topbar-h:56px`、`--appbar-h:46px`、`--widget-w:224px`、`--content-max:1120px`、`--panel-inset:10px`
- 语义间距：`--gap-card:20px`、`--gap-section:32px`、`--pad-card:20px`、`--pad-card-lg:24px`、`--pad-page-x:32px`、`--pad-page-t:28px`
- 圆角：`--r-xs/sm/md/lg/xl/2xl/full`（4→20）
- 阴影：`--shadow-xs/sm/md/lg`（原型原文值）
- 品牌梯度补齐：`--brand-50/100/300/400/700`（Foundation `--f-brand-*` 已有源值）
- 微动效时长：`--dur-micro/--dur-fast` + `--ease-out`（原型 tokens.css Motion 段；不碰 motion-tokens.css 既有 `--mt-*`）

## 五、图标

导航图标取原型 SVG symbol 原文（`#i-home/ws/grid/book/folder/sun/sparkle/card/monitor/blocks/settings`），内联进 `NavSide.vue` 的 `<symbol>` + `<use>`（stroke 1.6 / currentColor，与原型一致），不自创图形。
