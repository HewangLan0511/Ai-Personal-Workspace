-- 0006 · 阶段7 个人数字档案
-- 契约：docs/agent-dev/03-数据契约与接口规范.md §3.1（v9）
-- 规则：迁移只增不改 —— 只做 ADD COLUMN 与 CREATE TABLE。
--
-- profile_basic / profile_skills / profile_projects / profile_timeline 四张档案表
-- 0001 建库时已创建（含 source / confirmed 字段），本迁移不碰它们 —— 只补缺失的列。

-- ---------------------------------------------------------------------------
-- profile_skills：补「技能分类」列（10 §2：编程语言 / 框架 / 工具 / 领域知识）。
-- 0001 建表时只有 name/level/source/confirmed；没有分类则 §2 的"分组折叠"无从谈起。
-- 旧数据（阶段5 的 ai_context 只读过 confirmed=1 的 name）默认归入 'other'。
-- ---------------------------------------------------------------------------
ALTER TABLE profile_skills ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
-- other|lang|framework|tool|domain

-- ---------------------------------------------------------------------------
-- pending_suggestions：待确认建议队列（10 §5 的硬关口 —— ★ 用户确认 ★）。
--
-- 设计要点：
-- * AI / 采集器只允许 INSERT 本表（status='pending'），**永远不允许直接写档案四表**；
--   只有 confirm 动作（用户点击）才把 payload 落进正式表。红线 V3 的表级落实。
-- * ref_key 是**去重键**：同一来源（如同一个目标完成、同一款高频软件）只挂一条
--   pending 建议，由下方 partial UNIQUE INDEX 在库层面兜底 —— 采集器重复触发不会刷屏。
-- * payload 存 JSON：确认时要写入目标表的完整数据。确认动作由 core 按 kind 分发，
--   payload 结构不在这里校验（校验在 repository 的 apply_suggestion）。
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pending_suggestions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  kind       TEXT NOT NULL,                     -- timeline | skill | project
  ref_key    TEXT NOT NULL,                     -- 去重键，如 "goal_done:3" / "app_hot:Code"
  title      TEXT NOT NULL,                     -- 给用户看的一句话
  payload    TEXT NOT NULL,                     -- JSON：确认时写入正式表的数据
  status     TEXT NOT NULL DEFAULT 'pending',   -- pending | confirmed | ignored
  created_at TEXT NOT NULL,
  decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_status ON pending_suggestions(status, kind);
-- 部分唯一索引：同 kind+ref_key 只允许一条 pending（已决定的历史条目不占位，可再次建议）
CREATE UNIQUE INDEX IF NOT EXISTS idx_pending_unique_open
  ON pending_suggestions(kind, ref_key) WHERE status = 'pending';
