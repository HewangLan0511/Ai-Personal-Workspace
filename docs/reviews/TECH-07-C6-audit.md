# TECH-07-C6 审计报告 —— Phase 0~2 只读审计（C5 后续阶段）

> ⚠️ **已由 `docs/tech/TECH-07-C6-audit-report.md`（决策版，2026-09-16 晚）接替** —— 本文件保留为同日早轮的同源审计记录，后续以 tech 目录决策版为准。

> 日期：2026-09-16
> 性质：**只读审计**。零代码改动、零 boundary 调整、零 RunView/adapter 改动、零新增 command、零 schema/token 变更。
> 输入基线：C5 24/24 全绿 · C4 25/25 + 1 Deferred · C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 · 契约套件 exit 0
> 配套：`docs/tech/TECH-07-C6-checklist.md`（C6-01~06 逐项事实）

---

## 1. 当前状态总结

### 已完成

| 阶段 | 能力 | 出口证据 |
|---|---|---|
| **C1** | `/run` 页壳（run-head + 状态栏 + appbar + 舞台投影 + minimap）+ UI-FUSION-STANDARD v1 | verify_tech07c 16/16 |
| **C2** | observe 真值接线：facts-in 七项聚合投影、connectivity 三档（connected/degraded/offline）、DOM identity 冻结 | verify_tech07c2 25/25 |
| **C3** | actuate（唯一窗口控制）：windows_place 拖拽/缩放落位，归一化 intent → 物理像素，归属三重校验（unbound 拒绝） | verify_tech07c3 27/27 |
| **C4** | snapshot：真实探针 capture → 冻结 v1 校验 → config 原子落库；restore 两层匹配（hwnd+pid / exePath）+ 逐窗再校验 + safeRect 拓扑修正；同运行期与跨重启恢复均真实验收 | verify_tech07c4 25/25 + 1 Deferred（E：ambiguous 结构性不可构造） |
| **C5** | layout save/apply：受管窗口排布 → db_layout_upsert（apps.name + 归一化 rect，无实例身份）；模式绑定布局 → layout_apply（skip 语义透传、不自动启动）；RunView 两按钮接线 | verify_tech07c5 24/24 |

### 未完成

- **C6：未知**（本报告 §4 候选，待拍板）。
- 悬置方向（文档源反推，均未立项）：F5 跨重启自动恢复编排、F0 优雅关闭（core）、F3 尾巴（前台双向同步等原型交互）、B/C/D/E/F 候选（见 §3）。

---

## 2. 能力矩阵（core 事实，不判断是否启用）

### 2.1 workspace 相关 core 能力

| 能力 | 已存在 | 所在位置 | 是否冻结 | 风险 |
|---|---|---|---|---|
| 窗口枚举 windows_list | ✅ | `window_manager/window.rs:115` + `commands.rs:200` + GET /windows | adapter 只读白名单 | WindowInfo **无 exePath**（exePath 只能走登记证据链） |
| 按 pid/title 查窗 windows_find | ✅ | `commands.rs:206` | **adapter 禁区** | 可被用于绕过归属判据，保持禁 |
| 读矩形 windows_rect | ✅ | `commands.rs:219` | **adapter 禁区** | 同上 |
| 摆位 windows_place | ✅ | `window.rs:154` + `commands.rs:228` | adapter 白名单（C3） | `alwaysOnTop` 形参实际无效（PW-INTEGRATION-003 偏差登记，不阻塞）；拖拽路径 x+w 可越界（C5-06 登记） |
| **激活 windows_activate** | ✅ | `window.rs:190` + `commands.rs:247` + POST /windows/{hwnd}/activate | **core 有、adapter 禁**（C3/C4 决定：不恢复焦点） | 解禁 = C5 审计候选 B，需反转禁区 + 改 verify 判据；`is_foreground` 已在（`window.rs:219`），前台事实有读取能力 |
| **关闭窗口 windows_close** | ❌ **core 不存在** | 无 command；`window.rs` 无 close/WM_CLOSE 优雅关闭 | —（能力缺失，非冻结） | B 设计 F0（优雅关闭）未落地；`mode_exit` 硬杀语义（07-A R-1）。候选方向若涉"关窗/退模式收尾"需先补 core 能力 |
| 布局应用 layout_apply | ✅ | `window_manager/apply.rs:78` + `commands.rs:179` | adapter 白名单（C5） | resolve_pid 按 apps.name 大小写不敏感、一 app 一 pid；未运行 skip，不启动 |
| 布局落库 db_layout_upsert | ✅ | `commands.rs:439` + POST /db/layouts | adapter 白名单（C5） | slots 为自由 JSON（无 schema 冻结）——若 C6 动 slots 结构，建议先冻结契约 |
| 捕获环境→建模式 modes_capture_current | ✅ | `commands.rs` + POST /mode/capture | **adapter 禁区** | 语义超出（建布局+建模式），C5 已裁决不用 |
| 模式恢复 mode_restore | ✅ | `commands.rs:392` + POST /mode/restore | **adapter 禁区**；**ModeBar.vue:68 直连在用** | 恢复语义双链路并存（C5 审计 §7.1-5，决策"暂不收敛"） |
| 快照持久化（专用命令） | ❌ 无 | 走 get_config/put_config + `workspace.snapshot.last`（config.rs 三处登记，object 类型） | 快照 v1 契约冻结（schema + x-pw-v2-forbidden） | 无快照历史/自动触发的 core 侧入口（符合 v1） |
| 启动软件 apps_launch | ✅ | `commands.rs:106` | **adapter 禁区**（模式流水线内部使用） | — |
| 运行注册表 apps_running | ✅ | `commands.rs:100` | adapter 白名单（只读） | **一 app 一 pid** 结构 —— 多实例归属的硬约束（见 §5） |

