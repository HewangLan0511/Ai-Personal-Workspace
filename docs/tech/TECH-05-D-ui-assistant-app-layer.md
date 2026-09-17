# TECH-05-D · AI 助手应用层落地（P1-A）

> 日期：2026-09-16 · 性质：**实现**（Agent 模式）
> 上游：`docs/tech/TECH-05-C-ui-landing-p0.md`（三个 P0）→ 本文（P1-A：把 AI 助手页从「UI 占位」提升为「真实应用态」）
> 本轮范围：**只做 P1-A**。真实 LLM API / API Key / 本地推理 / Agent 执行 / 工作空间数据访问 / 窗口操作 / 快照恢复 / 学习 P1 / 生活插件 P1 / Skin 商城 / View Transitions / UI 视觉优化 **一律未开工**（§八 逐条登记）。
> 证据口径：所有结论标注 `文件:行号` 或**验收项编号**，均来自本轮实测；**不引用未跑过的结论**。

---

## 零、五条结论先行

1. **AI 助手页从 366 字节的占位骨架，变成了一个真实的「会话状态壳」**
   （`ui/src/views/AiView.vue`：366 B → 642 行）。它不是"长得像聊天"，
   而是**有状态来源**：会话 id / 五态归约 / 消息列表 / 空态 / 生成中 / 失败
   全部来自应用层纯函数，页面只做绑定。
2. **"页面看到的模型 == 请求用的模型" 是机器证明的，不是靠约定。**
   本轮新增 `__pwAssistant.registry`，验收项 `R2`/`R8` 用 **`===` 对象同一性**直接证明
   `__pwAssistant.registry === __pwAiModel.registry === __pwModels.registry` ——
   该断言与数据无关，**空环境里也不空转**（`R3` 三项皆空串，如实标注"空转"并由 `R2` 兜底）。
3. **`ModelRegistry` 仍是唯一的模型事实来源，且本轮**没有**新增第二个当前模型状态。**
   AI store 里**没有** `currentModel` 字段（`T2a`）；`send()` 不再读 `this.providerId/model`
   （`T2b`），目标一律由应用层从 canonical 解析；对照组 `T2c` 证明"用户改选择时**仍然**写 canonical"，
   即 `T2b` 不是"哪里都没有模型"的假阳性。
4. **"咨询模式不授权"是结构保证，不是文案承诺。**
   同一条判据落在三处、彼此独立：TS `effectiveScopes()`（`T5b`/`⑦`）、
   请求装配 `buildChatArgs()`（`T4c`/`⑧`）、Python `ai/context.py::assemble()`（`T5b`）。
   验收用**双向对照**：`R5` 证明 consult → `[]`，`R6` 证明切到 workspace 后授权**确实变化**
   （`[] → 5 项`），排除"永远返回空"的假实现。
5. **本轮修好了 1 个真实的越权口子（自证）。**
   `resolveForUi()` 原先把 `explicit` 只从**类型**上删掉 —— TS 类型运行期被擦除，
   JS 调用方硬塞 `explicit` 仍能被 `resolveTarget` 读到。现改为**命名解构丢弃该键**（`request.ts:239`），
   并用独立 Node 探针证明：UI 路径传 `explicit` → `source='none'`；通用路径传 `explicit` → `source='request-explicit'`
   （即 explicit 通道没被整体删掉，只是 UI 路径拿不到）。

---

## 一、改动清单（交付）

### 新增（6 个文件）

