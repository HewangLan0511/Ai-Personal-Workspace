# TECH-07-B-0 设计：Workspace Runtime 聚合层（只设计，不编码）

> 性质：**架构设计文档**。本轮零改码、零迁移、零新表、零新命令。
> 解决的问题：**UI 原型 Workspace（纯内存演示态）与真实程序实体（进程/窗口/模式）的错位**。
> 审计基础：`docs/tech/TECH-07-A-window-capability-audit.md`（窗口能力与链路现状）。

---

## 一、五域现状盘点（设计的输入事实）

| 域 | 载体 | 关键形态 | 写入者 |
|---|---|---|---|
| work_modes | SQLite 表（迁移 0001 建、0003 加 switch_policy） | `WorkMode{id, name, apps[名], openTargets, layout?, aiProfile?, autoApply, switchPolicy(additive/exclusive/ask), useCount, lastUsedAt}`，软删除过滤 | 仅 Rust（`ModeRepo`） |
| layouts | SQLite 表（0001 建、0004 加 ai_sidebar）+ `config/layouts/*.json` **派生导出** | `Layout{name, monitor, slots[{app, rect(归一化), z, alwaysOnTop, maximized}], aiSidebar?}`；**库是唯一真相，JSON 是导出品** | 仅 Rust（`layout_upsert` 唯一写入口） |
| window | 纯内存 Win32 事实 | `WindowInfo{hwnd:isize, pid, title, class, rect, minimized/maximized}`；place/activate/minimize/open_path；**无优雅关闭（只有 TerminateProcess）** | 无持久化（volatile） |
| scheduler | `work_modes` 定义 + 内存 `RunRecord`（`modes_run`） | `RunRecord{current, launched_by(mode→appIds), last_snapshot(mode→appIds)}`；七步流水线；显式状态机；`mode.current` / `mode.switch_memory` 落 config | 内存态 + config |
| snapshot | **契约冻结、接口就绪、零执行** | `WorkspaceSnapshotV1`（hwnd/pid/exeName/exePath/appId/rectPx/rectNorm/state/zIndex + 显示器表 + 模式上下文 managed/launchedAppIds）；UI 侧 `capture/restore/validate` 纯函数；`runtime.ts` 预留 `injectedProbe / persistedReader / currentRunId` 三注入点；**core 侧无写入者，`workspace.snapshot.last` 键未登记白名单** | （待 B-1） |

事件面（`event_bus`，已桥接 webview 通道 `pw://event`，前端 `eventBridge.ts` 可订阅）：
`MODE_CHANGED / MODE_APPLY_PROGRESS / MODE_APPLY_FAILED / APP_OPENED / APP_CLOSED / WINDOW_LAYOUT_APPLIED / WINDOW_LAYOUT_FAILED`。
⚠️ 事件桥是 Tauri 通道；浏览器降级层收不到，UI 侧需保留轮询兜底（ModeView 的 progress 轮询已是先例）。

UI 原型域（`ui/src/workspace/`，TECH-02 冻结）：
`WorkspaceRuntime{workspaceId, name, goal, mode, apps[WorkspaceApp{appId, name, status(running/waiting/closed), windowId?, layoutNode?}], layout}` + `WorkspaceTemplate{id, name, goal, apps, layoutSnapshot(DOM 几何)}` + `LayoutSnapshot`（**DOM 几何，与系统窗口快照是两个东西**）。
**硬边界**：零 core（不 import `@/api`）、零持久化、深冻结防篡改、`verify_tech02` T1 锁方法集合。

## 二、核心决策：Workspace 与 Mode 的关系

> **Mode 是"配方"（定义态），Workspace 是"一次开火做出来的菜"（运行态实例）。**

| 维度 | Mode（工作模式） | Workspace（工作空间） |
|---|---|---|
| 本质 | 可复用的启动配方：软件名单 + 布局名 + 文件入口 + AI 配置 + 切换策略 | 一次模式执行的运行期聚合：真实进程 + 真实窗口 + 落位结果 + 快照 |
| 载体 | `work_modes` 表（持久） | `RunRecord`（内存）+ `workspace.snapshot.last`（config 快照，B-1）—— **不新增表/列** |
| 数量 | 0..N | 同一时刻 **0..1 活跃**（`modes_run.current` 承载）；历史只有"最近一份快照"（v1 契约禁止 history） |
| 生命周期 | 用户编辑/删除独立发生 | 随 `mode_apply` 诞生、随 `mode_exit`/进程退出消亡；**定义变更不追踪到已打开的 Workspace**（名字取 apply 时刻的快照值） |
| 身份 | `modeId`（稳定） | `runId`（core 运行期）+ `snapshotId`；hwnd/pid **volatile**，持久身份只有 appId/exePath |

由此派生三条定案：

