# learning/ —— 学习成长模块（阶段6 交付）

> 指令：`docs/agent-dev/09-阶段指令-学习成长.md`
> 定位一句话：**AI 规划，用户执行，系统提醒。**

## 一句话职责

把"我想学 X"变成一个**可执行、可勾进度、会被温和提醒**的路线；AI 只出建议，
**状态永远由用户决定**。

## 交付物落点

| 交付物 | 落点 |
|--------|------|
| 表结构 | `core/migrations/0005_learning_projects.sql`（`learning_goals` 补 `expected_at`/`priority`/`last_reminded_at`；`learning_roadmap` 补 `estimated`/`resources`） |
| 数据访问（**唯一写入口**） | `core/src/learning/repository.rs`（`LearningRepo`：目标/节点 CRUD、`roadmap_confirm`、`node_move`、进度派生） |
| 路线 JSON 解析 + 降级 | `core/src/learning/roadmap.rs`（`parse` → `ParsedRoadmap { nodes, degraded, reason }`） |
| 提醒机制 | `core/src/learning/reminder.rs`（`should_remind` 纯函数 + `scan` + `spawn_watcher`） |
| 模块门面（AI 建议 / 写入口发事件） | `core/src/learning/mod.rs` |
| 提示词 | `ai/prompt/roadmap_generate.md`（严格 JSON）、`ai/prompt/study_assistant.md`（优化/总结） |
| 接口 | `core/src/api/commands.rs` 的 `learning_*`；`core/src/api/mod.rs` 的 `/api/v1/learning/*` |
| UI | `ui/src/views/LearningView.vue`、`ui/src/api/learningService.ts`、`ui/src/stores/learning.ts`、`ui/src/widgets/LearningProgressWidget.vue` |
| 验收脚本 | `tools/verify_stage6.py` |

## 关键设计（三个不变量）

1. **AI 不写库**（红线 V3）。`learning::ai_suggest` 只读目标与进度用于组装提问，
   产出带 `advisory: true` 的建议返回给 UI。**代码里没有任何一条从 AI 到数据库的路径** ——
   要落库必须用户点"采纳" → `learning_roadmap_confirm`。
   → 机器判据：`verify_stage6.py` 验收项 6（调用前后四张表全行快照必须一致）。
2. **进度由 core 派生**（`done / total / percent`，见 `Progress`）。前端**不自己数节点** ——
   两侧各算一套必然不一致。
3. **提醒是建议不是催促**。同目标 7 天冷却；`paused`/`done`/`archived` 一律不打扰；
   总开关 `learning.remind_enabled` 可关（09 §禁止事项：不做强制提醒）。

## 提醒规则（`reminder.rs`，逐条可断言）

| 规则 | 值/来源 |
|------|---------|
| 阈值 | `config.learning.remind_after_days`，默认 **30 天**；`0` = 立即；**负数 = 关闭** |
| 判据时间 | `learning_goals.updated_at`（改状态/改标题都会刷新它） |
| 冷却 | **7 天**（`last_reminded_at` 节流） |
| 不打扰的状态 | `paused` / `done` / `archived` |
| 触发后的动作 | 发 `LEARNING_REMINDER` 事件 + 写 `last_reminded_at`；由 UI 提供**继续 / 暂停 / 归档** |

## 验收步骤

机器验收（先 `python tools/rust.py build --release`）：

```bash
python tools/verify_stage6.py          # 覆盖 09 §验收标准 1~8
python tools/verify_stage6.py --keep   # 保留临时数据目录供排查
python tools/gate.py --stage 6 --build # 静态门禁 + 编译
```

人工验收（机器测不到的部分 —— 真窗口 + 真模型）：

1. 学习页输入"学习计算机视觉并完成项目"，选一个真 Provider → 生成路线；
   界面必须标着**「AI 建议，待确认」**，此时刷新页面路线应**消失**（未落库）。
2. 编辑节点（改名/增删/调序）→ 点"采纳" → 刷新后仍在。
3. 把某节点改成"完成" → 进度条实时变化 → **重启应用**后仍是这个进度。
4. 设置里把 `learning.remind_after_days` 改成 `0` → 回到 Dashboard 应看到提醒条；
   点"暂停"→ 提醒消失且 7 天内不再出现。
5. 让真模型回一段不含 JSON 的话 → 界面应显示**文本 + 手动录入**，**不能出现 JSON 解析错误**。
6. 项目页建一个项目并绑定某个工作模式 → 进入该模式后 Dashboard「当前项目」Widget 显示它。

## 边界与已知未覆盖

- `verify_stage6.py` 的验收项 1 用 mock 的**固定夹具**（`tools/ai_mock.py --reply roadmap`）：
  它证明**链路通、结构合法、数量在 3~7**，**不证明**模型规划质量 ——
  后者是人工判据（上面的步骤 1）。
- 事件投递到 webview 一步只有**接线级**证据（常量登记 + 发布点 + 前端订阅点），
  运行时投递需真窗口验收（core 的 `/internal/*` 面没有事件订阅入口，脚本读不到）。
