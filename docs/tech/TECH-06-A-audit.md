# TECH-06-A · AI 模型真实连接完善 —— 审计（先审计，后编码）

> 日期：2026-09-16 · 性质：**审计**（只读，本文件不含任何代码改动）
> 上游：`docs/tech/TECH-05-D-ui-assistant-app-layer.md`（P1-A 收口）
> 本轮范围：TECH-06-A 一个子阶段。**不实现**模型市场 / 自动下载模型 / Agent 执行。

---

## 一、审计问题：模型管理中心现在是"展示态"还是"真实态"？

**结论：链路已经是真实的，但"状态语义"是失真的。**
取数与探测都真的走 core → sidecar → HTTP；问题出在**归约层把不同原因糊成了同一个词**，
以及**三类连接里有一类（Agent）根本没探测**。

---

## 二、已有能力（可直接复用，禁止重建）

| 能力 | 落点 | 证据 |
|---|---|---|
| 唯一事实来源 | `ModelRegistry` | `ui/src/ai/model/registry.ts:216`（class）；全应用单例 `ai/model/bridge.ts:53` `getSharedRegistry()` |
| 唯一"会发请求"的方法 | `registry.check(id)` | `registry.ts:646`；注释明确写"**唯一会发请求的方法**" |
| 探测 → 真实 HTTP | `providers.testConnection` → `ModelIo.listRemoteModels` | `ai/model/provider.ts`（三个 Adapter）；`ai/model/ports.ts:161` 调 `ai_list_models` |
| core 侧命令 | `ai_list_models` | `core/src/api/commands.rs:638` → `crate::ai::list_models`（`core/src/ai/mod.rs:288`）→ sidecar `/ai/models` |
| sidecar 侧实现 | `ai/service.py` | `/ai/models` 端点（Provider 真实 HTTP，key 从系统凭据库取） |
| 状态归约（已存在） | `entryStatusOf(profile)` | `registry.ts:196` → `disabled / unavailable / ready / unchecked` |
| UI 状态词表（已存在） | `ModelsView.vue:124` `STATUS_LABEL` | 已连接 / 未测试 / 不可用 / 已停用 |
| **Agent 健康探测（已存在，未被模型域用）** | `agents_list` / **`agent_health`** | `core/src/agents.rs:121` / `:209`（真实 `GET {url}{healthCheck}`，含审计）；UI 侧仅 `api/pluginService.ts` 包了壳 |

> 实测：`agents_list` / `agent_health` / `agents_save` / `agent_invoke` 四个命令名在
> `ui/src` 下**只出现在 `api/pluginService.ts`**，**零页面/零 Runtime 消费**。
> → "Agent 连接状态检测"可以**复用既有 core 能力完成，零新增后端命令**。

---

## 三、缺口（本轮要补的四件事）

### A-1 状态词表与需求不符（**失真**）

需求要四个语义：**已连接 / 未配置 / 连接失败 / 离线**。
现状把 **离线（本地服务没起）** 与 **连接失败（鉴权/超时/限流）** 一起塞进「不可用」：

```
registry.ts:196   entryStatusOf(): lastError 一旦有值 → 一律 'unavailable'
ModelsView.vue:127  unavailable: { text: '不可用' }   ← 两个语义挤在一个词里
```

而 `ProviderErrorCode`（`provider.ts:67`）本来就能区分：`local_model_down` / `unreachable`
是"离线"，`auth_failed` / `timeout` / `rate_limit` / `bad_response` 是"连接失败"。
**信息在归约时丢了。**

### A-2 `ModelListEntry` 不透出失败原因（**UI 拿不到证据**）

`ModelListEntry`（`registry.ts:133-142`）字段：`status / capabilities / isDefault / hasSecret / enabled`。
**没有 `lastError`、没有 `lastCheck`、没有 `needsSecret`** ——
所以 UI 即便想区分"离线"与"连接失败"也**没有数据可用**，只能显示一个笼统词。
→ 必须把失败码与探测时间透出到列表投影（**加法**，不改既有字段语义）。

### A-3 Agent 连接检测缺失（**三类连接缺一类**）

`AgentAdapter.testConnection`（`provider.ts`）**不探测**，直接：

```
const why = d.enabled ? 'Agent 接入协议（握手 / 鉴权 / 流式分帧）尚未定稿' : d.note || '…'
return result(d, false, 'not_implemented', why, 0, 0, false)
```

需求要"支持 Agent 连接状态检测"。core 已有 `agent_health`（真实 HTTP 探测），
缺的只是**把它接进 `ModelIo` 端口**。这是"新接口包裹旧逻辑"，不是新能力。

### A-4 探测存在一处潜在**假绿**入口

```
ports.ts:157-159   if (!inTauri()) return []      // 浏览器/无 core 环境
provider.ts        ApiAdapter: 不抛错 → ok=true, '连通，0 个模型'
```

即**无 core 环境下，探测会把"拿不到"报成"已连接"**。
（本环境因 `loadProviders()` 也返回 `[]`、页面显示"核心服务未连接"，故未实际触发；
但这是真实的假绿入口，与 TECH-06-A 的验收口径"UI 显示状态 == 真实状态"直接冲突。）
→ 必须改成如实失败（`unreachable`）。

---

## 四、**本轮不做**（显式登记，避免被误读为遗漏）

| 项 | 为什么不做 | 影响 |
|---|---|---|
| 模型清单持久化 | `registry.list()` 只读内存 `this.store`；`hydrate()`（`registry.ts:276`）只灌 Provider / 凭据 / canonical，**不灌模型档案**；全 `ui/src` **无任何模型清单持久化写点**（实测 grep `setItem('…models…)` 零命中）。→ **刷新后"我的模型"为空**。 | **本轮不补**：补它要么新增 localStorage 键（会推翻 TECH-05-D 冻结的模型域键基线 `{ui.ai.provider, ui.ai.model, ui.ai.apiBase}`），要么在 core 加 config 键 + 迁移。两者都超出"A 阶段最小改动"，且需求原文把"刷新后仍在"这条验收**放在了 B 阶段**。列为下一步第一优先。 |
| 模型市场 / 自动下载 | 需求明确禁止 | — |
| Agent 执行（`agent_invoke`） | 需求明确禁止；本轮只做**检测** | — |
| 真实凭据写入 / 密钥面 | 已有（设置页 `ai_set_credential`），本阶段不碰 | — |

---

## 五、下一阶段建议（移交）

1. **模型清单持久化**（最高优先）：建议落 core config 键（如 `ai.models.registry`，
   JSON 字符串），与 canonical 同层——避免新增 localStorage 键、避免两处真相。
   需要在 `core/src/db/config.rs` 三处登记 + 迁移版本 +1，并在验收里**显式记账**基线变更。
2. 探测结果的**跨会话保留**（`lastCheck` / `lastError`）可与上条一并落库；
   否则每次启动都要重测（现状即如此，且 UI 已如实显示"未测试"）。
3. `web-ai` / `user-agent` 两个占位 Provider 的 `enabled=false` 语义，
   建议在 UI 上显式表达为「未开放」而不是挤进「离线」（本轮用 `offline` 承接，语义上可接受但不精确）。
