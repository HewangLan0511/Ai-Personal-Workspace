# TECH-07-C6 审计与决策报告 —— Phase 0~2（只读，零代码改动）

> 日期：2026-09-16
> 性质：**只读审计 + 决策矩阵**。未修改 boundary.ts / RunView / runtime / core Rust / snapshot schema / verify 脚本。
> 说明：上一轮同源审计 `docs/reviews/TECH-07-C6-audit.md` 为本报告的评审目录版；**本报告为决策版（以本文件为准）**。
> 配套事实底稿：`docs/tech/TECH-07-C6-checklist.md`（C6-01~04 逐项）。

---

## 1. 当前状态：C1~C5 完整链路

| 阶段 | 能力 | 验收结果 | 当前边界 |
|---|---|---|---|
| **C1 shell** | `/run` 页壳：run-head + 状态栏 + appbar + 舞台窗口投影 + minimap；UI-FUSION-STANDARD v1 立标 | `verify_tech07c.py` **16/16** | 纯只读投影；窗口控制类按钮 disabled（后续阶段逐步接线） |
| **C2 observe** | facts-in 真值接线：7 项聚合投影（windows/mode/apps/progress/layouts/monitors/modes）+ connectivity 三档（connected/degraded/offline）+ DOM identity 冻结 | `verify_tech07c2.py` **25/25** | 零窗口控制；投影不伪造（UI 集合 ⊆ core 真实窗口）；offline 作废 lastFacts 缓存 |
| **C3 place** | actuate 唯一窗口控制：拖拽/缩放 → windows_place；归属三重校验（段位/∈最新 facts 且 belongsToMode/manageable，unbound 拒绝）；归一化 intent → 物理像素 | `verify_tech07c3.py` **27/27** | 仅 Move/Resize；windows_activate/close/find/rect、mode_restore、apps_launch 仍在 FORBIDDEN |
| **C4 snapshot** | 实例快照：真实探针 capture → 冻结 v1 校验 → config `workspace.snapshot.last` 原子落库；restore 两层匹配（hwnd+pid 同运行期 / exePath 跨重启）+ 逐窗再校验 + safeRect 拓扑修正；focus 步骤恒 skip | `verify_tech07c4.py` **25/25 + 1 Deferred**（E：ambiguous 结构性不可构造——apps.path UNIQUE + 一 app 一 pid） | 不激活焦点、不启动软件、不关窗；快照历史/自动触发属 v2 禁区 |
| **C5 layout** | 模板布局：保存（受管窗口排布 → db_layout_upsert，slot=apps.name+归一化 rect，命名 run-<模式>-<时间戳>）；应用（模式绑定布局 → layout_apply，未运行 skip 不启动）；RunView 两按钮接线 + 结果 chip | `verify_tech07c5.py` **24/24**（2026-09-16 晚全绿） | 模板语义：不做跨重启身份、不做 fail-closed 恢复契约；与 snapshot 双轨并存，互不读写 |

**链路整体能力** = 观察 + 受限摆位 + 实例快照（手动 capture/restore）+ 模板布局（手动 save/apply）。
**全链回归基线（2026-09-16 晚）**：C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 · 契约套件 exit 0 · C4 25/25+1D（均嵌在 C5 R 段内首跑通过）。

### 已知悬置（来源：C4 §十一 / C5 audit §7.4 / B 设计 §五）

- B 设计未落地项：**F0 优雅关闭（core）**、**F3 尾巴（appbar⇄前台双向同步、Esc 链、吸附三类）**、**F5 恢复执行编排**。
- 登记在案小项：windows_place alwaysOnTop 形参无效（PW-INTEGRATION-003）、拖拽 x+w 可越界（C5-06）、exePath 比较大小写敏感（C4 §六）、db_layout_upsert slots 无 schema 冻结。

---

## 2. C6 候选决策矩阵

前置事实（Phase 1 代码审计结论，详见 checklist C6-02/C6-04）：
- `windows_activate` core **已存在**（`hwnd: i64 → {hwnd, foreground}`），adapter 禁区中；
- `windows_close` core **不存在**（无命令、无优雅关闭实现，F0 未落地）；
- `mode_restore` 当前行为 = 重跑模式流水线（config `mode.current` → apply_mode 硬语义重建），且 **ModeBar.vue:68 直连绕过 adapter**（复核确认仍在）；
- 快照恢复 = UI 侧编排（runtime/snapshot.ts），core 无快照感知；layout_apply = 模板摆位（未运行 skip）。