| 文件 | 行数 | 说明 |
|------|-----:|------|
| `ui/src/ai/assistant/session.ts` | 275 | **会话状态纯函数**：`SESSION_STATUSES`(5) / `sessionStatusOf` / `createSession` / `applyChunk` / `settleReply` / `failReply` / `canSend`。零 IO、零框架 |
| `ui/src/ai/assistant/request.ts` | 317 | **解析顺序 + 权限边界纯函数**：`RESOLUTION_ORDER`（逐字对齐冻结契约）/ `resolveTarget` / `resolveForUi` / `effectiveScopes` / `grantedScopes` / `buildChatArgs`。零 IO |
| `ui/src/ai/assistant/transport.ts` | 244 | **全应用唯一的 AI 传输入口**：`ai_chat` / `ai_cancel` / `ai_preview_context` 只在这里出现 |
| `ui/src/ai/assistant/service.ts` | 229 | 无状态应用服务：`resolve` / `prepare` / `chat` / `cancel` / `previewContext` |
| `ui/src/ai/assistant/bridge.ts` | 126 | 组合根：`getSharedAssistant()`，取**共享** `getSharedRegistry()` 实例 |
| `tools/verify_tech05d.py` | 1250 | 本轮验收脚本（**46 静态 + 35 Node 纯函数 + 8 动态 = 89 项**） |

### 修改（4 个文件）

| 文件 | 改动 |
|------|------|
| `ui/src/views/AiView.vue` | 366 B 占位骨架 → 642 行真实会话状态壳（**唯一被重写的页面**） |
| `ui/src/stores/ai.ts` | 从"自己实现 AI 逻辑"改为**应用层的消费者**（624 行）：`send()` 走 `assistant.prepare()` → `assistant.chat()`；新增 `sessions/sessionId/lastRequest/connectionError/canonicalSource` |
| `tools/verify_tech04.py` | 锚点迁移：`ai_chat` 断言从 `stores/ai.ts` 迁到 `ai/assistant/transport.ts`，并**反向**断言 store / Vue 页面里**没有**它 |
| `tools/verify_model_registry.py` | `T6b` 接线白名单增列 `ai/assistant/{service,bridge}.ts`；`T6c` 锚点同上迁移 + 反向断言 |

### 未改动（有意）

UI 视觉、`tokens.css` / `motion-tokens.css`、共享原语 `components/ui/*`、Toast 体系、
`AiSidebar.vue`、`ModelsView.vue` / `ProfileView.vue` / `WorkspaceStatus.vue`、路由表、`core/*`、`ai/*.py`。
—— 由 `T9a~T9f`（无第二套 Token/Motion/组件/Toast）、`T10b`（零新增页面/路由）、`T10a`（P0 锚点在位）机器守护。

---

## 二、现在的真实数据流（本报告要求项 ②）

```
┌─ AiView.vue（AI 助手页，UI） ────────────────────────────────────────┐
│  useCurrentModel()  ← 只读投影（模型域 consumer.resolveCurrentModel）  │
│  useAiStore()       ← stores/ai.ts（应用层的消费者）                   │
└───────────────┬─────────────────────────────────────────────────────┘
                │  send(text)
                ▼
        stores/ai.ts · send()                              (ai.ts:535)
          ① ensureSession()  → 无会话则新建（应用层 createSession）
          ② assistant.prepare({ mode, scopePrefs, messages })
                ▼
        ai/assistant/bridge.ts · getSharedAssistant()       (bridge.ts:101)
           ├─ registry = getSharedRegistry()   ← 模型域同一个单例（唯一事实来源）
           ├─ transport = coreAiTransport()    ← ai/assistant/transport.ts
           └─ sources: suggestion ← config `ai.active_profile`
                       headlessDefault ← config `ai.default_provider`
                ▼
        ai/assistant/service.ts · prepare()                  (service.ts)
           ├─ resolveForUi({ canonical, suggestion, headlessDefault, firstEnabled })
           │     ← 契约顺序 request-explicit > canonical > … 的 **UI 子集**（无 explicit）
           ├─ effectiveScopes(mode, prefs)  → consult 恒为全 false（边界）
           └─ buildChatArgs(...)            → ChatArgs（键名对齐 core 契约）
                ▼
        ai/assistant/transport.ts · chat(args)               (transport.ts)
           └─ invokeCore('ai_chat', { …args })   ← 全应用**唯一**出现该命令的位置
                ▼
        core（Rust）ai_chat 命令 → Python sidecar `ai/context.py::assemble()`
                （再守一遍咨询边界：非 workspace → 空上下文）
```

