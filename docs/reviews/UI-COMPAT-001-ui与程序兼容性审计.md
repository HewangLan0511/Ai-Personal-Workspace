# UI ↔ 程序 兼容性审计（UI-COMPAT-001）

> 日期：2026-09-16 · 执行：肉编器001号 · 性质：**只读审计，零代码修改**
> 范围：工作区两套 UI 资产 × Rust core 程序面
> 方法：三路并行探查（core 暴露面 / ui 前端调用面 / sidecar·插件·配置）+ 承重结论逐条复核

---

## 0. 一句话总判

**程序侧边界干净、121 条命令与真实前端 `ui/` 严丝合缝；但设计包的核心叙事「工作空间」在程序里根本不存在这个实体 —— 设计包 91/91 的绿，绿的是原型自己，不是程序。**

---

## 1. 审计对象澄清（先消除歧义）

工作区里有**两套 UI 资产**，性质完全不同，混谈会误判：

| 资产 | 路径 | 性质 | 是否接程序 |
|---|---|---|---|
| **真实前端** | `ui/`（Vue3 + TS + Pinia） | 产品代码，Tauri webview 真跑 | ✅ 接 core（invoke 约 135 处） |
| **设计包** | `personal-workspace-ui/` | 单文件原型 `index.html` + Token + 规范 + 13 套 e2e | ❌ **纯内存 mock**，自述「无数据库、无账号、无持久化」（`docs/ui-handoff/ui-overview.md:62`） |

本报告因此分两层结论：**① 真实前端 ↔ 程序（契约层）② 设计包 ↔ 程序（能力层）**。

---

## 2. 检查范围与硬证据

| 层 | 实读位置 | 关键事实 |
|---|---|---|
| 命令面 | `core/src/api/commands.rs` | **121 个** `#[tauri::command]`，全集中在这一个文件；注册点 `core/src/main.rs:127-261`（121 条逐条登记，无遗漏） |
| HTTP 面 | `core/src/api/mod.rs:34-214` | axum，`127.0.0.1:0` 随机端口写回 `runtime.http_port`；路由含 `/api/v1/*`、`/internal/db/query|exec`、`/internal/event/publish` |
| 事件 | `core/src/event_bus/events.rs:4-22` | 18 个事件常量；统一走单通道 `pw://event`（`event_bus/mod.rs:89`），调用点 `main.rs:109` |
| 配置 | `core/src/db/config.rs:68-151` | 33 个白名单键，**未登记键 `set` 直接 bail**（:41-43） |
| 数据 | `core/migrations/0001..0008` | 19 张表；`profile_basic(id,name,direction,interests,motto,updated_at)`（`0001_init.sql:88`） |
| 前端调用 | `ui/src/api/*.ts` + `client.ts` | 双通道：`invokeCore`（Tauri）/`request`（HTTP 兜底），浏览器层再有 localStorage |
| 设计包 | `personal-workspace-ui/docs/ui-handoff/*` | 18 条路由；`ui-08-report.md` 自述 13 套 e2e **91/91 全绿** |
| 门禁实测 | `tools/gate.py --stage 9` | **FAIL=0 · WARN=74 · PASS=28**（静态；**未加 `--build`，编译门禁跳过 —— 本轮未编译、未跑 cargo test，如实标注**） |

---

## 3. ★ P0 · 一等实体错位：「工作空间」在程序里不存在

设计包的全部核心叙事围绕 **Workspace（工作空间）**：我的工作空间列表、创建向导、运行界面、Mini Map、保存布局、从当前环境保存。

程序侧对应物是**分裂的三块**，且没有一块叫 workspace：

