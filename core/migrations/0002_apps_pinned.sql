-- 0002 · apps 表补 pinned 字段
-- 契约依据：docs/agent-dev/05-阶段指令-软件管理.md §4「常用软件排序」
--   「支持用户置顶（pinned 字段，可在本阶段给 apps 表加 pinned INTEGER DEFAULT 0）」
-- 规则：迁移只增不改（契约 3.1）—— 只 ADD COLUMN，不改已有列、不删列。
ALTER TABLE apps ADD COLUMN pinned INTEGER DEFAULT 0;

-- 置顶排序用（pinned DESC 优先于 launch_count）
CREATE INDEX IF NOT EXISTS idx_apps_pinned ON apps(pinned DESC);
