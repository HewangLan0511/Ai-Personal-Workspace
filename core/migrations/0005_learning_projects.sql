-- 0005 · 阶段6 学习成长与项目管理
-- 契约：docs/agent-dev/03-数据契约与接口规范.md §3.1（v8）
-- 规则：迁移只增不改 —— 本脚本只做 ADD COLUMN 与 CREATE TABLE，
--       不改动任何既有列（SQLite 的 ADD COLUMN 是幂等友好的唯一增量手段）。

-- ---------------------------------------------------------------------------
-- learning_goals：补齐阶段6 §1 的表单字段（期望完成时间 / 优先级）
-- 与 §5 提醒机制所需的节流字段（同目标最多 7 天提醒一次）。
-- ---------------------------------------------------------------------------
ALTER TABLE learning_goals ADD COLUMN expected_at TEXT;
ALTER TABLE learning_goals ADD COLUMN priority TEXT DEFAULT 'medium';  -- low|medium|high
ALTER TABLE learning_goals ADD COLUMN last_reminded_at TEXT;

-- status 的取值域扩展为 not_started|learning|paused|done|archived
-- （§5 提醒动作「归档」）。该列是无 CHECK 的 TEXT，故无需 DDL —— 仅契约登记。

-- ---------------------------------------------------------------------------
-- learning_roadmap：补齐阶段6 §2 的结构化路线字段。
-- AI 返回的节点带 estimated（预估时长）与 resources（资料方向），
-- 原表只有 title/note/sort_order，存不下这两项 ⇒ 只能塞进 note，
-- 那样"结构化到表"就名存实亡（§禁止事项第 4 条）。
-- ---------------------------------------------------------------------------
ALTER TABLE learning_roadmap ADD COLUMN estimated TEXT;
ALTER TABLE learning_roadmap ADD COLUMN resources TEXT;   -- JSON 数组：["..."]

-- ---------------------------------------------------------------------------
-- projects：项目管理（阶段6 §6）。
-- 与 profile_projects（阶段7 个人档案的"项目经历"）是**两个不同的实体**：
--   - projects       = 正在做/要做的事（有目录、可绑定工作模式、可挂学习目标）；
--   - profile_projects = 档案里的经历条目（AI 建议需用户确认，阶段7 从本表同步）。
-- 混用会让"进行中的项目"与"已入职历的经历"语义打架。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS projects (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL,
  role        TEXT,                                 -- 承担角色
  summary     TEXT,                                 -- 简介
  tech_stack  TEXT,                                 -- JSON 数组
  start_date  TEXT,
  end_date    TEXT,
  status      TEXT NOT NULL DEFAULT 'ongoing',      -- ongoing|paused|done
  directory   TEXT,                                 -- 关联目录（可选）
  mode_name   TEXT,                                 -- 绑定的工作模式名（§6 与核心的联动点）
  goal_id     INTEGER REFERENCES learning_goals(id),-- 关联学习目标（完成项目 = 达成目标）
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  deleted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_projects_mode ON projects(mode_name);
CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
CREATE INDEX IF NOT EXISTS idx_projects_goal ON projects(goal_id);
