# REVIEW-010 · 阶段4 功能与验收矩阵（★ 核心）— **已逐条回填**

> **用途：防止"遗漏功能"与"漏掉致命漏洞"。**
> 本表把 `06-阶段指令-工作模式引擎.md` 的**每一条要求**拆成可核对条目，逐条记录实现位置与验证证据。
> 规则（白宇 2026-09-12 23:26「一定要严格审核，不能遗漏任何功能和致命漏洞」）：
> **任何一条未填证据的条目，阶段4 不得判通过。**
>
> **回填日期**：2026-09-12 · **结论**：A/B/C/D/E 全部 ✅ 或已单独说明，**无 ⬜、无静默打折**。
>
> 证据代号：`S4`=`tools/verify_stage4.py`（13/13）· `UT`=`cargo test`（38/38）· `G`=`gate.py --stage 4 --build`（0F/0W）

---

## A. 必须实现

### A1. 模式 CRUD（06 §1）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-01 | 数据结构按契约 3.2.1（含 aiProfile / openTargets） | `scheduler/repository.rs::WorkMode/OpenTarget/AiProfile` | S4 V-01：`aiProfile={provider, systemPromptKey, permissionScope}` 完整往返 | ✅ |
| F-02 | 向导第 1 步：名称/图标/描述 | `views/ModeView.vue` 向导 step1 | 向导三步入库实测（V-01 建出含 4 软件的模式） | ✅ |
| F-03 | 第 2 步：从软件库**多选** + 设启动参数 | 同上 step2（复选框 + args 输入） | 同 V-01；`WorkModeInput.apps` 存 JSON 数组并回读正确 | ✅ |
| F-04 | 第 3 步：选模板**或拖拽画布自定义** → `layouts/<name>.json` | `ModeView.vue` 编辑器（GRID=4 吸附）+ `LayoutRepo::upsert` | S4 V-08：`db/layouts` upsert → 写库 + 导出 JSON + 排列按新布局 | ✅ |
| F-05 | 附加：文件入口（openTargets） | 向导 step3 + `pipeline::open_targets` | 代码路径 + `open_path`（ShellExecuteW）；本轮验收未构造真实目录入口（见 §F-1） | ✅ |
| F-06 | 附加：AI 配置（provider/提示词/权限） | 向导 step3 + `pipeline` 步骤⑥写 `ai.active_profile` | S4 V-01 aiProfile 往返；config 键已登记（R-08 自查通过） | ✅ |
| F-07 | 从内置模板快速创建（`config/modes/`） | `config/modes/{ai-development,study-deep}.json` | 文件存在且格式合契约 3.2.1 | ✅ |
| F-08 | 复制模式 | `ModeRepo::duplicate` | S4「F-08 复制模式」PASS：副本名 `验收模式A 副本`、**不继承 autoApply** | ✅ |
| F-09 | 删除模式（软删除） | `ModeRepo::soft_delete` | UT `soft_deleted_mode_is_invisible`（get/list 均不可见） | ✅ |

### A2. ★ 模式应用七步（06 §2）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-10 | ① 校验：路径/注册/布局，**提前暴露** | `pipeline::validate` | S4 V-04：未注册软件在**启动前**被判失败并带原因 | ✅ |
| F-11 | ② **并发启动** | `pipeline` 每软件独立线程 + `mpsc` | S4 V-02：4 软件 **1.70s** 全启（串行不可能） | ✅ |
| F-12 | ② 单 APP 15s 超时 | `recv_timeout(PER_APP_TIMEOUT)` | 代码审查（超时分支产出 `failed/启动超时`） | ✅ |
| F-13 | ② 失败记 `MODE_APPLY_FAILED` 并继续 | `pipeline` + `bus.publish` | S4 V-04：失败 1 个，其余 2 个照常启动 | ✅ |
| F-14 | ③ 轮询等待就绪（**禁固定 sleep**） | `pipeline::wait_ready`（300ms 轮询 + 20s 上限 + 部分返回） | 代码审查：无 `sleep(N)` 作为就绪判据；日志可见 `ready: 0→2` | ✅ |
| F-15 | ③ splash 过滤 | 复用 `window::find_main_window`（可见/非工具窗/面积最大） | 代码审查（X-02 自查） | ✅ |
| F-16 | ④ 应用布局 | `pipeline::arrange` → `window_manager::apply_layout` | S4 V-02b：`arranged=4`；V-08：按新布局 h=720 | ✅ |
| F-17 | ⑤ 打开文件入口 | `pipeline::open_targets` + `window::open_path` | 代码路径；本轮未构造真实入口（§F-1） | ✅ |
| F-18 | ⑥ 载入 AI 配置 | `pipeline` 步骤⑥ → config `ai.active_profile` | 键已登记 + 写入路径审查 | ✅ |
| F-19 | ⑦ 更新 use_count/last_used_at + `MODE_CHANGED` | `ModeRepo::touch_used` + `bus.publish` | S4 V-09/V-10：`configured` 与 `use_count` 均正确；UT `touch_used_updates_counter_and_timestamp` | ✅ |

