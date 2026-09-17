# TECH-07-C6 Implementation Checklist（冻结版）

> 日期：2026-09-16 冻结
> 依据（仅限）：C1~C5 验收报告（verify_tech07c 16/16 · c2 25/25 · c3 27/27 · c4 25/25+1D · c5 24/24）、
> HANDOFF、LEDGER、UI-FUSION-STANDARD v1、`docs/tech/TECH-07-C6-audit-report.md`（决策版）
> 性质：**本文件冻结 C6 目标与判据。冻结后不扩展范围；偏离本文件 = 违规。**

---

## 0. 目标冻结（决策记录）

**C6 = 方向 B：恢复语义收敛（方案 1：并存 + 显式豁免登记 + 三链语义锁死）。**

### 为什么冻结为 B / 方案 1（对照停止条件逐条排除）

| 候选 | 排除/采纳理由 |
|---|---|
| A 焦点恢复 | **命中停止条件「需要扩大 windows 控制权限」**：windows_activate 在 adapter FORBIDDEN（C3/C4 冻结口径"不恢复前台焦点"），解禁 = 扩权。禁止。 |
| C F5 自动恢复编排 | **命中停止条件「验收发现历史阶段语义冲突」**：C4 已验收"恢复 = 手动按钮"语义，自动触发改变它；且验证难度高、可能需 core 改动。留给后续（需产品口径先行）。 |
| B 方案 2（ModeBar 改走 adapter） | 需要 mode_restore 移出 FORBIDDEN_COMMANDS = 边界反转，间接触碰 verify_tech07c2 冻结判据（A2 系列锁死边界语义）→ 违反「不改变已有验收语义」。禁止。 |
| **B 方案 1（采纳）** | 三条恢复链路**并存**（各有真实语义），**口径分层冻结** + ModeBar 直连**显式豁免登记** + verify_tech07c6 锁死。零 schema / 零冻结域 / 零边界 / 零 UI 变更，满足全部实施原则。 |

### 三条恢复链路的冻结口径（本阶段的核心交付）

| 链路 | 冻结语义 | 触发入口 | 数据源 | 软件启动？ |
|---|---|---|---|---|
| **mode_restore（重建）** | 重跑"上次使用模式"的完整流水线：按模式定义重新拉起软件（硬语义，07-A R-1） | ModeBar「恢复「上次模式」」按钮（**豁免点**，直连 modeService） | config `mode.current` + 模式模板 | **是（唯一启动链）** |
| **snapshot restore（实例还原）** | 把当前窗口几何拉回快照时刻：两层身份匹配（hwnd+pid / exePath）+ 逐窗再校验 + safeRect；不启动、不激活 | RunView `run-snap-restore`（经 adapter） | config `workspace.snapshot.last` | 否（missing ⇒ skip） |
| **layout_apply（模板摆位）** | 按模式绑定布局的模板 slots（apps.name+归一化 rect）摆位；未运行 skip、不启动 | RunView `run-layout-apply`（经 adapter） | layouts 表 | 否（skipped_not_running） |

### 豁免登记（ModeBar 直连）

- `ModeBar.vue` 直连 `modeApi.restore() / apply() / exit()`：TECH-06 时代既有组件，先于 adapter 存在；
  C2 的边界判据（a1/a2）只扫 `/run` 视图，ModeBar 不在其列 —— **登记为永久豁免点**，不作为 /run 页直连的先例。
- Run 页「退出模式」入口（PD-001）：**留给产品拍板，不在 C6**（登记为 open item）。

### 明确不在 C6 范围

焦点恢复（A）、自动恢复编排（C）、多显示器、一 app 多实例、快照历史、优雅关闭（F0）、任何 UI 视觉/交互变更、任何 core 改动。

---

## Phase 1：实施前审计记录（只读，已完成）

1. **adapter 边界状态**：ALLOWED 15 项 / FORBIDDEN 8 项 / `ADAPTER_MODE='actuate'`；C5 后零改动（hash `19dfb41e2df31ccd` 冻结为 C6 基线）。
2. **core 已有/禁用能力**：windows_activate 有（adapter 禁）、windows_close 无（F0 未落地）、mode_restore 有（ModeBar 直连在用）、layout_apply/db_layout_upsert 有（adapter 白名单）；快照无专用命令（config 承载）。
3. **RunView 交互状态**：C3 place（run-placement）+ C4 快照（run-snap-*）+ C5 布局（run-layout-*）三组状态/chip 独立无混用；两布局按钮 `:disabled="layoutBusy"`。
4. **三链关系**：见上表 —— 重建 / 实例还原 / 模板摆位，数据源与启动语义互斥，当前无代码级互相调用（Phase 1 审计确认零污染）。
5. **TECH-02 冻结域**：`ui/src/workspace/`（store/layout/snapshot/runtime 门面）C1~C5 零触碰，本轮审计确认 C6 计划零触碰；hash 见 S3。

