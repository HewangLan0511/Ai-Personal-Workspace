-- 0008 · 阶段9：插件审计日志（12 §A3/C4）
-- 所有插件 API 调用与外部 Agent 网关调用（含被拦截的越权尝试）都落一行：
-- 谁（plugin_id，外部 Agent 记作 "agent:<name>"）、何时、做了什么、结果如何。
-- 审计是安全边界的证据面：权限拒绝（PLUGIN_PERMISSION_DENIED）与崩溃（PLUGIN_ERROR）
-- 均可由本表回溯，管理页据其展示"最近活动"。

CREATE TABLE IF NOT EXISTS plugin_audit (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  plugin_id  TEXT NOT NULL,              -- 插件 id 或 "agent:<name>"
  action     TEXT NOT NULL,              -- 如 "file.read" / "system.mediaNow" / "gateway.mode.read"
  outcome    TEXT NOT NULL,              -- ok | denied | error
  detail     TEXT,                       -- JSON 摘要（不含大正文，数据轻量化）
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_plugin_audit_plugin
  ON plugin_audit(plugin_id, created_at DESC);
