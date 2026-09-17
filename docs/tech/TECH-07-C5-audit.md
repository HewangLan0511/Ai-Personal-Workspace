# TECH-07-C5 只读审计报告

> 日期：2026-09-16 · 性质：**只读审计**（未改任何代码 / 未新增 command / 未新增 migration / 未改 UI）
> 输入基线：C4 25/25 PASS + 1 Deferred · C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 · 契约套件全绿
> 配套判据台账：`docs/tech/TECH-07-C5-checklist.md`
>
> **前置结论（最重要）**：`TECH-07-C5` 的目标在现有文档中**没有定义**。
> 检索过 `docs/`（全部）、`HANDOFF.md`、`LEDGER.md`、`docs/ui/UI-FUSION-STANDARD.md`、
> TECH-07-B 两份设计文档 —— 出现的 "C5" 均是其他文档（PW-INTEGRATION-002/003）里
> 无关的编号，TECH-07-C 系列只有 C1(Observe 骨架) / C2(Observe 接线) / C3(Actuate 摆位) /
> C4(Snapshot 持久化恢复) 四个已定义阶段。
> ⇒ **C5 目标需要拍板后才能冻结 checklist 编号语义**；本审计把全部候选工作面摸清并列出，
> 供拍板选择。

---

## 一、C4 当前真实状态（审计项 1）

### 1.1 snapshot runtime adapter（`ui/src/workspace/runtime/snapshot.ts`，C4 新增）

| 项 | 状态 | 证据 |
|---|---|---|
| capture 链 | ✅ 完整 | `takeFacts()`（新鲜事实，非 lastFacts）→ 模式判定 → `buildSource()`（core 自报 pid@started_at）→ `buildEvidence()`（slots ∪ running → appId → apps_list.path）→ `buildProbe()` → 冻结 `capture()`（内部 validate）→ `putCore` 原子写 |
| read/status | ✅ | `readSnapshot()`：none（默认 `{}`）/ invalid（validate 拒绝，保留原值）/ valid 三态 |
| restore 链 | ✅ 两层 | Layer 1 = 冻结 `restore()` plan 作意图 + **执行前逐窗重校验**（存在/归属/pid 未变）；Layer 2 = exePath 在**当前已归属窗口**内找唯一候选 |
| fail-closed | ✅ | facts 拉取失败 / `connectivity==='offline'` ⇒ 立即返回 offline，零 actuation；损坏快照 ⇒ invalid，**不改写不删除原值** |
| 超时 | ✅ | `restoreSnapshot({timeoutMs})` 默认 10s，逐窗查 deadline，超时 `skip(timeout)` |
| 诚实降级 | ✅ | `foregroundHwnd=null`（不猜前台）、`zIndex=枚举序+1`（近似 Z 序，注释+UI 双声明）、最小化窗口 skip |

### 1.2 config 持久化链

```
captureSnapshot() ──putCore('workspace.snapshot.last', snap)──> Tauri put_config / HTTP PUT /api/v1/config/{key}
                                                                     │（同源验证构建下经 C4 代理 PUT 转发）
                     core ConfigService::set() ──> KEYS 白名单 + expected_type('object') 校验 ──> SQLite config 表
```

- UI 侧 `getCore/putCore`（`ui/src/api/configService.ts`）：**失败即抛，无 localStorage 降级**（C4-D2）。
- core 侧 `db/config.rs`：三处登记齐备（KEYS / `"object"` / `json!({})`），`cargo test config` 6/6（含两个"必须齐登记"锁死测试）。
- 跨进程证据已实证：SQLite 有行 → 杀 core → 新进程新端口读回同 snapshotId、runId 已变（C4 B 段）。

### 1.3 restore 执行链（谁在真正摆窗）

```
restoreSnapshot() ──safeRect()──> placeWindow(intent, wa)（C3 既有能力，actions.ts）
                                     ├─ 段位=actuate 校验
                                     ├─ hwnd ∈ lastFacts && belongsToMode && manageable（否则 unbound）
                                     └─ layoutApi.place() ──> Tauri 'windows_place' / HTTP POST /api/v1/windows/{hwnd}
```

