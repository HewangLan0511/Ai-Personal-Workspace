# AI Model Management Runtime（TECH-03-A）

> 日期：2026-09-15 · 状态：**已交付，验收 31/31**
> 验收工具：`tools/verify_model_registry.py`（tsc 编译领域层 → Node 直跑 T1~T5 + 静态零改动面 T6）
> 本层：`ui/src/ai/model/{model.ts, provider.ts, registry.ts, ports.ts}`
> 前置契约：`docs/reviews/PW-INTEGRATION-003-contract-freeze.md`（五层 canonical 冻结）

## 零、一句话

把散落在五个地方的 Provider / 模型配置，收进**一个 Python 侧仍为唯一真相、UI 侧只有一个读写门面**的模型层；
本轮**只建层，不改任何现有 AI 链路**（不新增 core 命令、不新增 config 键、不迁移数据库、不动 UI 页面）。

## 一、这条层解决什么问题

TECH-03-A 之前，"当前用哪个 AI 模型"这件事有**五个来源**，谁都在写、没人说了算：

| 代号 | 来源 | 键 / 位置 | 现状 |
|------|------|-----------|------|
| S1 | UI localStorage | `ui.ai.provider` / `ui.ai.model` | **读的来源**（`stores/ai.ts` 启动时读它） |
| S2 | core config 同名镜像 | `ui.ai.provider` / `ui.ai.model` | **只写不读**（UI 写进去，没人读） |
| S3 | mode `aiProfile` | `work_modes.ai_profile.provider` → `config ai.active_profile` | 建议值，非权威 |
| S4 | 无头默认 | `ai.default_provider` | pluginHost / agents / settings 消费，**无 UI 调用方** |
| S5 | 请求级 | `AiChatArgs.provider` | 单次覆盖，不持久化 |

后果：换个模型要改五个地方；加个 Provider 要动 AI 页面；本地模型和云 API 走两套逻辑。

TECH-03-A 建一层**模型管理基座**，把这五个来源统一到一个读写口后面，为后续「AI 模型管理页 / AI 助手 / Workspace Agent」准备唯一数据源。

## 二、执行原则（本轮的硬边界）

**原则一 · 只做设计，不碰 UI：**
✅ 数据结构、API Contract、Provider 管理逻辑、模型状态管理、文档、测试接口
❌ 新建模型管理页、改 AI 页布局、改聊天交互、新建视觉组件

**原则二 · 稳定性优先：**
✅ 新接口**包裹**旧逻辑（`reuse-existing-over-add`）
❌ 破坏现有 AI 助手、改现有 Provider 调用流程、替换现有模型来源、迁移数据库

落到文件上的三条：**零新增 core 命令、零新增 config 键、零数据库迁移**。

## 三、分层结构

```
┌──────────────────────────────────────────────────────────────┐
│  UI（未来）：AI 模型管理页 / AI 助手 / Workspace Agent            │
│      ↓ 只调 models.list() / setDefault() / check() / remove()  │
├──────────────────────────────────────────────────────────────┤
│  registry.ts   ModelRegistry + createModelsApi()  ← 唯一门面    │
│                （canonical 读写、CRUD、默认模型、连通性检查）      │
├──────────────────────────────────────────────────────────────┤
│  provider.ts   ProviderRegistry + 三类适配器                     │
│                （registerProvider / getModels / testConnection） │
├──────────────────────────────────────────────────────────────┤
│  model.ts      ModelProfile 领域模型 + 校验 + 密钥检测           │
│                （**零外部依赖** —— Node 可直接编译执行）           │
├──────────────────────────────────────────────────────────────┤
│  ports.ts      端口的生产实现（**唯一 import @/api 的文件**）      │
│                ai_info / ai_list_models / ai_set_credential      │
│                get_config / put_config / localStorage            │
└──────────────────────────────────────────────────────────────┘
```

**为什么把 IO 单拎到 `ports.ts`：** `model.ts` / `provider.ts` / `registry.ts` 三个文件**不 import Vue、不 import `@/`**，
所以它们能被项目自带的 `typescript` 直接编译成 CommonJS 并在 Node 里跑 —— 这正是验收脚本 T1~T5 的执行方式
（TECH-01/02 验 UI 用 Edge headless；本层是纯领域层，无需浏览器）。

