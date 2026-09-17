# 审核报告 REVIEW-014 · 阶段6：学习成长模块（含项目管理）

> **本模板已按 2026-09-12 22:32 口径收敛。** 报告只写 3 项：**判定+理由 / 硬证据 / 阻塞项**。

| 项目 | 内容 |
|------|------|
| 审核编号 | REVIEW-014 |
| 审核日期 | 2026-09-13 |
| 审核阶段 | 阶段 6 · 学习成长模块（含项目管理） |
| 审核对象 | `core/src/{learning,project}`（repository / roadmap / reminder）、迁移 `0005_learning_projects.sql`、`core/src/api/{commands.rs,mod.rs}`、`ui/src/{views/LearningView.vue,views/ProjectView.vue,widgets/LearningProgressWidget.vue,widgets/CurrentProjectWidget.vue,stores/learning.ts,api/learningService.ts}`、`modules/learning/README.md`、`tools/verify_stage6.py`、契约 `03` v8 |
| 审核基准 | `docs/agent-dev/09-阶段指令-学习成长.md` + `SUPERVISOR.md` 第四章唯一标准 |
| 审核方式 | 自动门禁 + 目标复现（5 条脚本独立重跑）+ 调用点检索 |
| **独立性声明（必填）** | **自审 + 机器门禁** —— 本报告**不产生独立审核效力** |
| **判定** | **✅ 通过（4 项记录在案）** |

---

## 〇、独立性声明（必填，不可省略 —— **不属收敛对象**）

- 本报告性质：**自审 + 机器门禁**（角色合并状态下，架构/开发/审核同属肉编器001号）。
- 本报告**不产生独立审核效力**；可机器判定的部分一律外化为可复现证据（§二，均为本轮**独立重跑**，不引用交付方数字）。
- 拿不到证据的项一律标"**未实测**"，不折算通过（红线 V6 对自审同样适用）。
- 未经「申请独立复核阶段 6」口令不发起独立复核（13.3 回调后口径）。

---

## 一、判定与理由

### 判定：✅ **通过（4 项记录在案）**

1. **目标达成** ✅ —— 09「定位一句话」（*AI 规划，用户执行，系统提醒*）与 8 项验收标准**全部有机器判据**：
   `verify_stage6.py` **37/37**（覆盖验收 1~8，含 ★ 验收项 6 的"AI 只建议"四表全行快照比对）；
   提醒判据做成纯函数（时间入参）并由 7 条单测锁死阈值/冷却/暂停/坏时间戳；路线解析 6 条单测覆盖围栏、字段变体、括号在字符串内、截断。
   UI 侧三个落点均在：学习页（目标卡片 + 路线时间轴 + 提醒条三动作）、Dashboard（`learning-progress` / `current-project` 两个 Widget **默认启用**）、项目页（含绑定工作模式）。
2. **无致命漏洞** ✅ —— 红线 **0 命中**。V3 是本章重点，落实在**三层**而非一句口号：
   ① 结构上 `ai_suggest` 只读，代码里**没有从 AI 到数据库的路径**（`core/src/learning/mod.rs:95`）；
   ② 界面上强制标"★ AI 建议，待确认（不会自动写入你的学习计划）"（`LearningView.vue:462`）；
   ③ 端到端由验收项 6 对 `learning_goals`/`learning_roadmap`/`learning_updates`/`projects` **四张表全行快照比对**断言（脚本 `SNAPSHOT_TABLES`）。
   V1（不碰凭据）、V2（AI 建议走 workspace 模式且由用户显式发起）、V7（UI 只经 command/HTTP，不直连库）、V8（无产物入库）均未命中。
3. **无冗余垃圾** ✅ —— 门禁 **0 WARN**（无孤儿模块/未引用文件）；20 个 `learning_*`/`project_*` command 中 18 个有前端 invoke，
   另 2 个（`learning_goal_get` / `project_get`）有 HTTP 路由且被验收脚本实际调用，**非死代码**；无临时产物残留；迁移 `0005` 只增不改。

---

## 二、硬证据（**必须粘贴原文，不许转述**）

### 2.1 自动门禁（本轮独立重跑）

```
python tools/gate.py --stage 6 --build
```

```
  [PASS] S100 — [阶段6] 存在：modules/learning
  [PASS] W100 — ui/src/utils/logger.ts 已被 ui/src/api/appsService.ts 引用（接线到位）
  [PASS] W100 — ui/src/utils/markdown.ts 已被 ui/src/components/AiSidebar.vue 引用（接线到位）
  [PASS] W100 — ui/src/composables/useWidgets.ts 已被 ui/src/views/DashboardView.vue 引用（接线到位）
  [PASS] B120 — externalBin 产物就绪：binaries/service → service-x86_64-pc-windows-msvc.exe
  [PASS] B131 — sidecar 发行产物不落后于源码：core/binaries/service-x86_64-pc-windows-msvc.exe
  [PASS] B134 — 打包脚本会把 ai/prompt/*.md 打进单文件（发行态 AI 可用）
  [PASS] B100 — cargo check 通过
  [PASS] B110 — 前端 typecheck 通过

✅ 门禁通过   FAIL=0  WARN=0  PASS=20
```