### 2.2 UI adapter 出口现状（`workspaceAdapter`）

facts（snapshot/windows/modeProgress/layouts/monitors/modes/apps/lastSnapshot）+ actions（applyMode/cancelApply/exitMode/placeWindow）
+ windowSnapshot（capture/restore/status/currentRunId）+ layout（save/apply）。
白名单 15 项 / 禁区 8 项（见 checklist C6-03）。段位 = actuate。

---

## 3. 候选 C6 工作面（只能列候选，禁止执行）

来源：C5 审计 §7.2 剩余候选（A 已被 C5 采纳、G 违反冻结排除）+ B 设计 F 阶梯未落地项 + C4 报告 §十一。
按"最小修改面优先"排序列三候选：

### 候选 A —— 焦点恢复（windows_activate 解禁 + 前台双向同步）

- **内容**：C5 审计候选 B + B 设计 F3 尾巴（appbar⇄前台双向同步）合并：快照 restore 的 focus 步骤从"恒 skip"改为真实 activate；Run 页 appbar 接 `is_foreground` 事实做前台高亮/同步。
- **收益**：补齐原型交互的"前台感知"一块；快照恢复语义完整（不再只恢复几何）；core 零改动（windows_activate/is_foreground 均已在）。
- **涉及模块**：runtime/snapshot.ts（focus-skip 反转）、boundary.ts（windows_activate 移入白名单 + windows_find/windows_rect 是否需要一并评估）、RunView（前台高亮 + chip）、verify_tech07c4/c5 判据更新、新 c6 verify。
- **是否需要 core 改动**：**否**（windows_activate、is_foreground 均已存在且已验收）。
- **是否突破冻结域**：否（不动 snapshot v1 schema；focus 字段已存在于契约中，当前恒 null）。风险点：C3 起的"不激活"是产品决定，反转需要新的产品口径 + 旧判据显式记账反转。

### 候选 B —— 恢复语义收敛（mode_restore ⇄ snapshot restore 分层）

- **内容**：C5 审计候选 C：明确"模式恢复（core 硬杀重建）"与"工作区快照恢复（实例身份摆位）"的分层口径；ModeBar 直连改走 adapter（或明确豁免登记）；Run 页是否补"退出模式/完成工作"入口（PD-001）。
- **收益**：消除双链路并存的心智负担与误用面（用户在两个入口触发两种语义完全不同的"恢复"）；让 adapter 消费规则全 UI 一致。
- **涉及模块**：ModeBar（直连收敛）、RunView（入口决策）、boundary 判据不变或微调、verify_tech07c2/c3 判据核对。
- **是否需要 core 改动**：否～小（若要求 mode_exit 优雅化则升级为 F0 方向，需要 core）。
- **是否突破冻结域**：否。风险点：需要产品口径拍板（这是"文档工作 + 小接线"，不是能力增量）。

### 候选 C —— F5 跨重启自动恢复编排（enter_mode 触发）

- **内容**：B 设计 F5：enter_mode → 读 `workspace.snapshot.last` → 身份再定位 → wait_ready → rectNorm 摆位 → 拓扑降级；把 C4 的"手动恢复按钮"升级为"进模式自动恢复"。
- **收益**：B 设计 F 阶梯的最后一块；"重启即回到工作状态"的完整故事线；复用 C4 全部恢复原语（两层匹配/safeRect/逐窗校验）。
- **涉及模块**：core（mode_apply 流水线挂钩或 UI 侧编排触发点）、runtime/snapshot.ts、facts/projection（wait_ready 需要 launching 进度事实）、RunView（prep overlay 接恢复进度）、verify（端到端：保存→退出→重启→恢复→几何比对）。
- **是否需要 core 改动**：**可能**（触发点放 core mode_apply 还是 UI 编排未定；wait_ready 需要进度事实出口，现有 mode_progress 是否覆盖待查）。
- **是否突破冻结域**：否（读既有快照，不写新结构）；但触发语义改变会触碰 C4 "trigger 只有 enter_mode 且当前为手动"的口径，需显式记账。

