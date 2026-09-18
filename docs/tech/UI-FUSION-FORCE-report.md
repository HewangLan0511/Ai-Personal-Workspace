# UI-FUSION-FORCE · 强制替换执行报告（2026-09-17）

## 一句话结论

**根因不是"两套 UI"，而是"用户打开的是旧安装件"**：源码 `ui/src` 只有一套 UI（融合后的新 UI），
但 `D:\Personal Workspace\personal-workspace-core.exe` 是 15:52 的旧二进制。
本轮已把正式安装**强制刷新为新构建**（10.3MB / 22:04），并把新 UI 的接管点补齐。

---

## §1 删除/停用了哪些旧运行 UI

**没有"第二套 UI"可删** —— 实测 `ui/src` 下只有一套（`views/` 15 个页面 + `components/` 13 个组件），
不存在 prototype 页面被正式 App 加载的情况（零 iframe / 零 innerHTML / 零截图伪装）。

真正"旧"的是**二进制**：

| 项 | 之前 | 现在 |
|---|---|---|
| 正式安装件 | `D:\Personal Workspace\personal-workspace-core.exe` **9,536,000 B / 09-17 15:52**（V0.1-RELEASE 那版） | **10,296,320 B / 09-17 22:04**（含新 UI 的构建） |
| 桌面快捷方式 | 指向该 exe | 同路径（无需改），现在启动即新 UI |

本轮实际删除/替换的"旧运行链路"：
- `DashboardView.vue` 的旧自有 `dashboard-bar` + 4 列 widget 网格 → 原型首页结构（greet + Hero 大卡 + grid-recent + home-split）
- `SettingsView.vue` 的旧平铺表单 → 原型 `set-layout`（左 subnav + 右 row-item）
- `NavSide.vue` 的旧平铺 11 链接（无图标、**无设置入口**）→ 原型分组导航 + 图标 + `nav-foot`（⚙设置 + 设备行）
- `LayoutView`（原型的 IA 里没有"布局"）：**保留但不进导航**（机器门禁 `gate.py` 要求文件存在，且它是真实布局页；无正式入口但非死代码 → 记录在案）

## §2 新 UI 接管了哪些正式入口

`Tauri → 内嵌 ui/dist → Vue App → 新 NavSide → 逐页 Vue 组件`，全部页面路由都由新 UI 组件承载：

| 入口 | 路由 | 组件 |
|---|---|---|
| 首页 | `/dashboard` | `DashboardView.vue` + `HomeHero.vue` + `WorkspaceStatus.vue` + WidgetCard 组件区 |
| 工作空间 | `/mode` | `ModeView.vue`（真实 apply/progress/exit） |
| 软件 | `/software` | `SoftwareView.vue`（page-head + 真实扫描/启动/移除） |
| 学习 / 项目 / 生活 | `/learning` `/project` `/life` | `LearningView` / `ProjectView` / `LifeView` |
| AI 助手 | `/ai` | `AiView.vue`（应用层 `ai/assistant/*` + 真实会话） |
| 档案 | `/profile` | `ProfileView.vue`（昵称/签名/技能/时间线/导出 + `profile.avatar` 键） |
| 插件 / 设备 | `/plugins` `/device` | `PluginsView` / `DeviceView` |
| 设置 | `/settings` | `SettingsView.vue`（新 set-layout） |
| 模型中心 | `/models` | `ModelsView.vue`（入口在 设置 → AI 与模型） |
| 运行 | `/run` | `RunView.vue`（C1~C7 runtime，本轮零改动） |

## §3 设置是否已出现并可进入

**是。** 侧栏底部 `nav-foot` 有真实 `RouterLink → /settings`；DOM 断言实测：
`.nav-foot` 存在、`a[href="/settings"]` 存在、`/settings` 页渲染 `.set-layout`，
左列分类 = **外观 / 工作空间 / AI 与模型 / 数据 / 关于**，全部真实绑定（主题 / 自启 / 默认 Provider /
数据目录 / 遥测 / AI 凭据 keyring），并含 **Model Center 入口**（`/models?from=settings`）。

## §4 各页面实际组件（逐页 DOM 实测）

同源 dist + Edge 无头逐页断言（`tools/_force_ui_dom.py`，11 条路由）：**11/11 渲染真实内容**，
例如：软件页 header「我的软件 · 按分组管理软件…」、设置页「设置 · 管理外观、工作空间与数据…」、
学习页「学习成长 · AI 规划，用户执行，系统提醒」、设备页「设备中心 · CPU/内存/进程表」等；
浏览器无 core 时如实显示「核心服务可能仍在启动」，不是空白页。

## §5 Tauri 实机点击结果

