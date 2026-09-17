# TECH-06-A · AI 模型真实连接完善 —— 交付报告

> 日期：2026-09-16 · 子阶段：TECH-06-A（真实能力接入阶段的第 1 步）
> 上游：`docs/tech/TECH-06-A-audit.md`（先审计后编码）· `docs/tech/TECH-05-D-ui-assistant-app-layer.md`
> 验收：`tools/verify_tech06a.py` **43/43**（FAIL=0）
> 性质：**自审 + 机器门禁**，不具独立审核效力（按 `SUPERVISOR.md` §13 与 22:32「减弱审核力度」口径）

---

## 〇 一句话结论

模型连接**链路本来就是真的**（真 core → 真 sidecar → 真 HTTP），本轮修的是**"状态语义失真"**：
把「离线」和「连接失败」从一个笼统的「不可用」里拆开，补上「未配置」，并给 Agent 一类接上
**既有的** `agent_health` 健康探测 —— **零新增后端命令、零新增存储键、零 UI 视觉改动**。

审计里的四个缺口 A-1~A-4 全部闭环；审计里列为"本轮不做"的**模型清单持久化**仍未做
（需求把"刷新后仍在"的验收放在 **B 阶段**，本轮不越界）。

---

## 一 目标与边界

| 需求项 | 要求 | 本轮落点 |
|---|---|---|
| 让 ModelRegistry 接真实状态 | 状态来自真实探测，不是猜 | `displayStatusOf()` 唯一判据；`ready` 只能由真探测得出 |
| 完善 Provider 连接检测 | 三类连接都能测 | API / 本地（既有 `ai_list_models`）+ **Agent（接上 `agent_health`）** |
| 展示真实状态 | 已连接 / 未配置 / 连接失败 / 离线 | `DISPLAY_STATUS_META` 5 态（含如实保留的「未测试」） |

**禁止项遵守声明**（逐条核对）：不做模型市场 ✅ · 不做自动下载模型 ✅ · 不实现 Agent 执行 ✅ ·
不重新设计 UI ✅ · 不建第二套架构 ✅ · 不新增后端命令 ✅。

---

## 二 ① 改动文件清单

**新增 3 个**

| 文件 | 作用 |
|---|---|
| `ui/src/ai/model/status.ts` | 显示状态词表 + 归约纯函数（**唯一出处**）。零 IO / 零框架运行期依赖，可被 Node 直接编译穷举 |
| `docs/tech/TECH-06-A-audit.md` | 先审计后编码的审计文档（只读，先于代码产生） |
| `tools/verify_tech06a.py` | 验收脚本（Node 直驱穷举 + 静态 T1~T8 + 动态 R1~R4） |

**改动 4 个（全部是加法或就地收口，无重构）**

| 文件 | 改了什么 | 为什么必须动 |
|---|---|---|
| `ui/src/ai/model/registry.ts` | `ModelListEntry` **加 3 个字段**：`needsSecret` / `lastError` / `lastCheck`；`list()` 把三项填进投影 | 缺口 A-2：UI 拿不到"为什么失败"的证据，只能显示一个笼统词 |
| `ui/src/ai/model/provider.ts` | `ModelIo` 加**可选** `agentHealth()`；`AgentAdapter.testConnection` 由"恒 `not_implemented`"改为**真探测** | 缺口 A-3：三类连接缺一类 |
| `ui/src/ai/model/ports.ts` | ① `coreModelIo.listRemoteModels` 无 core 时**抛错**（原来 `return []`）② 实现 `agentHealth`（`agents_list` + `agent_health`）③ `memoryPorts` 加 `agentProbe` 种子 | 缺口 A-4（假绿）+ A-3 的端口落地 |
| `ui/src/views/ModelsView.vue` | 删掉页面自带的 `STATUS_LABEL`/`TYPE_LABEL`，改为**消费领域层**；`__pwModels` 加只读句柄 | 缺口 A-1：状态判断不该散在页面里（收拢到唯一出处） |

**未动**（有意为之）：`core/` 一行未改 · 任何 `*.css` / token 未改 · 任何路由 / 新页面未加 ·
模型域 localStorage 键集合**不增不减**（仍为 TECH-05-D 冻结的 3 个）。

---

## 三 ② 数据流

### 3.1 探测链（本轮唯一新增的一环是 Agent）

