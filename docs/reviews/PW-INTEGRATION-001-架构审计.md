# PW-INTEGRATION-001 · 整合前架构审计报告

> 日期：2026-09-15 · 性质：**只分析，未修改任何代码**
> 方法：三路实读（core Rust / ui Vue3 / Python·数据·插件）+ 关键结论二次复核（承重结论均经 grep/读码验证）
> 证据标注：文中「文件:行号」均为实际读码位置

---

## 〇、一句话总判

**边界设计优秀，接线严重不足。** Core 已真实存在且分层规范（不是"未来 Core"），数据纪律是全项目最强资产；但 Motion/Skin 底座"建成未接线"（业务消费≈0），浮层组件三套自造，core 接口双通道同源靠纪律硬撑。整合阶段的主线不是补架构，而是**把已建成的能力接线 + 收口**。

---

## 一、实际检查结果概览

| 层 | 实读范围 | 关键事实 |
|----|---------|---------|
| 技术栈 | — | Tauri 2.x（Rust core + axum）+ Vue3/TS + Python stdlib sidecar + rusqlite(WAL) |
| core/src | main.rs、api/、scheduler/、app_manager/、window_manager/、plugins/、ai/、event_bus/、db/ | 15+ 模块、**121 个 tauri commands**、axum `/api/v1/*` + `/internal/*` 双通道、tokio broadcast 事件总线 |
| ui/src | router、7 stores、9 services、12 views、motion/、widgets/ | `invoke(` 全局仅 1 处（api/client.ts:53）——单点封装 |
| system/ | service.py、life.py、apps_probe.py | 随机端口 announce，core 拉起+重启监管 |
| ai/ | providers/registry.py、service.py、credentials.py | 4 实装 Provider + 2 占位；凭据走 Windows CredRead/W |
| 数据 | core/migrations 0001–0008，17 张表 | **core 是唯一 DB 写入者**（sidecar `/internal/db/*` 显式 410 拒绝，service.py:440-449） |
| 插件 | core/src/plugins、plugins/×2 | 权限网关+审计+`pwplugin://` 协议；示例插件零 core 改动（阶段9 验收项1 实测过） |
| Motion | ui/src/motion/×9 文件 + motion-tokens.css | 运行时完备（guards/conflict/interrupt/pageTransition/cinema/viewTransition/skin） |
| Skin | ui/src/motion/skin.ts | v1.0 已实现：Loader/Registry/Apply/白名单/Guard 优先级，验收 12/12 |

---

## 二、真实架构图（实际 vs 理想）

### 2.1 当前真实结构

```
Personal Workspace
│
├── Core ★真实存在且完整 = core/src（Tauri + axum）
│   ├── scheduler/（工作模式引擎★：七步流水线，全项目核心）
│   ├── app_manager/（软件注册/真实 CreateProcessW 启动/存活轮询/终止）
│   ├── window_manager/（真实 Win32：枚举/定位/激活，hwnd=isize）
│   ├── plugins/（权限网关+审计+六类 API 分发）
│   ├── ai/（手写 TCP HTTP/1.1 流式转发 → sidecar）
│   ├── learning/life/profile/project/device/agents（各带 repository）
│   ├── event_bus/（tokio broadcast → pw://event 单通道）
│   └── db/（rusqlite 唯一写入者）+ sidecar/（Python 监管）
│
├── Modules = 上述业务模块（core 内部目录，非独立包）
├── Plugin System = core/src/plugins + plugins/×2 示例 + ui/pluginService+PluginFrame
├── AI System = ai/(Python Providers) + core/src/ai(转发) + system/(sidecar) + ui/stores/ai
├── Motion System = ui/src/motion/（UI 层局部，位置正确）
├── Skin System = ui/src/motion/skin.ts + tokens.css 三层（UI 层局部，位置正确）
├── UI Layer = ui/src（12 产品页 + 8 自渲染 widget + 7 pinia store + 9 service）
└── Data Layer = core/src/db + core/migrations + {APPDATA}/PersonalWorkspace/workspace.db
```

### 2.2 与理想结构的差距（不重构，只指出）