| 方向 | 内容 | 是否需要 core 改动 | 风险 | 冻结影响 | 验证难度 |
|---|---|---|---|---|---|
| **A 焦点恢复** | adapter 白名单 += windows_activate；C4 restore 的 focus 步骤从"恒 skip"转真实 activate；快照 v1 `foregroundHwnd` 接真值；（可并入 F3 尾巴：appbar 接 is_foreground 做前台高亮） | **否**（activate/is_foreground 均已存在） | 中：焦点断言在无头环境不稳（验收设计难点）；C3/C4"不激活"产品口径需显式反转记账 | 否（schema 不动；foregroundHwnd 字段已存在，当前恒 null） | **中高**（真实前台链路自动化弱） |
| **B 恢复语义收敛** | 裁决 mode_restore（重建）/ snapshot restore（实例还原）/ layout_apply（模板摆位）三者口径与入口关系；ModeBar 直连收敛走 adapter（或豁免登记）；Run 页是否补"退出模式"入口（PD-001） | **否～小**（若要求 mode_exit 优雅化则升级为 F0 子项，需 core） | 低～中：纯口径 + 小接线；主要风险是产品语义拍错方向造成用户心智混乱 | 否 | **低**（判据核对 + ModeBar 接线 + 文档） |
| **C F5 自动恢复编排** | enter_mode 成功后自动执行快照恢复（身份再定位 → wait_ready → rectNorm 摆位 → 拓扑降级），手动恢复按钮保留为兜底 | **看编排位置**：UI orchestration = 否；core lifecycle = 是（apply_mode 挂钩 + wait_ready 事实出口） | 高：端到端时序（重启/重登记/wait_ready）；触发语义触碰 C4"手动恢复"口径，需显式记账；失败兜底策略复杂 | 否（只读既有快照，不写新结构） | **高**（端到端重启编排） |
| 落选项：快照历史/自动快照/hwnd 映射 | — | — | — | **是（违反 x-pw-v2-forbidden，机器可判）** | — |
| 落选项：一 app 多实例归属（C4-E 回 Real） | slots/apps_running 结构 + apps.path UNIQUE | 是 | 高（动归属判据核心） | schema 不动但归属语义变 | 高；C5 已 REJECTED，重提需独立契约评审 |
| 落选项：多显示器 | to_pixels/actions/facts 三层主屏假设 | 是 | 高 | 否 | 高；C4 Deferred |
| 落选项：F0 优雅关闭（单独立项） | core close(hwnd) + mode_exit 优雅化 | 是 | 中 | 否 | 中；建议仅作为 B/C 需要"关窗收尾"时的前置子项，不单独立阶段 |

---

## 3. 阻塞决策点（等待产品拍板）

**① C6 目标选择：A / B / C / 组合？**

建议排序参考：B（最轻，先清口径）→ A（零 core 改动的能力增量）→ C（端到端编排，最重）。
组合允许（如 B+A 同阶段、C 独立阶段），但每个方向独立出判据与验收脚本。

**② 如果 A：是否允许 windows_activate 进入 adapter 白名单？**

- 影响面：boundary.ts FORBIDDEN→ALLOWED 反转 + verify_tech07c2/c3/c4 相关判据显式记账反转 + 快照 restore focus-skip 反转 + （可选）appbar 前台高亮。
- 需要拍板的子项：(a) 仅恢复路径允许 activate，还是前台高亮也放开？(b) windows_find/windows_rect 是否维持禁区（建议维持）？(c) 用户无操作时是否允许自动夺焦（建议：仅显式恢复动作触发，不做后台自动夺焦）。

**③ 如果 B：mode_restore 与 snapshot restore 的关系？**

| 方案 | 内容 | 代价 |
|---|---|---|
| 方案 1：并存 + 口径分层 | 两个入口保留，文档明确"重建 vs 实例还原"；ModeBar 直连豁免登记 | 最小；但 adapter 消费规则出现永久豁免口 |
| 方案 2：统一入口 | 恢复动作全部经 adapter（ModeBar 改走 runtime 门面或显式 service 层登记），语义分层不变 | 小（UI 接线）；消费规则恢复一致性 |
| 方案 3：废弃其中一个 | 明确哪个是唯一"恢复"（如 ModeBar 一键恢复改调 snapshot restore，或 Run 页快照恢复并入模式流水线） | 中～高：语义取舍 + 用户习惯迁移；若废 mode_restore 需评估"跨重启重拉软件"场景归属 |

**④ 如果 C：恢复编排位置？**

- **UI orchestration**：apply 成功后 UI 调 `adapter.windowSnapshot.restore()`。零 core 改动；wait_ready 轮询、失败兜底、进度展示全在 UI；快照数据已在 config（core 可读但无需感知）。
- **core lifecycle**：apply_mode 流水线内挂恢复步骤。需要 core 新增恢复编排代码 + wait_ready 事实出口（现 mode_progress 是否覆盖待查）+ 与 UI 进度展示对齐；改动面大，建议先出契约评审（同 C5 审计对 D/E 方向的建议）。
- 无论哪种：手动恢复按钮建议**保留**（自动恢复失败的手动兜底）；触发口径变化需在 C4 判据上显式记账。

---

## 4. 发现的问题（审计副产品，登记不修）

1. `mode_restore` 语义命名有歧义：实际是"重跑上次模式流水线"（重建），与用户直觉的"恢复工作区"（几何还原）不同——候选 B 的拍板素材。
2. ModeBar.vue:68 绕过 adapter 直连 `modeApi.restore()`——adapter 消费规则的既有豁免口（C5 审计登记，仍未收敛）。
3. db_layout_upsert 的 slots 为自由 JSON（core 仅校验数组），无 schema 冻结——若 C6 动 slots 结构需先冻结契约。
4. core 无优雅关闭能力（F0 未落地）：任何涉及"退出模式收尾/关窗"的候选都隐性依赖它。
5. 快照 v1 `foregroundHwnd` 恒 null（诚实降级）——候选 A 的直接改造点。
6. exePath 大小写敏感比较（C4 §六登记）；windows_place alwaysOnTop 形参无效（PW-INTEGRATION-003 登记）。

---

## 5. 停止声明

Phase 0~2 完成：checklist（C6-01~04）+ 本决策报告交付。冻结域 hash 与基线全部一致，TECH-02 域零触碰，
边界零反转，候选零实现，verify 脚本零改动。**等待拍板事项 ①②③④，拍板前不进入实现阶段。**
