# TECH-07-C6 实施报告 —— 恢复语义收敛（方向 B / 方案 1）

> 日期：2026-09-16
> 冻结依据：`docs/tech/TECH-07-C6-implementation-checklist.md`（Phase 0 冻结版）
> 验收：`tools/verify_tech07c6.py` → **27/27 通过（R 段全部首跑通过，零重跑）**
> 日志：`tools/_c6_run1.log`
> 停止条件核对：**零触发** —— 未改 snapshot schema、未改冻结域、未新增 core 表迁移、未扩大 windows 控制权限、未发现历史阶段语义冲突。

---

## 1. 本阶段做了什么（一句话）

把 C1~C5 并存的三条"恢复"链路**语义分层冻结**：重建（mode_restore）/ 实例还原（snapshot）/ 模板摆位（layout_apply），
显式登记 ModeBar 直连为唯一豁免点，并用 verify_tech07c6 把口径变成机器可判的回归资产。**产品代码零变更。**

### 为什么"零代码"是本阶段的正确形态（决策复述）

- 方向 A（焦点恢复）需要把 windows_activate 移入白名单 → **直接命中停止条件「扩大 windows 控制权限」**；
- 方向 C（F5 自动恢复）改变 C4 已验收的"恢复 = 手动"语义 → **命中「历史阶段语义冲突」**；
- 方向 B 方案 2（ModeBar 改走 adapter）需要 mode_restore 出 FORBIDDEN → 间接触碰 c2 冻结判据 → **违反「不改变已有验收语义」**；
- 方案 1（并存 + 豁免登记 + 语义锁死）是唯一同时满足全部实施原则（最小增量/不改 schema/不改冻结域/不扩权/不改既有验收语义）的形态。

## 2. 变更清单（全部在变更白名单内）

| 文件 | 类型 | 内容 |
|---|---|---|
| `docs/tech/TECH-07-C6-implementation-checklist.md` | 新增 | Phase 0 目标冻结 + Phase 1 审计记录/风险列表/变更白名单/禁区 + Phase 2 判据 |
| `docs/tech/TECH-07-C6-implementation-report.md` | 新增 | 本报告 |
| `tools/verify_tech07c6.py` | 新增 | S 静态 14 项 + R 回归 7 套件 + D 真实环境 6 项 |

`ui/src/**`、`core/**`、`database/**`、既有 verify 脚本：**零改动**（boundary.ts `19dfb41e2df31ccd`、ModeBar.vue `eccb9c10727d3d30` hash 冻结为机器证据）。

## 3. 三链语义冻结（交付核心）

| 链路 | 冻结语义 | 入口 | 启动软件？ | 真实证据（本轮 D 段） |
|---|---|---|---|---|
| **mode_restore = 重建** | 重跑"上次使用模式"流水线，按模式定义重新拉起软件 | ModeBar「恢复「上次模式」」按钮（豁免点，直连 modeService） | **是（唯一）** | D4：restore 后 charmap 回归，pid 41312→41652、hwnd 8916294→8064322（真新进程） |
| **snapshot restore = 实例还原** | 两层身份匹配把当前窗口几何拉回快照时刻；不启动、不激活 | RunView `run-snap-restore`（经 adapter） | 否 | D1：rect 精确回归 {18,80,572,536}；D2：missing ⇒ skip + 零摆位 + 零启动 |
| **layout_apply = 模板摆位** | 按绑定布局模板 slots 摆位；未运行 skip、不启动 | RunView `run-layout-apply`（经 adapter） | 否 | D3：skipped_not_running（charmap:未运行）+ 零摆位 + 零启动 |

**豁免登记**：`modeApi.restore()` 全 UI 调用点恰好 1 处（ModeBar.vue，S2a 机器判定）；RunView 零 @/api（S2b）。
豁免仅限该既有组件（TECH-06 时代、先于 adapter 存在、非 /run 页），不构成 /run 页直连先例。

## 4. 验收结果

### S 静态（14/14）

三链互不污染（S1a-d：snapshot/layout/actions/冻结域 零 mode_restore 串线）· 豁免唯一性（S2a-b）·
冻结域 hash 8 项全一致（S3：纯函数域 + 四 CSS + schema + boundary + ModeBar）·
视觉基线（S4a-b：RunView/ModeBar 零私造 token/动画/硬编码色）·
禁止能力未误开放（S5a-d：FORBIDDEN 8 项全在、白名单零禁区、adapter 四文件零禁区名、段位仍 actuate）·
RunView C3/C4/C5 交互状态全集在位（S6）。

### R 回归（7/7，全部首跑通过、零重跑）

| 套件 | 结果 |
|---|---|
| verify_tech07c.py（C1） | 16/16 |
| verify_tech07c2.py（C2） | 25/25 |
| verify_tech07c3.py（C3） | 27/27 |
| verify_tech07c4.py（C4） | 25/25 + 1 Deferred |
| verify_tech07c5.py（C5，含其内部全量嵌套回归） | 24/24 |
| verify_tech02_workspace.py（TECH-02 冻结域门禁） | 11/11 |
| verify_contracts.py（snapshot v1 契约） | exit 0 |

### D 真实环境（6/6，charmap + 真 core + 真 Edge 页面，全部非 mock）

| # | 场景 | 证据 |
|---|---|---|
| D1 | 快照链实例还原 | chip `快照：已恢复 1 个窗口（同运行期）`；rect 精确回归 `{x:18,y:80,w:572,h:536}` |
| D2 | 快照链失败路径 | 杀软件后 restore → chip `…跳过 1：missing`；窗口 before=0 after=0（**零启动**） |
| D3 | 布局链模板语义 | 绑定=True；chip `◐ 布局部分应用 0/1 · 跳过 1（charmap:未运行）`；窗口=0（**零启动**） |
| D4 | 模式链重建语义 | `/mode/restore` 后 charmap 真实回归：pid_old=41312 → pid_new=41652（**唯一启动链实证**） |
| D5 | offline fail-closed | 杀 core 后：快照 chip `…跳过 1：offline`、布局 chip `✕ 未连接 —— 应用未执行`，无伪成功 |
| D6 | 不产生伪事实 | UI 投影 10 项 ⊆ core 真实窗口 13 项，伪造=无 |

## 5. 能力边界（C6 后）

保持 C5 收官状态不变：观察 + 受限摆位（place）+ 实例快照（手动 capture/restore）+ 模板布局（手动 save/apply）+ 模式重建（mode_restore，ModeBar）。
**未新增任何能力、未放开任何禁区、未改任何冻结域。**

## 6. 登记在案（留给后续，未实施）

- Run 页「退出模式」入口（PD-001）：需产品口径（exitMode 为硬杀语义，入口设计需谨慎）。
- 焦点恢复（A）/ F5 自动恢复编排（C）/ 优雅关闭（F0）：冻结理由与前置条件见 checklist §0，未解除。
- db_layout_upsert slots 无 schema 冻结；exePath 大小写敏感；windows_place alwaysOnTop 形参无效（沿袭登记）。

## 7. 停止声明

C6 按 Phase 0~2 完成：checklist ✅ · implementation report（本文件）✅ · verify_tech07c6.py ✅（27/27）· 回归结果 ✅（7/7 首跑）。
四项停止条件均未触发。**未明确开启 C7 前，不继续扩展。**
