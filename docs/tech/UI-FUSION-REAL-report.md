# UI-FUSION-REAL 交付报告（2026-09-17）

> 指令：`personal-workspace-ui/` = 唯一视觉源，迁移进 `ui/` 成为真实 Vue 组件 + 既有 stores/services/runtime。
> 汇总对照文档：`docs/tech/UI-FUSION-REAL-mapping.md`（Phase 1 只读对照与逐页映射）。

## §17 结构化结论

### Source（视觉源）
- `personal-workspace-ui/index.html`（单文件原型，5535 行，含内联 SVG symbols）+ `personal-workspace-ui/tokens.css`。
- 迁移方式：原型结构/类名/排版/间距/圆角/阴影逐段搬入真实 Vue SFC；**零 iframe / 零截图 / 零 innerHTML 拷贝 / 零重新设计**。
- Token 只**补缺口**（映射表 §四）：排版标度 `--fs-*/--lh-*/--fw-*`、Shell 布局（`--sidebar-w:236px`/`--sidebar-w-mini:64px`/`--content-max:1120px` 等）、语义间距 `--gap-*/--pad-*`、圆角 `--r-xs..2xl`、阴影 `--shadow-xs..lg`、品牌梯度补齐 `--brand-50..700`、微动效 `--dur-micro/fast`+`--ease-out`，均含暗色映射。既有 `--mt-*` Motion 冻结域零改动。

### Pages migrated（本轮实际改动面）
| 页面 | 动作 | 文件 |
|---|---|---|
| 侧边栏 | **重建**为原型 NAV：分组（首页/工作[工作空间·软件]/学习/项目/生活/[AI助手·设备·档案·插件]）+ nav-foot（⚙设置 + 设备行在线状态）+ 原型 SVG symbol 图标 + active 左竖条；collapsed 映射原型 mini 态 | `ui/src/components/NavSide.vue` |
| 首页 | **整体重建**为原型 `#/home`：greet 问候 + Hero 当前工作大卡（新组件）+ grid-recent 6 个真实常用应用（真实启动）+ home-split（左=我的工作空间 WorkspaceStatus，右=WidgetCard 组件区，管理/锁定原样保留） | `ui/src/views/DashboardView.vue` · 新增 `ui/src/components/HomeHero.vue` |
| 设置 | **重建**为原型 `#/settings` set-layout：左 192px subnav（外观/工作空间/AI 与模型/数据/关于）+ 右 row-item 行式；全部真实绑定保留（主题/自启/默认Provider/数据目录/遥测/AI 凭据 keyring/Model Center 入口 `/models?from=settings`） | `ui/src/views/SettingsView.vue` |
| 软件 | 补原型 page-head（"我的软件"）+ 分组形态，apps-toolbar/扫描/启动/移除全链不动 | `ui/src/views/SoftwareView.vue` |
| 全局样式 | tokens.css 并入原型标度块；base.css 的 `.app-nav` 改原型侧栏形态、`.app-main` 用语义间距、全局 h2/h3 接原型排版、`.page-head` 工具类 | `ui/src/styles/tokens.css` · `ui/src/styles/base.css` |

**核对为已融合、本轮零改动**：AI 助手（AiView）/ 模型中心（ModelsView）/ 档案（ProfileView）——已是 Pw* 原语 + 原型视觉语言（TECH-05-C/D·TECH-06 交付）；RunView——run-head/run-status/run-stage 结构已按原型落地（C1~C7 交付），本轮只核对视觉细节，runtime 零触碰。

**记录在案（非阻塞）**：映射表原计划对 工作空间/学习/项目/生活/设备/插件 六页做 page-head 轻改，本轮未执行——六页均为真实数据视图（ModeView 为 C4/C5/C6 验收依赖面），视觉已属原型卡片语言；保留现状待下一轮视觉打磨，不阻塞判定。

### Visual（视觉体系）
- 原型层级/卡片/间距/字号/圆角/阴影/hover/图标/留白/密度经 token 标度逐段恢复；窗口即纸面与既有 token 体系兼容（无新变量系统，只并标度）。
- 未新增任何 `--mt-*` 之外的自造 token 名；Motion Guard / Page Transition / Skin 通道零触碰（回归佐证）。

### Real data（真实能力保留）
- 首页 Hero 消费 `workspaceRuntime`（已登记 verify_tech02 T1c 白名单）；grid-recent 走既有 apps store 真实图标与 launch；WorkspaceStatus/WidgetCard/usage/lock 全链原样。
- 设置页全部 configService / keyring 凭据 / Model Center 入口原绑定迁移。
- 侧栏保留全部验收 DOM 依赖：`.app-nav` 类 + 7 条 NAV_ROUTES href + 页面文案标记；"布局"项移除（原型 IA 无此项，路由保留）。
- RunView / AiView / ModelsView / ProfileView 既有真实链路零改动。

### Build
- `vue-tsc --noEmit` **0 error**；`vite build` 通过（`VITE_CORE_BASE=''` 同源验证构建）。
- Tauri 正式 release 构建成功（`ui/scripts/tauri.mjs build`，exit 0）：msi + nsis + exe 产出于 `core/target/release/bundle/`，新 UI 已嵌入。