| 设计包假设 | 程序真实情况 | 判定 |
|---|---|---|
| Workspace 实体（含应用集合 + layout） | `work_modes` 表（工作**模式**）+ `layouts` 表 + `db_layouts_list/get/upsert` 三命令 | **PARTIAL** —— 模式≠空间，两个概念被强行共享一张表 |
| 前端 Workspace Runtime | `ui/src/workspace/store.ts:13-18` 自述硬边界：**零数据库 / 零 core / 不发 invoke 不发 HTTP / 不碰 Win32 / 窗口几何是 DOM 几何** | **MOCK** —— 刷新即重置 |
| `workspace_*` 命令 | core 121 命令中**零条** | **MISSING** |
| 运行界面（`#/run`） | 无独立页；仅 dev-only `/dev/workspace` 固件 | **MISSING** |

这不是漏做，是 PW-INTEGRATION 的**有意冻结**（HANDOFF §1：Workspace Resize 复用 `windows_place`，零 Core 新增命令）。
但结论必须说清：**设计包 UI-01/02/03 三页的"工作空间"，今天 100% 是前端内存态，保存/恢复/真实窗口编排均未落库。**

**设计包的 91/91 全绿，断言的是原型内部 DOM 行为，不触及 core 一次 —— 它不是兼容性证据。**（这正是本项目反复踩的"假通过"形态：脚本绿 ≠ 功能在。）

---

## 4. 路由兼容矩阵（设计包 18 条 × 真实前端 15 条）

| 设计包路由 | 前端路由 | 状态 |
|---|---|---|
| `#/home` | `/dashboard` | ✅ 语义一致（命名不同） |
| `#/apps` | `/software` | ✅ |
| `#/learn` `#/project` `#/life` `#/ai` `#/device` `#/profile` `#/plugins` `#/settings` | 同名 | ✅ |
| `#/models` | `/models` | ✅ TECH-05-C 已落地（不进主导航，与原型定位一致） |
| **`#/workspaces`** 我的工作空间 | 无（`/mode` 部分承载） | ❌ **缺** |
| **`#/run`** 运行沉浸态 | 无（`/layout` 为布局调试向） | ❌ **缺** |
| **`#/create`** 创建向导 | 无 | ❌ **缺** |
| `#/showcase` `#/guard` `#/skinlab` `#/spec` | 无 | ➖ 原型专有工具页，不进产品 IA，**合理，不算缺口** |

净缺口 = **3 个页面**，且恰好是产品最核心的三页。

---

## 5. 数据契约缺口

| 设计包要求 | 程序落点 | 判定 |
|---|---|---|
| 头像 | config 键 `profile.avatar`（`config.rs:122`，TECH-05-C） | ✅ REAL |
| 个性签名 | **无落点，前端挪用 `profile_basic.motto` 列**（`ProfileView.vue:141` 用 `basicForm.motto` 做 60 字计数） | ⚠️ **语义挪用**（座右铭 vs 签名），日后若要分家需改 schema |
| 标签 tags（数组） | **无落点**；`profile_basic.interests` 是 TEXT，可塞 JSON 但未结构化；P0-2 明确"禁止改数据库 schema"（`config.rs:117-121`） | ❌ MISSING |
| 首页组件区「待办」 | core 与前端**均无 todo 能力**（grep 零命中） | ❌ MISSING |
| 天气 / 正在播放 | `life_weather`、`life_media_now/control` | ✅ 能力在（但 `WeatherWidget.vue` 是纯静态 `--°C` 占位，**未接线**） |
| 组件区显隐 / 排序 / 布局锁定 | `ui.dashboard.widgets`(array) / `ui.dashboard.usage`(object) / `ui.dashboard.layout_locked`(bool) | ✅ 键已登记 |
| Mini Map（layout 数组） | `layouts` 表 + `db_layouts_*` | ✅ 数据在，但随 §3 实体问题一起悬空 |

---

## 6. 契约层：真实前端 ↔ 程序（这一层是健康的）

