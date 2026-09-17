# TECH-04 · 核心能力接入规划与第一阶段落地

> 日期：2026-09-15 · 状态：**已交付，验收 44/44**
> 验收工具：`tools/verify_tech04.py`（tsc 编译被测模块 → Node 直跑 T1/T2/T3 + 静态全局红线 T2/T3/T4）
> 回归：门禁 `--stage 9 --build` FAIL=0 WARN=0 PASS=30 · core `cargo test` 86/86 · 七套既有验收脚本全绿
> 前置：TECH-01（Motion）/ TECH-02（Workspace Runtime）/ TECH-03-A（Model Registry）/ TECH-03-B（接线准备）

---

## 零、一句话

前几轮造完了 Runtime 设施，这一轮**把它们接进真实产品**：让"模型管理中心 → Model Registry → AI 助手"
成为一条**真实数据链**（不再有"显示模型 ≠ 实际调用模型"），把 workspace 快照挂进门面（**只准备接口，不动窗口**），
并把「工作完成」的概念做成一份**纯设计**（不写一行 UI）。

三阶段边界（全部在代码里可断言，不只在文档里承诺）：

| 阶段 | 做什么 | 硬边界 |
|------|--------|--------|
| 一 · AI 模型真实闭环 | canonical 落到 L1，AI 请求与顶栏显示同源 | 不破坏镜像兼容 · 保留迁移路径 · 更新契约文档 |
| 二 · Snapshot 接入准备 | 快照挂进 `workspaceRuntime` 门面，UI 可读三视图 | **禁止：移动窗口 / 杀进程 / 改外部状态** |
| 三 · 工作完成概念 | 状态模型（开始→进行→暂停→完成→归档） | **只设计，不实现；不新增 UI** |

全局禁止项（后文 §四 逐条机器核验）：**不大规模重构 · 不新增 UI 页面 · 不新增动画体系**。

---

## 一、架构变化报告

### 1.1 接线前：AI 数据链的断点

梳理「模型管理页面 → Model Registry → AI 请求层 → AI 助手」四段，接线前的真实链路是**断的**：

```
模型管理页 (SettingsView)
    │  写 localStorage 键 ui.ai.provider / ui.ai.model
    ▼
模型镜像键（仅 UI 自用，无权威）
    ✗ 断点①：Model Registry 从未参与，"当前模型"没有唯一事实来源
    ▼
stores/ai.ts（自己维护一份 providerId/model）
    │  send() 用它组请求
    ▼
AI 请求层 core（ai_info / ai_list_models）—— 它按**自己**的规则选模型
    ✗ 断点②：顶栏显示的模型 ≠ core 实际调用的模型
    ✗ 断点③：canonical L1 键（ai.provider.current/ai.model.current）**从未在 core 登记**，
              只活在过渡镜像键里，没有正式落点
```

三个断点的后果是同一个症状：**用户以为在用 A，实际发出去的是 B**。

### 1.2 接线后：canonical 成为唯一事实来源

```
┌─────────────────────────── UI 层 ────────────────────────────┐
│                                                              │
│  模型管理页 / 顶栏选择器                                      │
│        │  setProvider() / setModel()                         │
│        ▼                                                     │
│  stores/ai.ts  ── syncCanonicalNow() ──┐                     │
│        ▲                               │                     │
│        │ alignWithCanonical()（启动）   ▼                     │
│        │ bindCanonical()（运行期订阅） ai/model/bridge.ts     │
│        │                               │  （薄接线：只转发）  │
│        └──────── 投影 ───────────────  │                     │
│                                        ▼                     │
│                         ai/model/session.ts（纯逻辑）        │
│                                        │                     │
│                         ai/model/selection.ts（纯决策·零 IO） │
│                                        │                     │
│                         ai/model/registry.ts（唯一写口）      │
│                                        │  setCanonical()      │
│                                        ▼                     │
│                            ★ canonical L1 落点 ★             │
│                      ai.provider.current / ai.model.current  │
│                                        │                     │
│  ───────────────────────────────────── ┼ ───────────────────  │
│                                        ▼                     │
│  顶栏「当前模型」（useCurrentModel）  =  请求依据（send()）    │
│                    ↑ 同一 registry 单例，构造上不可能分叉 ↑   │
└──────────────────────────────────────────────────────────────┘
                              │ invoke
                              ▼
              core：get_config / put_config（既有命令，零新增）
                      镜像键 ui.ai.provider / ui.ai.model 继续写（老版本可读）
```

### 1.3 三条硬边界怎么落的