- C4 与 C3 共用**同一条**摆位链路，无第二实现（S1/S2 静态项锁死）。
- `safeRect()`（C4 修正后）：装得下 ⇒ 整窗进工作区；装不下 ⇒ 退化为"至少 MIN_VISIBLE 像素可见"。只动位置不改尺寸。

### 1.4 offline / degraded 行为

- `facts.snapshot()` 聚合 7 项 core 事实（6 项算 core 连接证据 + apps_list 不算），失败数 0=connected / 全败=offline / 部分=degraded。
- **offline ⇒ `lastFacts` 缓存作废**（C3 收尾审计加的 fail-closed），`placeWindow` 无事实不下发，snapshot capture/restore 同样 fail-closed（C4 G 段实测 `已恢复 0 … 跳过 1：offline`）。
- degraded 时 UI 走 `run-degraded` chip 如实展示失败明细。

**结论：C4 状态健康，无已知运行时缺陷，可作为 C5 地基。**

---

## 二、Workspace Runtime Adapter 边界（审计项 2）

### 2.1 facts 输入（`runtime/facts.ts`）

7 项读取：`modes_current` / `mode_progress` / `windows_list` / `layouts_list` / `monitors_list` / `modes_list` / `apps_list`（+ `apps_running` 静默降级）。core DTO 不出 adapter（projection.ts 投影）。**零新命令，全部既有已验收命令。**

### 2.2 actions 输出（`runtime/actions.ts`）

| 动作 | 命令 | 段位门 |
|---|---|---|
| applyMode | `mode_apply` | actuate |
| cancelApply | `mode_cancel` | 无门（非窗口控制） |
| exitMode | `mode_exit` | ⚠️ 已在 adapter 导出，但 core 侧是**硬杀语义**（07-A R-1），Run 页未暴露 |
| placeWindow | `windows_place` | actuate + 段位 + 归属 + manageable + 工作区钳制 |

### 2.3 boundary 白名单（`runtime/boundary.ts`）

- ALLOWED（13）：`modes_list, modes_current, mode_progress, layouts_list, monitors_list, windows_list, apps_list, apps_running, ping, mode_apply, mode_cancel, mode_exit, windows_place`
- FORBIDDEN（9）：`windows_activate, windows_find, windows_rect, layout_apply, mode_restore, modes_capture_current, apps_launch, windows_close, apps_terminate`
- 段位：`ADAPTER_MODE = 'actuate'`（C3 起）。
- ⚠️ 文档债：`runtime/index.ts:30` 注释仍写"段位（C1/C2 固定 observe）"，与 `ADAPTER_MODE='actuate'` 不符（纯注释，不影响行为；登记 C5-08，不顺手改）。

### 2.4 是否存在绕过 adapter 直连 core 的路径

**Run 页面 / workspace 域：零绕过** —— `RunView.vue` 无任何 `@/api` import（C2 A1a 静态项持续锁定）；workspace 域内只有 `runtime/` 子目录可 import `@/api`。

**全局既有页面（阶段 2~4 成果，不在 workspace 红线内）存在直连，登记在案：**

| 位置 | 直连调用 | 与 adapter 禁令的关系 |
|---|---|---|
| `views/LayoutView.vue:70` | `layoutApi.apply()`（=`layout_apply`） | 该命令在 adapter FORBIDDEN —— 但这是布局页的**既有合法功能**，说明 FORBIDDEN 是"adapter 层"的边界，不是全 UI 的边界 |
| `components/ModeBar.vue:59,68` | `modeApi.exit()`、`modeApi.restore()`（=`mode_restore`） | ⚠️ `mode_restore`（把窗口恢复到上次模式布局）与 C4 的 snapshot restore **概念相邻**，且 ModeBar 已在实际调用 —— C5 若做恢复语义收敛，这里是绕不开的撞点 |
| `views/ModeView.vue:93` | `modeApi.exit()` | 同上，模式管理页既有功能 |