| 项 | 结论 |
|---|---|
| 命令名 | 121 条**全 snake_case**，无点号命名空间（`mode_apply`、`windows_place`）；前端按同名调用 → **对齐 ✅**。风险点：CRUD `modes_*` 与执行类 `mode_*` 单复数混用，靠人记 |
| 参数风格 | 全 snake_case，无任何 camelCase 转换（`commands.rs` 零 `rename_all`）；`PxRect` 是 `{x,y,w,h}` 非 `{width,height}` → 前端按此写 ✅ |
| 事件 | 单通道 `pw://event` + `envelope.event` 二次分发；前端 `eventBridge.ts:74` 同构 ✅。**18 个事件里前端只消费 6 个**，其余 12 个无消费者（已建成未接线，非缺陷） |
| 双通道 | ⚠️ **不等价**：`modeService.ts:179-181` invoke 传 `{modeId, policy}`，HTTP 兜底 `/api/v1/modes/{id}/apply` **不传 policy** |
| 返回字段 | ⚠️ **风格双轨**：`layoutService` `took_ms`/`degraded_monitor`(snake) vs `modeService` `tookMs`/`modeId`(camel)；`deviceService` 同文件内混用。**无 shim 无运行时校验**，core 任一侧改名 → 前端静默拿到 `undefined` |
| V7 红线 | 未突破：全仓无 `/internal/db/*` 前端直连、无直连 SQLite ✅ |
| 降级掩盖 | ⚠️ `configService`/`appsService` 的 localStorage 兜底**不回写 core**（`configService` 头部自述），浏览器态与桌面态数据会分叉；且兜底静默吞错 → "前端绿"可能只是降级层生效 |

---

## 7. 风险分级

| 级 | 风险 | 依据 | 现有回归资产 |
|---|---|---|---|
| **P0** | 工作空间无实体，核心三页只能停在内存态 | §3 | `verify_stage*.py`、`tools/verify_contracts.py` |
| **P0** | 设计包 91/91 被误读为"对接已通" | §3 末 | 13 套 e2e（仅覆盖原型内 DOM） |
| **P1** | 3 个核心页面无路由 | §4 | `verify_stage1.py --routes-url`（9 条路由渲染） |
| **P1** | tags 无落点 / signature 语义挪用 motto | §5 | `config.rs` 白名单测试锁 |
| **P1** | 双通道参数不等价 + 返回字段风格双轨 | §6 | 无（建议补契约测试） |
| **P2** | 12 个事件无消费者；`WeatherWidget` 占位未接线 | §5/§6 | — |
| **P2** | 门禁 74 条 WARN 主要来自 `personal-workspace-ui/verify_*.py` 的 print 残留 | §2 实测 | `gate.py` |
| **P2** | 双轨维护成本：原型与真实前端各自演进 | §1 | — |

---

## 8. 需要白宇拍板的 4 个决策点

1. **工作空间要不要升格为 core 一等实体？** 选 A：新增 workspace 表 + 命令 + migration 0009（真持久化，代价是动 schema）；选 B：维持冻结口径（work_modes + layouts + `workspace.snapshot.last` config 快照，零 migration，代价是能力天花板明显）。
2. **设计包 `index.html` 的定位**：继续做"视觉事实源"独立演进，还是并进 `ui/` 后停止维护？——两套 UI 双轨是长期成本。
3. **档案 tags 落点**：新 config 键（不改 schema，符合 P0-2）还是复用 `interests` TEXT 列塞 JSON？signature 是否正式承认"= motto"？
4. **74 条 WARN 要不要清**：清 `personal-workspace-ui/verify_*.py` 的 print，或在 `gate.py` 加豁免。

---

## 9. 声明

- 本轮**零代码修改**，只产出本文件与 `.workbuddy/gate_out*.txt`（门禁输出，可删）。
- 门禁仅跑静态（`--stage 9`，FAIL=0/WARN=74/PASS=28）；**未跑 `--build`、未跑 cargo test、未跑任何 verify 脚本** —— 本轮未做编译与端到端验证，如实标注，不冒充已验。
