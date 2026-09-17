# REVIEW-017 · 阶段9（插件系统与小组件）验收报告

> 日期：2026-09-13 · 审核人：监制（肉编器001号）

## §〇 独立性声明

**本报告 = 自审 + 机器门禁，不具独立审核效力**（角色合并状态，M-5 裁决下的效力等级）。
判定依据全部来自本轮**独立重跑**的机器证据（未引用交付方数字）与**强制调用点检索**。
如需独立效力，白宇可下口令「申请独立复核阶段 9」。

**基线漂移检查**：本轮 mtime 扫描**不可用** —— 沙箱环境对全部文件（含 release 产物）给出同一合成时间戳。
改用更强判据：`gate.py --build` 内部走 cargo 增量编译，**全程零 `Compiling` 行** ⇒ 编译器判定源码与产物一致，
基线零漂移由 cargo 自证（比 mtime 可靠）。审核中修正 1 处 UI（见 §三·附 #10），修复后门禁复跑取新证据。

---

## §一 判定：✅ 通过（按白宇 2026-09-12 22:35 验收唯一标准）

### ① 目标达成 ✅

12 定位一句话「第三方能力进入工作空间，但权限收口在 core」，四大块全部落地：

- **插件宿主**：manifest 校验 / 安装三态（已注册拒绝·原地注册·拷贝安装）/ 默认零权限网关 + 逐次审计 / 8 类 API 分发 / `pwplugin://` 协议静态资源服务（5MB 上限 + 路径前缀守卫）/ zip 导入（zip-slip 防护）/ 崩溃上报隔离；
- **插件管理页 + 沙箱运行时**：`PluginsView.vue`（安装/启停/审计/预览）、`PluginFrame.vue`（`sandbox="allow-scripts"` 无同源 iframe，10s 就绪超时）、`pluginHost.ts`（postMessage 桥，origin 严格校验 `http://pwplugin.localhost`，ui.notify / ai.invoke）；
- **桌面小组件**：`desktop-widget` 独立 Tauri 窗口（开关 / 边界持久化 / 置顶 / 关闭事件回写，`main.ts?pwWindow=desktop-widget` 分支挂载）；
- **外部 Agent 网关**：core→Agent raw TCP HTTP/1.1 健康检查与调用；Agent→core `/agent/gateway`（`X-Agent-Name` 身份 + 未注册 401 + action 白名单 403 + 全量审计）。
- **★ 架构判据**（12 设计目标）：新增插件**零核心代码改动** —— 番茄钟 / 音乐两个示例插件不改一行 core，discover→install→invoke→widget 全流程实测（验收 1a~1g）。
- 11 组验收全部机器可判，`verify_stage9.py` **29/29**（release 产物 + 自起真实 core + mock Agent，本轮独立重跑）。

### ② 无致命漏洞 ✅

红线 V1~V8 **0 命中**（V2/V3 本阶段不涉及）：

- **V7（插件或 UI 直接访问数据库）= 结构级保证**：插件 JS 跑在 `sandbox="allow-scripts"` 无同源 iframe（opaque origin），一切能力必经 core 权限网关；`verify_stage9` 验收 11 实测 core 源码对插件**零特判分支** —— 插件没有任何比 UI 更多的 DB 通路。
- **V4（插件默认拥有权限）**：manifest 未声明一律 403 + 审计 `denied` + `PLUGIN_PERMISSION_DENIED` 事件（验收 2 实测）；安装即展示权限清单且与 manifest 逐项一致（验收 3）。
- **V5（破坏性操作二次确认）**：外部 Agent 的 `mode.switch` 即使已授予 `mode:switch`，**每次**仍需 `payload.confirm===true`，缺即 400（验收 10h 实测）；卸载插件在 UI 层有二次确认。
- **数据安全**：插件数据落点锁定 `plugins/<id>/data/`（验收 1e 实测跨插件不可达）；`pwplugin` 协议共享 `serve_file` 的 canonicalize + 前缀守卫，5MB 上限；外部 Agent 拒收 https（无 TLS 能力时如实拒绝而非假装支持，验收 10j）。
- **不可恢复架构错误**：无。单一写入者未破坏（插件表走 core repo）；ADR-001 合规。

### ③ 无冗余垃圾 ✅

- 门禁 **0 WARN**；
- 调用点检索 10 组符号全部接线，无"零调用即功能不成立"项（审核中抓出 1 处入口缺失，已当场修复，见 §三·附）；
- 示例插件即为 ★ 验收载具 + 开发指南配套样例，非一次性脚手架。

---

## §二 硬证据（全部本轮独立重跑，2026-09-13 18:46~18:53）