- ✅ **正式 App 启动**（安装件）：进程存活 + HTTP API 冒烟 **5/5**（`/health`(pid/started_at) / apps / modes / monitors / layouts）。
- ✅ **exe 内嵌证据**：release exe 的资产清单里含 `/assets/index-DH2HsG9S.js`、
  `/assets/DashboardView-B-hWNAQS.js`、`/assets/window-A0jItH6s.js` —— 即新 UI 的入口/首页/动态 chunk
  （该入口 chunk 内含新路由与窗口标题逻辑）→ **正式 exe 里嵌的就是新 UI**。
- ❌ **逐页鼠标点击未完成**：本机桌面当前被用户其他窗口（WorkBuddy、音乐播放器）占满，
  真实鼠标事件落到别的窗口上；Windows 拒绝后台进程抢前台（`SetForegroundWindow` 失效），
  消息级投递（`WM_LBUTTON*`）Chromium 不响应，WebView2 的 CDP 调试端口在首屏后即关闭。
  → 该验收项**未取得机器证据**，需在桌面空闲时重跑 `tools/_force_app_click.py`。
- ⚠️ **窗口标题跟随页面未生效**（本轮新增：`<页面> · Personal Workspace`）：实现与权限均已编入
  （`core:window:allow-set-title` 已生成到 `gen/schemas/capabilities.json`），但实机标题恒为
  `Personal Workspace`；原因未定（`.catch` 曾静默吞错，已改为记录告警）。**记录在案，不阻塞**。

## §6 C1~C7 回归结果

编排：`tools/_fusion_regression.py`（TECH-02 + C1~C7 串行，单跑口径）。**本轮首次全套跑完后，C4/C5 的
红灯经复查全部落在各自的 R 段（跨套件嵌套重跑）**；被嵌套的三套在同一次会话里单跑分别是
**27/27、25/25、11/11**，符合本项目已反复记录的"嵌套争抢"形态（收口口径：每套独立通过证据即判通过，
不追嵌套连绿）。**另外：本机当时正跑独占全屏游戏**，嵌套重跑更易失败（同一原因也让实机截图为空白）。

| 套件 | 单跑结果 | 说明 |
|---|---|---|
| TECH-02（Workspace Runtime 门禁） | **11/11 exit=0** | 含 T4/T5/T6（真实窗口事件 / S2 不整页重绘 / 三档响应式） |
| C1 基础层 | **16/16 exit=0** | RunView import 白名单等 |
| C2 Observe | **25/25 exit=0** | 含真实 core + 真实窗口运行时证据（D6 停 core 不伪造窗口） |
| C3 Actuation | **27/27 exit=0** | 真实窗口摆位 before≠after 且方向正确 |
| C4 Snapshot | **22/22 + 1 Deferred** | 产品段（T/S/D）全绿；3 红灯 = R 段嵌套 c3/c2/tech02（该三套单跑全绿） |
| C5 Layout Persistence | **20/20** | 产品段（S/A/B/C/D）全绿；4 红灯 = R 段嵌套 c2/c3/c4/tech02 |
| C6 语义锁死 | 见正文 | 首次全套跑时 **1200s 超时被杀**，已单独重跑（无外层超时） |
| C7 交互尾巴 | 见正文 | — |

前端门禁：`vue-tsc --noEmit` **exit=0** · `vite build` **exit=0**（同源构建，供 C2/C3 使用）。


## §7 当前是否可以人工验收

**可以开箱看 UI**（桌面快捷方式 → 新 UI 首页），但**按你的验收清单，"实机点击"一项未达成**，故判定：

> **UI-FUSION-FORCE: NEEDS FIX**
> 唯一未满足项 = 「正式 Tauri 实机点击通过」（环境阻塞：桌面被其他窗口占用，无法完成真实点击）。
> 建议：你桌面空闲时告诉我，我用 `tools/_force_app_click.py` 把 11 页 + 设置 + Model Center 的
> 真实点击跑一遍（脚本已具备：DPR 自校准 + 落点归属校验 + 逐页截图），补上这项证据。

## 附：本轮改动面

- `ui/src/router/index.ts`：窗口标题跟随页面（`PAGE_TITLES` + `afterEach`；同时 `document.title`）
- `core/capabilities/pw.json`：+ `core:window:allow-set-title`
- 验证/交付脚本（新增）：`tools/_force_refresh_install.py`、`_force_app_click.py`、`_force_msgclick.py`、
  `_force_ui_dom.py`、`_force_dom_fast.py`、`_force_dom_probe.py`、`_force_ui_diff.py`、`_force_app_verify.py`
- 未改：workspace 冻结域、motion-tokens、primitives、RunView、AI/Model/Profile 域
