# providers/ —— AI Provider 抽象层（阶段5 交付）

详见 `docs/agent-dev/08-阶段指令-AI助手.md` §1。

必实现的 Provider（契约 3.3 / 3.4）：

| Provider | 接入 | 备注 |
|----------|------|------|
| OpenAI 兼容 | HTTP `/v1/chat/completions` | 覆盖 OpenAI / DeepSeek / 通义 / Kimi 等 |
| DeepSeek | OpenAI 兼容 | base_url + api_key |
| Ollama | localhost:11434 | 本地，无需 key |
| LM Studio | localhost:1234/v1 | 本地，OpenAI 兼容 |
| 网页 AI | 内嵌 WebView | 无 API 费用 |
| 用户 Agent | HTTP / WebSocket | 自定义 Agent 接入（契约 3.2.5） |

阶段1 占位：目录已建立，无代码。