| 文件 | 行数 | 职责 | 外部依赖 |
|------|------|------|----------|
| `model.ts` | 589 | `ModelProfile` 结构、`validateModelProfile`、密钥检测、`maskOf` | 无 |
| `provider.ts` | 472 | `ProviderRegistry`、三类适配器、连接类型推断、错误码表 | 无 |
| `registry.ts` | 823 | `ModelRegistry`、canonical 五层读写、CRUD、`ModelsApi` 门面 | 无（仅端口接口） |
| `ports.ts` | 437 | 端口的 core / localStorage 实现 | `@/api/client`、`@/utils/logger` |

## 四、TASK-01 · Model Domain（`model.ts`）

```ts
ModelProfile = {
  id: string                     // 不透明键，`deriveModelId(provider, model)` 确定性推导
  provider: string               // 必须是 L0 已注册的 Provider
  name: string                   // 展示名（默认 = model）
  model: string                  // 模型标识（如 'deepseek-chat' / 'qwen2.5:7b'）
  connection: {                  // 三种连接类型统一到一个结构
    type: 'api' | 'local' | 'agent'
    endpoint?: string            // api/local 的服务地址
    authRef?: string             // 只放 Secret Reference：pw/<provider>/<slot>
    localPath?: string           // 本地权重路径
    healthPath?: string          // 自定义健康检查路径
  }
  capabilities: { chat, vision, coding, agent: boolean }
  status: { enabled, available: boolean; lastCheck?: number }
  metadata: { createdAt, updatedAt, extras? }
}
```

四条设计决定：

1. **字段可扩展** —— `metadata.extras` 是唯一的任意字段挂载点，新增厂商特性不动主干结构。
2. **厂商无关** —— 不绑定 OpenAI 格式；`connection` 用 `type` 分流，而不是给每家一个字段。
3. **id 保留冒号** —— `deriveModelId` 只压 `[a-z0-9._:-]` 之外的字符。**刻意保留 `:`**，因为本地模型 tag 大量用冒号
   （Ollama 的 `qwen2.5:7b`）；压掉会让 id 和真实模型名对不上（`ollama:qwen2.5-7b`）。
   id 是不透明键，解析按**第一个** `:` 切分即可。
4. **`validateModelProfile` 分四段** —— 结构 → 连接（按 `type` 各自必填 + endpoint 协议）→ 引用（`authRef` 必须是引用形态）→ 安全（递归扫密钥）。
   **失败即整单拒绝**，不产生"半套状态"。

`add()` **自动补缺省**，让 UI 可以"无脑调用"：

| 字段 | 缺省来源 |
|------|----------|
| `connection.type` | Provider 描述符的 `connectionType`（显式传入可覆盖） |
| `connection.endpoint` | Provider 的 `defaultEndpoint` |
| `connection.authRef` | `secret.refFor(provider)` → `pw/<provider>/default`（**只写引用**） |
| `capabilities` | L0 声明的能力键（显式声明优先） |

于是 UI 只需 `models.add({ provider: 'deepseek', model: 'deepseek-chat' })`。

## 五、TASK-02 · ProviderRegistry（`provider.ts`）

```ts
registerProvider(input)   // 幂等 upsert；返回规格化后的 ProviderDescriptor
removeProvider(id)        // 命中 true / 未命中 false
listProviders()           // 全部描述符
getModels(id, io)         // 拉模型列表（远端 + 声明的默认模型合并去重）
testConnection(id, io, {hasSecret})  // 统一连通性检查
```

**三类连接统一抽象**（`ConnectionType`），用适配器分流，而不是在三处写 if：

| 类型 | 适配器 | 关键行为 |
|------|--------|----------|
| `api` | `CloudApiAdapter` | 缺 key → **本地短路**返回 `no_api_key`（`probed=false`，不发请求） |
| `local` | `LocalRuntimeAdapter` | 不可达（ECONNREFUSED）→ 归一到 `local_model_down` |
| `agent` | `AgentAdapter` | 返回 `not_implemented`（握手协议未定稿，见 §八） |

`inferConnectionType` 的判据顺序：**显式声明 → 已知本地 id 表 → 无 key 且指向回环 → id 含 agent → 兜底 `api`**。

