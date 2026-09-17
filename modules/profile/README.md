# profile/ —— 个人数字档案模块（阶段7 交付）

**定位一句话**：记录"我是谁，我正在成为谁。"
指令：`docs/agent-dev/10-阶段指令-个人档案.md` · 契约：`03` §3.1 profile 表族 + §3.4 `/api/v1/profile/*`（v9）

## 交付物落点

| 交付物 | 位置 |
|--------|------|
| 档案数据层（basic/skills/projects/timeline CRUD + 建议队列） | `core/src/profile/repository.rs` |
| 采集器（学习目标完成 / 项目 done / 新增项目 / 高频软件 → 建议） | `core/src/profile/mod.rs`（`collect_*` / `scan_app_usage`） |
| Markdown 导出（只含 confirmed=1 + 隐私告知） | `core/src/profile/export.rs` |
| 迁移 0006（`pending_suggestions` 表 + `profile_skills.category` 列） | `core/migrations/0006_profile.sql` |
| 拒绝清单 config 键 `profile.rejected_kinds` | `core/src/db/config.rs` |
| 22 个 command + 16 组 HTTP 路由 | `core/src/api/commands.rs` / `core/src/api/mod.rs` |
| 档案主页（引导 3 字段 / 技能分组折叠 / 项目 / 时间线 / 建议条 / 导出） | `ui/src/views/ProfileView.vue` |
| API 封装 + 状态订阅 | `ui/src/api/profileService.ts` / `ui/src/stores/profile.ts` |
| 验收脚本（8 项验收全机器化 + 接线检查） | `tools/verify_stage7.py` |

## 三个不变量（审核重点）

1. **AI 只建议，用户拍板（红线 V3）** —— 采集器/AI 的唯一写路径是 `pending_suggestions`
   （`status='pending'`）；档案四表只被「用户手动编辑」与「`suggestion_confirm`（用户点击）」写入。
   机器断言：`verify_stage7.py` 验收项 3 的**档案四表全行快照比对**（触发全部采集链前后逐行一致）。
2. **咨询模式读不到档案（红线 V2）** —— 档案进 AI 上下文的唯一通道是 `ai_context.rs`
   的 `profile` scope，且 `is_data_allowed()` 只放行 workspace；sidecar 侧 `assemble()`
   对 consult 返回空。两侧各有单测/端到端证据（`only_workspace_mode_is_data_allowed` /
   `verify_stage7.py` 验收 7）。
3. **同源只挂一条 pending** —— `idx_pending_unique_open`（部分唯一索引）在库层面兜底，
   采集器重复触发不刷屏；`ref_key` 语义：`goal_done:{id}` / `project_new:{id}` /
   `project_done:{id}` / `project_done_tl:{id}` / `app_hot:{app_name}`。

## 提醒/建议的规则

| 触发点 | 产生建议 | 触发时机 |
|--------|----------|----------|
| 学习目标 status → done | timeline（type=learning） | `learning::apply_goal_update` 状态转变沿 |
| 项目 status → done | project + timeline（type=project） | `project::apply_update` 状态转变沿 |
| 新增项目 | project（status=ongoing） | `project::apply_add` |
| 软件启动次数 ≥ 20 | skill（等级 = min(90, 次数×2)，分类=tool） | `profile_suggestions_scan` 显式扫描 |

用户对建议可：**逐条确认 / 批量确认 / 忽略 / 永久拒绝某类**（拒绝清单落 `profile.rejected_kinds`，
之后该类变化不再入队）。确认写入正式表后发布 `PROFILE_UPDATED { changed }`。

## 验收步骤

**机器**（前置 `python tools/rust.py build --release`）：

```bash
python tools/gate.py --stage 7 --build      # 0F/0W
python tools/rust.py test                   # 74/74（新增 8 个 profile 单测）
python tools/verify_stage7.py               # 验收 1~8 + 接线检查
```

**人工**（机器测不了的两条）：

1. 真窗口打开 `/profile`：首次引导 3 字段 → 保存 → 顶部展示 + 签名可见；
   技能分组条形图随等级输入即时变化；导出按钮下载 `个人档案.md` 且内容可读。
2. 事件运行时投递：在「项目管理」完成一个项目，切到档案页 —— 待确认条应**即时**出现
   （`PROFILE_UPDATED` 经事件桥 → `PROFILE_UPDATED` 订阅刷新；脚本只有接线级证据）。

## 边界（如实声明）

- 「AI 从项目目录推断项目经历」（10 §3 数据来源之三）**未做自动推断** —— 需要读用户
  文件系统的内容做启发式分析，隐私收益存疑且不可复现验收；本阶段以「项目管理模块
  的用户确认数据 + 手动添加」为来源。采集器的建议文案是**规则模板**，不调 LLM ——
  确定性优先（10 §5 的"AI 生成建议"以建议产出为准，产出走的是确定规则，质量可控且可机器验收）。
- 技能建议的等级（`min(90, 启动次数×2)`）是**近似**，不是能力评估 —— 用户确认时就是
  在人工校准这个值。
- 导出只做 Markdown；PDF（10 §6 "优先做 Markdown"的次要项）未做。