### 落选项（审计确认不可行/被拒，仅登记）

- **快照历史 / 自动快照 / hwnd 映射表**：违反 `x-pw-v2-forbidden`（契约机器可判），除非先解冻契约 —— 不做。
- **一 app 多实例归属**（C4-E 回 Real）：动归属判据核心（slots/apps_running 结构 + apps.path UNIQUE），改动面最大；C5 checklist 已 REJECTED，重提需独立契约评审。
- **多显示器**：C4 明确 Deferred，主显示器假设遍布三层（layout.rs to_pixels / actions.ts / facts）；独立立项，不宜与 UI 接线混合。
- **exePath 大小写不敏感比较**：一行级改动但改变 C4 已验收语义，可并入任一候选的顺手项（需回归 C4）。
- **F0 优雅关闭（core close(hwnd) + mode_exit 优雅化）**：core 必改；若候选 B/C 落地时需要"关窗收尾"，则作为其 core 前置子项，不建议单独立阶段。

---

## 4. 阻塞决策点（需白宇确认）

1. **【阻塞】C6 目标 = A / B / C 中的哪一个（或组合/其他）？** —— 全部文档源无 C6 定义；C5 审计 §7.2 的剩余候选是唯一结构化来源。
2. **【若选 A】windows_activate 禁区反转的产品口径**：C3 起的"不恢复前台焦点"是明示决定；解禁后 verify_tech07c2/c3/c4 的相关判据要显式记账反转（不是偷偷改）。
3. **【若选 B】mode_restore 收敛口径**：二选一 / 分层并存？ModeBar 直连是豁免登记还是必须改走 adapter？Run 页要不要"退出模式"入口？
4. **【若选 C】触发点位置**：core mode_apply 流水线内自动恢复，还是 UI 侧 enter_mode 成功后编排？后者零 core 改动但要求 UI 编排器承担 wait_ready 轮询。另：是否同时把 C4 的手动恢复按钮保留（建议保留，作为自动恢复失败的手动兜底）。
5. **【非阻塞，登记在案】**：db_layout_upsert 的 slots 无 schema 冻结（C5 checklist §对比表指出的差距）；exePath 比较大小写敏感（C4 §六）；windows_place alwaysOnTop 无效 + 拖拽 x+w 可越界（PW-INTEGRATION-003 / C5-06）—— 均不阻塞方向选择，但若 C6 动到相邻模块建议顺手登记处理。

---

## 5. 跨重启身份链现状（Phase 1 重点 5，事实登记）

| 标识 | 生命周期 | 来源 / 结构 | 关系 |
|---|---|---|---|
| `appId` | 跨重启持久 | `apps` 表（database schema） | 一 appId 绑定一 `path`（**UNIQUE**）+ 一 `name` |
| `app.name` | 跨重启持久 | apps 表 | `resolve_pid` 按 name **大小写不敏感**匹配（apply.rs） |
| `app.path` | 跨重启持久 | apps 表，BINARY 排序 UNIQUE | exePath 的唯一合法来源（经登记证据链） |
| `pid` | 每次开机/进程 | `apps_running`（appId→pid，**一 app 一 pid**）+ mode 流水线 slots | 归属判据的根；窗口归属 = pid ∈ slots ∪ running |
| `hwnd` | 每次开机/窗口 | windows_list（WindowInfo，无 exePath） | 快照 v1 的窗口键；跨重启必然失效 |

**支持能力事实**：
- **多实例（同 exe 多进程）**：❌ 不支持 —— `apps.path` UNIQUE ⇒ 一 appId 一 exe；`apps_running` 一 app 一 pid ⇒ 第二实例拿不到归属证据（C4-E 三条构造路线实测失败，Deferred）。
- **同 exe 多窗口（同 pid）**：◐ 部分 —— windows_list 枚举全部顶层窗口且同 pid 窗口都"归属"；但流水线/恢复的 find_main_window 取**主窗口**（面积最大），非主窗口无独立身份。
- **模糊匹配**：❌ 禁止 —— 按标题猜 exePath/归属被 C4 §5 明令禁止；唯一"软"匹配是 apps.name 大小写不敏感。exePath 比较是大小写敏感 `===`（Windows 路径理论上可出现两种写法，C4 §六登记未处理）。

---

## 6. 停止声明

本报告为 Phase 0~2 只读产物，**零代码改动**。产出仅两个新文档：本报告 + `docs/tech/TECH-07-C6-checklist.md`。
冻结域 hash 全部与基线一致（见 checklist C6-05）；六套验证脚本就位且可复用（见 checklist C6-06）。
**立即停止，等待方向确认。**