**错误码表**与 Python 侧 `ai/providers/base.py` 对齐，UI 拿到的永远是这十个中的一个：

```
ok · no_api_key · unreachable · local_model_down · timeout
rate_limit · auth_failed · bad_response · not_implemented · unknown
```

`classifyProbeError(raw)` 把任意错误文本归一到这里 —— UI 不做字符串匹配。

## 六、TASK-03 · Canonical Source（核心）

### 6.1 五层读写（对齐 PW-INTEGRATION-003 §3.2）

```
L0 能力真相    Python ai/providers/registry.py PROVIDERS   ← 谁是 Provider、能不能用（只读）
L1 canonical   ai.provider.current / ai.model.current      ← 权威"当前用哪个"（**本轮尚未登记**）
L2 缓存        localStorage ui.ai.provider / ui.ai.model   ← 启动兜底
L3 建议        work_modes.ai_profile.provider              ← 非权威
L4 无头默认    ai.default_provider                         ← pluginHost 消费
L5 传输        AiChatArgs.provider / model                 ← 单次覆盖
```

**读序**：L1 → 过渡镜像键 → L2 缓存，**如实回报 `source`（core / mirror / cache）+ `stale` + `pendingSync`**，绝不谎报"已落库"。

**写序**：L1 →（落不住则）core 过渡镜像键 → L2 缓存。

### 6.2 本轮的关键妥协：过渡镜像键

L1 的两个键 `ai.provider.current` / `ai.model.current` **尚未在 `core/src/db/config.rs` 的 KEYS 登记**，
`put_config` 对未登记键会 bail。为守住"零 core 改动面"，本层写入时：

1. 先试 L1（core 登记后自动生效，**本文件无需改动**）；
2. L1 落不住 → 落**已登记**的过渡镜像键 `ui.ai.provider` / `ui.ai.model`（`config.rs:96-97`），
   也正是 `stores/ai.ts` 在写的两个键 —— 于是新层与旧链路**天然共用同一份持久化**；
3. 都不行 → 落 L2 缓存，`stale=true`。

> 结果：**没有新增任何 config 键，没有数据库改动**，而 canonical 语义（含 `pendingSync`）已经就位。
> core 登记 L1 后，本层零改动自动切到 L1。

### 6.3 默认模型不是 `ModelProfile` 的字段

这是与 TASK-01 字面描述的一处刻意偏离：**默认模型由 canonical 推导，不作为 `profile.default` 字段存**。

- 若把 default 存成 profile 字段，就得再同步回 canonical（多一处可漂移的状态）；
- 现在 `getDefault()` = 读 canonical → 在当前 store 里 `findByCanonical()` → 返回 `{canonical, profile, dangling, unset}`；
- 删掉默认模型时，canonical **不动**（不顺手清掉用户在 AI 助手里的选择），进入 `dangling=true` 状态如实上报；
  同 id 的模型再 `add()` 回来，自动认出，`dangling` 消失。
- `explicitDefaultId` 仅是本会话内的显式覆盖，不持久化。

### 6.4 旧来源的去留

| 来源 | 处置 | 理由 |
|------|------|------|
| S1 localStorage | **保留为 L2 缓存** | 键与 `stores/ai.ts` 完全一致 → 新旧共用 |
| S2 core 镜像键 | **保留，升级为过渡 canonical 落点** | 已登记、旧链路在写 → 零改动的持久化通道 |
| S3 `aiProfile` | **降为建议**（不改代码，仅定位） | 非权威 |
| S4 `ai.default_provider` | **保留为无头默认**（不动） | pluginHost/agents 在用 |
| S5 请求级 | **保留为单次覆盖**（不动） | 传输层语义 |

**本轮不删任何旧来源、不改任何旧读写** —— 只在旧来源之上叠一层门面。真正下线旧来源是后续阶段的事。

## 七、TASK-04 · UI Access Contract

UI 只依赖一个窄接口，不接触 Registry 内部：

```ts
const models = createModelsApi(registry)

models.list()                 // → [{ id, name, provider, model, connectionType, status, capabilities, isDefault, hasSecret, enabled }]
models.get(id)                // → ModelProfile | null（副本，改它不影响注册表）
models.add({ provider, model })      // → ModelProfile（自动补 endpoint/authRef/能力）
models.update(id, patch)      // → ModelProfile（保留 createdAt）
models.remove(id)             // → boolean（**不动 canonical、不动凭据**）
await models.setDefault(id)   // → DefaultModelView（写 canonical）
models.getDefault()           // → { canonical, profile, dangling, unset }
await models.check(id)        // → ConnectionTestResult（唯一会发起真实探测的方法）
```

