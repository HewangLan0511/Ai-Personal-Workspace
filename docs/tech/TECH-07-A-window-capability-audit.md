# TECH-07-A 审计报告：工作空间真实窗口能力（只审计，不开发）

> 性质：**只读审计**，本轮零改码、零新增验收。
> 结论先行：**"工作模式真实启动"这条链路在 core 侧已经基本存在**（阶段 2/3/4 依次落地并验收过），
> TECH-07-B 的真实增量不是"从零实现启动"，而是三件事：
> **① UI 消费面收口（工作台接真实模式 API）② WorkspaceSnapshot v1 的真实采集/落盘/执行侧放开
> ③ 窗口优雅关闭补齐**。逐项见下。

---

## 一、Windows 窗口控制能力对照表

| # | 需求能力 | 现状 | 位置 | 说明 |
|---|---|---|---|---|
| 1 | 获取窗口句柄 | ✅ 已存在 | `core/src/window_manager/window.rs` | `list_windows()`（EnumWindows + 可见/非工具窗/正尺寸/有标题过滤）→ `WindowInfo{hwnd(isize), title, class_name, pid, visible, minimized, maximized, rect, area}`；`find_main_window(pid)`（面积最大）、`find_by_title()`。Tauri 命令 `windows_list / windows_find / windows_rect` 已暴露 |
| 2 | 获取进程 | ✅ 已存在 | `core/src/app_manager/launcher.rs`（CreateProcessW 返回 pid）+ `status.rs`（pid 存活轮询 `is_alive`，OpenProcess/GetExitCodeProcess）+ `device/processes.rs`（EnumProcesses 全量进程 + `process_image_name(pid)`→exe 名，QueryFullProcessImageNameW） | 窗口→pid→进程名 的完整链路已通；`modes_capture_current`（commands.rs:460）就在用它 |
| 3 | 移动窗口 | ✅ 已存在 | `window.rs::place()` | 先还原（IsIconic/IsZoomed→SW_RESTORE）再 SetWindowPos；最大化窗口直接摆是无效的这个坑已处理 |
| 4 | 缩放窗口 | ✅ 已存在（与 3 同一入口） | `window.rs::place(hwnd, rect, ...)` | 按像素矩形 set；布局层有归一化坐标→物理像素换算（`layout.rs::layout_pixels`，以工作区为基准）+ AI 侧栏留位（AiSidebar） |
| 5 | 激活窗口 | ✅ 已存在 | `window.rs::activate()` | AttachThreadInput 绕前台锁定 + BringWindowToTop + SetForegroundWindow；`is_foreground()` 判据；apply 按槽位 z 升序激活（z 大的后激活=在最上层） |
| 6a | 关闭窗口（优雅） | ❌ **缺失** | — | 没有 WM_CLOSE / PostMessage 路径。现状 `exit_mode` / exclusive 切换走 `kill_registered` → `terminate(pid)`（TerminateProcess **硬杀**，status.rs:99）。风险：VS Code / 浏览器未保存现场直接丢 |
| 6b | 隐藏窗口 | ❌ **缺失** | — | 只有 `minimize()`（SW_MINIMIZE，标注 dead_code）；无 SW_HIDE / SW_SHOW |
| 6c | 最小化/最大化 | ✅ 已存在 | `place(maximized=true)` / `minimize()` | — |
| 7 | 多屏 + DPI | ✅ 已存在 | `monitor.rs` | SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)（物理像素口径）+ EnumDisplayMonitors 工作区枚举；目标显示器不存在自动降级主屏（apply.rs degraded_monitor） |

## 二、启动链路逐环节对照：工作模式 → 应用列表 → 启动 → 获取窗口 → 绑定 → 布局

