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
2. **现状**：**阶段0~9 全部 ✅ 通过，项目阶段收官**（阶段9 插件系统与小组件 REVIEW-017：`verify_stage9.py` 29/29 · cargo test 86/86 · 门禁 0F/0W/22P）。后续 = 维护 / 遗留项 / 新需求。
3. **你的下一步**：读 `HANDOFF.md` 与 `docs/reviews/LEDGER.md` 确认状态 → 接新需求时先跑基线 `python tools/gate.py --stage 9 --build`（应 0F/0W）再动代码，改完自跑门禁 + 对应 verify 脚本。插件开发看 `docs/plugin-dev-guide.md`。

## 环境提醒

`grep` / `head` / `find` / `rm` 在本机不可用，请用内置文件工具与 Python。
python：`C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe`

**`.workbuddy/` 目录不可删除。**
