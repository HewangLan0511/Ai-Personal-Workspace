# providers/ —— AI Provider 抽象层

阶段5 交付。**禁止任何业务代码直接发某个模型的 HTTP 请求** —— 一切模型调用都经 `AIProvider` 接口。

## 一句话架构

```
core（装配上下文 + 转发）
  └─ HTTP POST /ai/chat  →  system/service.py（NDJSON 流式）
                              └─ ai/service.py::stream()
                                   └─ registry.get(provider).impl.chat()   ← 唯一的模型出口
                                        └─ http.client 直连模型服务
```

## 已实现的 Provider（共 7 个登记项）

| id | 实现 | 协议 | needs_key | enabled |
|----|------|------|:---------:|:-------:|
| `openai` | `openai_compat.OpenAICompatProvider` | `POST /v1/chat/completions`（SSE） | ✔ | ✔ |
| `deepseek` | 同上（复用） | 同上 | ✔ | ✔ |
| `compatible` | 同上（复用） | 同上 | ✔ | ✔ |
| `ollama` | `ollama.OllamaProvider` | `POST /api/chat`（**裸 JSON 行**） | ✘ | ✔ |
| `lmstudio` | `openai_compat`（其 OpenAI 兼容层） | 同上 | ✘ | ✔ |
| `web-ai` | `web_ai.WebAIProvider` | 内嵌 WebView | ✘ | **✘ 占位** |
| `user-agent` | `user_agent.UserAgentProvider` | HTTP / WebSocket | ✘ | **✘ 占位** |

**为什么 `deepseek` / `compatible` / `lmstudio` 与 `openai` 用同一个类**：
它们遵循的是**同一个协议**。为它们各写一个类 = 复制粘贴同一段解析逻辑，
协议一改就要改三处。分开登记只是为了 UI 上给用户**开箱即用的预填值**
（`default_base` / `default_model`）。

**为什么 `ollama` 必须单独实现**：它的原生协议有三处实质差异 ——
① 每行是**裸 JSON**（不是 `data: {...}` SSE 帧）；② 以 `{"done": true}` 结尾而非 `[DONE]`；
③ 参数名是 `options.num_predict` 而非 `max_tokens`。

**为什么 `web-ai` / `user-agent` 是诚实的占位而不是硬做**：
- `web-ai`：网页 AI 的响应**不经过本应用管线** → 无法满足 08 §3「必须支持流式」
  与 §禁止事项「不要做无流式的实现」。硬做一个"能聊天"的壳是**谎报**。
- `user-agent`：技术上可行，缺的是**协议设计与真实需求**（握手 / 鉴权 / 流式分帧）。
  没有需求方就没有正确的协议。

两者都 `enabled=False` + `chat()` 抛 `not_implemented`，并有单元测试锁死
「必须抛错，不得静默返回空」（`tools/test_ai.py`）。

---

## ★ 如何新增一个 Provider（三处，不改业务代码）

**判据**：Provider 抽象是否成功，就看"新增一个 Provider 需不需要动业务代码"。

### 1. 写实现类（`ai/providers/my_provider.py`）

```python
from .base import Chunk, Message, ProviderConfig, ProviderError, ERR_UNREACHABLE

class MyProvider:
    name = "my-provider"          # 与 registry 的 id 一致

    def chat(self, messages: list[Message], *,
             config: ProviderConfig, stream: bool = True) -> Iterator[Chunk]:
        # 逐块 yield Chunk(delta="...")，最后一块 Chunk(done=True, tokens=N)
        ...

    def list_models(self, *, config: ProviderConfig) -> list[str]:
        return []        # 拉不到就返回空列表，**不抛异常**

    def health(self, *, config: ProviderConfig) -> bool:
        return False     # 不抛异常
```

**硬约束**：
- `chat()` 是**同步生成器**，不是 `async def`。sidecar 是 `ThreadingHTTPServer`，
  用同步生成器即可逐块吐给客户端；在 stdlib-only 环境里引 asyncio 事件循环是净负债。
- `stream=False` 时**仍走同一实现**（内部收完再合并成一个 chunk 吐出），
  不要写第二套解析逻辑 —— 否则两份逻辑必然漂移。
- **只用标准库**（`http.client` + `json`）。sidecar 零依赖，不能因为一个 Provider 破例。
- 导入用**相对导入** `from .base import ...`。绝对导入 `from base import ...` 会让同一模块
  被以两个不同路径加载成两个类对象，`except ProviderError` 就抓不到异常（阶段5 踩过）。

### 2. 在 `registry.py` 登记（**只改这一个文件**）

```python
"my-provider": ProviderMeta(
    id="my-provider",
    label="我的供应商",
    impl=MyProvider(),
    default_base="https://api.example.com/v1",
    default_model="my-model",
    needs_key=True,
    capabilities=["chat", "stream", "models"],
    note="一句话说明",
),
```

### 3. （仅当 Provider 需要 key）确认凭据引用名

`ai/credentials.py::ref_for(provider_id)` 自动产出 `pw/{id}/default`，
**不需要额外登记**。UI 的设置页会自动列出所有 `needs_key=True` 的 Provider。

### 4. 自检

```bash
python tools/test_ai.py            # 抽象层 28 项断言
python tools/verify_stage5.py      # 端到端（含 mock Provider）
```

---

## 失败码与降级（08 §7）

| code | 触发 | UI 提示（`ui/src/stores/ai.ts::humanizeError`） |
|------|------|------|
| `no_api_key` | 未配置 key | 尚未配置 API Key —— 请到「设置 → AI」中添加 |
| `local_model_down` | 本地服务未启动（ConnectionRefused） | 本地模型未运行 —— 请先启动 Ollama / LM Studio |
| `unreachable` | 网络不可达 | 网络不可达 —— 可切换到本地模型继续使用 |
| `timeout` | 超时（`retryable=True`） | 请求超时 —— 可重试或换用更快的模型 |
| `rate_limit` | HTTP 429（`retryable=True`） | 请求过于频繁 —— 请稍后再试 |
| `auth_failed` | HTTP 401/403 | API Key 被拒绝 —— 请检查密钥是否正确 |
| `bad_response` | 返回体不符合预期 | 原样透出 |
| `not_implemented` | 占位 Provider | 该 Provider 尚未开放 |
| `empty_response` | 正常结束但零产出 | 模型未返回任何内容 |

**处理原则**：错误不中断流 —— 已输出的内容保持有效，错误作为**最后一行**发出。
用户已经看到的字不会因为最后失败而消失。

---

## 单元测试

`tools/test_ai.py`（28 项断言）：
- Provider 抽象：接口完整性、占位必须抛错、未知 provider 抛错、未配 key 报 `no_api_key`
- 红线 V2 双模式隔离：consult 不注入（含"workspace 确实注入"对照组、开关生效）
- 红线 V1 凭据掩码
- 提示词渲染：变量替换、漏传变量原样保留、拒绝目录穿越