⇒ **结论**：workspace 域边界完好；但"恢复"这个语义当前在 UI 里有**两条并存链路**（core 阶段4 的 `mode_restore` vs C4 的 snapshot restore），C5 必须拍板二者关系（见待拍板 #3）。

---

## 三、Core 当前窗口能力（审计项 3）

来源：`core/src/main.rs` 的 `generate_handler!`（Tauri 命令注册）+ `core/src/api/mod.rs`（HTTP 路由）+ `window_manager/` 模块。

| 能力 | Tauri 命令 | HTTP 路由 | core 支持 | adapter 白名单 | 备注 |
|---|---|---|---|---|---|
| windows_list | `windows_list` | GET `/api/v1/windows` | ✅ | ✅ 读 | 返回 hwnd/title/class_name/pid/visible/minimized/maximized/rect/area；**无 exe 路径** |
| windows_place | `windows_place` | GET+POST `/api/v1/windows/{hwnd}` | ✅ | ✅ 写 | 支持 `alwaysOnTop`（⚠️ PW-INTEGRATION-003 C6：该形参实际无效，偏差已登记）与 `maximized` |
| windows_activate | `windows_activate` | POST `/api/v1/windows/{hwnd}/activate` | ✅ **core 有能力** | ❌ FORBIDDEN | C4 逐条 skip focus-window；若 C5 要焦点恢复只需白名单化 + 判据，**无需 core 改动** |
| windows_close | — | — | ❌ **core 无此能力** | ❌ FORBIDDEN | window_manager 无 close 实现；要做须新增命令（违反"不新增 command"的当前约束，需拍板） |
| windows_find / windows_rect | `windows_find` / `windows_rect` | GET `/api/v1/windows/{hwnd}` | ✅（find 未在路由） | ❌ FORBIDDEN | rect 经 windows_list 已可得 |
| mode_apply | `mode_apply` | POST `/api/v1/modes/{id}/apply` | ✅ | ✅ | 七步流水线：validate→launch→wait_ready→arrange→open_files→load_ai→done |
| mode_restore | `mode_restore` | POST `/api/v1/mode/restore` | ✅ | ❌ FORBIDDEN | **ModeBar 在直连调用**（见 §二.2.4）——语义与 snapshot restore 相邻 |
| mode_exit | `mode_exit` | POST `/api/v1/mode/exit` | ✅ | ✅（Run 页未暴露） | 硬杀语义 |
| apps_running | `apps_running` | GET `/api/v1/apps/running` | ✅ | ✅ 读 | `appId→pid` **一 app 一 pid**（这是 C4-E 不可构造的根因之一） |
| apps_launch | `apps_launch` | POST `/api/v1/apps/{id}/launch` | ✅ | ❌ FORBIDDEN | 已验收；adapter 禁用 |
| 进程终止 | — | POST `/api/v1/device/processes/kill` | ✅（设备页功能） | ❌ FORBIDDEN | `app_manager::terminate(pid)`，**进程级**而非窗口级；拒绝杀 core 自身 |
| health/ping | `ping` | GET `/health` | ✅（C4 扩展） | ✅ 读 | `{service, pid, started_at}` —— runId 事实源 |
| layout_apply | `layout_apply` | POST `/api/v1/layouts/{name}/apply` | ✅ | ❌ FORBIDDEN | LayoutView 在直连调用 |

**是否需要 core 改动的判断**：
- 若 C5 = 焦点恢复 / 窗口激活类 ⇒ **不需要**（`windows_activate` 已在，白名单化即可）。
- 若 C5 = 关闭窗口类 ⇒ **需要新增**（core 无 windows_close；进程终止已有但语义不同）。
- 若 C5 = 一 app 多实例归属 ⇒ **需要改归属登记**（slots/apps_running 一 app 一 pid 的结构假设）。
- 若 C5 = 多显示器 ⇒ **需要改**（`placeWindow`/`safeRect`/facts 投影均主显示器硬编码）。

---

## 四、Snapshot v1/v2 边界（审计项 4）