| # | 差距 | 现状 | 严重度 |
|---|------|------|:---:|
| G1 | **Motion/Skin 底座建成未接线**：`var(--mt-` 在 views/components 零命中，`startCinema/runInterruptible/__pwMotion` 业务消费零命中；唯一生效的是 motion-tokens.css:101-116 的 button 级兜底 + App.vue 页过渡 | 底座空转 | **P0** |
| G2 | **core 双巨石**：api/mod.rs 与 commands.rs 各 1800+ 行，HTTP 与 command 双通道"逻辑同源"仅靠注释约定（api/mod.rs:314），无共享 handler 层 | 漂移风险随功能增长 | **P0** |
| G3 | **浮层无全局层**：Toast/Modal 三套自造（ModeView.vue:678/996 `mv-toast`、SoftwareView.vue:359/611 `apps-toast`、base.css:342 `saved-toast`），Drawer/ContextMenu 根本不存在 | 重复实现×3 | P1 |
| G4 | **service 层收口不全**：stores/ai.ts（402 行）是唯一无 service 包装的领域（直接 invoke×5，ai.ts:122-360）；TopBar.vue:25、SettingsView.vue:66-101 组件直调 invokeCore 越层 | 模式分裂 | P1 |
| G5 | **Skin 无产品入口**：唯一调用口是 `window.__pwMotion.skin` 调试口，SettingsView 只有 light/dark（SettingsView.vue:129-136） | 能力不可达 | P1 |
| G6 | sidecar HTTP 契约无 schema 校验（端口 announce/NDJSON 靠约定；PyInstaller 旧二进制错配已发生过=遗留项 L-043） | 已知坑 | P2 |

### 2.3 必须现在处理 vs 可以以后

- **现在**：G1（决定后续所有页面怎么写）、G3（决定 Skin 能否换组件形态的前提——浮层先统一才有"换"的对象）
- **本轮整合**：G2（小步试点，不推倒）、G4、G5
- **以后**：G6、索引 key 残留（LayoutView.vue:128 等 6 处）、skin schema v2

---

## 三、UI 与业务逻辑耦合（重点四问）

| 问题 | 判定 | 证据 |
|------|:---:|------|
| **换一套 UI Skin，是否需要修改业务逻辑？** | **否** ✅ | Skin 只写 `--mt-skin-*` 通道 + `--accent`（skin.ts:281-305）；Guard 硬设最终值，业务代码不感知。⚠️ 但 Skin 能改的范围有限（见 §六），且**没有 UI 入口** |
| **增加一个 Plugin，是否需要修改 Core？** | **否** ✅ | 六类 API 分发 + 权限网关 + 审计；阶段9 验收项1（新插件零核心改动）已实测通过 |
| **更换 AI Provider，是否需要修改 UI？** | **否** ✅ | Provider 列表是数据驱动（`ai_info` 返回 ProviderInfo 元数据，AiSidebar.vue:130-137 `v-for` 渲染）；新增 Provider 只改 ai/providers/registry.py 一行。⚠️ 选择入口分散三处（localStorage `ui.ai.provider` / 模式 JSON `aiProfile.provider` / 请求级覆盖） |
| **Workspace Engine 是否可以被不同 UI 调用？** | **是** ✅ | 双通道暴露：tauri commands 121 个 + axum `/api/v1/*`；core 返回统一 `Result<Value, String>`/envelope，**无表现语义泄漏**（grep 颜色/按钮/样式零命中） |

### 其他耦合点检查

- **页面直接操作业务数据**：❌ 不存在——`invoke(` 全局单点（api/client.ts:53），9 个 service 层。但 8 个视图绕过 store 直连 service（ModeView.vue:14、ProjectView.vue:11-12 等），页面逻辑与接口签名耦合。
- **UI 直接控制窗口**：❌ 仅 TopBar.vue:25 `minimize_window`（走 core 命令，归属正确）；零 `@tauri-apps/plugin-*` 导入。
- **UI 直接操作 SQLite**：❌ 不可能——前端无 DB 通路，sidecar 也被 410 拒绝。
- **Workspace 页面与 Engine 耦合**：✅ 健康——ModeView/ModeBar 经 modeService 走命令与 `MODE_CHANGED` 事件，不感知 pipeline 内部。

---

## 四、UI Contract 现状

