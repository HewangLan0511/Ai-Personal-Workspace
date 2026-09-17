-- 0003 · work_modes 补 switch_policy
-- 契约依据：docs/agent-dev/06-阶段指令-工作模式引擎.md §3「模式切换语义」
--   additive（默认）/ exclusive / ask
-- 规则：迁移只增不改（契约 3.1）—— 只 ADD COLUMN。
ALTER TABLE work_modes ADD COLUMN switch_policy TEXT DEFAULT 'additive';