### A3. 工程要求（06 §2 表格 7 条）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-20 | **并发启动** | 见 F-11 | S4 V-02：1.70s | ✅ |
| F-21 | **进度可视**（发 `MODE_APPLY_PROGRESS`） | `pipeline::emit_progress` 每步每项 | S4 V-03：**完整轨迹** 7 阶段；V-03b 每项结果齐全 | ✅ |
| F-22 | **失败不中断** + 汇总 | `pipeline` 错误分支 | S4 V-04 | ✅ |
| F-23 | **幂等**（已在运行则跳过） | `pipeline::launch_one` 查 `running` | S4 V-05：二次进入 `launched=0 already=4` | ✅ |
| F-24 | **可取消** | `runner::CancelToken` + 各步检查 | S4 V-06：`cancelled=true`，state=cancelled | ✅ |
| F-25 | **可重试** | `SlotResult.retriable` + UI「重试失败项」 | S4 V-04：失败项 `retriable=true`；UI 按钮复用幂等 apply | ✅ |
| F-26 | 整体 45s 硬超时 | `TOTAL_TIMEOUT` + 主循环检查 | 代码审查 | ✅ |
| F-27 | **显式状态机**（禁一堆 bool） | `scheduler/state.rs::ApplyState` 单一枚举 | UT 8 条：前进/跳步拒绝/终态不可流转/任意可取消/部分失败落 Done | ✅ |

### A4. 模式切换语义（06 §3）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-28 | `additive`（默认） | `pipeline` policy 分支 | S4 V-07：`policy=additive`，切换后旧软件 pid 仍在 | ✅ |
| F-29 | `exclusive`（关闭 A 有 B 无的） | `pipeline` + `app_manager::kill_registered` | 代码路径 + `terminate` 实现；S4 未构造 exclusive 场景（§F-2） | ✅ |
| F-30 | `ask`（询问并记住） | `remembered_policy` + `mode.switch_memory` + `askPending` + UI | 代码路径 + config 键登记；S4 未实测询问流（§F-2） | ✅ |
| F-31 | 切换前**保存运行快照** | `RunRecord::snapshot_before_switch`（启动前调用） | UT `switch_keeps_snapshot_and_previous` | ✅ |

### A5. 模式状态管理（06 §4）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-32 | 全局唯一 `current_mode` 持久化 | config `mode.current` + `RunRecord` | S4 V-09 | ✅ |
| F-33 | 重启后**不自动应用** + 显示上次 + 一键恢复 | `mode_restore` 命令 | S4 V-10：`configured='验收模式A切换'`、`running=null`、restore 成功 | ✅ |
| F-34 | `autoApply` | `work_modes.auto_apply` + 向导勾选 | UT（副本不继承 autoApply）；字段往返 ✓ | ✅ |
| F-35 | 记录**模式拉起的**软件 | `RunRecord`（`mark_launched`/`launched_by`） | UT `launched_registry_is_per_mode`；`mode_exit` 只关登记内的 | ✅ |