- **schema**（`docs/contracts/workspace-snapshot.v1.schema.json`）：顶层 8 字段
  `schemaVersion, snapshotId, takenAt, trigger, source, monitors, desktop, workspace`，
  `additionalProperties: false`；`trigger` 仅 `enter_mode`。
- **v2 禁区是机器可判的**：schema 内 `x-pw-v2-forbidden` 明确列出 10 个禁用字段名
  （`history, snapshots, snapshotHistory, previousSnapshots, multiSnapshot, hwndIdentity,
  windowIdentityMap, restoreCount, restoreLog, keepAliveRegistry`）——任何 v2 想法
  （快照历史/多快照/hwnd 身份映射）都被契约挡住，且 `verify_contracts.py` + `validate()` 双重校验。
- **冻结 `restore()` guardrails**（`ui/src/workspace/snapshot.ts`）：四项护栏是**可断言的数据**
  而非注释承诺：`killsProcesses:false / launchesApps:false / writesDatabase:false /
  touchesUnmanagedWindows:false`；plan 恒 `executable:false`（只算不做）。
- **跨重启恢复三原则复核（基于 C4 验收实证）**：
  1. **不猜测身份** ✅ —— 同运行期 hwnd+pid 需实时 facts 命中；跨重启只认 exePath，且 exePath 只能来自登记链（slots ∪ running → appId → apps_list.path），无证据窗口根本不进快照；
  2. **不控制未登记窗口** ✅ —— Layer 2 候选集 = `belongsToMode && manageable` 的窗口；C2 段附加断言"未归属同 exe 窗口零摆位"实证；
  3. **不伪造状态** ✅ —— `foregroundHwnd=null`、zIndex 声明为近似、skip 原因逐条如实透出到 UI chip；offline/invalid 一律 fail-closed 不猜。
- **已知边界（非缺陷，登记待拍板）**：
  - E（ambiguous）真实环境不可构造（apps.path UNIQUE + 一 app 一 pid）⇒ 该防御分支无法 Real 验证；
  - exePath 比较是大小写敏感 `===`（Windows 路径理论可同文件异写法两条登记）；
  - `trigger` 只有 `enter_mode` —— "保存当前状态"按钮语义上是借用 enter_mode 口径采集（C4 已声明）。

---

## 五、UI 当前 Run 页面（审计项 5，只读）

文件：`ui/src/views/RunView.vue`（唯一 workspace 消费页面）。

| 区块 | 现状 |
|---|---|
| 状态栏 `run-status` | 当前任务 chip · 应用三态 chips（running/launching/failed + `×N` 窗口计数）· 布局 chip · 模式 chip · **C4 快照区**（`run-snap-chip` + save/restore 两按钮，`snapBusy` 防重入）· C3 摆位结果 chip（`run-placement`，placed/unbound/offline/failed 四态）· 降级警告 `run-degraded` |
| 操作入口 | 头部 `run-back` 返回 · 布局 seg（**disabled**）· **`恢复默认` 按钮（disabled，title="C3 放开（窗口控制）"）** · **`保存布局` 按钮（disabled，同 title）** —— 这两个是原型遗留的"可见未接线"占位 |
| 恢复入口 | 仅 C4 的 `run-snap-restore`；**Run 页无"退出模式/完成工作"入口**（exitMode 在 adapter 导出但未被 RunView 引用；ModeBar/ModeView 是别的页面的入口） |
| 错误状态展示 | 三层：connectivity（未连接整页提示）→ degraded（`run-degraded` 列失败明细）→ 单动作结果（placement chip / snapshot chip 如实透出 reason） |
| 交互状态机 | `idle → beginInteraction(move/resize) → pointermove 预览（8 向，左/上侧同步移动 left/top）→ pointerup commitInteraction（placeWindow → 非 placed 写回起始几何）`；异常路径 `pointercancel` / `lostpointercapture` ⇒ `cancelInteraction`（只清理不摆位）；新交互开始前先清旧状态（C3 收尾审计加固） |

