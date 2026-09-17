# TECH-07-C7 审计报告 —— Phase 1（F3 交互尾巴收敛，只读）

> 日期：2026-09-16
> 方向（已冻结）：C7 = F3 交互尾巴收敛 —— Esc 退出当前交互态、窗口交互异常恢复、边界吸附（仅 UI 预览层）、窗口树状态展示补全（只读）。
> 性质：**只读审计，零代码改动**。事实底稿：`docs/tech/TECH-07-C7-implementation-checklist.md`（C7-01~06）。
> 停止：本报告交付后立即停止，等待 Phase 2 拍板。

---

## 1. 当前状态

- **Pointer 生命周期（C7-01）**：五路径中四条已闭环（pointerup=commit / pointercancel=cancel / lostpointercapture=cancel / 残留防护），全部满足"interaction=null → listener detach → 恢复"。监听为交互期挂载、对称移除，非全局常驻。**两个缺口**：① Esc 键退出链不存在（全文件无 keydown/Escape）；② cancel 路径只做本地回滚（writeGeometry(start)），无 facts refresh（commit 路径有）。
- **Esc 链（C7-02）**：不存在。现有 cancelInteraction 语义已天然满足 Esc 四条要求（清预览 / 不 commit / 不调 core / 位置不变）——实现 = 复用 cancel 通路，零新增 core 交互。
- **Geometry（C7-03）**：预览→clamp→place→facts 确认链路清晰；**x+w/y+h 联合越界未防**（C5-06 登记项仍未修，x/w 独立 clamp）；MIN 口径分裂（预览 0.04 vs adapter 0.02，实际不触发但口径不统一）；多方向 resize 数学对称、无回弹缺陷；safeRect 仅 C4 restore 使用，边界清晰。
- **吸附（C7-04）**：无现状。冻结原则已立：只动 previewGeometry（预览层）、禁止 pointermove 实时摆位、不改 commit 单次提交语义；候选（monitor edge / window edge / grid）暂不决定。
- **窗口树（C7-05）**：数据链已具备（WindowInfo → RunWindowFacts 含 belongsToMode/manageable/state）；舞台卡片已做 managed/unmanaged 二分（is-managed + 只读标注，unmanaged 无 pointerdown）；**无独立 drawer**；**无 unknown 类别**（无证据源，建议不引入第三类）。
- **回归边界（C7-06）**：c2 A2（placeWindow 恰 1 处）、A3-A5/c6 S4（零新视觉）、c2 D4（DOM identity）、c6 S3/S6（hash 基线 + 交互状态全集）是 C7 实施的硬护栏；RunView.vue 不在 hash 冻结内（可改）。

## 2. 可实现项（Phase 2 范围，全部 RunView.vue 内、零 core 改动）

| # | 项 | 最小增量 | 回归影响 |
|---|---|---|---|
| 1 | **Esc 链** | 交互期间挂 window keydown(Escape) → cancelInteraction（attach/detach 与 pointer 监听同进同出）；非交互态无操作 | 零（不新增 placeWindow 调用点、不碰 mode 动作、零视觉） |
| 2 | **cancel 路径补 refresh** | cancelInteraction 追加只读 `refresh()`（与 commit 路径对齐，满足"异常退出 → facts refresh 恢复"判据） | 零 core 风险（只读） |
| 3 | **联合越界修复（C5-06 顺手闭环）** | 最小修：adapter placeWindow 联合 clamp（x+w≤1 / y+h≤1，装不下退化为 MIN_VISIBLE 可见）或预览层 clamp；**动 actions.ts 属 adapter 内修改，需 Phase 2 确认是否入 scope** | c3 判据核对（其摆位回归容差内不受影响）；c5-06 登记项闭环 |
| 4 | **MIN 口径统一** | 预览 0.04 与 adapter 0.02 二选一对齐 | 极小 |
| 5 | **吸附（预览层）** | previewGeometry 内目标修正；候选三选一待拍板；不做实时摆位 | 零（无监听/无 core/零 Token 前提下） |
| 6 | **窗口树展示补全** | 口径 a：现有卡片补 state/几何文本（最小）；口径 b：新增只读 drawer（新 UI 面）——**二选一待拍板**；不新增控制入口；新增 data-pw 需同步登记 c6 S6 类判据 | 口径 a 零风险；口径 b 需 DOM identity 核对 |

## 3. 禁止项（本阶段已确认全部未触碰，Phase 2 同样禁止）

windows_activate 白名单化 ✗ · windows_close 开发 ✗ · mode_restore 改造 ✗ · snapshot schema 修改 ✗ ·
layout_apply 修改 ✗ · 多显示器 ✗ · 多实例归属 ✗ · 新增视觉 Token ✗ · 修改冻结 CSS ✗ ·
新增常驻全局鼠标监听 / document 级 hack ✗ · pointermove 直调 core（实时摆位）✗ · 窗口树新增控制入口 ✗。

## 4. 风险

| 风险 | 等级 | 对策 |
|---|---|---|
| Esc 监听若实现为常驻全局键监听 → 违反"禁止全局监听"禁令 | 低 | 冻结设计已限定：交互期挂载、detach 对称移除（与 pointer 监听同模式） |
| 联合越界修复动 adapter（actions.ts）→ c3 摆位回归判据受影响 | 低～中 | clamp 只收紧不放宽；c3 容差内回归；若拍板不入 scope 则维持 C5-06 登记状态 |
| 窗口树 drawer（口径 b）新增 UI 面 → 视觉判据/DOM identity 风险 | 中 | 只读、消费既有变量、保 identity；或直接选口径 a 规避 |
| 吸附候选未拍板即实现 → 返工 | 低 | Phase 2 先拍候选再动手；实现落点唯一（previewGeometry） |
| 真实环境回归偶发（C5 教训） | 低 | 串行 + 重跑消抖 + 收尾零残留（既有纪律） |

## 5. 是否需要 core 改动

**不需要。** 六个可实现项全部落在 `ui/src/views/RunView.vue`（± adapter `actions.ts` 的联合 clamp 一处，仍属 UI 层）。
无新增命令、无边界反转、无 schema/冻结域/Token/CSS 变更、无三链语义变更。core 能力矩阵与 C6 收口态完全一致。

## 6. 需要拍板的问题（Phase 2 前）

1. 联合越界修复（C5-06 闭环）是否纳入 C7 scope？（动 adapter actions.ts 一处 clamp——建议纳入，最小且闭环历史登记项）
2. 吸附候选三选一：monitor edge / window edge / grid？（或 Phase 2 先做 Esc+refresh+越界修复，吸附留后）
3. 窗口树补全口径：a 现有卡片信息补全（推荐，最小）还是 b 新增只读 drawer？
4. MIN 口径统一取 0.04 还是 0.02？（建议统一到 0.04=预览现值，避免收窄既有可操作性）

---

## 停止声明

Phase 1 完成：checklist ✅ · audit report（本文件）✅ · 零代码修改 ✅（冻结域 hash 未复验变动——本轮未触碰任何文件）。
**立即停止，等待 Phase 2 拍板。**