### Regression（C1~C7 + 机器门禁，清洁环境串行复跑）
| 套件 | 结果 |
|---|---|
| TECH-02（Workspace Runtime 门禁） | **11/11**（新 CSS hash 基线已登记：tokens.css / base.css） |
| C1 基础层 | **16/16** |
| C2 Observe | **25/25** |
| C3 Actuation | **27/27** |
| C4 Snapshot | **25/25 + 1 Deferred**（E 项，沿用 C4 收口口径） |
| C5 Layout Persistence | **S+A+B+C 全过**（唯一嵌套红灯为 c4 资源争抢，独立跑绿） |
| C6 语义锁死 | **27/27** |
| C7 交互尾巴 | **S 13/13 · R 7/8 · D 6/6**（R 红灯为嵌套争抢轮转，独立证据齐，收口口径同 V0.1-FINAL） |
| TECH-05-C（P0 三页） | **34/34** |
| contracts | 6/6 |

### Smoke（发行态）
- release exe 启动 + HTTP API 冒烟 **6/6**（`tools/_fusion_smoke.py`：进程存活 / /health / apps / layouts / monitors 全 OK）。

### Visual comparison（视觉对比证据）
- Edge headless + CDP（自研 WebSocket 客户端，`tools/_fusion_visual2.py`）对 **12 个真实页面** 截图，与 **4 张原型页** 同目录对照：`tools/_fusion_shots/`（`cdp-*.png` ×12 + `proto-*.png` ×4 + 首轮 `*.png` 存档）。
- DOM 级确认：设置页 set-layout 完整渲染、软件/工作空间页结构正确、侧栏分组+图标+设置底栏到位。
- **如实声明**：截图已生成供白宇人工比对（模型无法读图）；"明显看出是同一个产品"的最终判定权在人工验收。

### Changed files（全部改动面）
- 修改：`ui/src/components/NavSide.vue` · `ui/src/views/DashboardView.vue` · `ui/src/views/SettingsView.vue` · `ui/src/views/SoftwareView.vue` · `ui/src/styles/tokens.css` · `ui/src/styles/base.css` · `tools/verify_tech02_workspace.py` · `tools/verify_tech07c2.py` · `tools/verify_tech07c3.py` · `tools/verify_tech07c4.py` · `tools/verify_tech07c5.py` · `tools/verify_tech07c6.py`（仅 CSS hash 基线登记）
- 新增：`ui/src/components/HomeHero.vue` · `docs/tech/UI-FUSION-REAL-mapping.md` · `tools/_fusion_*.py`（构建/回归/视觉/冒烟 5 件套）
- **零改动**：core Rust 侧、workspace 冻结域（snapshot/boundary/actions hash 不变）、motion-tokens.css、primitives.css、AI/Model/Profile/Run 域。

### Release status
**NOT RELEASED / READY FOR REVIEW。**
按 §15 约定：UI Fusion → Build → Visual → C1~C7 回归 → Smoke 全部通过后**才**生成新 release；当前等待白宇人工视觉比对确认后再打包发版。**tag `v0.1` 未覆盖**，未产生任何新 release/tag。

## Navigation（导航专项 · 用户硬性要求）

| 项 | 结果 |
|---|---|
| 侧栏完整 IA | ✅ 首页 / 工作（工作空间·软件）/ 学习 / 项目 / 生活 / AI助手 / 设备 / 档案 / 插件，分组+图标+active 竖条 |
| ⚙设置真实入口 | ✅ nav-foot 底栏 RouterLink → `/settings` 真实路由+视图（此前设置只在 TopBar，侧栏无入口——已补） |
| 设置页内 AI 与模型 | ✅ subnav「AI 与模型」分组：默认 Provider / AI 凭据（keyring）真实绑定 |
| Model Center 入口 | ✅ 设置页 → `/models?from=settings`，返回导航保留 |
| 未删除/未合并 | ✅ 设置/设备/插件/档案/AI助手 全部独立入口，无"更多"合并；仅移除原型 IA 没有的"布局"项 |
| 设备在线状态行 | ✅ nav-foot 设备行接 `connection.online` |
| 验收依赖 | ✅ `.app-nav` 类 + 全部既有 href/文案标记保留（verify_stage1/05c/05d 回归绿佐证） |

**Navigation: PASS**（注：本专项按指令登记为独立导航恢复项，**不计为 C8**。）

## 边界如实声明
1. 六个域页面（工作空间/学习/项目/生活/设备/插件）的 page-head 轻改未执行（映射表计划项），记录在案非阻塞。
2. 视觉"同一产品"结论 = DOM/结构/token 层机器证据 + 截图材料；最终人工判定待白宇。
3. C7 R 段 7/8 为嵌套沙箱资源争抢（历史已知形态），各套件独立通过证据齐备。
4. 本轮 `config/layouts/run-C5*/run-C6*` 为回归脚本运行产物（验证残留），非交付物。
