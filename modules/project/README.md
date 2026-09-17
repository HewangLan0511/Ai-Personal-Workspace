# project/ —— 项目管理模块（阶段6 交付）

> 指令：`docs/agent-dev/09-阶段指令-学习成长.md` §6（与学习成长同章节交付）
> 后续衔接：`10-阶段指令-个人档案.md`（项目经历将从中同步为档案条目）

## 一句话职责

记录"我在做哪些项目"，并把它**接到核心的两个联动点上**：
① 绑定工作模式（进入模式即显示当前项目）；② 关联学习目标（完成项目 → **提议**达成目标）。

## 交付物落点

| 交付物 | 落点 |
|--------|------|
| 表 | `core/migrations/0005_learning_projects.sql` 的 `projects` 表（含 `mode_name` / `goal_id` 与三个索引） |
| 数据访问（唯一写入口） | `core/src/project/mod.rs`（`ProjectRepo`：CRUD、`by_mode`、"优先未完成"判据、`ProjectWrite.linkedGoalDone`） |
| 接口 | `core/src/api/commands.rs` 的 `project_*` / `projects_list`；`core/src/api/mod.rs` 的 `/api/v1/projects*` 与 `/api/v1/project/by-mode` |
| UI | `ui/src/views/ProjectView.vue`、`ui/src/widgets/CurrentProjectWidget.vue`、`ui/src/api/learningService.ts`（`projectApi`） |

## 与 `profile_projects` 的区别（**别混**）

| | `projects`（本模块） | `profile_projects`（阶段7） |
|---|---|---|
| 语义 | 正在做 / 要做的事 | 档案里的**经历条目** |
| 有目录 | ✅ 可绑定项目根目录 | ❌ |
| 有状态 | ✅ `ongoing/paused/done` | ❌ |
| 联动 | 绑工作模式、挂学习目标 | 由 AI 建议、需用户确认 |

混用会让"进行中的项目"与"已入职历的经历"语义打架。

## 关键设计

1. **"选哪个项目"由 core 决定**（`ProjectRepo::by_mode`）：优先返回未完成的项目，
   否则回退到最新一个。**前端不自己过滤** —— 两侧各写一套规则迟早不一致。
2. **完成项目只提议、不代改**：PUT 把项目置为 `done` 时，若它挂着未完成的学习目标，
   响应里带 `linkedGoalDone: true`，**目标状态一个字都不动** —— 由 UI 询问用户是否一并完成
   （红线 V3 的邻居：系统不替用户改状态）。
3. **绑定时校验存在性**：`mode_name` 必须是已存在的工作模式（防止拼错名字造成"绑了个空气"）；
   `goal_id` 同理。

## 验收步骤

机器验收：

```bash
python tools/verify_stage6.py    # 验收项 7 覆盖：绑定模式 / by-mode 命中 / 优先级 / 只提议不代改
```

人工验收：

1. 项目页新建项目，填写名称/角色/技术栈/起止时间/目录，**选择要绑定的工作模式**与学习目标。
2. 到 Dashboard 进入该工作模式 → 「当前项目」Widget 应显示它（不刷新页面，靠 `MODE_CHANGED` 事件更新）。
3. 把项目标记为"完成" → 界面**询问**是否一并完成关联目标；
   **拒绝**该询问后，去学习页确认目标状态**没变**。
4. 同一模式挂两个项目（一个已完成、一个进行中）→ Widget 显示的是**进行中**那个。
