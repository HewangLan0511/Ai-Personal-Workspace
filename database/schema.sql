-- 0001 · 初始库结构
-- 契约：docs/agent-dev/03-数据契约与接口规范.md §3.1（v2）
-- 规则：迁移只增不改；时间统一本地时区 ISO8601 文本。

CREATE TABLE IF NOT EXISTS config (
  key         TEXT PRIMARY KEY,
  value       TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS apps (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  name         TEXT NOT NULL,
  path         TEXT NOT NULL UNIQUE,
  args         TEXT DEFAULT '',
  icon         TEXT,
  type         TEXT,
  category     TEXT,
  launch_count INTEGER DEFAULT 0,
  last_used_at TEXT,
  pinned       INTEGER DEFAULT 0,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  deleted_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_apps_category ON apps(category);
CREATE INDEX IF NOT EXISTS idx_apps_launch_count ON apps(launch_count DESC);
CREATE INDEX IF NOT EXISTS idx_apps_pinned ON apps(pinned DESC);

CREATE TABLE IF NOT EXISTS work_modes (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  name          TEXT NOT NULL UNIQUE,
  description   TEXT,
  icon          TEXT,
  apps          TEXT NOT NULL,
  open_targets  TEXT,
  layout        TEXT,
  ai_profile    TEXT,
  auto_apply    INTEGER DEFAULT 0,
  switch_policy TEXT DEFAULT 'additive',   -- additive|exclusive|ask（06 §3；迁移 0003 追加）
  use_count     INTEGER DEFAULT 0,
  last_used_at  TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  deleted_at    TEXT
);

CREATE TABLE IF NOT EXISTS layouts (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,
  slots       TEXT NOT NULL,
  monitor     INTEGER DEFAULT 0,
  ai_sidebar  TEXT,                        -- AI 侧栏配置（契约 3.2.2；迁移 0004 追加）
  is_builtin  INTEGER DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_goals (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  title            TEXT NOT NULL,
  description      TEXT,
  status           TEXT NOT NULL DEFAULT 'not_started',  -- not_started|learning|paused|done|archived
  roadmap          TEXT,          -- AI 原始输出快照（JSON 解析失败时的降级展示依据）
  expected_at      TEXT,          -- 期望完成时间（迁移 0005 追加）
  priority         TEXT DEFAULT 'medium',  -- low|medium|high（迁移 0005 追加）
  last_reminded_at TEXT,          -- 上次提醒时间；同目标最多 7 天一次（迁移 0005 追加）
  sort_order       INTEGER DEFAULT 0,
  created_at       TEXT NOT NULL,
  updated_at       TEXT NOT NULL,
  deleted_at       TEXT
);

CREATE TABLE IF NOT EXISTS learning_roadmap (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id      INTEGER NOT NULL REFERENCES learning_goals(id),
  title        TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'not_started',
  note         TEXT,
  estimated    TEXT,              -- 预估时长，如 "2周"（迁移 0005 追加）
  resources    TEXT,              -- JSON 数组：资料方向（迁移 0005 追加）
  sort_order   INTEGER DEFAULT 0,
  completed_at TEXT,
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_updates (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id    INTEGER NOT NULL REFERENCES learning_goals(id),
  node_id    INTEGER REFERENCES learning_roadmap(id),
  content    TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 项目管理（阶段6 §6；迁移 0005 新建）。
-- 与 profile_projects（阶段7 档案的"项目经历"）是两个实体，勿混。
CREATE TABLE IF NOT EXISTS projects (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  role       TEXT,
  summary    TEXT,
  tech_stack TEXT,                                 -- JSON 数组
  start_date TEXT,
  end_date   TEXT,
  status     TEXT NOT NULL DEFAULT 'ongoing',      -- ongoing|paused|done
  directory  TEXT,
  mode_name  TEXT,                                 -- 绑定的工作模式名
  goal_id    INTEGER REFERENCES learning_goals(id),-- 关联学习目标
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS profile_basic (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT,
  direction  TEXT,
  interests  TEXT,
  motto      TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_skills (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL UNIQUE,
  level      INTEGER NOT NULL DEFAULT 0,
  category   TEXT NOT NULL DEFAULT 'other',  -- 0006：other|lang|framework|tool|domain
  source     TEXT DEFAULT 'user',
  confirmed  INTEGER DEFAULT 1,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_projects (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  name       TEXT NOT NULL,
  role       TEXT,
  summary    TEXT,
  tech_stack TEXT,
  start_date TEXT,
  end_date   TEXT,
  status     TEXT DEFAULT 'ongoing',
  source     TEXT DEFAULT 'user',
  confirmed  INTEGER DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profile_timeline (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  event_date  TEXT NOT NULL,
  title       TEXT NOT NULL,
  description TEXT,
  type        TEXT,
  source      TEXT DEFAULT 'user',
  confirmed   INTEGER DEFAULT 1,
  created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plugins (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  plugin_id    TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,
  version      TEXT NOT NULL,
  author       TEXT,
  entry        TEXT NOT NULL,
  enabled      INTEGER DEFAULT 0,
  installed_at TEXT NOT NULL,
  updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS plugin_permissions (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  plugin_id   TEXT NOT NULL,
  permission  TEXT NOT NULL,
  scope       TEXT,
  granted_at  TEXT NOT NULL,
  UNIQUE(plugin_id, permission, scope)
);

-- 阶段9 落地形态（与迁移 0008 一致）：插件与外部 Agent 审计日志。
-- 卸载插件保留审计行（历史事实），plugins/plugin_permissions 行物理删除。
CREATE TABLE IF NOT EXISTS plugin_audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  plugin_id  TEXT NOT NULL,              -- 插件 id 或 "agent:<name>"
  action     TEXT NOT NULL,
  outcome    TEXT NOT NULL,              -- ok | denied | error
  detail     TEXT,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plugin_audit_plugin
  ON plugin_audit(plugin_id, created_at DESC);

-- 阶段8 落地形态（与迁移 0007 一致）：只存"按天+应用"的聚合秒数，
-- 不存前台切换的时间点明细（11 §A4 数据轻量化）。
-- 原预设结构（id/stat_date/foreground_s）在阶段8 实现时更新为三列主键形态。
CREATE TABLE IF NOT EXISTS usage_stats (
  day      TEXT    NOT NULL,
  app_name TEXT    NOT NULL,
  seconds  INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (day, app_name)
);

CREATE INDEX IF NOT EXISTS idx_usage_day ON usage_stats(day, seconds DESC);

CREATE TABLE IF NOT EXISTS ai_conversations (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  title         TEXT,
  provider      TEXT NOT NULL,
  model         TEXT,
  mode          TEXT NOT NULL,
  message_count INTEGER DEFAULT 0,
  working_dir   TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