```
点击「测试连接」（或脚本 probe(id)）
  └─ registry.check(id)                       ← 唯一"会发请求"的方法（既有）
       └─ providers.testConnection(desc, io)  ← 按 connection.type 选适配器
            ├─ CloudApiAdapter   → io.listRemoteModels → invoke ai_list_models ─┐
            ├─ LocalRuntimeAdapter → io.listRemoteModels ────────────────────┤
            └─ AgentAdapter      → io.agentHealth      ← ★ 本轮新增            │
                 └─ agents_list + agent_health（core 既有命令，真实 GET）      │
                                                                               ↓
                                    core/src/api/commands.rs → ai/mod.rs → sidecar /ai/models
                                                                               ↓
                                                    真实 HTTP 到 Provider（key 从系统凭据库取）
```

`agentHealth` **不是新能力**：`core/src/agents.rs:121/209` 早就在做真实 `GET {url}{healthCheck}`。
本轮只是把它包进 `ModelIo` 端口 —— 满足"优先复用已有 Runtime 接口"与"所有新增能力必须经过现有入口"。

### 3.2 状态归约链（本轮的核心）

归约本来就是两段，以前只有第一段；第二段散在页面里，于是信息在页面处丢了：

```
ModelProfile.status
   │  entryStatusOf()        ← 既有（registry.ts），领域内部态
   ▼
ready / unchecked / unavailable / disabled
   │  displayStatusOf()      ← ★ 本轮新增（status.ts），唯一出处
   ▼
connected / unconfigured / failed / offline / unchecked
```

判据（顺序即优先级，逐条可证伪）：

| # | 事实 | 结论 | 为什么 |
|---|---|---|---|
| ① | `enabled=false` 或 `entryStatus='disabled'` | `offline` | 未开放的 Provider（`web-ai`/`user-agent` 占位）谈不上"连接" |
| ② | `needsSecret && !hasSecret` | `unconfigured` | **缺前提，请求根本发不出去** —— 报"失败"是冤枉它 |
| ③ | `entryStatus='ready'` | `connected` | **唯一**由真实请求得出的正向结论（反假绿） |
| ④ | `entryStatus='unchecked'` | `unchecked` | 如实说"没测过"，不猜 |
| ⑤ | `lastError ∈ {local_model_down, unreachable}` | `offline` | 处置动作 = "把服务起起来" |
| ⑥ | 其余失败码 | `failed` | 处置动作 = "查 Key / 网络 / 额度" |

### 3.3 fake-green 的修法（A-4）

```
旧：  ports.ts  if (!inTauri()) return []        →  不抛错
      CloudApiAdapter  "没抛错" ⇒ ok=true        →  页面显示「已连接 · 0 个模型」  ← 假的
新：  ports.ts  if (!inTauri()) throw new Error('unreachable：…')
      → classifyProbeError → unreachable → 归入「离线」  ← 真的
```

修法方向刻意是**让错误更响**（抛错而不是返回空），验收 `T5a/T5b` 与动态 `R2` 双向锁住。

---

## 四 ③ 风险

| # | 风险 | 等级 | 处置 / 现状 |
|---|---|---|---|
| R1 | **模型清单不持久化**：刷新后"我的模型"仍为空 | **重要** | `registry.list()` 只读内存 `store`；`hydrate()` 只灌 Provider/凭据/canonical。**本轮按需求边界不补**（验收在 B 阶段）。审计 §四 已显式登记，B 阶段第一优先 |
| R2 | `enabled=false` 的占位 Provider 落进「离线」 | 一般 | 语义上可接受但不精确（应表达为"未开放"）。审计 §五·3 已登记；本轮不引入新显示态（避免 UI 词表扩张） |
| R3 | Agent 探测的端到端只有**端口级**证据 | 一般 | `agentHealth` 的真实 HTTP 由 core 既有实现保证，本轮验收只证明"端口接对了 + 缺前提如实回 short"。**未接真实第三方 Agent**（需求未要求，且无可用 Agent） |
| R4 | 状态**跨会话不保留**（`lastCheck`/`lastError` 每次启动清零） | 一般 | 与 R1 同源，一并留给 B/R1 的落库方案；现状 UI 如实显示「未测试」 |
| R5 | `OFFLINE_CODES` 是**硬编码码表**，与 Python 侧 `ProviderError` 靠人肉同步 | 建议 | 码表来自 `provider.ts` 的 `PROVIDER_ERROR_CODES`（同一文件内），未跨语言；扩大码表时需同步 —— 已在 `status.ts` 注释写明同源关系 |

无致命漏洞：未触碰红线 V1~V8；未新增密钥面（页面仍**零**凭据写入，验收 `T8b`）；未新增存储键（`T7a/T7b` 与基线逐项一致）。

---

## 五 ④ 验收结果