**(a) 不破坏镜像兼容。** `ui.ai.provider` / `ui.ai.model` 这两个镜像键**继续写、不删旧值**
（`core/src/db/config.rs:96-97` 保留在 `KEYS`，且 `default_for` 仍给空串）。
老版本客户端回滚后照常能读到值。canonical 只是**新增权威**，不是**替换**。

**(b) 保留迁移路径。** 老数据只写过镜像键 ⇒ `source='mirror'` ⇒ `needsMigration()` 为真 ⇒
启动时 `resolveAtBoot()` 把镜像值**前向拷贝**到 L1（`mirror → core`），旧值原地保留。
幂等：第二次调用是 no-op。**只前向拷贝，绝不删除。**

**(c) 更新契约文档。** `docs/agent-dev/03-数据契约与接口规范.md` §3.1.1 补录两个 L1 键，
版本号 `v10 → v12`，并加一行 v12 变更说明。

### 1.4 core 侧登记：三处齐改，否则键等同不存在

L1 键要在 core 里"存在"，必须在 `core/src/db/config.rs` **三处同时**出现——缺一处该键就是死的：

| 位置 | 行 | 内容 |
|------|----|------|
| `KEYS` 白名单 | `106-107` | `"ai.provider.current"` / `"ai.model.current"` |
| `expected_type` | `166` | 两者 → `"string"` |
| `default_for` | `224-225` | 两者 → `serde_json::json!("")` |

两个既有单测 `every_registered_key_has_an_explicit_type` / `_explicit_default` 把这条锁死。
`CONTRACT_SCHEMA_VERSION` `11 → 12`（`migrations.rs:28`）——**未新增迁移**，因为本轮只登记键、无 schema 变化。

### 1.5 分层：决策与 IO 分离

新增两个纯模块，把"决策"从"落盘"里剥出来——这样它能在 Node 里被直接断言，也让测试不依赖 Tauri：

| 模块 | 行数 | 职责 | 依赖 |
|------|------|------|------|
| `ai/model/selection.ts` | 157 | **纯决策·零 IO**：`resolveSelection` 五种情形 + `needsMigration` | 仅类型 |
| `ai/model/session.ts` | 221 | **纯逻辑**：`createModelSession(registry)` 注入 registry，不自己 new | registry 接口 |
| `ai/model/bridge.ts` | 95 | **薄接线**：持有真实 registry 单例，只做转发 | 上两者 |
| `stores/ai.ts` | 512 | 会话投影：`alignWithCanonical` / `bindCanonical` / `syncCanonicalNow` / `requestTarget` | bridge |
| `composables/useCurrentModel.ts` | 116 | 顶栏只读显示，改用**共享单例**（原来自建一份） | bridge |
| `workspace/runtime.ts` | 549 | 门面，新增 `snapshot` 命名空间 + `getRecoveryStatus()` | snapshot |

**关键点：`stores/ai.ts` 与 `useCurrentModel.ts` 现在指向同一个 registry 单例。**
"顶栏显示"和"实际发送"读的是同一个 `current()`，因此分叉在**构造上不可能**，而不是靠"记得同步"。

### 1.6 Phase 2：快照挂进门面（只准备，不执行）

`workspaceRuntime` 新增 `snapshot` 命名空间，UI 可读三视图（**全部只读、零副作用**）：

| 视图 | 字段 | 来源 |
|------|------|------|
| 一、当前工作空间状态 | `workspaceId` / `name` / `mode` / `appCount` / `runningCount` / `waitingCount` | 内存 store 当前值 |
| 二、最近布局状态 | `type` / `snapshotId` / `entryCount` / `snapshotCount` / `persistedSnapshotId` / `persistedValid` | DOM 布局元信息 + （若注入）持久快照校验 |
| 三、恢复可用性 | `available` / **`executable:false`** / `blockers` / `reason` / `guardrails` / `runIdMatch` / `planStepCount` | 上两者 + 计划步数 |

四条红线以 `guardrails` 形式恒为 `false`：`killsProcesses` / `launchesApps` / `writesDatabase` / `touchesUnmanagedWindows`。
**`executable` 恒为 `false`——本轮没有执行入口，`snapshot` 命名空间里只有
`capture/restore/validate/status/isProbeWired/setProbe/setPersistedReader/setCurrentRunId`，
没有任何"真的去动窗口"的方法。**

`capture()` 在未注入探针时恒 `dryRun`；`restore()` 只**算计划**（返回 `steps` 数组），不执行。
`snapshot.ts` 本身**零 import**（不碰 core、不碰 Pinia），门面通过模块级注入点
（`injectedProbe` / `persistedReader` / `currentRunId`）把外部能力喂进去。

### 1.7 Phase 3：工作完成概念（纯设计）

