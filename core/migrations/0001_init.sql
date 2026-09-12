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
  created_at   TEXT NOT NULL,
  updated_at   TEXT NOT NULL,
  deleted_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_apps_category ON apps(category);
CREATE INDEX IF NOT EXISTS idx_apps_launch_count ON apps(launch_count DESC);

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
  is_builtin  INTEGER DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS learning_goals (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  title       TEXT NOT NULL,
  description TEXT,
  status      TEXT NOT NULL DEFAULT 'not_started',
  roadmap     TEXT,
  sort_order  INTEGER DEFAULT 0,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL,
  deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS learning_roadmap (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  goal_id      INTEGER NOT NULL REFERENCES learning_goals(id),
  title        TEXT NOT NULL,
  status       TEXT NOT NULL DEFAULT 'not_started',
  note         TEXT,
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

CREATE TABLE IF NOT EXISTS usage_stats (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  stat_date    TEXT NOT NULL,
  app_name     TEXT NOT NULL,
  foreground_s INTEGER NOT NULL DEFAULT 0,
  UNIQUE(stat_date, app_name)
);

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