### 5.1 主验收 `tools/verify_tech06a.py` = **43/43**（FAIL=0，exit 0）

分三层，全部在**最终构建产物**（`ui/dist`）上跑：

**① 纯函数穷举（Node 直驱，无浏览器）**

| 项 | 结果 |
|---|---|
| ① 288 种事实组合全部落词表内，4 条决定性属性零违例 | **0 违例 / 288** |
| ①b 5 个显示态全部可达 | `connected/unconfigured/failed/offline/unchecked` |
| ①c **反假绿**：非 ready 组合 216 种，出现「已连接」**0 次** | `{非ready:216, 假绿:0}` |
| ② 同一失败态按码分流 | `local_model_down→offline`、`unreachable→offline`、`auth_failed→failed`、`timeout→failed` |
| ②b 对照组：只改失败码即改结论 | `unreachable→offline` vs `rate_limit→failed`（证明 ② 有区分度） |
| ③ 需要密钥没配 → 未配置 | `unconfigured` |
| ③b 对照组：配齐凭据后同码改判 | 无凭据`unconfigured` → 有凭据`failed`（证明 ③ 真读了 `hasSecret`） |
| ③c 本地模型（不需密钥）不判「未配置」 | `unchecked` |
| ④ 未发起探测不显示「失败/已连接」 | `未发起探测：尚未注册该 Agent` |
| ④b 对照组：真探测过才允许出现正向结论 | `已连接（3 个 · 20 ms）` / `探测失败（auth_failed）：401` |
| ⑤/⑤b 只映射到既有 dot 类 `ok/wait/off`；4 个要求词齐备 | `["off","ok","wait"]` · `[已连接,未配置,连接失败,离线,未测试]` |
| ⑥ 连接类型展示名收拢在领域层 | `api/local/agent` 三档 |

**② 静态门禁（T1~T8）**：词表唯一定义（T1a）· 页面无自带状态表（T1b）· 页面是消费方（T1c）·
页面零就地三元判据（T1d）· 证据三项**真的填进投影**（T2a/T2b/T2c）· Agent 端口在位（T3a）·
Agent 真走 `io.agentHealth`（T3b）· 未注册末位 `probed=false`（T3c）· 三类适配器齐备（T3d）·
**零新增后端命令**且所用命令 core 侧**确实存在**（T3e/T3f/T4a/T4b）· 无 core 抛错 + 可归类 + Tauri 分支仍在（T5a/T5b/T5c）·
**UI 冻结**（T6a~T6d：零自定义属性 / 零裸色值 / 复用共享原语 / 复用共享 toast）·
存储键不增不减（T7a/T7b）· **零新增页面路由**（T8）· 页面零凭据写入（T8b）。

**③ 动态端到端（Edge headless + CDP，跑 `ui/dist`）**

| 项 | 关键证据（原文） |
|---|---|
| R1 | 句柄齐备；本环境模型列表为空 ⇒ **显式标注"空转"**，不冒充有效证据（真证据在 R2） |
| **R2 反假绿（端到端）** | 注入真实模型 → 真探测 → `probe={ok:false, probed:true, code:"local_model_down"}`；Registry `display=offline`；**DOM `data-pw-model-status="offline"`**；逐项不一致 `[]` |
| **R3 未配置 ≠ 连接失败** | 注入 API 模型无凭据 → Registry `{needsSecret:true, hasSecret:false, display:"unconfigured"}`；**DOM `status="unconfigured"`** |
| R4 出厂包归约函数 | `ready→connected`、`unconfigured→unconfigured`、`offline→offline`、`failed→failed`、`fakeGreen→unchecked`（**≠connected**）、`notEnabled→offline` |

> **R2/R3 是本轮"UI显示状态 == Registry真实状态"的**非空转**证据** —— 空环境里这条断言天然空转，
> 所以脚本先 `registerProvider` + `add()` 造真实模型、再 `probe()` 触发真实失败/缺凭据，
> 最后**逐个模型比对 DOM 属性与 Registry 真值**。两个注入模型都在 DOM 里渲染出了真实卡片
> （R2 卡片文案：`t6a-modelT6A 本地桩 · t6a-model · 本地模型 离线查看 …`）。

### 5.2 回归（全量，0 失败）

