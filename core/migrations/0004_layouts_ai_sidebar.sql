-- 0004 · layouts 补 ai_sidebar
-- 契约依据：03-数据契约与接口规范 §3.2.2 的布局 JSON 含 `aiSidebar`（AI 侧栏留位）。
-- 问题：`layouts` 表此前**没有这一列**，而阶段4 的 `scheduler::arrange` 优先从数据库读布局
--       （契约 3.2.2 的技术要点「数据库是唯一真相」）—— 于是**侧栏配置在库路径上被丢掉**，
--       阶段3 验收过的「AI 侧栏留位」在阶段4 路径上回归失效。
-- 处置：补列，让数据库形态与 JSON 契约一致。
-- 规则：迁移只增不改（契约 3.1）—— 只 ADD COLUMN。
ALTER TABLE layouts ADD COLUMN ai_sidebar TEXT;
