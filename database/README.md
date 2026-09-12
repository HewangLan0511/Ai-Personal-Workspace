# database/ —— 参考性 schema 与种子

> 本目录的 schema.sql 是 `core/migrations/` 的**镜像快照**，仅供人阅读与 diff 审查。
> 真相来源是 `core/migrations/`（core 启动时内嵌执行）——改表请改 migrations，再同步本文件。

- `schema.sql`：当前版本的完整建库 DDL（= 全部 migrations 串联）
- `seeds/`：首次建库时写入的默认数据

契约：`docs/agent-dev/03-数据契约与接口规范.md`