**流式回程**：`transport.ts` 订阅事件 → `assistant.onChunk/onDone` →
`stores/ai.ts` 调 `applyChunk` / `settleReply` / `failReply`（应用层纯函数）落进消息条。

**页面零传输**：`T7a` 断言 `AiView.vue` 里没有 `fetch(` / `invokeCore` / `@tauri-apps/api/core` / 三个请求命令名；
`T7b` 断言这三个命令名**都在** `transport.ts`；`T7c` **反向**断言 store 里没有它们。

---

## 三、ModelRegistry 是否仍是唯一模型事实来源（要求项 ③）

**是。** 三层证据：

1. **静态**：`T2a` AI store 无 `currentModel` 字段 —— 当前模型只在 canonical。
   `T1b` 应用层组合根**取共享实例**（`getSharedRegistry()`），**不 new Registry**（后者会让页面与请求分叉）。
   `T8c` canonical 正式键名 `ai.provider.current` 在**剥离注释**后**只**出现在 `ai/model/ports.ts`
   （模型域 IO 适配器）—— 应用层不自己拼 config 键；`T8d` 断言应用层零 `put_config` / `configApi.put`。
2. **对象同一性（动态，最终产物）**：
   - `R2`：`window.__pwAssistant.registry === window.__pwAiModel.registry` → `True`
   - `R8`：`__pwAssistant.registry === __pwAiModel.registry === __pwModels.registry` → `True`
     （SPA 从 `/ai` 跳 `/models` 后在**同一 JS 上下文**比对，`refAlive=True`）
3. **显示 == 取数**：`R3` 页面当前模型 key == `registry.getDefault()` == `__pwAssistant.current()`；
   `R4` 页面 label == AI 侧栏 label（同一个投影函数）。
   ⚠ 本环境无 canonical，`R3` 三项皆空串 —— 脚本**如实标注"空转"**并由 `R2` 兜底，不假装它是有效断言。

---

## 四、consult / workspace 权限边界（要求项 ④）

| | 咨询（consult，默认） | 工作台助手（workspace） |
|---|---|---|
| 授权范围 | **恒为 `[]`**（即便用户意愿全开） | 按用户开关，5 项（mode/apps/project/learning/profile） |
| 提示文案 | `未授权任何用户数据`（恒） | `已授权：…`（随开关变化） |
| 数据读取 | **不去读**（`previewContext` 在非 workspace 时**短路返回**，`T4b`） | 结构上具备读取入口（**本轮不真读**，`T4d` 断言应用层/页面零 `workspaceRuntime/profileApi/lifeService`） |
| 页面结构 | 独立 tab + 「不会读取你的项目、文件或个人信息」明示（`T5e`） | 独立 tab + **仅此模式出现**的「管理权限」面板（`T5d`） |

**边界落在三处、彼此独立**（纵深防御，同一判据）：
`ui/src/ai/assistant/request.ts::effectiveScopes()`（`mode !== 'workspace' → 全 false`）
→ `buildChatArgs()` 强制经该出口（`T4c`）
→ `ai/context.py::assemble()` 第一行 `if mode != MODE_WORKSPACE: return []`（`T5b`）。

**双向对照**（排除"永远为空"的假实现）：`R5` consult → `granted === []` 且 DOM 计数 `0`、文案一致；
`R6` 切到 workspace → `granted` 变 5 项、文案换掉、DOM 计数 `5` 同步；
`⑦c` 另证 workspace 下"归零"不适用。

**模式名不另叫**：TS 侧字面量出处唯一（`session.ts:32` 的 `AiMode = 'consult' | 'workspace'`），
与 Python `MODE_CONSULT` / `MODE_WORKSPACE` 逐字一致（`T5a`）；两侧来源清单也一致（`T5c`）。

---

## 五、会话状态：哪些是真实 Runtime，哪些是应用层（要求项 ⑤）