对应测试要求：T1 创建模型 · T2 切换默认 · T3 删除 · T4 Provider 多类型 · T5 非法配置拒绝 · T6 旧功能无影响 —— 全部通过。

> 门面刻意做窄：UI 拿不到 `store` / `canonical` 写口 / `ports`，扩展只能通过显式新增方法。

## 八、TASK-05 · 本地模型与 Agent 预研（设计态）

**统一发现路径**：本地运行时（Ollama / LM Studio）与云 API **共用同一套 `ModelProfile`**，
只以 `connection.type` 区分（`local` vs `api`）。`inferConnectionType` 覆盖已知本地 id 表 + 回环地址判定。

**连接信息保存**：
- 本地服务地址 → `connection.endpoint`（如 `http://localhost:11434`）；
- 本地权重文件 → `connection.localPath`（`local` 类型允许"只有 endpoint"或"只有 localPath"）；
- 本地 Provider **不写 `authRef`**（`needsKey=false` 时 `add()` 不补引用）。

**普通模型 vs Agent 的界线**：同为 `ModelProfile`，靠 `connection.type='agent'` 分流。
Agent 不是"另一种模型"，是**另一种接入协议** —— 所以 `AgentAdapter` 现在**明确返回 `not_implemented`**，
消息里写明"握手 / 鉴权 / 流式分帧尚未定稿"，而不是假装能连通。

> 本轮**不实现**自动下载、不做 Agent 工作流（§十一停止条件）。

## 九、TASK-06 · 安全设计（凭据红线）

**硬约束**：API Key 绝不以明文进入 UI state、绝不写入任何普通配置文件。

```
ModelProfile.connection.authRef = 'pw/deepseek/default'   ← 只存"引用"
        ↓
SecretPort.set(provider, secret)  →  ai_set_credential（进系统凭据库：Windows Credential Manager）
        ↑ 返回值只有掩码：{ provider, ref, mask: 'sk-****uvwx', backend }
```

四道防线，全部有验收用例：

1. **引用形态契约** —— `AUTH_REF_PATTERN = /^pw\/[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+$/`，`authRef` 不合形态即拒。
2. **字段名黑名单** —— `apikey / token / secret / password / privatekey / credential …`（归一化比较，含 `_`/`-`/`.` 变体），出现即拒。
3. **值形态启发式** —— `sk-` / `sk-ant-` / `AIza` / `ghp_` / `xoxb-` / `Bearer` / 32+ 位 hex / 40+ 位随机串，命中即拒；**宁可误报**（代价是一条 issue，漏报代价是泄密）。
4. **掩码只在纯层生成** —— `maskOf(secret)` 规则 `sk-****abcd`，与 Python `CredentialStore.mask` 同规则，保证两侧显示一致。
   `setCredential` 返回值不含明文，`exportProfiles()` 也不含明文。

## 十、验收结果（`tools/verify_model_registry.py`）

**31/31 PASS**。执行分两段：

- **Node 段（T0~T5）**：tsc 把领域层编成 CommonJS → 在 Node 里用内存端口跑完整业务链路；
- **静态段（T6）**：证明"零改动面"与"旧链路无影响"。