1. **UI 的 `WorkspaceTemplate` 不升级为持久实体** —— 它是 `WorkMode` 的**只读投影**：
   `template.name ← mode.name`、`template.apps ← mode.apps × apps 表`、
   `template.layoutSnapshot ← layouts.slots 换算`。映射在适配器完成，**禁止双写、禁止给模板建表**。
2. **`WorkspaceApp.windowId ← hwnd`、`appId ← apps.id` 的字符串化映射**只在适配器做；
   store 域内形状一字不改（`verify_tech02` T1 门禁不破）。
3. **`WorkspaceApp.status` 语义对齐真实事实**：
   `waiting` = 已 `mark_launched` 但 `find_main_window(pid)` 尚无可见窗口；
   `running` = pid 存活且 hwnd 在；`closed` = `reap_exited` 判死或被模式收尾关闭。

## 三、聚合层设计（四层模型）

```
L3 消费层   DashboardView / ModeView / DevWorkspaceHarness / 未来工作台页
            ── 只经 workspaceRuntime 门面取数，不碰 @/api
L2 聚合层   ★ 本设计对象 ★
            core 侧：ModeRunAggregate = WorkMode + RunRecord + RunningApps
                     + windows_list(按 launched_by 过滤) + snapshot 读
                     —— 全部由现有命令/查询组装，零新命令
            UI  侧：runtime.aggregate() = 注入适配器把 L0/L1 事实映射成 store 形状
L1 快照层   workspace.snapshot.last（config 键；唯一写入者 core；触发=enter_mode）
            WorkspaceSnapshotV1（契约已冻结，PW-INTEGRATION-003）
L0 事实层   work_modes / layouts / apps 表 · RunningApps · window_manager
            RunRecord · event_bus —— 已存在，一律不动
```

**聚合视图（ModeRunAggregate，设计稿）**：

```
{
  runId,                       // core 运行期标识（hwnd 有效性边界）
  mode: { id, name, switchPolicy },   // apply 时刻的名字快照，不追踪后续编辑
  current: bool,               // modes_run.current === mode.name
  apps: [{                     // mode.apps × apps 表 × RunningApps × windows_list
    appId, name, path,
    pid?,                      // RunningApps 登记（.lnk 启动为 null → status 恒 waiting/closed）
    hwnd?, rect?,              // find_main_window(pid) 现值（volatile，仅运行期有效）
    status,                    // running / waiting / closed（§二 定案 3）
    launchedByMode: bool,      // RunRecord.launched_by 包含 → exit/exclusive 才会碰它
  }],
  layout: { name?, monitor?, placed/skipped/failed },  // 最近一次 WINDOW_LAYOUT_APPLIED
  snapshot: { id?, valid?, runIdMatch? },              // workspace.snapshot.last 摘要
}
```

## 四、数据流图

### ① 进入模式（写路径 —— 单一写入口不变）

```
用户点击模式（ModeView）
  └→ mode_apply(modeId, policy?)            【既有命令】
       └→ scheduler 七步：
          校验 ─→ 并发启动 CreateProcessW ─→ pid
              ─→ wait_ready: find_main_window(pid) ─→ hwnd
              ─→ arrange: layout_pixels + place/activate ─→ WINDOW_LAYOUT_APPLIED
              ─→ open_targets ─→ ai_profile ─→ 状态机 Done
       ├→ RunRecord.mark_launched(mode, appIds)     【内存】
       ├→ config.set("mode.current")                【持久·既有键】
       ├→ [B-1] snapshot 聚合 → config.set("workspace.snapshot.last")  【持久·新键，显式记账】
       └→ 事件：MODE_CHANGED / APP_OPENED / WINDOW_LAYOUT_APPLIED
              └→ 桥 pw://event → eventBridge → UI 适配器 → workspaceRuntime
```

### ② 消费（读路径 —— 聚合层只读组装）

```
工作台页 ─→ workspaceRuntime.aggregate()
              └→ 注入适配器（域外，可 import @/api）
                   ├─ modes_current / modes_get        【既有】
                   ├─ running.snapshot + windows_list   【既有】
                   ├─ snapshot 读（persistedReader 注入）【L1】
                   └─ 映射 → 深冻结视图 → store 订阅者 render
   轮询兜底：事件桥不可用时（浏览器降级层）按 1~2s 轮询聚合视图
```

### ③ 恢复（三级路线，详见 §六）

```
重启后
  ├─ 一级（会话内重排）：WINDOW_LAYOUT_APPLIED 失败槽位 → 重试已有
  ├─ 二级（模式级重放）：mode_restore ─→ 重放 apply_mode（重新启动 + 重排列）【既有】
  └─ 三级（窗口级复原）：读 workspace.snapshot.last → validate
        ├─ runId 不匹配（必然，跨重启）→ 身份再定位：
        │    按 exePath/appId 找已运行实例（windows_list + process_image_name）
        │    缺 → launch_registered 重启 → wait_ready 拿新 hwnd
        ├─ 显示器拓扑校验（bounds/work 一致才用 rectNorm；不一致降级主屏）
        └─ place(newHwnd, rectNorm×work) → 复位完成
```