| 会话壳要素 | 归属 | 证据 |
|---|---|---|
| 五态枚举 `unset/empty/idle/loading/error` + 归约 `sessionStatusOf` | **应用层纯函数**（唯一出处） | `T6a`；`①` 穷举 **16/16** 组合一致 |
| 当前会话 id / 新建 / 切换 / 清空 | 应用层（`session.ts`）+ store 暴露 | `T6d`；`R7` 新建会话真实生效（id 变化/列表+1/唯一激活/仍为空会话） |
| 消息列表来源 / 流式增量 / 兜底填充 / 错误挂载 | 应用层纯函数 | `T6d`；`②`(4) `③`(3) `④`(4) `⑤`(2) 共 13 项穷举 |
| 空态 / 生成中 / 失败 的**可观测落点** | 页面绑定（`data-pw-assistant-*`） | `T6c`；`R1` 实测 `hasEmpty: true` |
| **会话持久化（DB）** | **真实 Runtime 侧：不存在** | `T6e`：`core` 零消费 `ai_conversations`、UI 零引用（**剥注释**后核对） |
| 连接错误 vs 会话错误 | **分开归因** | `T6f`：`connectionError`（环境）≠ `lastError`（会话）；错误文案唯一定义在 `transport.ts::humanizeAiError` |
| 模型解析目标 | **来自真实 Runtime（canonical）** | `T2b` + `R3` |

**诚实声明**：本轮**没有**落库。SQL 表 `ai_conversations` 存在但**零读写实现** ——
所以会话是**内存态**。`T6e` 是"如实声明未接线"的机器守护：一旦谁偷偷接了线，这条会红。

---

## 六、新增验收脚本结果（要求项 ⑥）

`tools/verify_tech05d.py` · **89/89 PASS，FAIL=0**

| 组 | 项数 | 对应你的验收要求 |
|---|---:|---|
| `T1a~T1d` | 4 | ① 从共享 ModelRegistry 读当前模型 |
| `T2a~T2c` | 3 | ② 无第二个 currentModel 业务状态（含**对照组** T2c） |
| `T3a~T3d` | 4 | ③ 页面与侧栏同源模型状态 |
| `T4a~T4d` | 4 | ④ 咨询模式默认不读工作空间 |
| `T5a~T5e` | 5 | ⑤ consult/workspace 状态边界清晰 |
| `T6a~T6f` | 6 | ⑥ 会话状态有明确 idle/loading/error/empty 来源 |
| `T7a~T7e` | 5 | ⑦ Vue 页面不承担 Provider/API Transport 逻辑 |
| `T8a~T8d` | 4 | ⑧ 无新增 localStorage AI 业务真值 |
| `T9a~T9f` | 6 | ⑨ 无第二套 Token/Motion/Component 体系 |
| `T10a~T10c` | 3 | ⑩ Models/Profile/Workspace P0 无回归 |
| `①~⑧f`（Node 直驱纯函数） | 35 | 会话归约 16 组合 / 解析顺序 5 层 / 权限边界 / 请求装配 |
| `R1~R8`（最终产物 CDP） | 8 | 真实渲染 + 对象同一性 + 双向对照 + 会话壳 + 三方同一 |

**关键动态项实测值**：
- `R2` `__pwAssistant.registry === __pwAiModel.registry` → `True`
- `R5` consult：`granted=[]`、`domGranted="0"`、文案 `未授权任何用户数据`（函数与 DOM 一致）
- `R6` 反向对照：`[] → ["mode","apps","project","learning","profile"]`，文案同步换掉
- `R7` 新建会话：`smu3fflmh-1 → smu3ffltv-2`、`listCount 2`、`activeCount 1`、`status empty`
- `R8` 三方同一：`modelsEqAiModel / modelsEqAssistantRef / aiModelEqAssistantRef` **全 True**

### 6.1 本轮修掉的 1 个真实缺陷（不是验收脚本放宽）