**风险列表**：
- R-1 三链语义若不锁死，后续阶段可能"顺手"让 snapshot/layout 调 mode_restore（伪造启动）或反向 —— 用 verify 静态项锁死。
- R-2 ModeBar 豁免若不显式登记，未来边界审计会把它当违规或被复制为 /run 先例 —— 用"豁免唯一性"静态项锁死。
- R-3 真实环境套件连跑互相污染（C5 教训）—— c6 R/D 严格串行 + R 段失败重跑一次消抖。

**变更白名单（Phase 2 允许新建/修改的全部文件）**：
1. `docs/tech/TECH-07-C6-implementation-checklist.md`（本文件）
2. `docs/tech/TECH-07-C6-implementation-report.md`（实施报告）
3. `tools/verify_tech07c6.py`（新增验收脚本）
4. `.workbuddy/memory/2026-09-16.md`（日志追加）

**明确禁止修改区域**：
- `ui/src/**` 全部（含 RunView、ModeBar、adapter、boundary.ts、snapshot 纯函数域、样式）
- `core/**` 全部、`database/schema.sql`、任何迁移
- 既有验收脚本 `tools/verify_tech07c*.py`、`verify_tech02_workspace.py`、`verify_contracts.py`
- snapshot v1 schema（含 x-pw-v2-forbidden）、四 CSS 基线、Token 体系

**本阶段 C6 无产品代码变更** —— 交付 = 语义冻结（决策记录）+ 豁免登记 + 验收锁死脚本。这是"最小增量"约束下的唯一合规形态。

---

## Phase 2：验收判据（verify_tech07c6.py）

### S 静态
- **S1 三链互不污染**：runtime/snapshot.ts 零 mode_restore/不 import modeService；runtime/layout.ts 零 mode_restore/零 snapshot 键；runtime/actions.ts 零 mode_restore；冻结域 snapshot.ts 零 mode_restore。
- **S2 豁免唯一性**：`modeApi.restore` 调用点全 UI 恰好 1 处（ModeBar.vue）；RunView 零 @/api / 零 mode_restore。
- **S3 冻结域 hash**：snapshot 纯函数域 `604fe010e0d3f980` + 四 CSS 基线 + schema `d95ca49cc3285166` + **boundary.ts `19dfb41e2df31ccd` + ModeBar.vue `eccb9c10727d3d30`**（C6 零改动的机器证据）。
- **S4 视觉基线**：RunView 零新 token/动画/硬编码色；ModeBar 零 hex。
- **S5 禁止能力未误开放**：FORBIDDEN 8 项全在；ALLOWED 不含 windows_activate/windows_close/mode_restore/apps_launch/modes_capture_current；adapter 四文件（facts/actions/snapshot/layout）零禁区命令名。
- **S6 RunView 交互状态锁死**：C3/C4/C5 的按钮 disabled 绑定与 chip data-pw 全集在位。

### R 回归（全串行，真实环境项失败重跑一次消抖）
`verify_tech07c.py` 16/16 · `c2` 25/25 · `c3` 27/27 · `c4` 25/25 + 1 Deferred · `c5` 24/24 · `tech02` 11/11 · `contracts` exit 0。

### D 真实环境（全部非 mock，charmap + 真 core + 真 Edge 页面）
- **D1 快照链（实例还原）**：真窗口 capture → 挪走 → restore → rect 回归（不启动软件）。
- **D2 快照链失败路径**：杀 charmap → restore → skip missing + 零摆位 + **零启动**（窗口数不变）。
- **D3 布局链（模板）**：杀 charmap → layout_apply（绑定布局）→ skipped_not_running + 零摆位 + **零启动**（与 D4 形成对照）。
- **D4 模式链（重建）**：POST /mode/restore → charmap **真实回归且 pid 变化**（唯一启动链的真证据）。
- **D5 offline fail-closed**：杀 core → UI 快照保存/布局应用均失败态，无伪成功 chip。
- **D6 不产生伪事实**：UI 投影集合 ⊆ core 真实窗口集合。

### 停止条件（任一触发立即停并报告）
需要改 snapshot schema / 改冻结域 / 新增 core 表迁移 / 扩大 windows 控制权限 / 验收发现历史阶段语义冲突。
（Phase 0 推演已确认 B/方案 1 不触发任何一条。）
