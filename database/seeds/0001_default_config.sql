-- 0001 · 默认配置种子（首次建库时由 core 写入；键登记见 core/src/db/config.rs KEYS）
--
-- 注意：`schema_version`（数据契约版本）**不在此处写入** —— 它由 db::initialize()
-- 按 migrations::CONTRACT_SCHEMA_VERSION 统一落库（单一所有者，修复 L-006）。
-- 本文件只负责业务默认值；全部 INSERT OR IGNORE，重复执行无副作用。

INSERT OR IGNORE INTO config (key, value, updated_at) VALUES
  ('ui.theme', '"light"', datetime('now', 'localtime')),
  ('ui.nav.collapsed', 'false', datetime('now', 'localtime')),
  ('ui.dashboard.widgets', '[]', datetime('now', 'localtime')),
  ('ui.dashboard.usage', '{}', datetime('now', 'localtime')),
  ('ui.dashboard.layout_locked', 'false', datetime('now', 'localtime')),
  ('app.autostart', 'false', datetime('now', 'localtime')),
  ('app.data_dir', '""', datetime('now', 'localtime')),
  ('ai.default_provider', '""', datetime('now', 'localtime')),
  ('privacy.telemetry', 'false', datetime('now', 'localtime'));