## 五、Runtime 边界（硬边界清单，B 段实施时逐条可验）

1. **聚合层是只读组装器**：不写表、不摆窗、不杀进程；一切写动作仍只经
   `mode_apply / mode_exit / layout_apply / modes_*`（单一写入口不变）。
2. **Workspace 不落库**：运行期身份活在 RunRecord（内存）+ `workspace.snapshot.last`（config 快照）；零新表、零新列、零迁移。
3. **hwnd/pid 是 volatile 事实**：可进聚合视图，不进持久身份；持久身份 = appId / exePath（快照契约已定）。
4. **Mode 定义态与 Workspace 运行态解耦**：编辑/删除 Mode 不影响已打开 Workspace；UI 显示 apply 时刻的名字。
5. **UI workspace 域保持零 core**：事实经**注入适配器**（域外新文件，如 `ui/src/workspace/adapter.ts`）进入；
   `store.ts / layout.ts / snapshot.ts / runtime.ts` 的形状与门禁方法集合不改。
6. **快照唯一写入者是 core**：UI 侧只读/只组装/只校验（契约既有约束，沿袭）；触发点只有 `enter_mode`（v1 禁止切换时写）。
7. **`workspace.snapshot.last` 是 config 键不是表**：登记方式沿 TECH-06-B `ai.models.registry` 同法
   （KEYS / expected_type=string / default_for=""，契约版本 +1）——**键登记不是"新增命令"，但仍是显式记账项**，B-1 实施时列入 LEDGER。

## 六、后续窗口恢复路线（里程碑排序）

| 里程碑 | 内容 | 依赖 | 验收锚点 |
|---|---|---|---|
| **B-1 采集+落盘** | core 聚合快照（windows_list × RunningApps × apps 表反查 appId/exePath × 显示器归属 → rectNorm）→ 写 `workspace.snapshot.last`（登记键 + 契约 v14） | L0 全部现成 | 真 core：enter_mode 后直读 SQLite（JSON 编码形态）+ 解码 == 快照（TECH-06-B C3 同法） |
| **B-2 UI 受控解冻** | 域外适配器注入 `injectedProbe / persistedReader / currentRunId`；`getRecoveryStatus()` 的 blockers（probe-not-wired / runid-mismatch）开始反映真实值；工作台显示真实 pid/hwnd/status | B-1 | verify_tech02 门禁仍全绿（方法集合/零 core 不破）+ 新增注入器验收 |
| **B-3 执行侧放开** | core"按快照恢复"编排（身份再定位 → wait_ready → rectNorm 摆位 → 拓扑不一致降级）；`recovery.executable` 由真值驱动；**优雅关闭（WM_CLOSE→超时回退 terminate）先行补齐**（07-A R-1） | B-1、B-2 | 端到端：真启动记事本/资源管理器 → enter_mode → 退出 → 重启 core → 恢复 → 窗口几何比对（rectNorm 容差 0.02） |

验收基建沿用：`verify_stage9` 双启动（真重启）、TECH-06-B 的 boot() 探活（端口残留坑）、
Node 直编纯函数（snapshot.ts 可直接穷举恢复计划）。

## 七、开放问题（B-1 实施前需定案）

1. 同 exe 多窗口（浏览器多窗）：身份再定位取 `find_main_window`（面积最大）会丢其余窗口；
   建议按快照条目逐条用 title 前缀辅助匹配，**匹配失败降级 skip 并上报，不猜**（07-A R-2）。
2. `.lnk` 应用（pid_tracked=false）：快照条目 pid 为 null → 恢复时按 exePath ShellExecute 重启但不等待就绪，如实降级。
3. 事件桥仅 Tauri 通道：浏览器降级层的聚合视图新鲜度依赖轮询，工作台需标注"数据时刻"。
4. `mode.switch_memory` / 快照的交互：exclusive 切换关闭上一模式软件**前**才写快照（现 pipeline 顺序是
   先快照后关闭 —— 已正确），B-1 保持该顺序并加测试锚。

---

## 附：约束自查

| 约束 | 自查 |
|---|---|
| 不新增数据库迁移 | ✅ Workspace 全部落在 RunRecord（内存）+ config 键；键登记在 B-1 显式记账，非迁移 |
| 不新增表 | ✅ 零 |
| 不新增命令（本轮设计） | ✅ 聚合视图 = 现有命令/查询组装；若 B-1 实施发现必须新增**读**命令，按显式记账处理，不在本设计承诺内 |
| 不修改代码 | ✅ 本轮仅产出文档 |
| 不破坏已有 mode/layout/window | ✅ 单一写入口不变；L0 全部不动；UI store 形状不动 |