**已成形（数据/事件层）**：
- 统一 envelope `{ok, data?, error{code,message}}`（api/mod.rs:23-32）+ 统一 `Result<Value, String>`
- 事件单通道 `pw://event` + 20 个事件常量（events.rs）——core 不给 UI 发"表现指令"，发的是状态/进度/错误
- 能力元数据先例：`ProviderInfo{label, capabilities, needsKey}`——这就是 UI Contract 的雏形

**未成形（表现/能力层）**：
- ❌ 无命令名常量表：前端各 service 硬编码字符串命令名（`invoke("ai_chat")` 散布）
- ❌ 无 Capability 声明：UI 通过硬编码知道有 `minimize_window`，core 无法表达"我能做什么"
- ❌ Skin 无法换 Component：业务数据是原始 JSON，UI 组件自渲染——skin 改不了组件形态（这是 v1.0 白名单的设计决定，不是缺陷）

**最小可行方案（不推倒）**：
1. `ui/src/api/contracts.ts`：命令名/事件名常量表 + TS 类型（纯收口，零行为变化）
2. 浮层统一为全局单例组件（PwfToast/PwfModal），core→UI 只发语义事件，浮层形态由组件决定
3. AI Provider 选择入口收拢为一个（settings 页），消除三处分散

---

## 五、Motion System 检查（重点）

### 5.1 现状分级：**运行时完备 · 接线不足**

| 能力 | 运行时 | 业务接线 |
|------|:---:|:---:|
| 页面切换 Page Transition | ✅ latest-wins | ✅ App.vue:39-42 唯一接线点 |
| Button/可点击元素 token | ✅ | ✅ motion-tokens.css:101-116 全局兜底 |
| Guard 三档/Performance Guard | ✅（#22 实测 off/reduced 生效） | ✅（CSS 层自动生效） |
| **Modal / Toast** | — | ❌ **三套自造，不走 token，modal 无 enter/leave 动画（v-if 直切）** |
| **Drawer** | — | ❌ **不存在**（全仓无实现组件） |
| **ContextMenu** | — | ❌ 不存在 |
| Workspace Cinema | ✅ 原语+Gate+resize 收敛（verify 9/9） | ❌ **零业务消费**（Dashboard 进入/退出未触发） |
| Interrupt Guard / Conflict Guard | ✅ | ❌ 仅页过渡间接消费 |
| Toast 动画 | — | ❌ 文本 v-if 直接出现，无 token |
| Card/Loading/Empty State | — | ⚠️ 无统一组件，各页自写 |

### 5.2 特别检查：局部状态变化是否触发整页 enter animation

**否，安全。** `<transition>` 绑定 `:key="$route.path"`（App.vue:41）——只有路由变化才触发 enter/leave；页内过滤/排序/选中不触发。且 S2 纪律是结构性的（DevMotionHarness 注释 + #22 实测 diff 路径样式计算 ≈ 整页重挂 1/5）。

**残留问题（只报告不修改）**：
1. 三套自造浮层动画未走 token（G3）
2. 4 处硬编码 transition：base.css:617、base.css:625、LearningView.vue:604、ProfileView.vue:774
3. 索引 key 6 处（LayoutView.vue:128,149、ModeView.vue:479,506,618,659、LearningView.vue:393,476）——重排会 remount 子项，多数为不重排槽位，风险低

---

## 六、Skin Engine 现状（分级）

**按 A-E 标尺的精确位置：跨档态——「A（仅 Theme）完整 + D 的 Motion 变量层已运行时化」，Component/Layout 级为 0。**

| 能力 | Skin 能否改变 | 机制 |
|------|:---:|------|
| 颜色 accent | ✅ | `--accent` 内联覆盖（明暗主题同值） |
| 动画（intensity/duration/easing/stagger） | ✅ | `--mt-skin-*` 通道，Guard 优先级结构性保证（T4/T5 实测） |
| 字体/间距/圆角/阴影 | ❌ | **v1.0 白名单明确禁止**（layout/spacing/typography/radius 在 FORBIDDEN_KEYS） |
| Component 形态 | ❌ | 无组件级 contract，业务组件自渲染 |
| Layout | ❌ | 禁止 + 无布局契约 |
| 换 Skin 是否改业务逻辑 | **否** | 白名单变量层隔离，12/12 验收含"拒绝后状态不变" |

**结论**：Skin Engine 的**引擎部分已达 E 级子集**（Loader/Registry/Apply/Guard 优先级），但它是"无产品的引擎"——没有 Settings 入口、没有持久化、没有与 data-theme 的联动策略。

