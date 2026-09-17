# TECH-07-C6 Checklist —— Phase 0 只读审计（冻结版）

> 日期：2026-09-16（v2，按 C6 冻结指令重排：C6-01~C6-04）
> 性质：**Phase 0 = 建 checklist + 只读审计，零代码改动**。
> 停止条件：✅ 本 checklist + ✅ `docs/tech/TECH-07-C6-audit-report.md` → 立即停止，等待拍板。

---

## C6-01 目标定义来源审计

### 检索范围与命中情况

| 来源 | 位置 | 与 C6 相关的内容 | 结论 |
|---|---|---|---|
| docs/ 全量 grep "C6" | `docs/` | 仅 3 处无关命中：LEDGER 提"TECH-06-B C6"（另一技术项的验收方法引用）、PW-INTEGRATION-002/003 的行号 C6（表格序号） | **无 C6 目标定义** |
| HANDOFF | `HANDOFF.md` | 通用交接规程，进度外置在 LEDGER | 无 C6 目标 |
| LEDGER | `docs/reviews/LEDGER.md` | 判据台账截至 C5；无 C6 条目 | 无 C6 目标 |
| UI-FUSION-STANDARD | `docs/ui/UI-FUSION-STANDARD.md`（v1 Phase C1） | 融合标准 + Run 页信息架构；引用 C2/C3/F0-F5，无 C6 | 无 C6 目标 |
| TECH-07-B 设计 | `docs/tech/TECH-07-B-ui-fusion-design.md` §五 | F0~F5 阶梯。对照已执行阶段：F1≈C2、F2≈C1、F3（place 部分）≈C3、F4≈C4、F3（布局保存/应用部分）≈C5。**未落地：F0 优雅关闭（core）、F3 尾巴（appbar⇄前台双向同步/Esc 链/吸附三类）、F5 恢复执行编排** | C6 的最大候选池 |
| C1~C5 报告 | `docs/tech/TECH-07-C*-report.md` / `C2/C3-*-report` / `C3-closure-audit` / `C4-report` §十一 / `C5-audit` §7.2/§7.4 | C4"不做清单"：多显示器、一 app 多实例、快照历史/自动触发、最大化语义恢复、Z 序还原、前台焦点恢复；C5 审计候选 A~G：A 布局（C5 已采纳）/**B 焦点恢复 / C 恢复语义收敛 / D 一 app 多实例 / E 多显示器 / F exePath 大小写**，G 快照历史（违反 x-pw-v2-forbidden） | 结构化候选池（见 C6-04） |
| C5 checklist 决策记录 | `docs/tech/TECH-07-C5-checklist.md` 尾部 | mode_restore 收敛**暂不收敛**；一 app 多实例/多显示器/exePath 扩展**不做（REJECTED）** | C5 显式拒绝项，C6 重提需新理由 |
| memory 日志 | `.workbuddy/memory/2026-09-1*.md` | C1~C5 执行与验收记录（C5 24/24 全绿停机）；无 C6 | 无 C6 目标 |

### 结论

**C6 未定义。** 全部来源零命中"C6 目标/范围"。本文档与审计报告只列候选方向并给出决策矩阵，
**不默认实现任何候选** —— 实施前必须先形成决策记录（拍板结果回写本 checklist 为冻结判据版）。

---

## C6-02 当前能力矩阵

### UI（RunView，`ui/src/views/RunView.vue`）

| 能力 | 状态 | 出口 | 结果呈现 |
|---|---|---|---|
| observe | ✅ C2 | `workspaceAdapter.snapshot()`（2s 轮询）+ connectivity 三档 | 舞台窗口卡片 / appbar / 状态栏 chips / minimap |
| place | ✅ C3 | 拖拽/缩放 commit → `workspaceAdapter.actions.placeWindow()`（归属三重校验 + 归一化→物理像素） | `run-placement`（placed/unbound/offline/failed 四态如实） |
| snapshot | ✅ C4 | `run-snap-save` / `run-snap-restore`（`:disabled="snapBusy"`） | `run-snap-chip`（保存/恢复 skip 明细） |
| layout save/apply | ✅ C5 | `run-layout-save` / `run-layout-apply`（`:disabled="layoutBusy"`） | `run-layout-chip`（✓ 已保存 / ✓ 已应用 / ◐ 部分应用+skip 明细 / ✕ 失败态；detail 走 title）；布局名展示 `run-layout-name-chip` |

### Adapter（`ui/src/workspace/runtime/`）

| 文件 | 职责 | 备注 |
|---|---|---|
| `boundary.ts` | 白名单 15 项（modes_list/current、mode_progress、layouts_list、monitors_list、windows_list、apps_list、apps_running、ping、mode_apply/cancel/exit、db_layout_upsert、layout_apply、windows_place）；禁区 8 项（windows_activate、windows_find、windows_rect、mode_restore、modes_capture_current、apps_launch、windows_close、apps_terminate）；`ADAPTER_MODE='actuate'` | C5 后唯一边界反转 = layout_apply/db_layout_upsert 移入白名单 |
| `facts.ts` | 只读事实聚合（7 项 Promise.allSettled + failures 明细 + connectivity 判据）；`lastFacts` 运行时缓存（offline 作废） | 不 import client.ts |
| `projection.ts` | core DTO → UI 投影（纯映射，仅 type import） | 零副作用 |
| `actions.ts` | applyMode / cancelApply / exitMode / placeWindow（C3 唯一窗口控制） | exitMode 未从 Run 页暴露（core 硬杀语义） |
| `snapshot.ts` | C4：真实探针 → 冻结 v1 capture → 校验 → 原子写 config；restore 两层匹配 + 逐窗再校验 | **从不**把 lastFacts 当 snapshot，反之亦然 |
| `layout.ts` | C5：saveLayout（登记证据链 pid→appId→apps.name + 归一化 rect） / applyBoundLayout（skip 语义透传） | 不读写 `workspace.snapshot.last` |
| `index.ts` | 统一出口 `workspaceAdapter`（facts/actions/windowSnapshot/layout 四组） | RunView 只 import 本文件 + facts 类型 |

### Core

| 分类 | 内容 |
|---|---|
| **已存在命令**（122 个 Tauri command，workspace 相关） | windows_list / windows_find / windows_rect / windows_place / **windows_activate**（`commands.rs:247`，参数 `hwnd: i64`，返回 `{hwnd, foreground: bool}`，内部 `window.rs:190 activate` + `window.rs:219 is_foreground`）/ layouts_list / layout_get / **layout_apply** / **db_layout_upsert** / monitors_list / apps_list/running/launch / modes_* / mode_apply/cancel/progress/restore/exit / modes_capture_current / get_config / put_config / ping（返回 identity_facts JSON：pid+started_at） |
| **禁止命令**（adapter FORBIDDEN，core 可能有） | windows_activate、windows_find、windows_rect、mode_restore、modes_capture_current、apps_launch、windows_close（core 也没有）、apps_terminate（core 无此命令名，杀进程走 device_process_kill 等无关路径） |
| **未实现能力** | ❌ windows_close / 优雅关闭（无 close(hwnd)、无 WM_CLOSE；`mode_exit` 硬杀语义 07-A R-1，B 设计 F0 未落地）❌ 快照专用命令（UI 经 config 读写自管）❌ 一 app 多实例归属（apps.path UNIQUE + apps_running 一 app 一 pid）❌ 跨屏/多显示器拓扑重构（主屏假设遍布 to_pixels/actions/facts）❌ 自动快照触发（v1 trigger=enter_mode 仅登记，实际为手动） |

---

## C6-03 冻结域检查（2026-09-16 实测 sha256[:16]）

| 文件 | hash | 基线来源 | 状态 |
|---|---|---|---|
| `ui/src/workspace/snapshot.ts` | `604fe010e0d3f980` | C1 起冻结（v1 capture/restore/validate 纯函数） | ✅ 一致 |
| `ui/src/styles/tokens.css` | `f329f50bddd31d59` | C1 视觉基线 | ✅ 一致 |
| `ui/src/styles/motion-tokens.css` | `e5e44af4aa807d38` | C1 视觉基线 | ✅ 一致 |
| `ui/src/components/ui/primitives.css` | `2de660ce01c2c7d5` | C1 视觉基线 | ✅ 一致 |
| `ui/src/styles/base.css` | `46d26e1bc27716a7` | C1 视觉基线 | ✅ 一致 |
| `database/schema.sql` | `d95ca49cc3285166` | C5 首次登记 | ✅ 一致 |

- **Token 体系**：单一体系（`ui/src/styles/tokens.css` + motion-tokens + primitives 原语）；UI-FUSION-STANDARD §2.3：组件内禁止硬编码色值/字号/间距，缺 Token 先并入 Semantic 层（含暗色映射）。
- **TECH-02 冻结域**：`ui/src/workspace/`（store.ts / layout.ts / snapshot.ts / runtime.ts 门面）——C1~C5 全部只在其外（`workspace/runtime/` 子目录）接线，`verify_tech02_workspace.py` 11/11 持续把门。
- **snapshot 契约**：`workspace-snapshot.v1.schema.json`（`additionalProperties:false` + `x-pw-v2-forbidden` 十字段：snapshotHistory/windowIdentityMap/restoreCount/restoreLog/keepAliveRegistry 等）——任何"快照历史/多快照/hwnd 映射"方向直接违反契约。

**本轮（Phase 0~2）以上全部零改动。**

---

## C6-04 候选方向分析（只分析，不实现）

### 候选 A：焦点恢复

| 检查项 | 事实 |
|---|---|
| windows_activate | core **已存在**（`commands.rs:247`：`hwnd: i64 → {hwnd, foreground}`；`window.rs:190` SetForeground 语义）；HTTP POST `/api/v1/windows/{hwnd}/activate`。**core 零改动** |
| foreground state | `is_foreground(hwnd)`（`window.rs:219`）已存在且已验收——前台**读取**能力在，前台**控制**（activate）也在，只是 adapter 禁 |
| adapter 边界 | `windows_activate` 在 FORBIDDEN_COMMANDS（C3/C4 明示禁区，语义="不恢复前台焦点"的产品决定）。解禁 = 边界反转，需：移入白名单 + verify_tech07c2/c3/c4 相关判据显式记账反转 + 新 c6 判据 |
| 验收风险 | **高**：焦点断言在无头/自动化环境天然不稳（headless Edge 不产生真实前台；activate 后 GetForegroundWindow 受系统焦点策略影响）；C4 restore 的 focus-skip 恒 skip 语义要反转；快照 v1 `foregroundHwnd` 恒 null 的"诚实降级"口径要改写。均为判据/口径级风险，非 schema 级 |

### 候选 B：恢复语义收敛

| 三者关系（当前事实） | 语义 | 触发方 | 数据源 |
|---|---|---|---|
| `mode_restore`（`commands.rs:392`） | **重跑模式流水线**：读 config `mode.current` → get_by_name → `apply_mode(state, id, None)`（硬语义：按模式定义重新拉起软件，07-A R-1 硬杀口径） | ModeBar.vue:68 **直连** `modeApi.restore()`（绕过 adapter，C5 审计登记，C5 决策"暂不收敛"） | config + 模式模板 |
| snapshot restore（C4） | **实例身份几何还原**：两层匹配（hwnd+pid / exePath）+ 逐窗再校验 + safeRect；不启动软件 | RunView `run-snap-restore`（经 adapter） | config `workspace.snapshot.last` |
| `layout_apply`（C5） | **模板摆位**：模式绑定布局 slots（apps.name+归一化 rect）→ resolve_pid → place；未运行 skip 不启动 | RunView `run-layout-apply`（经 adapter） | layouts 表 |

三者是三种不同的"恢复"：**重建（mode_restore） vs 实例还原（snapshot） vs 模板摆位（layout）**。
用户侧存在两个语义不同的"恢复"入口（ModeBar 一键恢复 vs Run 页快照恢复），且 ModeBar 绕过 adapter 消费规则。

### 候选 C：F5 自动恢复编排

| 检查项 | 事实 |
|---|---|
| enter_mode | `mode_apply`（`commands.rs:321`）→ scheduler 七步流水线（含 launch/登记）；完成后 `mode.current` 写 config；`modes_current` 区分 configured/running |
| mode lifecycle | apply → progress（mode_progress 七步）→ current → exit（硬杀自己拉起的软件）→ restore（一键重跑）。**无"恢复上次工作区几何"的钩子** |
| core/UI 职责边界 | 快照的 capture/restore **全部在 UI 侧**（runtime/snapshot.ts + config 读写），core 无快照感知。两种编排位置：① **UI orchestration**（apply 成功后 UI 调 adapter.windowSnapshot.restore()）= 零 core 改动，但 wait_ready 轮询/失败兜底在 UI；② **core lifecycle**（apply_mode 流水线内挂恢复步骤）= 需要 core 读 config 快照 + 新增恢复编排代码 + wait_ready 事实出口，改动面大 |
| 其他 | 复用 C4 全部恢复原语；触发语义改变触碰 C4"手动恢复"口径，需显式记账；验证 = 端到端（保存→退出→重启→进模式→自动恢复→几何比对），C4 verify 的 D 段骨架可复用 |

---

## 停止声明

本 checklist 为 Phase 0 只读产物。冻结域 hash 全部一致、TECH-02 域零触碰、边界零反转、候选零执行。
实施判据（C6-xx 验收项 + F0~F3 执行序）**待方向拍板后**按 C5 先例重写本文件为冻结版。
