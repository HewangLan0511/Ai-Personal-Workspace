# modules/ —— 第一方功能模块

业务逻辑与 UI，按主题切分。核心原则：

| 原则 | 说明 |
|------|------|
| 不依赖 plugins/ | 第一方模块与第三方插件互不影响 |
| 不写数据库 | 走 core HTTP 接口（/api/v1/* 或 Tauri command） |
| 不做窗口/进程控制 | ADR-001：交给 core |

## 模块清单

| 模块 | 阶段 | 指令文件 | 当前状态 |
|------|------|----------|----------|
| learning/ | 6 | `docs/agent-dev/09-阶段指令-学习成长.md` | ✅ 通过（REVIEW-014） |
| project/ | 6 | `docs/agent-dev/09-阶段指令-学习成长.md` §6 | ✅ 通过（REVIEW-014） |
| profile/ | 7 | `10-阶段指令-个人档案.md` | ✅ 已实现（待审核）：档案四表 + 建议确认队列 + 导出 |
| life/ | 8 | `11-阶段指令-生活与设备.md` | 阶段1 占位（将以插件形式实现） |
| device/ | 8 | `11-阶段指令-生活与设备.md` | 阶段1 占位 |

> **说明**：`learning/` 与 `project/` 是**文档 + 前端页面**的归口目录；
> 真正的实现落在 core（Rust `core/src/learning`、`core/src/project`）与 `ui/src/`。
> 这是 02 §2.2「core 是唯一写入者」的必然结果 —— modules/ 不写数据库（见上表三原则）。