产出 `docs/tech/workspace-work-lifecycle-design.md`（183 行，**零代码**）：
五态模型 `idle → starting → running → paused → completed → archived`（转换 T1–T10）、
7 条不变量、四条红线（不杀进程 / 不移窗口 / 不改外部软件 / 不外泄）、
学习 / 项目 / 日常任务三种模式的差异、与既有 Runtime 的映射。**未新增任何 UI。**

---

## 二、数据流说明

### 2.1 启动路径（含老数据迁移）

```
boot
 └─ stores/ai.ts init()
     ├─ loadProviders()                        ← core ai_info / ai_list_models
     ├─ alignWithCanonical()
     │   └─ bridge.resolveAtBoot({providerId, model})
     │       └─ session.resolveAtBoot()
     │           └─ selection.resolveSelection(canonical, selection)   ← 纯函数，5 种情形
     │               ├─ 都空          → {source:'none'}               不写
     │               ├─ canonical空+界面有 → 采用界面选择，**前向写 L1**
     │               ├─ canonical有+界面空 → 以 canonical 为准，界面跟随
     │               ├─ 都有且相同     → 无操作（不产生多余写入）
     │               └─ 都有且不同     → **收敛到 canonical**（落点是唯一事实来源）
     │           └─ registry.setCanonical(...)  （唯一写口，走 core put_config）
     ├─ bindCanonical()
     │   └─ subscribeCanonical(fn)             ← 运行期 canonical 变，会话立即跟随
     └─ （镜像键 ui.ai.provider / ui.ai.model 同时被写，老版本兼容）
```

### 2.2 用户改选择路径

```
用户点选 provider/model
 └─ store.setProvider() / setModel()
     ├─ 更新 store 自身状态（会话投影）
     ├─ void syncCanonicalNow()      → bridge.syncSelection() → registry.setCanonical() → L1
     └─ 写镜像键（ui.ai.*）
         ↓
     顶栏（useCurrentModel 读共享单例）与 send()（读 requestTarget()）同时变
```

### 2.3 读路径（显示 == 调用）

| 读取方 | 入口 | 读到的对象 |
|--------|------|-----------|
| 顶栏「当前模型」 | `useCurrentModel` → `getSharedRegistry().current()` | 共享单例 |
| AI 请求依据 | `stores/ai.ts` getter `requestTarget()` → `{provider, model, apiBase}` | 同一共享单例 |

`verify_tech04.py` 的 `t1-j` **逐字段**断言两者相等；`t1-l` 是对照组（不登记模型时顶栏确实报"已失效"），
证明 `t1-k` 有区分度，不是"反正都通过"。

### 2.4 快照读路径（Phase 2）

```
UI 读 getRecoveryStatus()
 ├─ getSnapshot() / getAppsSnapshot() / getLayoutMeta() / listLayoutSnapshots()   ← 内存，只读
 ├─ persistedReader?.()   （未注入 → null）
 ├─ validateSnapshot(persisted)        ← 校验 v1 契约
 └─ restoreSnapshot(persisted, {currentRunId})   ← **只算计划**，返回 steps + guardrails(false)
     └─ deepFreeze(视图) 返回
```

---

## 三、风险列表

| # | 风险 | 等级 | 现状与缓解 |
|---|------|------|-----------|
| R1 | **canonical 与镜像键双写，可能写出不一致** | 中 | 双写在同一次调用内完成；`t2-k` 断言改选择后两侧同时更新；镜像键不再是权威，读侧只认 L1 |
| R2 | **老版本回滚后读不到 canonical** | 低 | 镜像键不删、继续写（`core/src/db/config.rs:96-97`）；`t2-e` 断言旧值保留 |
| R3 | **迁移是破坏性的（删旧值）** | 低 | 迁移**只前向拷贝**，`t2-e`/`t2-f` 断言旧值保留 + 幂等（第二次 no-op） |
| R4 | **迁移"反正都成功"，没区分度** | 低 | `t2-g` 对照组：L1 **未**登记时迁移确实失败（`source` 仍 `mirror`），证明 `t2-d` 的绿是有意义的 |
| R5 | **快照接口将来被误当成"执行入口"** | 中 | `executable` 恒 `false` + 四条 `guardrails` 恒 `false` + 命名空间内**无执行方法**（`T3c` 静态核验） |
| R6 | **挂门面触发 `T1c` 消费者白名单边界扩张** | 低 | `snapshot` 是**内部模块**，唯一 import `runtime.ts` 的仍是 `DevWorkspaceHarness.vue`；白名单**未改动**（`T3e` 断言） |
| R7 | **`CONTRACT_SCHEMA_VERSION` 11→12 影响旧验收脚本** | 低 | 只有 `verify_stage9.py` 断言版本号，已由 `== 11` 放宽为 `>= 11`；其余脚本断言各自阶段的版本，不受影响 |
| R8 | **AI store 与 `useCurrentModel` 各持 registry 导致再分叉** | 低 | 两者改用 `bridge.getSharedRegistry()` 同一单例；`t1-n` 断言只读面与订阅读同一落点 |
| R9 | **本轮改动被误认为"大规模重构"** | 低 | 新增 2 个纯模块 + 薄桥，改造 4 个既有文件；`T4` 静态核验路由基线 15、视图基线 15、`@keyframes` 仅 `ai-blink` 一处 |
| R10 | **`restore()` 计划步数依赖注入的 `runId`** | 低 | 未注入 `runId` 时 `runIdMatch=null`（未知），**不误判为失效**；`blockers` 显式列出 `runid-mismatch` |