**C5 相关发现**：
- 两个 disabled 按钮是当前 Run 页**唯一**"看得见但没接"的交互（保存布局/恢复默认）——若 C5 是布局方向，它们就是现成入口；
- `placeWindow` 的归一化钳制（`clamp(x,0,1)`）**不保证 x+w ≤ 1**：拖拽路径理论上可把窗口右缘推出工作区（C4 的 safeRect 只管快照路径）。快照路径已闭环，**拖拽路径未闭环** —— 登记为 C5-06 候选项，本轮不修。

---

## 六、验证基础设施（审计项 6）

| 套件 | 文件 | 规模 | 基线 | 备注 |
|---|---|---|---|---|
| C1 | `tools/verify_tech07c.py` | 207 行 · 16 判定 | 16/16 | ⚠️ **命名映射**：C1 套件文件名是 `verify_tech07c.py`，**没有** `verify_tech07c1.py` |
| C2 | `tools/verify_tech07c2.py` | 559 行 · 25 判定 | 25/25 | ProxyHandler（SPA 回退 + GET/POST 代理 + HTTPError 如实透传） |
| C3 | `tools/verify_tech07c3.py` | 527 行 · 27 判定 | 27/27 | 手势目标收紧为"归属 + 标题=真实拉起软件" |
| C4 | `tools/verify_tech07c4.py` | 737 行 · 26 判定 | 25/25 + 1 DEFER | S(12)+R(5)+D(8)+DEFER(1)；含 PUT 代理子类、`ui_click_and_wait`（防陈旧 chip 假绿）、`unrun()` 兜底、DEFER 三态 |
| TECH-02 | `tools/verify_tech02_workspace.py` | 820 行 · 11 判定 | 11/11 | 冻结域回归（含 T1b：runtime/ 外禁 import store/layout/snapshot 门面） |
| 契约 | `tools/verify_contracts.py` | 344 行 | exit 0 | snapshot 契约 + x-pw-v2-forbidden 对齐 |

**给 C5 的复用建议**：C4 脚本里沉淀的三个章法值得直接继承——①点击后必须"文案变化"才算真跑（防陈旧 chip）；②判据必须比**独立事实源**（/health 的 pid@started_at、SQLite 行、core windows_list 回读）；③构造不出来的场景 DEFER 三态 + 结构性证据，不伪造。另有环境前提：dist 必须以 `VITE_CORE_BASE=''` 构建（C4 踩过：普通 build → C2 D2 假红）。

---

## 七、审计输出

### 7.1 当前 C5 输入条件

1. ✅ C4 全链路健康（capture/read/restore/fail-closed/offline），无已知缺陷；
2. ✅ 冻结域 + schema 双重 v2 禁区（`additionalProperties:false` + `x-pw-v2-forbidden`）——**任何"快照历史/多快照/hwnd 映射"方向都直接违反契约**，除非先解冻契约；
3. ✅ 验证基础设施六套件全绿，C4 章法可复用；
4. ⚠️ C5 目标**未定义**（本审计最大发现）；
5. ⚠️ 恢复语义双链路并存（`mode_restore` 被 ModeBar 直连 vs snapshot restore）；
6. ⚠️ Run 页两个 disabled 按钮（保存布局/恢复默认）是唯一"可见未接线"项；
7. ⚠️ 多显示器/一 app 多实例/焦点恢复均需动 core 或动归属结构，超出"纯 UI 接线"的最小面。

### 7.2 候选方向 × 最小修改面（供拍板）

