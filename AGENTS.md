# AGENTS.md（仓库根入口）

> 本文件是**指针文件**，不是完整指令。作用只有一个：让任何自动读取 `AGENTS.md` 的工具都能找到真正的入口。

## 你要读的顺序

| 顺序 | 文件 | 作用 |
|:----:|------|------|
| 1 | [`HANDOFF.md`](HANDOFF.md) | **交接总入口**：当前进度、必读顺序、环境坑、红线、送审流程、下一步任务 |
| 2 | [`docs/agent-dev/AGENTS.md`](docs/agent-dev/AGENTS.md) | **最高优先级开发指令**：十条硬约束、五步工作流、审核关卡 |
| 3 | [`docs/agent-dev/02-架构与目录规范.md`](docs/agent-dev/02-架构与目录规范.md) | 强制目录结构、分层红线、Rust/Python 边界 |
| 4 | [`docs/agent-dev/03-数据契约与接口规范.md`](docs/agent-dev/03-数据契约与接口规范.md) | 数据表、JSON Schema、事件总线、接口契约 |
| 5 | [`docs/reviews/LEDGER.md`](docs/reviews/LEDGER.md) | **项目进度唯一真相来源** |

## 三句话版本（若你只有 10 秒）

1. **项目**：Personal Workspace —— 本地优先、AI 增强、插件可扩展的个人智能工作空间。
2. **现状**：阶段0（指令集）已通过审核，**阶段1~9 未开工，工作区无代码**。
3. **你的下一步**：读 `HANDOFF.md` → 定稿 ADR-001 → 按 `docs/agent-dev/04-阶段指令-基础框架.md` 开发阶段1 → 「申请审核阶段 1」。

## 环境提醒

`grep` / `head` / `find` / `rm` 在本机不可用，请用内置文件工具与 Python。
python：`C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe`

**`.workbuddy/` 目录不可删除。**
