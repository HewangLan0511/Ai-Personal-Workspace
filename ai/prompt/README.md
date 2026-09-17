# prompt/ —— AI 提示词模板集中管理

阶段5 交付。**硬要求（08 §4）：提示词禁止散落在代码里。**

## 模板清单

| 文件 | 用途 | 变量 | 阶段 |
|------|------|------|:----:|
| `consult_default.md` | 咨询模式默认人格 | （无） | 5 ✔ |
| `dev_assistant.md` | 开发/工作助手 | `{{context}}` | 5 ✔ |
| `study_assistant.md` | 学习助手 | `{{context}}` | 5（待接） |
| `profile_suggest.md` | 档案更新建议 | `{{profile}}` 等 | V2 |
| `roadmap_generate.md` | 学习路线生成 | `{{goal}}` 等 | V2 |

**模板选择规则**（`ai/service.py::_resolve_prompt_key`）：
调用方不传 `promptKey` 时 —— `consult` → `consult_default`，其余 → `dev_assistant`。

## 变量语法

`{{变量名}}`（`\w+`，即字母数字下划线）。渲染器 `ai/prompt_renderer.py`：

```python
render("dev_assistant", {"context": "[系统] 当前工作模式：开发模式\n..."})
```

**关键取舍：未提供的变量原样保留**（输出里还是 `{{foo}}`），而不是替换成空串。
理由：漏传变量时在输出里**一眼可见**，而不是静默变成一句缺词的话。
`unresolved(text)` 可用于自检。

**不支持条件 / 循环**。提示词模板不需要图灵完备 ——
需要动态内容时，由 `ai/context.py::assemble()` 把整段装配好，
作为**一个** `{{context}}` 传入（这也是为什么只有一个变量）。

**为什么不用 Jinja2**：sidecar 是 stdlib-only（不能因为一个模板引擎破例）。
单遍正则替换足够，且**更容易审**。

## `{{context}}` 的来源（红线 V2 的关口）

`{{context}}` 由 `ai/context.py::assemble()` 产出：

| mode | assemble 的返回值 |
|------|------------------|
| `consult` | **第一行就返回**（`system_prompt = consult_default 文案`，`used_scopes = []`），**不触碰 source 的任何字段** |
| `workspace` | 按用户开关拼装「当前工作模式 / 已打开软件 / 项目目录 / 最近学习目标 / 技能背景」 |

这是**结构性**隔离，不是"提示词里叫它别看"。`consult_default.md` 里那段
"你没有任何用户数据的访问权限"是给模型**话术**上的辅助，
真正的防线是**数据根本不进请求体**（`ai/context.py:98` 的提前 return）。

> 这一段有对抗性测试锁死：`tools/verify_stage5.py` 会**故意在 consult 请求体里硬塞
> 一整套用户数据**，然后检查 mock Provider 实际收到的 system 提示词里
> 是否出现了那些标记串 —— 一个都不许出现。

## 新增模板

1. 在 `ai/prompt/` 放 `<name>.md`
2. 在 `ai/prompt_renderer.py::TEMPLATES` 加进集合（用于 `list_templates()` 与错误提示）
3. 不需要改任何业务代码 —— 调用方用 `promptKey` 指定

模板名会被校验（`/`、`\`、`..` 一律拒绝），防配置被改后目录穿越。