**下一步最小整合方案（不在本轮实现）**：
1. SettingsView 加 skin 选择器（3 个内置 skin，读写 config 表 `ui.skin.active`）
2. 启动时按 config 恢复 active skin
3. 明确 data-theme（颜色）× skin（motion+accent）的正交关系并写进文档
4. 字体/间距/圆角类扩展 = schema v2 议题，**本轮不做**

---

## 七、核心链路真实度标记

```
用户 → 首页 → 选择工作模式 → 进入 Workspace → 启动软件 → 自动布局
     → 软件栏切换 → AI Assistant → 完成工作 → 退出 Workspace → 恢复普通工作台
```

| # | 环节 | 判定 | 证据/缺口 |
|---|------|:---:|----------|
| 1 | 首页 Dashboard | [REAL] | widget 布局/使用计数持久化 config 表（stores/widgets.ts:6-10），8 个真数据 widget |
| 2 | 选择工作模式 | [REAL] | work_modes 表 + config/modes/*.json + capture 模式创建（ModeView 完整 CRUD） |
| 3 | 进入 Workspace | [REAL] | scheduler 七步流水线（pipeline.rs:1-24）：校验→并发启动→等待就绪→排列窗口→开文件→载AI→更新状态；additive/exclusive/ask；45s 超时/可取消 |
| 4 | 启动相关软件 | [REAL] | 真实 CreateProcessW（launcher.rs:87），pid 登记；.lnk 走 ShellExecuteW 无 pid（已知边界） |
| 5 | 自动布局窗口 | [REAL] | 真实 Win32 SetWindowPos/EnumWindows（window.rs:11-20），布局持久化 layouts 表（"数据库是唯一真相"，scheduler/mod.rs:7） |
| 6 | 软件栏切换工作软件 | [PARTIAL] | 窗口激活能力存在（SetForegroundWindow+AttachThreadInput）；ModeBar UI 存在；但"工作软件焦点切换"的完整闭环（软件栏↔窗口激活联动）未见完整接线 |
| 7 | AI Assistant | [REAL] | 流式全链路：core 手写 HTTP → sidecar → ai/providers → NDJSON 流 → AI_STREAM_CHUNK 事件 → AiSidebar |
| 8 | 完成工作 | [MISSING] | 无"工作会话"概念：无总结、无产出归档、无会话时长统计进 usage |
| 9 | 退出 Workspace | [REAL] | exit_mode → kill_registered → 真实 TerminateProcess（status.rs），只关模式自己拉起的（R-01 红线） |
| 10 | 恢复普通工作台 | [PARTIAL] | **快照仅内存且只到模式级**：`last_snapshot: Option<(String, Vec<i64>)>`（runner.rs:142）——只有"回到上一个模式"，不含窗口布局、不持久化、重启即丢。用户退出后桌面恢复成什么样，没有保证 |

**链路总评**：进入侧（1→7）是全项目完成度最高的真实链路；退出侧（8/10）是核心体验的两处断点，且 #8 完全缺位。

---

## 八、数据流与绕过点

```
User Action
  ↓
UI（view / store）                    ← 绕过点 B/C 在此层
  ↓
service 层（9 个，统一 invokeCore）    ← 绕过点 A：ai 无 service
  ↓
invokeCore / eventBridge（单点封装）
  ↓
Tauri command ／ axum /api/v1/*       ← 绕过点 D：双通道同源靠约定
  ↓
core module service → *Repo → SQLite  （db/ 唯一写入者 ✅）
  ↓
System / sidecar / ai Provider        （sidecar 只拉不推 ✅）
  ↓
event_bus（tokio broadcast）
  ↓
pw://event 单通道 → eventBridge → store → UI 更新
```

| 绕过点 | 性质 | 判定 |
|--------|------|------|
| A. stores/ai.ts 直接 invoke×5，无 service 层 | 层级缺失（唯一领域） | 需收口 |
| B. TopBar.vue:25 / SettingsView.vue:66-101 组件直调 invokeCore | 越层（3 处） | 需收口 |
| C. 8 个视图绕过 store 直连 service（ModeView.vue:14 等） | **无缓存层的直连**——不是脏，是模式分裂 | 统一口径即可，不强改 |
| D. 双通道（command/HTTP）逻辑同源仅注释约定 | 漂移风险 | 小步试点共享 handler |
| 正当例外：widgets store 直写 config 表 | config 是白名单写入键（写串行化队列 L34-39） | 设计内，✅ |

**干净的部分**：sidecar 不碰 SQLite（410 拒绝）、凭据走系统 keyring 不落库、事件必经 core 中转、插件必经权限网关——四条红线全部结构性落实。

---

## 九、整合风险分级

### P0（不解决则架构/核心体验无法继续）
| 风险 | 说明 |
|------|------|
| **底座空转锁死方向** | Motion/Skin 已验收但零消费。若继续按现状堆页面，token 债（每页自造动画）和浮层债（三套×N 页）指数放大；之后任何 Skin/主题产品化都要回头逐页改 |
| **双巨石漂移** | api/mod.rs + commands.rs 各 1800+ 行，每加一个功能同步三处（command/HTTP/前端 service），靠纪律硬撑。整合阶段功能会继续加，先定同源机制再继续 |

### P1（本轮整合解决）
| 风险 | 说明 |
|------|------|
| 浮层三套自造 | 统一为全局组件 = Motion 接线的第一块真实阵地（overlay 优先级本就在 Conflict Guard 表里） |
| AI/service 收口 | contracts 常量表 + aiService + 3 处越层收编 |
| Workspace 退出恢复不完整 | 快照仅内存仅模式级（runner.rs:142）；升级为持久化窗口快照（涉 DB 迁移） |
| Skin 无入口 | Settings 选择器 + config 持久化——引擎现成，只差产品面 |
| 插件桥 postMessage `'*'` | com.example.music/index.js:18 通配目标源；core 宿主侧应校验来源帧（安全加固） |

### P2（后续处理）
- sidecar 契约 schema 校验（L-043 坑已证明需要）
- 索引 key 残留 6 处、硬编码 transition 4 处
- "完成工作"环节的产品设计（属新功能，需白宇决策，本轮不擅自加）

### 回退风险专项
| 项 | 风险 | 防线 |
|----|------|------|
| UI/动效回退 | 接线 Motion 时顺手改视觉 | 现成回归资产：verify_tech01 9/9 + verify_skin_engine 12/12 + perf_tech01_22（0 Long Task 基线），每阶段交付前后各跑一轮 |
| Workspace 回退 | 动 scheduler/window_manager | scheduler 单测 86 个 cargo test 在；动快照先加迁移不删旧列 |
| 数据丢失 | 任何 DB 变更 | 迁移只加不删；WAL；审计表独立 |
| 大规模重构诱惑 | 双巨石"顺手重写" | 路线图明确：试点 3 个模块共享 handler，不推倒 |

---

## 十、整合路线图（小步整合，不推倒重来）

> 原则：每个阶段独立可验收、可回退；先接线后收口；Skin 排在浮层统一之后（Skin 换组件的前提是组件先收敛）。

### IP1 浮层统一 + Motion 第一波接线
- **目标**：PwfToast / PwfModal / PwfDrawer 全局单例组件，动画全走 `--mt-*` token，注册 Conflict Guard `overlay` 优先级
- **修改**：ui/src/components/（新 3 组件）、ModeView/SoftwareView/SettingsView（替换三套自造）、motion-tokens.css（+overlay 档位）
- **涉及**：UI ✅ / DB ❌ / Core ❌ / Motion ✅ / Skin ❌
- **风险**：替换时漏改某页调用点 → 全文检索 toast/modal 收口清单
- **验收**：三套旧类名清零；Toast/Modal 开合走 runInterruptible；verify_tech01 9/9 不回退；S8 toast 场景复测通过

### IP2 UI Contract v1 + service 层收口
- **目标**：命令/事件名常量化；aiService 补齐；TopBar/Settings 越层收编
- **修改**：ui/src/api/contracts.ts（新）、aiService.ts（新）、stores/ai.ts（改走 service）、TopBar/SettingsView
- **涉及**：UI ✅ / DB ❌ / Core ❌ / Motion ❌ / Skin ❌
- **风险**：ai store 402 行重构引入流式回归 → 事件桥行为不动，只搬调用路径
- **验收**：`invoke(` 仍全局单点；`__pwMotion` 之外的裸命令字符串清零；AI 流式对话手工回归

### IP3 Motion 第二波接线（业务消费）
- **目标**：4 处硬编码 token 化；卡片/widget hover-lift 走 token；Cinema 接入 Workspace 进入/退出真实链路（订阅 MODE_CHANGED/MODE_APPLY_PROGRESS 驱动 startCinema）
- **修改**：base.css、LearningView、ProfileView、DashboardView/ModeView、motion/cinema 接线层
- **涉及**：UI ✅ / DB ❌ / Core ❌ / Motion ✅ / Skin ❌
- **风险**：Cinema 接真实布局后性能表现未知 → #22 的 S6b 场景（真实布局成本）在此阶段补测
- **验收**：`grep transition: 0.` 业务视图清零；进入模式时 Cinema 时序 trace 可见；perf 脚本 0 Long Task 保持

### IP4 Skin 产品化入口
- **目标**：SettingsView 加 skin 选择器（default/calm/lively）；active skin 持久化 config 表；启动时恢复
- **修改**：SettingsView.vue、stores/settings.ts、motion/skin.ts（+restore from config）、configService
- **涉及**：UI ✅ / DB ❌（config 表键值，无迁移）/ Core ❌ / Motion ❌ / Skin ✅
- **风险**：skin×data-theme 叠加的视觉组合未设计 → 先限定"skin 独立于主题"的正交文档
- **验收**：切换 skin 重启后保持；verify_skin_engine 12/12 不回退；切换时无整页 remount（T6 复测）

### IP5 Workspace 退出恢复（核心链路补全）
- **目标**：进入模式前快照当前桌面（可见窗口矩形+pid+z序）持久化；exit_mode 可选恢复
- **修改**：core/src/scheduler/（runner 快照升级+repository）、window_manager（枚举存取）、迁移 0009_workspace_snapshots.sql、ui/ModeView（退出确认 UI）
- **涉及**：UI ✅ / DB ✅ / Core ✅ / Motion ✅（退出 Cinema）/ Skin ❌
- **风险**：动 scheduler 核心链路——**先加表不动旧逻辑**，快照失败不阻塞进入模式（降级为现行为）
- **验收**：cargo test 全绿+新增快照用例；进入→退出→桌面窗口位置恢复实测；kill 红线（R-01 只关自己拉起的）回归

### IP6 core 双通道同源化（试点）
- **目标**：抽共享 handler 层，先试点 3 个重复度最高的模块（learning/profile/device）
- **修改**：core/src/api/（handler 抽取）、commands.rs（改调用 handler）、试点模块
- **涉及**：UI ❌ / DB ❌ / Core ✅ / Motion ❌ / Skin ❌
- **风险**：**本项目最大重构风险点**——严格限试点 3 模块，其余模块不动；HTTP envelope 与 command 返回值字节级兼容
- **验收**：cargo test 86/86+；HTTP 与 command 双通道同一用例返回一致（新增对拍测试）；前端零改动

### IP7 安全与契约加固
- **目标**：插件桥宿主侧校验来源帧；sidecar 契约最小 schema 校验（端口/端点/错误码）
- **修改**：ui/pluginService.ts / core/src/plugins（origin 校验）、core/src/sidecar（握手版本号）
- **涉及**：UI ✅ / DB ❌ / Core ✅ / Motion ❌ / Skin ❌
- **验收**：伪造 origin 的 postMessage 被拒并审计；sidecar 版本错配时启动即报错（不再是运行期神秘 404）

### IP8 「完成工作」设计输入（不实现）
- **目标**：产出工作会话（时长/软件/AI 对话/产出物）的产品设计稿，交白宇决策——**只设计不编码**
- **涉及**：纯文档
- **验收**：设计稿评审通过后另立任务单

---

## 十一、给白宇的三个决策点

1. **IP5 的"恢复普通工作台"产品口径**：退出后是"恢复进入前的窗口快照"还是"回到默认工作台+模式残留提示"？影响 DB 设计。
2. **AI Provider 选择入口**：三处分散（localStorage/模式 JSON/请求级）收拢到哪个？建议 Settings 页统一 + 模式 aiProfile 只做默认值。
3. **IP8「完成工作」**：这是链路里唯一 [MISSING] 的产品级缺口，是否立项由你定。

---

*本报告基于 2026-09-15 仓库实读。审计过程零代码修改。*