---

## 四、回归测试

### 4.1 本轮验收：`tools/verify_tech04.py` 44/44 PASS

| 组 | 覆盖 | 代表用例 |
|----|------|---------|
| T1 · 链路（Node 直跑真实模块） | `resolveSelection` 五情形 / 首写 / **显示==调用** / 运行期订阅 | `t1-a`~`t1-n` |
| T2 · 迁移与静态（+ 对照组） | 镜像→L1 迁移 / 旧值保留 / 幂等 / **对照组：L1 未登记则迁移失败** | `t2-c`~`t2-l` |
| T3 · 快照门面 | 命名空间 + 4 方法 / 三视图 / **零执行入口** / `guardrails` 恒 false / `snapshot.ts` 零 import | T3 组 |
| T4 · 全局红线 | 路由基线 15 / 视图基线 15 / `@keyframes` 仅 `ai-blink` / AI 链锚点完好 | T4 组 |

被测模块经 `tsc` 编译后由 Node 直接执行（`selection.ts` / `session.ts` 零 `@/` 依赖），
`FAKE_PORTS_JS` fixture 可复现"L1 未登记"的历史行为，供对照组使用。

### 4.2 全量回归（本轮实测）

| 检查 | 命令 | 结果 |
|------|------|------|
| 门禁（含编译） | `gate.py --stage 9 --build` | **FAIL=0 WARN=0 PASS=30** |
| core 单测 | `cargo test`（core/） | **86 passed / 0 failed** |
| 技术验收 | `verify_tech04.py` | **44/44** |
| 技术验收 | `verify_tech03b.py` | **81/81** |
| 模型注册表 | `verify_model_registry.py` | **32/32** |
| 契约 | `verify_contracts.py` | **6/6** |
| 动效 | `verify_tech01.py` | **9/9** |
| 皮肤引擎 | `verify_skin_engine.py` | **12/12** |
| 工作空间 | `verify_tech02_workspace.py` | **11/11** |
| 性能基线 | `perf_tech01_22.py` | 12 场景 longtask **全 0** |

> 注：`verify_tech02_workspace.py` 首跑报 `ui/dist 早于 ui/src`，是**它在 vite build 进行中并发启动**导致的
> 时序问题，不是产品缺陷——`npm run build` 完成后重跑即 11/11。该脚本"拒绝在过期产物上验收"的行为是**有意的**
> （与既有纪律一致：验收必须跑在最终产物上）。

### 4.3 上游脚本的边界翻转（显式记账）

canonical 落到 L1 后，两个**上游阶段**的断言前提被本轮**有意改变**，均属"边界扩张"而非"静默放宽"：

| 脚本 | 判据 | 改动 |
|------|------|------|
| `verify_model_registry.py` | `T6d` | 由"L1 未登记"翻转为"**已在三处登记 + 镜像键保留 + 端口只调既有命令**" |
| `verify_model_registry.py` | `T6b` | `WIRING_ALLOWED` 加入 `stores/ai.ts`（白名单内仍**不得**出现 registry 写方法） |
| `verify_tech03b.py` | `T5b` | 由"L1 未登记"翻转为"已在三处登记 + 镜像键保留" |
| `verify_stage9.py` | 预检 | `CONTRACT_SCHEMA_VERSION == 11` → `>= 11`（意图：确认迁移 0008 已应用） |

---

## 五、下一阶段建议（非本轮遗留项）

1. **设置页接管 canonical 写口**，与顶栏只读显示形成完整闭环——本轮已把写路径打通，但 UI 仍可只显示。
2. **core 实现窗口探针**，`capture()` 转 `dryRun:false`——那时才考虑放开 `restore()` 执行侧。
3. **`restore()` 执行侧放开时**，`executable` 与四条 `guardrails` 才允许从 `false` 变为受控开关。
4. **Phase 3 状态模型的 UI 落地**另行立项——本轮刻意只做设计，未新增任何界面。