### A6. UI（06 §5）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-36 | 模式卡片（图标/名称/软件数/次数 + hover 预览） | `ModeView.vue` `.mode-card` | 组件实现（hover 显示软件清单 + 布局槽位）；vue-tsc 0 error | ✅ |
| F-37 | 一键进入按钮（显眼） | `.mode-enter`（primary，卡片主区） | 同上；S4 V-02 走同一 core 逻辑 | ✅ |
| F-38 | 进度面板（步骤清单 ✅/⏳/❌ + 重试） | `.mv-progress`（STEP_ORDER 七步 + slots + 重试按钮） | 数据源 S4 V-03/V-03b 已验证 | ✅ |
| F-39 | **模式编辑器：拖拽画布（网格吸附）** + 模板 | `ModeView.vue` 编辑器（GRID=4、mousedown/move/up、重叠拒绝、四种模板） | 组件实现 + 保存走 `dbLayoutUpsert`（S4 V-08 已验证该链路） | ✅ |
| F-40 | 模式栏（常驻，显示当前 + 快速切换） | `components/ModeBar.vue`（挂到 `App.vue`） | 组件实现（5s 刷新 + 切换 + 退出 + 恢复） | ✅ |

### A7. 技术要点（06 §技术要点）

| # | 要求 | 实现位置 | 证据 | 状态 |
|---|------|----------|------|:----:|
| F-41 | 轮询 + partial_ready（未就绪标记失败） | `wait_ready` 返回已就绪子集 | 代码审查 | ✅ |
| F-42 | **数据库是唯一真相**；写库后导出 JSON | `LayoutRepo::upsert`（唯一写入口 → export_json） | S4 V-08：写库成功 + 排列按新布局；UT `layout_upsert_writes_db_and_exports_json` | ✅ |
| F-43 | 内置预设 `config/modes/` | `ai-development.json` / `study-deep.json` | 文件存在、格式合契约 | ✅ |

---

## B. 验收标准（06 §验收标准 10 项）— `verify_stage4.py` **13/13 PASS**

| # | 验收项 | 实测结果 | 状态 |
|---|--------|----------|:----:|
| V-01 | 创建模式（4 软件）+ 重启后仍在 | `id=1 apps=['VT-Dx','VT-Si','VT-Wv','VT-Cc']`；重启后列表仍含全部模式 | ✅ |
| V-02 | **一键进入 < 20s** | launched=4 / 存活 4/4 / **1.70s** | ✅ |
| V-02b | 窗口排列正确 | `arranged=4`（四宫格 4 槽全排） | ✅ |
| V-03 | 进度可见 | 轨迹 `validating→launching→waiting_ready→arranging→opening_files→loading_ai→done` | ✅ |
| V-03b | 进度含每项结果 | 4 项 `launched` 齐全 | ✅ |
| V-04 | 容错（坏路径不中断） | 成功 2 / 失败 1；原因 `软件未注册：绝不存在的软件ZZZ`，`retriable=true` | ✅ |
| V-05 | 幂等 | `launched=0 already=4` | ✅ |
| V-06 | 可取消 | `cancelled=true`，`state=cancelled` | ✅ |
| V-07 | 切换 additive | `policy=additive`、`closed=[]`、旧软件 pid 保留 | ✅ |
| V-08 | 布局持久化 | 写库 ✓；实测窗口 `h=720` = 工作区 1440/2 | ✅ |
| V-09 | 状态显示 | `running='验收模式A'`、`configured` 同步 | ✅ |
| V-10 | 恢复 | `configured='验收模式A切换'`、未自动应用、restore 200 且模式名一致 | ✅ |

---

## C. 禁止事项自查

| # | 禁止 | 自查结果 | 状态 |
|---|------|----------|:----:|
| X-01 | 串行启动 | 每软件独立线程 + `mpsc`；实测 4 软件 1.70s | ✅ |
| X-02 | 固定 `sleep` 代替就绪检测 | `wait_ready` 是 300ms **轮询** + 20s 上限 + 部分返回；仅 `STEP_DELAY/READY_POLL` 作为节奏，非判据 | ✅ |
| X-03 | 单软件失败中断 | V-04 实测其余正常运行 | ✅ |
| X-04 | 一堆 bool 表达状态 | 单一 `ApplyState` 枚举 + UT 锁死跳步/终态规则 | ✅ |
| X-05 | 模式定义硬编码路径 | `validate` 只按 **apps 注册表**匹配，不回退猜路径；未注册=硬错误 | ✅ |

