# REVIEW-015 · 阶段7（个人数字档案）验收报告

> 日期：2026-09-13 · 审核人：监制（肉编器001号）

## §〇 独立性声明

**本报告 = 自审 + 机器门禁，不具独立审核效力**（角色合并状态，M-5 裁决下的效力等级）。
判定依据全部来自本轮**独立重跑**的机器证据（未引用交付方数字）与**强制调用点检索**。
如需独立效力，白宇可下口令「申请独立复核阶段 7」。

**基线漂移检查**：审核开始前扫描 core/src、ui/src、system、ai、tools、core/migrations
全部文件的 mtime —— 自最后一次已验证的 release 构建（2026-09-13 05:47Z）后**零漂移**，审核基线有效。

---

## §一 判定：✅ 通过（按白宇 2026-09-12 22:35 验收唯一标准）

### ① 目标达成 ✅

10 定位一句话「记录我是谁，我正在成为谁」，核心流程「系统发现变化 → AI 生成建议 → ★ 用户确认 ★ → 写入档案」已完整落地：

- 档案四表（`profile_basic`/`profile_skills`/`profile_projects`/`profile_timeline`）+ repository + 迁移 `0006_profile.sql`（契约升 v9）；
- 待确认建议队列 `pending_suggestions`（部分唯一索引防刷屏）+ 4 类采集触发点全部接线；
- 档案主页 UI（引导填写 / 技能分组条形图 / 项目列表 / 年月分组时间线 / 建议条 / 导出）；
- Markdown 导出只含已确认条目并带隐私告知。

8 项验收全部有机器判据，`verify_stage7.py` **29/29**（release 产物，本轮独立重跑），
其中 ★ 验收项3 由**四表快照逐行比对**判定（3d），★ 验收项7 由 mock 记录的 system 提示词端到端断言 + **workspace 对照组**（7b）判定——排除"链路断了导致读不到"的假通过。

### ② 无致命漏洞 ✅

红线 V1~V8 **0 命中**：

- **V3（AI 不自动改档案）= 表级落实**：采集器与 AI 只能写 `pending_suggestions`；`suggestion_confirm` 是唯一入档通路（`source='ai_suggested'`），只能由用户动作触发。验收 3d 快照比对端到端断言。
- **V2（consult 读不到档案）= 双闸**：core `is_data_allowed()`（单测覆盖大小写/空格/未知模式拒绝）+ sidecar `assemble()`（验收 7a），AI 上下文只取 `confirmed=1` 的技能（W5）。
- **数据安全**：迁移只增不改；`apply_reject_kind` 先写清单后清 pending（失败不产生半执行）；重复确认状态机拒绝（4c=400）。
- **不可恢复架构错误**：无。双通道同源（写路径统一走 `profile::apply_*`），单一写入者未破坏。

### ③ 无冗余垃圾 ✅

- 门禁 **0 WARN**；
- 本阶段无死代码新增；cargo test 的 4 条 `dead_code` 警告（`PLUGIN_LOADED`/`PLUGIN_ERROR`/`PLUGIN_PERMISSION_DENIED`/`DEVICE_METRICS_UPDATED`）为阶段8/9 骨架事件常量，按 22:35 口径「骨架预留不算冗余垃圾」；
- 临时产物：验收脚本用临时数据目录自清，未污染仓库。

---

## §二 硬证据（全部本轮独立重跑，2026-09-13 14:02~14:04）

| 项 | 结果 |
|----|------|
| `python tools/gate.py --stage 7 --build` | **FAIL=0 · WARN=0 · PASS=21**（含 cargo check + 前端 typecheck） |
| `cargo test`（core） | **74 passed; 0 failed**（含 8 个 profile 单测：去重确认入档 / ignore-reject 只动 pending / 非法值拒绝 / 导出隐私注记等） |
| `python tools/verify_stage7.py`（**release 产物**） | **29/29 PASS**（8 项验收 + 附加 + W1~W6 接线；含重启持久化 1b、四表快照 3d、consult 隔离 + 对照组 7a/7b、未确认条目不进导出 8b、永久拒绝落库 9） |
| 基线漂移 | 最后已验证构建（05:47Z）之后源码零改动 |

## §三·附 强制调用点检索（零调用 = 功能不成立）

| # | 功能符号 | 调用点（文件:行） | 结论 |
|---|----------|------------------|------|
| 1 | `collect_goal_done` | `learning/mod.rs:79`（status→done 边） | 已接线 |
| 2 | `collect_project_done` / `collect_project_created` | `project/mod.rs:321/328/349`（`apply_add`/`apply_update` 门面内） | 已接线 |
| 3 | `scan_app_usage` | `api/mod.rs:1242` · `commands.rs:939` | 已接线 |
| 4 | `suggestion_confirm`（唯一入档通路） | repo `repository.rs:588` ← `profile/mod.rs:306` ← 双通道 `commands.rs:954` / `api/mod.rs:1265` | 已接线 |
| 5 | `apply_reject_kind` | 双通道 `commands.rs:978` / `api/mod.rs:1301` | 已接线 |
| 6 | `export_markdown` | 双通道 `commands.rs:985` / `api/mod.rs:1308` | 已接线 |
| 7 | 22 个 `profile_*` command | `main.rs:155-176` 注册 ↔ `ui/src/api/profileService.ts` 22 处 invoke（跨语言两侧均查） | 已接线 |
| 8 | `PROFILE_UPDATED` 事件 | core `profile/mod.rs:48` publish → `events.rs:17` 常量 → 前端 `stores/profile.ts:72` 订阅 | 已接线 |
| 9 | V2 双闸 | `is_data_allowed`（`ai_context.rs:39`）← `ai/mod.rs:307` + `ai_context.rs:53`；`confirmed_skills` 只取 confirmed=1（`ai_context.rs:94/152`） | 已接线 |
| 10 | 并行 Edit 事故修复点①`profile.rejected_kinds` 三处登记 | `config.rs:107/139/184` | 已落位 |
| 11 | 修复点②HTTP `project_add/update` 走采集门面 | `commands.rs:771/780` · `api/mod.rs:1016/1027` | 已落位 |

无"零调用即功能不成立"项。

## §四 阻塞项

**无。**

记录在案（不阻塞、不处理）：

1. **事件运行时投递到 webview 仍只有接线级证据**（W2 + 前端订阅代码，无真窗口断言）——与阶段6 同源，`PROFILE_UPDATED` 已走阶段5 建成的事件桥（该桥链路已验）。
2. **「AI 从项目目录推断项目经历」未做自动推断**——10 列为数据来源③（可选项），本轮以项目管理同步 + 手动添加为来源（隐私收益存疑且不可复现验收）。
3. **PDF 导出未做**——10 明示"优先做 Markdown"，Markdown 已过 8a/8b。
4. 采集器建议文案为规则模板不调 LLM——确定性优先，不属"AI 生成建议"的实现偏差（建议结构由系统生成、语义由触发点决定）。

---

*审核依据：HANDOFF.md §⚖️（22:35 唯一标准）· SUPERVISOR.md §四/§九 · 10-阶段指令-个人档案.md。报告格式：收敛版 3 项。*
