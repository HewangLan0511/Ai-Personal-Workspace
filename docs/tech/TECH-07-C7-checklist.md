# TECH-07-C7 Checklist —— Phase 0 只读审计（冻结版）

> 日期：2026-09-16
> 性质：**Phase 0 = 建 checklist + 全量只读审计，零代码/零配置/零验收脚本改动**。
> 输入：`docs/tech/TECH-07-C6-implementation-report.md`（27/27 全绿收口）、LEDGER、HANDOFF、
> UI-FUSION-STANDARD v1、C1~C6 全部报告、同日 C6 审计事实（当日复检 hash 8/8 一致，状态可平移）。
> 停止条件：✅ 本 checklist + ✅ `docs/tech/TECH-07-C7-audit-report.md` → 立即停止，等待方向确认。

---

## A. 阶段目标确认

### C7 是否已有冻结定义

**没有。** 全 docs 检索 "C7" 仅两处命中且均非目标定义：
- `LEDGER.md:419`（TECH-06-B 时代的方法论脚注，"C6/C7"指另一技术项的验收轮次）；
- `TECH-07-C6-implementation-report.md:91`（C6 收尾语"未明确开启 C7 前不扩展"）。

结论：**C7 未定义，只列候选方向（见审计报告 §3），不执行。**

### C1~C6 已完成能力边界（当前系统能力快照）

| 阶段 | 能力 | 验收 | 边界 |
|---|---|---|---|
| C1 | `/run` 页壳（run-head/状态栏/appbar/舞台投影/minimap） | 16/16 | 只读投影 |
| C2 | Observe：facts-in 七项聚合 + connectivity 三档 + DOM identity | 25/25 | 零窗口控制 |
| C3 | Place：windows_place 拖拽/缩放落位 + 归属三重校验 | 27/27 | 仅 Move/Resize |
| C4 | Snapshot：真实探针 capture → v1 校验 → config 原子落库；restore 两层身份匹配 + safeRect | 25/25 + 1 Deferred | 手动恢复；不激活焦点 |
| C5 | Layout Save/Apply：模板语义（apps.name+归一化 rect）；RunView 两按钮接线 | 24/24 | 不做跨重启身份 |
| C6 | 恢复语义收敛：三链口径冻结（重建/实例还原/模板摆位）+ ModeBar 豁免登记 + verify_tech07c6 锁死 | **27/27（R 全部首跑）** | 零产品代码变更；A/C 方向被停止条件排除 |

当前能力面 = 观察 + 受限摆位 + 实例快照（手动）+ 模板布局（手动）+ 模式重建（mode_restore，ModeBar）。
**未具备**：焦点控制（activate 在 FORBIDDEN）、窗口关闭（core 无此能力）、跨重启自动恢复编排、多显示器、一 app 多实例。

---

## B. Adapter 边界审计（`ui/src/workspace/runtime/`）

| 检查项 | 结果 |
|---|---|
| index.ts | 统一出口 `workspaceAdapter`（facts/actions/windowSnapshot/layout 四组）；无越组出口；S2b（c6）确认 RunView 零 @/api |
| facts.ts | 只读聚合（7 项 allSettled + failures + connectivity）；`lastFacts` 缓存 offline 作废（C3 closure audit 语义）；不 import client.ts |
| projection.ts | 纯映射（仅 type import @/api），零副作用 |
| actions.ts | applyMode/cancelApply/exitMode/placeWindow（C3 唯一窗口控制）；exitMode 未从 Run 页暴露 |
| boundary.ts | ALLOWED 15 / FORBIDDEN 8 / actuate；hash `19dfb41e2df31ccd`（C6 冻结基线，本轮复检一致） |
| **新增 core 绕过** | 无（S5c：adapter 四文件零禁区命令名；S2a：modeApi.restore 全 UI 恰好 1 处 = ModeBar 豁免点） |
| **新增 FORBIDDEN 消费** | 无（S5a/b：FORBIDDEN 8 项全在、白名单零禁区命令） |
| **三链串线** | 无（S1a-d：snapshot/layout/actions/冻结域 零 mode_restore；layout.ts 零 snapshot 键；c6 D 段实证三链行为互斥） |

## C. Core 能力矩阵审计