| 环节 | 现状 | 位置 |
|---|---|---|
| 工作模式（定义/持久化/策略） | ✅ | `scheduler/repository.rs`（WorkMode/ModeRepo，迁移 0004）+ `modes_*` 命令 9 个；切换策略 additive/exclusive/ask + `mode.switch_memory` 记忆 |
| 应用列表 | ✅ | `apps` 注册表（app_manager/repository.rs），路径白名单即启动依据，**禁止硬编码路径**（校验期拦截） |
| 启动软件 | ✅ | `launcher.rs` CreateProcessW（返回 pid，禁 shell 拼串；.lnk 走 ShellExecuteW 不跟踪 pid）；`launch_registered` 统一登记/事件 |
| 工作模式→并发启动→等待就绪→排列→开文件→AI→状态 七步 | ✅ | `scheduler/pipeline.rs::apply_mode`（并发线程+mpsc、单软件 15s 超时、就绪轮询 20s、45s 兜底、显式状态机、可取消、单点失败不中断、幂等 already_running） |
| 获取窗口（启动后） | ✅ | `wait_ready()`：轮询 `find_main_window(pid)` 拿 hwnd（splash 过滤天然生效），部分就绪可用 |
| 绑定 workspace（core 侧） | ✅ | `RunRecord`：`modes_run.mark_launched/lunched_by/current`——"模式只管理自己拉起的"（R-01），exit/exclusive 只碰登记内的 app |
| 绑定 workspace（UI 侧） | ❌ **缺失（有意为之）** | `ui/src/workspace/` 域**零 core**（store/layout/runtime/snapshot 四模块不 import `@/api`，TECH-03-B 冻结铁律）。UI 的 workspace 状态是内存态，与真实 pid/hwnd 无连接 |
| 调整布局 | ✅ | `window_manager/apply.rs::apply_layout`（z 序排序→重试 2 次×500ms→步进 80ms→激活；WINDOW_LAYOUT_APPLIED/FAILED 事件）；UI `LayoutView.vue` + `layoutService`（layout_apply / windows_place） |
| 保存当前桌面为模式 | ✅ | `modes_capture_current`（commands.rs:460）：枚举窗口→pid→exe 名→归一化坐标→建布局入库→建模式绑定。**"保存工作状态"的 v0 已经能用** |
| UI 一键进入/退出/进度 | ✅ | `ModeView.vue`（modeApi.apply + progress 轮询 + exit + captureCurrent）+ ModeBar/ProjectView/CurrentProjectWidget |

**链路断点只有一个：UI `workspace` 域与 core 真实窗口/进程状态之间没有通道。**
即：点"RGB-T视觉项目模式"→ VS Code/浏览器/AI 已经会真启动、真排列（ModeView 已能触发），
但"工作台"页面（`workspaceRuntime`，`DashboardView` 注释明言"不启动真实软件、不控制窗口、不做真实恢复"）
看不到真实窗口树、也无法从工作台发起布局调整。

## 三、Snapshot 接入可能性：保存 → 退出 → 重新进入 → 恢复窗口

**契约已冻结**（PW-INTEGRATION-003 / `docs/contracts/workspace-snapshot.v1.schema.json`），
前端接口面已备好（`ui/src/workspace/snapshot.ts`，纯函数、Node 可直编、TECH-05/06 验收持续覆盖）：

| 环节 | 现状 | 缺口（= TECH-07-B 的技术条件清单） |
|---|---|---|
| 数据结构 | ✅ `WorkspaceSnapshotV1`：窗口条目含 hwnd/pid/exeName/exePath/appId/title/className/monitorIndex/rectPx/rectNorm/state/zIndex + 显示器表 + 模式上下文（launchedAppIds/managed） | 无 |
| 采集 | ⚠️ 接口就绪、**恒 dryRun**：`runtime.ts` 留有 `injectedProbe`（WindowProbe）注入点，未注入 | **B-①：core 出一个"窗口全量快照"命令**（list_windows 已具备全部原料，只差聚合：+显示器归属 +rectNorm 换算 + exe 名 + appId 反查）并注入 probe |
| 落盘 | ❌ 键 `workspace.snapshot.last` **未登记** core config 白名单（config.rs 无 workspace.* 键），无写入者 | **B-②：登记键 + core 写入**（触发点契约已定：仅 `enter_mode`；v2 越界字段黑名单已在 UI 侧锁定） |
| 校验/计划 | ✅ `validateSnapshot` / `restoreSnapshot`（runId 失效语义：hwnd volatile，跨 runId 全部降级 skip 并说明，**不假装能按旧 hwnd 恢复**） | 无 |
| 恢复执行 | ❌ `recovery.executable` **恒 false**（四条红线：不杀进程/不启动软件/不写库/不碰未登记窗口——TECH-03-B 禁止项），blockers：`probe-not-wired` / `runid-mismatch` | **B-③：放开执行侧**。技术条件：①身份再定位——恢复时旧 hwnd/pid 必失效，按 exePath（appId）重新 launch_registered → `find_main_window(new_pid)` → 按 rectNorm 摆放（链路②④全部现成，只是编排顺序不同）；②runId 注入（core 启动时生成，随 probe/persistedReader 传入）；③UI 侧解冻一个受控通道（注入而非让 workspace 域直接 import `@/api`，保持冻结铁律） |
| 重启级恢复（粗粒度） | ✅ 已存在：`mode_restore`（重启后按 `mode.current` 重放 apply_mode=重新启动+重排列）；切换前快照 `snapshot_before_switch`（内存态） | 与 v1 快照是两级恢复：mode_restore=「模式级重放」，snapshot=「窗口位置级复原」，互补不冲突 |