**门禁结论：0 FAIL / 0 WARN / 20 PASS**（含 `--build`）

### 2.2 阶段验收脚本

```
python tools/verify_stage6.py
```
```
PASS  8d 降级路径全程未写库
      快照一致
PASS  8e 围栏 + 前后废话包裹的 JSON 仍能解析（不误判为降级）
      degraded=False 节点数=5 status=200 err=None: None
PASS  7a 项目绑定工作模式 + 关联学习目标（含技术栈/目录）
      status=200 err=None: None project={'name': 'CV 小项目', 'modeName': '验收-开发模式', 'goalId': 1}
PASS  7b 进入模式时能取到当前项目（侧栏 Widget 的数据源）
      status=200 命中=CV 小项目 goalTitle=学习计算机视觉并完成项目
PASS  7c 同模式多项目时优先返回「未完成」（core 单一判据）
      返回=CV 小项目/ongoing
PASS  7d 完成项目只提议完成目标（linkedGoalDone=true），目标状态不被自动改
      linkedGoalDone=True 目标状态=not_started
PASS  接线：16 条订阅/注册关系全部成立
      全部命中
======================================================================
合计 37/37 通过
```

```
python tools/rust.py test
```
```
test result: ok. 66 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.21s
```

```
python tools/verify_sidecar_bundle.py      # 发行态回归（阶段6 改过 ai/ 与迁移，须复验）
```
```
合计 8/8 通过
```

```
node ./node_modules/vue-tsc/bin/vue-tsc.js --noEmit   （ui/ 下）
```
```
EXIT=0 （输出为空 = 0 error）
```

### 2.3 红线检查

| 红线 | 结果 |
|------|------|
| V1 明文密钥 | ✅ 未命中（阶段6 不碰凭据；沿用 Provider 的 keyring 通路） |
| V2 咨询模式读数据 | ✅ 未命中（AI 建议走 `workspace` 且**用户显式点击**发起，非背景咨询；`consult` 侧无新增通路） |
| V3 **AI 自动改学习进度/档案** | ✅ **未命中**，且是本章重点：结构（只读）+ 界面（待确认标记）+ 端到端（四表快照比对）三层均落实；验收 7d 还断言"完成项目只**提议**完成目标、目标状态不被自动改" |
| V4 插件默认权限 | ✅ 未命中（未涉及） |
| V5 破坏性操作无确认 | ✅ 未命中（删除走软删 `deleted_at`） |
| V6 谎报 | ✅ 未命中（本报告数字均为本轮独立重跑；未测项显式标注，见 §四） |
| V7 插件/UI 直连库 | ✅ 未命中（UI 只经 `invoke`/HTTP；进度由 core 派生，前端不自己数节点） |
| V8 产物/数据库入库 | ✅ 未命中（`core/binaries/`、`target/`、`*.db` 均已 gitignore） |

**红线命中：0**

### 2.4 契约与文档一致性（本轮核对）

| 项 | 结果 |
|----|------|
| `CONTRACT_SCHEMA_VERSION`（代码）= **8** | 与迁移 `0005` 注释"契约 v8"、契约文档自称 v8 **一致** |
| 契约 03 变更记录 v4→v8 连续 | ✅ 无跳版 |
| `projects` 表 / `learning.remind_after_days` / `learning.remind_enabled` / `/api/v1/learning/*` / `/api/v1/project/*` / `LEARNING_REMINDER` 已登记 | ✅ 全部命中 |
| 模块 README（`modules/learning/README.md`） | ✅ 含交付物落点表、三个不变量、提醒规则表、**机器+人工双份验收步骤**、边界声明 |

---

## 三、三条判据的核验要点（**只核这三条**）

| # | 判据 | 怎么判 | 结果 |
|:-:|------|--------|:----:|
| 1 | **目标达成** | 09 §验收标准 8 项 + 定位一句话，达成即算实现 | ✅ |
| 2 | **无致命漏洞** | 红线 V1~V8 + 数据安全 + 不可恢复架构错误 | ✅ |
| 3 | **无冗余垃圾** | 死代码 / 临时产物 / 重复实现 / 无人消费的半成品 | ✅ |

### 三·附 强制动作：调用点检索（**不属收敛对象**）