| 方向 | core 改动 | UI 改动 | 违反冻结？ | 备注 |
|---|---|---|---|---|
| **A. 布局保存/应用**（接通两个 disabled 按钮：把当前真实窗口几何存为 layout → layout_apply） | 无（`layouts_list/layout_apply` 均已存在） | RunView 两按钮 + adapter 白名单 += `layout_apply`（或经既有 LayoutView 服务） | 否（layout 不属 snapshot 冻结域） | 最小面最小；与 C4 快照互补（布局=模板，快照=实例） |
| **B. 焦点恢复**（快照 restore 附带 activate） | 无（windows_activate 已在） | adapter 白名单 += `windows_activate` + snapshot runtime 去掉 focus-skip | 否（属 C4 行为扩展，不改 schema） | 注意 C3 禁区语义反转需要新判据 |
| **C. 恢复语义收敛**（mode_restore vs snapshot restore 二选一/分层） | 无～小 | ModeBar/RunView | 否 | 需要产品口径 |
| **D. 一 app 多实例归属**（解锁 C4-E 回 Real） | **是**（slots/apps_running 结构） | projection/buildEvidence | schema 不动 | 改动面最大，动的是归属判据核心 |
| **E. 多显示器** | **是** | placeWindow/safeRect/facts/projection | 否 | C4 明确 Deferred；主显示器假设遍布三层 |
| **F. exePath 大小写不敏感比较** | 无 | runtime/snapshot.ts 一行级 | 否 | 小，但会改变 C4 已验收的比较语义，需回归 |
| **G. 快照历史/自动触发** | — | — | **是（违反 x-pw-v2-forbidden）** | 除非解冻契约，否则不做 |

### 7.3 推荐实施顺序（假设按"最小修改面优先"）

1. **先拍板 C5 目标**（见 7.4 #1）——决定走 A/B/C/F 中的哪条（均为零 core 改动）还是 D/E（动 core）；
2. 若选零 core 改动方向：checklist 细化 → 实现 → 复用 C4 验收官（S+R+D 结构）→ 全量回归；
3. 若选 D/E：先单独立"core 归属/拓扑改动"的契约评审，再动代码（改动面触及归属判据核心，不宜与 UI 改动混在一个阶段）。

### 7.4 需要拍板的事项

1. **【阻塞】C5 目标是什么？** —— 现有文档无定义。候选见 7.2（A 布局保存/应用、B 焦点恢复、C 恢复语义收敛、D 一 app 多实例、E 多显示器、F exePath 大小写、G 快照历史【违反冻结】）。
2. **Run 页两个 disabled 按钮（恢复默认/保存布局）**：C5 是否接通？接通的话走方向 A 吗？（它们 title 写着"C3 放开（窗口控制）"，但 C3 实际只放开了 place，这两个按钮从未接线。）
3. **恢复语义**：`mode_restore`（core 阶段4，ModeBar 在直连）与 C4 snapshot restore 并存还是收敛？若并存，Run 页要不要补"退出模式/完成工作"入口（PD-001 相关）？
4. **`windows_activate` 是否解禁**：C3 把它列为 FORBIDDEN 是"不恢复前台焦点"的产品决定；若 C5 选方向 B，需要明确反转这条禁区并改 verify 脚本判据。
5. **（非阻塞，登记在案）**：`placeWindow` 拖拽路径的 x+w 可越界（C5-06）、`runtime/index.ts:30` 过时注释（C5-08）、exePath 大小写（C5-09）—— 本轮均不修。

---

## 八、停止声明

本审计**零代码改动**：未新增 command、未新增 migration、未改 UI、未改冻结域、未动任何既有验收判据。
产出仅为两个新文档：本审计报告 + `TECH-07-C5-checklist.md`。
等待拍板（尤其 §7.4 #1）后再进入 C5 实施阶段。

---

## 九、补充审计（2026-09-16 晚：方向 A 冻结后，按执行指令重审）

> 拍板结果：C5 = **Workspace Layout Persistence（布局保存/应用）**，双轨并存，core 能不改则不改。
> 本节为方向 A 的针对性只读深挖（仍未改任何代码）。

### 9.1 保存链路 —— 全部现成，零 core 改动