| 套件 | 结果 |
|---|---|
| `gate.py --stage all` | **FAIL=0** · WARN=74（全为历史 `personal-workspace-ui/` Q001）· PASS=26 |
| tech06a / tech05d / tech05c / tech04 / tech03b / tech02_workspace / tech01 | 43/43 · 89/89 · 34/34 · 44/44 · 81/81 · 11/11 · 9/9 |
| model_registry / contracts / skin_engine / sidecar_bundle | 32/32 · 6/6 · 12/12 · 8/8 |
| `test_ai.py` | PASS=28 FAIL=0 |
| `vue-tsc --noEmit` | **exit 0**（零 error） |
| `vite build` | **exit 0**，184 模块，`index-BT76i9h0.js` —— 与上轮**哈希一致**（可复现） |

### 5.3 工具层记账（脚本判据修正，**不是放宽**）

验收脚本首跑 **39/41**，两处红全部是**脚本自身缺陷**，改脚本、不改产品断言：

| 项 | 根因 | 处置 |
|---|---|---|
| T3c | 断言写成 `"probed" in abody`，但 `probed` 只出现在**注释**里（脚本先 `strip_comments`），而它实际是 `result()` 的第 7 个**位置**参数 | 改为**按位置**取末位实参断言（无端口分支 / 未注册分支均须为 `false`），并保留反向对照组 |
| R1~R4 组异常 | 注入的 Provider id 用 `__t6a_local__`（下划线开头）→ `deriveModelId()` 拼出 `__t6a_local__:t6a-model` → 违反 `validateModelProfile()` 的 `^[A-Za-z0-9]…` ⇒ `ModelProfileError: id(bad_id)`，异常把整组带走 | ①改为合法 id `t6a-local` / `t6a-api`；②注入逻辑页内 `try/catch` 并把逐条错误回传（**一个注入失败不再吞掉整组证据**） |

> 口径沿用本项目既有规则：**"脚本红但产品对"不许用放松断言的方式变绿**。
> 这次是"产品对、断言写歪"，故只修断言与被测夹具，产品代码一行未因首跑进行调整。

---

## 六 ⑤ 下一阶段建议

**给 TECH-06-B（个人档案数据真实化）的接口提醒**（不越界，只移交）：

1. **别新建第二套存储层**：模型侧暴露的教训是"`hydrate()` 只灌一部分 ⇒ 刷新丢数据"。
   档案若加昵称/签名/标签，先确认 `profile_basic` 是否**已有列**（PW-INTEGRATION-002 记为
   "C Core 真缺口：`profile_basic` 无扩展列"），再决定是加列还是走 `metadata.extras` 扩展位 ——
   需求已明确"优先 config 字段或 profile 扩展，**不做大迁移**"，与本条一致。
2. **头像存储**：需求倾向 config 字段/扩展位；若最终走文件路径，务必沿用"凭据只存引用"的同款思路
   （**只存路径引用，不存二进制进 DB**），否则会撞上 TECH-03-A 定下的"明文不进配置"红线。
3. **验收要能证伪**：本轮的 R2/R3 值得照抄 —— **空环境下的"刷新后仍在"同样是空转断言**，
   必须先造真实数据、刷新、再比对，否则会得到一个永远绿的假验收。

**顺带产出（本轮未做，登记为后续第一优先）**：

- **模型清单持久化**（审计 §四 + 风险 R1）：建议落 core config 键（如 `ai.models.registry`，JSON 字符串），
  与 canonical 同层 —— 避免新增 localStorage 键、避免两处真相；需在 `core/src/db/config.rs` 三处登记
  + 迁移版本 +1，并在验收里**显式记账基线变更**。此项直接决定"模型管理中心刷新后还在不在"。
- 探测结果跨会话保留（`lastCheck`/`lastError`）可与上条一并落库。

---

## 七 边界如实声明（不主张未做到的事）

1. **模型列表刷新后仍为空** —— 本轮未做持久化（需求把它放在 B 阶段），不是遗漏，是**有意不越界**。
2. **未接真实第三方 Agent** —— Agent 探测走的是 core 既有 `agent_health`（真实 HTTP），
   但本环境无可用 Agent，故端到端只证明到"端口接线正确 + 缺前提如实短路"，未证明"能探活一个真实 Agent"。
3. **验收环境无 core** —— 所有动态断言跑在浏览器降级层；`inTauri()` 分支（真 `ai_list_models` /
   `agents_list` / `agent_health`）由静态断言 T5c/T3e/T3f/T4a/T4b 覆盖其存在与命令合法性，
   未做桌面端真机端到端。这与阶段1 以来的既有口径一致（L-026）。
4. **UI 交互为 CDP 合成** —— R2/R3 的 DOM 比对是脚本注入 + 程序化触发的真实探测，非真人点击。
5. **`enabled=false` 的占位 Provider 归入「离线」** —— 语义可接受但不精确（见风险 R2）。