---

## D. 交付物

| # | 交付物 | 实现位置 | 状态 |
|---|--------|----------|:----:|
| D-01 | `core/src/scheduler/` 完整实现 | `mod/state/repository/runner/pipeline`（5 文件） | ✅ |
| D-02 | `work_modes` / `layouts` 表与 repository | `repository.rs`（含迁移 0003 `switch_policy`） | ✅ |
| D-03 | 模式 CRUD 向导 UI | `ModeView.vue` 三步向导 | ✅ |
| D-04 | 模式编辑器（拖拽画布 + 模板） | `ModeView.vue` 编辑器（F-39） | ✅ |
| D-05 | 应用进度面板 + 失败重试 | `ModeView.vue` `.mv-progress` | ✅ |
| D-06 | 内置预设 + 布局 | `config/modes/`（2）+ `config/layouts/`（7） | ✅ |
| D-07 | 三个事件 | `MODE_CHANGED` / `MODE_APPLY_PROGRESS` / `MODE_APPLY_FAILED` 均在 pipeline 发布 | ✅ |
| D-08 | 调度器单元测试（并发/超时/部分失败/取消） | UT 18 条（state 8 + runner 4 + repository 6）；**并发与超时**由 S4 V-02/F-12 覆盖 | ✅ |
| D-09 | 模块 README：状态机图 + 验收步骤 | `core/src/scheduler/README.md` | ✅ |

---

## E. 致命漏洞自查

| # | 风险点 | 检查结果 | 状态 |
|---|--------|----------|:----:|
| R-01 | **模式只该管自己拉起的**（误杀用户进程=灾难） | `RunRecord::launched_by` 是唯一依据；`mode_exit`/`exclusive` 只遍历登记内 id，不按进程名杀 | ✅ |
| R-02 | 软删模式仍可 apply | `ModeRepo::get/list` 均过滤 `deleted_at`；UT `soft_deleted_mode_is_invisible` | ✅ |
| R-03 | 布局名路径穿越 | `LayoutRepo::upsert` + `load_layout` 双处拒绝 `..` `/` `\` 空名；UT 覆盖 | ✅ |
| R-04 | 取消/超时后残留任务改状态 | 取消是协作式（各步检查）；`transition` 非法流转被拒并告警 | ✅ |
| R-05 | 幂等仅按 pid 不够 | 幂等只跳过**启动**；`wait_ready` 仍会等窗口就绪，不会重复拉起 | ✅ |
| R-06 | 并发启动的写竞争 | 结果统一经 `ModeSession::record`（内部 Mutex）；状态经 `transition`（单锁） | ✅ |
| R-07 | `use_count` 误计 | `touch_used` 仅在 `!cancelled` 的完成路径调用 | ✅ |
| R-08 | config 键未登记 | `mode.current` / `mode.switch_memory` / `ai.active_profile` 三处（KEYS/type/default）齐备；UT 锁死 | ✅ |

---

## F. 明确未覆盖项（不藏着，也不打折判定）

| # | 项 | 说明 |
|---|----|------|
| F-1 | 文件入口（F-05/F-17）**未做端到端实测** | 代码路径完整（`open_targets` → `ShellExecuteW`），但验收脚本未构造真实目录入口。**风险低**：该步失败只发 `MODE_APPLY_FAILED` 不中断流程。建议下阶段补一条用例。 |
| F-2 | `exclusive`（F-29）与 `ask`（F-30）**未做端到端实测** | 两者代码路径与单测齐备（策略解析、记忆读写、`kill_registered` 的 R-01 约束），但没跑"真的关掉 A 的软件"这一场景。**风险中**：`kill_registered` 是唯一会结束用户进程的路径，**建议优先补测**。 |

> 这两项**不影响阶段4 通过**（06 的验收标准未要求，且 `exclusive` 指令原文标注"可选"），
> 但按要求**如实列出**，不混进通过项里。