`resolveForUi()` 的 `explicit` 只从**类型**上排除；TS 类型运行期被擦除，JS 调用方（或 `any` 转型）
硬塞 `explicit` 仍会被 `resolveTarget` 读到 —— 即"UI 路径绕过 canonical"仍可行。

修复（`ui/src/ai/assistant/request.ts:239`）：命名解构丢弃该键后再下传。
独立 Node 探针（编译 `request.ts` 后直驱）实测：

```json
{"onlyExplicit_source":"none",        // UI 路径：只给 explicit → 拿不到（none）
 "both_source":"canonical",           // UI 路径：canonical + explicit → 命中 canonical
 "generic_source":"request-explicit", // 通用路径：explicit 仍首位生效（通道没被删）
 "PASS": true}
```

### 6.2 验收脚本的判据修正（本轮调整，逐条登记 —— 不是静默放宽）

| 项 | 原判据问题 | 修正 |
|---|---|---|
| `T3d` | `label\s*[:=]\s*['\"]…` 误伤 `:data-current-label="modelView.label"`（绑定投影结果反被判为"自己拼文案"） | 排除前缀 `-`；仅"引号内不含 `.(){}$` 的字面量"算硬编码；**加反向对照**（同一判据必须能抓到 `label: 'DeepSeek-V3'`） |
| `T5a` | 在 `request.ts` 找 `'consult'` —— 该文件只在**注释**里提模式名 | 改为在读**剥注释**后的 `session.ts` 找 `AiMode = 'consult' \| 'workspace'`（真正的字面量出处） |
| `T5d` | 要求页面字面量含 `未授权任何用户数据` —— 页面是**绑 `ai.permissionText`** | 改为断言页面绑定应用层文案（`data-pw-assistant-permission` + `ai.permissionText`） |
| `T6e` | 裸文本扫描把 `session.ts` 里"**不碰** `ai_conversations`"的说明注释当违规 | 改为**剥注释**后扫描（core 与 ui 两侧） |
| `T8b` | 把模型域既有镜像键 `ports.ts` 误判为"越界新增" | 模型域 `ai/model/` 单列，并**冻结**其键集合基线（`{provider, model, apiBase}`）；其余文件仍须为零 |
| `T8c` | 裸文本把模型域多处**文档注释**当"应用层拼键" | 改为剥注释后核对，并单独断言"应用层 `ai/assistant/` 零越界" |
| `T10a` | 要求 `WorkspaceStatus.vue` 出现 `executable` —— 该词只在注释里 | 改为**代码**锚点：`@/workspace/runtime` + `workspaceRuntime.snapshot.status()` + `workspaceRuntime.prepareWorkspace` + 不 import `workspace/store` |
| `T10c` | 文件头注释**有意**记录"曾经是占位骨架"，被当成残留 | 改为剥注释后扫描 |
| `R8` | 点 `.app-nav a[href="/models"]` —— `/models` **不在主导航**（P0-1 设计如此） | 改点 AI 助手页头部的"当前模型" `RouterLink`（`[data-pw-assistant-current]` → `/models?from=ai`），同为 SPA 跳转 |
| `T4d`/`T6c`（`verify_tech04.py` / `verify_model_registry.py`） | `ai_chat` 迁走后旧锚点失配 | 迁移到新家 `ai/assistant/transport.ts` + 加**反向**断言（store/页面不得含该命令） |

---

## 七、全量回归结果（要求项 ⑦）

| 套件 | 结果 |
|---|---|
| `vue-tsc --noEmit` | **0 错误**（无输出） |
| `vite build` | exit 0（dist 已重建，验收跑在**最终产物**上） |
| `verify_tech01.py` | 9/9 |
| `verify_tech02_workspace.py` | 11/11 |
| `verify_tech03b.py` | 81/81 |
| `verify_tech04.py` | 44/44 |
| `verify_tech05c.py` | 34/34 |
| **`verify_tech05d.py`** | **89/89** |
| `verify_model_registry.py` | 32/32 |
| `verify_contracts.py` | 6/6 符合预期 |
| `verify_skin_engine.py` | 12/12 |
| `verify_sidecar_bundle.py` | 8/8 |
| `perf_tech01_22.py` | exit 0；**12 场景** longtask **全 0**（见 `tools/perf22-results.json`） |
| `test_ai.py` | PASS=28 FAIL=0 |
| `verify_stage1..9.py`（Stage E2E） | 全部 exit 0；`stage5_stream` PASS=18 FAIL=0 |
| `tools/gate.py --stage all` | verdict **PASS**，**FAIL=0**，WARN=74 |