| 分类 | 事实 |
|---|---|
| 已存在 command | 122 个（workspace 相关见 C6 checklist C6-02）；`windows_activate` **已存在**（commands.rs:247，`hwnd:i64 → {hwnd,foreground}`，HTTP POST /windows/{hwnd}/activate）——**adapter 禁区中，状态自 C3 起未变** |
| 已开放（adapter 白名单） | modes_list/current、mode_progress、layouts_list、monitors_list、windows_list、apps_list、apps_running、ping、mode_apply/cancel/exit、db_layout_upsert、layout_apply、windows_place |
| adapter 禁区 | windows_activate、windows_find、windows_rect、mode_restore、modes_capture_current、apps_launch、windows_close、apps_terminate |
| **windows_close** | **仍不存在**（无 command、window.rs 无 close 函数、无 WM_CLOSE 优雅关闭；`mode_exit` 硬杀语义 07-A R-1；B 设计 F0 未落地） |
| **layout_apply** | 存在且开放（C5）；resolve_pid 按 apps.name 大小写不敏感；未运行 skip_not_running |
| **mode_restore** | 存在（commands.rs:392：config mode.current → apply_mode 重跑流水线）；adapter 禁区；ModeBar 直连 = C6 登记的唯一豁免点 |
| **snapshot config 持久化** | 无专用命令；UI 经 get_config/put_config 读写 `workspace.snapshot.last`（object 类型，三处登记 + 两个 cargo test 锁死）；v1 schema + x-pw-v2-forbidden 冻结 |

## D. UI 状态审计（RunView / ModeBar）

| 检查项 | 结果 |
|---|---|
| RunView 五区域 | run-head / run-status（chips 带）/ run-stage（窗口卡片+拖拽摆位）/ appbar / minimap —— C1 立标后未破坏（c2 D4 DOM identity 持续把门） |
| chip 状态集合 | `run-mode-chip`、`run-layout-name-chip`（绑定展示）、`run-layout-chip`（C5 结果）、`run-snap-chip`（C4）、`run-placement`（C3）—— 五组独立无混用（C5 已消 querySelector 撞名） |
| disabled/未接按钮 | 已接：布局保存/恢复（layoutBusy）、快照保存/恢复（snapBusy）、ModeBar 退出/恢复（豁免点）。**无"可见未接线"残留**（C5 接掉了最后两个 disabled 占位） |
| DOM identity | stage/appbar/mini/head 四锚 identity 保持（c2 D4 首跑通过） |
| token/hash 基线 | RunView 零私造 token/动画/hex（S4a）；8/8 冻结 hash 一致（本轮复检） |
| **C6 后视觉变化** | **无** —— C6 零产品代码变更，ModeBar.vue hash `eccb9c10727d3d30` 冻结一致 |
| **新交互入口** | **无** —— C6 只加判据不加入口；"退出模式"入口仍是登记在案的 open item（未做） |

## E. 验证基础设施审计

| 脚本 | 规模 | 状态 | C7 可复用性 |
|---|---|---|---|
| verify_tech07c.py（C1；**无 verify_tech07c1.py 文件，C1 即此脚本**） | 207 行 | 16/16 | 视觉红线/壳 identity 扫描可复用 |
| verify_tech07c2.py | 585 行 | 25/25 | base 底座（CDP/Edge/代理）+ D 段骨架；D2 已修标题生命周期竞态 |
| verify_tech07c3.py | 527 行 | 27/27 | 归属/摆位回归判据 |
| verify_tech07c4.py | 737 行 | 25/25+1D | start_core/wait_new_port/place_via_core/wait_rect/ui_click_and_wait(snap chip)/契约校验 |
| verify_tech07c5.py | 500 行 | 24/24 | R 段重跑消抖+失败落盘；layout chip 读取器；fail-close 三段式 |
| verify_tech07c6.py | ~430 行 | 27/27 | 三链语义锁死判据 + hash 基线 8 项 + R 段消抖模式；**C7 直接继承为回归底座** |

**脆弱判据**（继承性风险，均已知且有对策）：真实环境偶发（已用重跑消抖 + 串行纪律）；chip 读取器与 data-pw 强耦合（改名即红——这是有意的防伪设计）；dist 必须同源构建（VITE_CORE_BASE=''）。
**历史环境污染风险**：目标软件进程泄漏（c2 D5 已修真实 pid 收尾）；套件连跑抢 Edge/core/端口（纪律：串行）；桌面窗口差集污染（收尾零残留已闭环）。
结论：**六套件 + c6 可直接作为 C7 回归基础**；若 C7 动边界/chip 文案/交互入口，需按 C5/C6 先例显式记账反转判据。

---

## 停止声明

本 checklist 为 Phase 0 只读产物：零代码、零配置、零验收脚本改动；冻结域 8/8 hash 一致。
配套 `docs/tech/TECH-07-C7-audit-report.md` 已交付。**立即停止，等待 C7 方向确认。**