| 环节 | 事实 | 位置 |
|---|---|---|
| 写入口 | `db_layout_upsert`（Tauri 命令，`LayoutRepo::upsert` 唯一写入口：先写库成功后导出 JSON，导出失败仅 WARN） | `core/src/api/commands.rs:439` · `scheduler/repository.rs` |
| HTTP 通道 | `GET+POST /api/v1/db/layouts`（`api_db_layouts` / `api_db_layout_upsert`） | `core/src/api/mod.rs` |
| UI 封装 | `modeApi.dbLayoutUpsert(name, description, slots, monitor)` —— Tauri + HTTP 双通道，已验收 | `ui/src/api/modeService.ts:227` |
| 保存先例 | ModeView 布局编辑器 `saveLayout()` → `dbLayoutUpsert`（手输 slots） | `views/ModeView.vue:382,403` |
| 相邻能力（**不用**） | `modes_capture_current`：捕获当前环境 → 布局入库（`captured-<ts>`）→ **建新 work_mode 并绑定** —— 语义超出 C5（会建模式），且在 adapter FORBIDDEN | `commands.rs:466` |

`LayoutRepo::upsert` 的入参校验：name 非空且不含 `..`/`/`/`\`；`slots` 必须是数组。
**除此之外 core 不校验 slot 内部结构** ⇒ C5 采集器必须自证合法（C5-02 风险已登记）。

### 9.2 恢复链路 —— `apply_layout` 语义与 C5-05 天然吻合

`core/src/window_manager/apply.rs::apply_layout`（经 `layout_apply` 命令调用，同步阻塞）：

1. `work_area_of(layout.monitor)`：目标显示器不存在 ⇒ **降级主显示器**（`degraded_monitor:true`）；
2. 槽位解析：`resolve_pid(state, slot.app)` —— **`slot.app` 按 `apps.name` 大小写不敏感匹配** →
   `running.get(app.id)`（运行注册表）；查无 ⇒ `skipped_not_running`（**不启动软件**）；
   pid 在但无可见顶层窗口 ⇒ `skipped_no_window`；
3. 定位：按 `z` 升序先摆靠后的；`window::place` 失败自动重试 2 次（间隔 500ms）；
4. 产出 `ApplyOutcome { placed, skipped, failed, slots[]（逐槽位 status/hwnd/rect/reason）, took_ms }`。

⇒ C5-05 要求的"失败 skip / 不自动启动 / 逐槽位明细"**全部由 core 现成产出**，UI 只做如实投影。
"恢复默认"取布局名的来源：当前模式绑定布局（`modes_list` 的 `meta.layout`，C2 投影 `RunModeFacts.layout` 已有）。

### 9.3 槽位身份口径（重要对齐点）

用户指令允许保存 `appId`；core 链路的真实口径是 **`slot.app` = 软件库 `apps.name`**
（`resolve_pid` 按 name 匹配，数字 id 不出 core）。实施时：受管窗口 pid →（slots/running）→ appId
→（apps_list）→ `apps.name` 落库；UI 层可用 appId 做显示映射。**禁止把 hwnd/pid 写进 slots**
（那是 snapshot 的实例身份，混用即破坏双轨边界）。

### 9.4 边界反转清单（实施时唯一动到的"禁令"）

| 项 | 现状 | 实施动作 |
|---|---|---|
| `layout_apply` | `boundary.ts::FORBIDDEN_COMMANDS` | 移入 `ALLOWED_COMMANDS`（与 C3 放开 `windows_place` 同一先例） |
| `verify_tech07c3.py` FORBIDDEN 扫描 | 含 `layout_apply` | 判据同步移除该词（判据更新 ≠ 放松：RunView 禁 @/api 仍有效） |
| `windows_activate` / `mode_restore` / `modes_capture_current` / `apps_launch` | FORBIDDEN | **不动** |

### 9.5 新增结论

- **core 改动：零**（不需要新 command、不需要 migration、不需要改 Rust）。
- **唯一新文件**：`ui/src/workspace/runtime/layout.ts`（F0）+ `tools/verify_tech07c5.py`（F3）。
- **UI 改动面**：`RunView.vue`（两按钮 handler + 状态 chip + title 修正）、`runtime/index.ts`（导出）。
- **实施前小拍板**：保存布局的命名策略（默认 `run-<模式名>-<时间戳>` vs 用户输入名）。
- 前轮候选面 checklist 已被本版替换；未选方向（多实例/多显示器/exePath/焦点恢复/mode_restore 收敛）
  在决策区登记为 REJECTED，不是"遗忘"。