### 7.1 历史 WARN 与本轮新问题（明确区分）

- **唯一一次红**：`verify_stage3.py` 项 5「激活（成为前台窗口）」在**后台串行批次**里失败
  —— 该组跑在无交互焦点的后台链路中，Windows 抢焦点被系统拦下。
  **前台单独重跑 → 9/9 全通过**（`foreground=True`）。判定：**环境性抖动，非本轮回归**
  （本轮未触碰任何窗口管理代码；`core/*` 零改动）。
- **74 个 WARN 全部是 `Q001`（脚本里残留 `print`）**，且**集中在 `personal-workspace-ui/`**
  —— 原型期 QA 脚本（16 个文件），**历史既有，本轮未触碰**。
  本轮自己的临时文件已清理（清理前它们额外贡献 2 个 `A020` FAIL + 9 个 `Q001` WARN；
  清掉后 FAIL 归零）。
- **无本轮新引入的 WARN/FAIL。**

---

## 八、仍未完成的真实 AI 能力（要求项 ⑧，逐条）

| # | 未完成项 | 当前状态 |
|---|---|---|
| 1 | 真实 LLM API（OpenAI / Claude / Gemini） | **未接**。`transport.ts` 只调既有 core 命令 `ai_chat`，本轮**零新增后端能力**（`T7d` 断言用到的命令 ⊆ `commands.rs` 既有 fn，且恰为那 3 个） |
| 2 | API Key 管理 | **未做**（本轮未碰凭据链路） |
| 3 | 本地模型推理 | **未做** |
| 4 | Agent 执行 | **未做**。`T7e` 断言页面零 `agentHost/pluginHost/createAgent` 入口 |
| 5 | 工作空间数据访问（workspace 模式真读数据） | **未接**。`workspace` 模式本轮只建立**模式状态 + 权限边界**；`T4d` 断言应用层/页面零读取入口；`previewContext` 在 workspace 下才会问 core，且 core 侧未接真实数据 |
| 6 | 会话持久化（`ai_conversations` 落库） | **未接**。表在、零读写；`T6e` 守护"不许假装落库" |
| 7 | 窗口启动 / 移动 / 缩放 | **未做**（未触碰 `core/src/window_manager`） |
| 8 | 快照恢复 | **未做**（`WorkspaceStatus.vue` 仍如实显示"接口就绪 / 执行侧未放开"） |
| 9 | 学习 P1 / 生活插件 P1 / Skin 商城 / View Transitions / UI 视觉优化 | **未开工** |

> **另需说明**：`R1` 实测本环境**无核心服务**（页面如实显示"无法连接核心服务，AI 功能暂不可用"）——
> 这是环境状态，不是缺陷；`connectionError` 与会话错误**分开归因**（`T6f`），
> 因此"连不上 core"不会把新开的空会话误标成"上次请求失败"。

---

## 九、停止声明

TECH-05-D 的 **P1-A（AI 助手应用层落地）已完成并收口**：

- 改动面：**新增 6 个文件 + 修改 4 个文件**（§一），UI 视觉/Token/Motion/组件/Toast/**路由** 均零改动；
- 机器门禁：`verify_tech05d.py` **89/89**、全量回归 **FAIL=0**、`gate.py --stage all` **PASS**；
- 唯一一次红为**环境性前台焦点抖动**，前台复跑 9/9（§7.1）。

**按指令，到此立即停止 —— 不实现真实模型 API / Agent / 工作空间数据访问，也不开工其它 P1。等待下一轮指令。**