| 组 | 用例 | 要点 |
|----|------|------|
| T0 | 领域层编译 | `model.js / provider.js / registry.js` 产出成功（后续全依赖它） |
| T1a-e | 创建模型 | 云 API 自动补 endpoint/authRef；本地无 authRef；自定义 endpoint；重复 id / 未注册 / 未开放一律拒；取回是副本 |
| T2a-e | 切换默认 | 写 canonical 且列表标记随之切；**跨实例存活**（真持久化）；canonical 契约拒绝；**降级①** L1 落不住 → `source=mirror/pendingSync=true`；**降级②** core 不可达 → `source=cache/stale=true` |
| T3a-c | 删除模型 | 命中 true / 未命中 false；**删默认项不动 canonical（dangling）也不动凭据**；再 add 回来自动认领 |
| T4a-f | Provider 多类型 | 连接类型推断 6 例；三类适配器分派；幂等重登记 + remove 语义；`getModels` 默认模型置顶去重；缺 key **本地短路 `probed=false`**；本地不可达 → `local_model_down`，Agent → `not_implemented` |
| T5a-e | 非法配置拒绝 | 11 类逐一拒绝（4 类明文密钥 + 5 类结构 + 2 类类型）；**拒绝是原子的**（store 无残留）；**对照组**同结构换引用/普通备注/apiBase 必须通过；检测器 9 项单测；写凭据只回掩码 |
| T6a | 零耦合 | 领域层不 import Vue、不 import `@/` |
| T6b | 零接线 | 无任何既有文件 import 新层（纯新增，未接线） |
| T6c | 旧链路符号完好 | `ai_info` / `ai_chat` / args 三键 / persist 三键 / 三处页面绑定均在 |
| T6d | 零 core 改动面 | L1 键仍未登记（走镜像兜底）+ 端口只用既有命令（`ai_info/ai_list_models/ai_set_credential/ai_delete_credential/get_config/put_config`），无不存在命令 |
| T6e | Python 侧原样 | 7 Provider / 2 未开放 / `available()` 字段 / 掩码规则不变 |
| T6f | 整仓构建 | `vue-tsc --noEmit && vite build` exit=0 |

**验收诚实性说明**：T6b 只能证明"没有既有文件 import 新层"，**不能**代替 `verify_stage5` 等既有端到端脚本；
它们在本轮**未被改动**，但也没有被本脚本重跑 —— "旧 AI 功能无影响"的强证据是 T6c/T6e/T6f + 既有脚本的持续通过。

## 十一、文件变更

| 文件 | 类型 | 说明 |
|------|------|------|
| `ui/src/ai/model/model.ts` | 新增 | 领域模型 + 校验 + 密钥检测 |
| `ui/src/ai/model/provider.ts` | 新增 | Provider 注册表 + 三类适配器 |
| `ui/src/ai/model/registry.ts` | 新增 | ModelRegistry + canonical + `ModelsApi` |
| `ui/src/ai/model/ports.ts` | 新增 | 端口的生产实现（唯一 import `@/api`） |
| `tools/verify_model_registry.py` | 新增 | 验收脚本（31 项） |
| `docs/tech/model-management-runtime.md` | 新增 | 本文 |

**零修改**：core（Rust）、Python（`ai/`）、既有 UI（`stores/ai.ts`、`AiSidebar.vue`、`SettingsView.vue`、`LearningView.vue` 等）。

## 十二、当前限制与下一阶段建议

### 限制（本轮**明确不做**，见 §十一停止条件）

1. **未接线** —— 新层尚无任何调用方，UI 未改（这是设计，不是缺陷）。
2. **L1 未登记** —— canonical 走过渡镜像键；core 登记 `ai.provider.current` / `ai.model.current` 后自动生效，本层零改动。
3. **模型列表未持久化** —— `ModelRegistry.store` 是内存态；跨会话的模型清单需要显式 `exportProfiles()/importProfiles()`（已提供，无密钥）。
4. **Agent 接入未实现** —— `AgentAdapter` 明确 `not_implemented`。
5. **无 UI 页面、无模型市场、无自动下载、无插件商店**。

### 下一阶段建议（按依赖排序）

1. **core 登记 L1 两键** —— 一次性小改动，让 canonical 落到权威层，去掉"过渡"语义。
2. **模型清单持久化** —— 决定放 DB 表还是 config；`exportProfiles/importProfiles` 已备好序列化口径。
3. **接第一个真实消费者** —— 建议从"AI 模型管理页（只读列表）"起步，`models.list()` 已满足；
   或让 `stores/ai.ts` 改为从本层读，验证"新旧共存"。
4. **本地模型端到端** —— 用真实 Ollama 跑一次 `check()`，把 `local_model_down` / 模型发现链路跑通。
5. **Agent 协议定稿后** —— 实现 `AgentAdapter` 握手，届时 `connection.type='agent'` 已有完整落点。

> 停止条件提醒：模型市场、自动下载、Agent 工作流、插件商店均属后续阶段，本轮不启动。