| 符号 | 定义处 | 调用点（文件:行） | 结论 |
|------|--------|-------------------|------|
| `ai_suggest`（只读建议） | `core/src/learning/mod.rs:95` | `core/src/api/commands.rs:709` · `core/src/api/mod.rs:118`（HTTP 路由）· 前端 `learningService.ts:306` | ✅ 已接线 |
| `learning_roadmap_confirm`（建议落库的唯一口） | `core/src/api/commands.rs:620` | 前端 `learningService.ts:216` · `LearningView.vue:261`（用户点"采纳"） | ✅ 已接线（**AI→库必经此口**） |
| `learning_goal_update`（提醒三动作落点） | `core/src/api/commands.rs:596` | 前端 `learningService.ts:181` | ✅ 已接线 |
| `LearningRepo::node_update` | `core/src/learning/repository.rs:443` | `core/src/learning/mod.rs:49`（`apply_node_update`） | ✅ 已接线 |
| `LearningRepo::mark_reminded`（7 天冷却） | `core/src/learning/repository.rs:284` | `core/src/learning/reminder.rs:121` | ✅ 已接线 |
| `LEARNING_REMINDER` 发布 | `core/src/learning/reminder.rs:124` | — | ✅ |
| 前端订阅 `LEARNING_REMINDER` | `ui/src/stores/learning.ts:82` | 消费：`LearningView.vue:303`（提醒条）、`LearningProgressWidget.vue:33`（Dashboard 提示） | ✅ 已接线 |
| 前端订阅 `LEARNING_PROGRESS_UPDATED` | `ui/src/stores/learning.ts:88` | — | ✅ 已接线 |
| `LearningProgressWidget` | `ui/src/widgets/LearningProgressWidget.vue` | `widgets/index.ts:19`（注册）· `stores/widgets.ts:18`（**默认启用**） | ✅ Dashboard 消费学习进度（09 §3） |
| `CurrentProjectWidget` | `ui/src/widgets/CurrentProjectWidget.vue` | `widgets/index.ts:16` · `stores/widgets.ts:15`（**默认启用**）· 数据源 `/project/by-mode`（`learningService.ts:359`） | ✅ 进入模式显示当前项目（09 §7） |
| `learning_goal_get` / `project_get` | `core/src/api/commands.rs` | 前端**无 invoke**；但有 HTTP 路由（`api/mod.rs:101/126`）且被 `verify_stage6.py` 实际调用 | ⚠️ 属 HTTP 读端点，非死代码（见 §四 4） |

- 全仓检索（`.rs` / `.ts` / `.vue` / `.py` / `.sql`），排除定义处本身；跨语言边界（Rust command ↔ 前端 invoke ↔ HTTP）三侧均已查。
- **未发现"零调用即功能不成立"的关键符号**（与阶段5 的 `ai_permission_scope` 不同，本章无此类项）。

---

## 四、记录在案（**不阻塞，仅备查**）

| # | 事项 | 为什么不阻塞 |
|:-:|------|--------------|
| 1 | **验收项 1 的"节点是否合理"是人工判据**：脚本用 mock 固定夹具，只证明"链路通、结构合法、数量 3~7"，不证明模型规划质量 | 把"链路通不通"与"模型答得好不好"分开是**正确做法**（真模型同题多次生成节点数会变，无法作为可复现判据）。人工步骤已写在 `modules/learning/README.md` |
| 2 | **事件运行时投递到 webview 未测**：core 的 `/internal/*` 面无订阅入口，脚本只能做接线级断言（常量登记 + 发布点 + 前端订阅点） | 阶段5 已闭环的事件桥（`bridge_to_webview` ← `main.rs:56`）是同一条链路；脚本已**显式声明不声称测过运行时**，未虚报 |
| 3 | **系统通知未实现**（09 §5 标注"可选"） | 指令本身标注可选；应用内提醒（Dashboard + 学习页）已实现且可关闭 |
| 4 | `learning_goal_get` / `project_get` 两个 command 前端零 invoke | 二者有 HTTP 路由并被验收脚本实际调用，属"按 id 取单个"的读端点，**非死代码**；保留 command 形态是为与 HTTP 同源（02 §2.2 双通道要求） |

---

## 五、阻塞项

| # | 阻塞项 | 阻塞了什么 | 完成判据 |
|:-:|--------|------------|----------|
| — | **无** | — | — |

> 阶段6 之后可进入阶段7（个人档案）。阶段7 会消费本模块的 `projects`/`learning_goals`（档案同步），
> **建议在阶段7 开工时把"项目经历 → 档案条目"的同步路径一并设计**，避免档案侧再建一套项目表（语义打架风险已由 `0005` 迁移注释点明）。
> 定性：**"机器门禁通过 + 自审记录"**，与阶段1~5 一致。

---

## 六、下一步

**开发 Agent 下一步动作**：开阶段7（`docs/agent-dev/10-阶段指令-个人档案.md`）；开工前重跑 `python tools/gate.py --stage 7 --build`。

**送审前必须准备**：`python tools/gate.py --stage 7 --build`（有 FAIL 不许送审）

**触发口令**：「申请审核阶段 7」· 独立复核：「申请独立复核阶段 6」

---

*审核人：肉编器001号（监制） · 2026-09-13*