| 项 | 结果 |
|----|------|
| `python tools/gate.py --stage 9 --build` | **FAIL=0 · WARN=0 · PASS=22**（含 cargo check + B110 前端 typecheck + B131 sidecar 产物新鲜度）× 2 轮（NavSide 修复后复跑同值） |
| `python tools/verify_stage9.py`（**release 产物**） | **29/29 PASS**（11 组：零改动扩展 ★1a~1g · 权限拦截 2 · 权限展示 3 · 崩溃隔离 4 · 卸载清理 5 · 小组件开/关 7a/7b · 边界持久化 9a · 外部 Agent 10a~10j（401/403/400 红线/健康/调用/审计/https 拒收）· 无特判 11） |
| `cargo test`（core） | **86 passed; 0 failed**（阶段8 的 77 + 阶段9 新增 9：权限清理 / widget 配置 / install 三态等） |
| 前端 typecheck | 门禁 B110 **通过**（交付轮的 4 个类型错已修） |
| sidecar 发行产物 | B131 新鲜度通过（`/plugin/import` 随重打进入发行态） |
| 基线漂移 | cargo 增量编译零 `Compiling` 行 ⇒ 源码与产物一致（mtime 在本环境为合成值，不可用） |

## §三·附 强制调用点检索（零调用 = 功能不成立）

| # | 功能符号 | 调用点 | 结论 |
|---|----------|--------|------|
| 1 | 17 个 `plugins_*`/`plugin_*`/`agents_*`/`agent_*`/`desktop_widget_*` Tauri command | 定义 `api/commands.rs` + `main.rs` generate_handler 全注册 | 已接线 |
| 2 | `/api/v1/{plugins,plugin,agents,agent,desktop-widget}/*` 路由 | `api/mod.rs:181~193` 注册（verify9 端到端实跑） | 已接线 |
| 3 | `pluginService.ts` 17 个封装 | invoke + HTTP 双通道；`PluginsView` / `DesktopWidgetView` / `PluginFrame` / `pluginHost` 消费 | 已接线 |
| 4 | `PluginFrame.vue`（沙箱 iframe） | `PluginsView.vue:211`（预览）+ `DesktopWidgetView.vue:75`（小组件宿主） | 已接线 |
| 5 | `startPluginHost`/`stopPluginHost`（postMessage 桥） | `PluginsView.vue:56` + `DesktopWidgetView.vue:26`；origin 校验 `pluginHost.ts:59` | 已接线 |
| 6 | `/plugins` 路由 + 导航入口 | `router/index.ts:56`；**NavSide 导航清单原本缺"插件"项 —— 审核中当场补上**（`NavSide.vue:26`），修复后门禁复跑 B110 通过 | 已接线（本轮修复） |
| 7 | `pwplugin` 自定义协议 | `main.rs:62` 注册，走 `serve_file` 守卫；CSP `frame-src` 已放行 | 已接线 |
| 8 | Agent 网关身份与红线 | `api/mod.rs:1694` 缺 `X-Agent-Name` → 401；`agents.rs:325` `mode.switch` 逐次 confirm → 400 | 已接线 |
| 9 | `PLUGIN_LOADED` / `PLUGIN_PERMISSION_DENIED` 事件 | `plugins/mod.rs:409` / `:514` publish → event_bus 桥接 webview（阶段5 链路） | 已接线 |
| 10 | `desktop_widget::auto_open_if_enabled` / `on_close_requested` | `main.rs:89/104` 装配（`?pwWindow=desktop-widget` 分支 `main.ts:15`） | 已接线 |

修复后无"零调用即功能不成立"项。

## §四 阻塞项

**无。**

审核中发现并当场修复 1 项（修复后复跑取证，不影响判定有效性）：

- **NavSide 缺"插件"导航入口**：`/plugins` 路由与 PluginsView 完整，但侧栏导航清单漏挂（阶段8 的生活/设备均有入口）——"页面在、入口没接"，按调用点检索规则属功能不成立。已补 `{ to: '/plugins', label: '插件' }`，门禁复跑 0F/0W/22P。

记录在案（不阻塞、不处理）：

1. **UI 运行时交互无真窗口断言**：iframe 内真实渲染、小组件窗口拖拽/置顶的人工体感、验收项 6（10s 超时）与 8（CPU<1% 长周期采样）——verify_stage9 内 6/8 项 honest declaration 已逐条标注，机器只给接线级 + HTTP 级证据。与阶段6~8 的事件投递口径一致。
2. **真实第三方 Agent 未接**：mock Agent（自建 ThreadingHTTPServer）覆盖健康检查/调用/401/403/400 全链路；真实 Agent 的行为差异（超时重试、畸形响应）未实测。
3. **生活/设备保留 core 模块形态**：媒体能力以音乐示例插件走**通用**插件通路验证（core 无插件特例，验收 11 实测）；整体插件化迁移按 12 §验收11 的口径已闭环为"通路可用"，未强制搬迁。
4. **`ai.invoke` 走 consult 模式**（pluginHost 转发，Provider 抽象复用）：插件侧 AI 权限粒度目前只有"通/不通"，无按插件细分的计费/限额。