**"保存→退出→重进→恢复"的最小技术条件**：B-① + B-② + B-③ 三件，全部落在已有骨架的预留注入点上，**不需要改快照契约、不需要改窗口编排层**。

## 四、风险登记

| # | 风险 | 等级 | 说明 |
|---|---|---|---|
| R-1 | `terminate()` 硬杀是当前唯一的"关闭"路径（exit_mode/exclusive/device_process_kill） | **高（数据丢失面）** | 用户未保存的 VS Code/浏览器现场会直接丢。B 应先补优雅关闭（WM_CLOSE→超时回退 terminate），并保持 R-01 边界（只碰模式自己拉起的） |
| R-2 | 快照恢复的身份再定位存在歧义：同 exe 多窗口（浏览器多窗、VS Code 多窗）时 `find_main_window` 只取面积最大 | 中 | v1 结构有 title/className 可辅助匹配；B 需定义"部分匹配失败→skip"的降级口径，不猜 |
| R-3 | UI workspace 域解冻方式：直接 import `@/api` 会破 TECH-03-B 冻结铁律（verify_tech02 T1 门禁会红） | 中 | 必须走既有注入点（`injectedProbe` / `persistedReader` / `currentRunId`），注入器放域外适配层 |
| R-4 | `.lnk` 启动无 pid（pid_tracked=false）→ 快照绑定与等待就绪对这类应用天然缺位 | 低 | 如实降级 skip；可在 B 登记为已知限制 |
| R-5 | DPI/多屏变化（恢复时显示器拓扑变了）→ rectNorm 基准漂移 | 中 | 契约已含显示器表（bounds/work），恢复前需校验拓扑一致，不一致降级 |
| R-6 | `modes_capture_current` 采集的是"全部可见窗口"还是"模式相关窗口"需要 B 明确口径（现实现排除自身进程后全量采集） | 低 | 建议保留全量（用户所见即所得），但需在 UI 展示时允许裁剪 |

## 五、TECH-07-B 工作清单建议（按依赖排序）

1. **优雅关闭补齐**（core）：`window.rs` 加 `close(hwnd)`（PostMessage WM_CLOSE + 超时回退 terminate）；`exit_mode`/exclusive 改走优雅关闭。机器证据：真启动记事本→exit→进程退出且窗口有 goodbye 机会。
2. **快照采集 + 落盘**（core）：`windows_snapshot()` 聚合命令（含 rectNorm/exe/appId 反查）+ 登记 `workspace.snapshot.last`（config 三处登记，沿 TECH-06-B 同法）+ `enter_mode` 触发写入。
3. **恢复执行侧放开**（core+UI 注入层）：core 提供"按快照恢复"命令（launch→wait_ready→place 编排，复用七步组件）；UI 侧适配器注入 probe/persistedReader/runId，把 `recovery.executable` 从常 false 变为真值驱动。
4. **工作台 UI 收口**（UI）：DashboardView/工作台从 `workspaceRuntime` 切到注入后的真实数据源；"调整窗口大小/保存布局/恢复"三个动作落到 windows_place / capture / restore。
5. **验收**：沿"真启动→真窗口→真恢复"做端到端（记事本/资源管理器这类零副作用的系统程序做被测物），重启级恢复用 verify_stage9 同款双启动基建。

## 六、机器证据基础（审计依据，均为既有验收资产）

- 阶段 3：窗口三能力 + 多屏 DPI（verify_stage3.py，真窗口摆位比对）
- 阶段 4：模式引擎七步 + 切换策略 + 退出边界（verify_stage4.py，含 R-01"不碰用户程序"）
- `cargo test`：window_manager layout/monitor、scheduler 状态机/RunRecord 快照保留 等单测在位
- TECH-02/03-B/05：workspace 域冻结门禁（T1 方法集合锁）与快照纯函数验收持续全绿

---

*停止条件遵从：仅审计，未进入 TECH-07-B。*
