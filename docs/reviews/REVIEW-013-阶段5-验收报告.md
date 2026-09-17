# 审核报告 REVIEW-013 · 阶段5：AI 助手系统

> **本模板已按 2026-09-12 22:32 口径收敛。** 报告只写 3 项：**判定+理由 / 硬证据 / 阻塞项**。

| 项目 | 内容 |
|------|------|
| 审核编号 | REVIEW-013 |
| 审核日期 | 2026-09-13 |
| 审核阶段 | 阶段 5 · AI 助手系统 |
| 审核对象 | `core/src/{sidecar,db,event_bus,ai,scheduler}`、`ai/*`、`system/{service.py,build_sidecar.py}`、`ui/src/{stores/ai.ts,components/AiSidebar.vue,views/SettingsView.vue,api/eventBridge.ts}`、`tools/{gate.py,verify_stage5.py,verify_sidecar_bundle.py}`、契约 `03` |
| 审核基准 | `docs/agent-dev/08-阶段指令-AI助手.md` + `SUPERVISOR.md` 第四章唯一标准 |
| 审核方式 | 自动门禁 + 目标复现（6 条脚本全跑） |
| **独立性声明（必填）** | **自审 + 机器门禁** —— 本报告**不产生独立审核效力** |
| **判定** | **✅ 通过（3 项记录在案）** |

---

## 〇、独立性声明（必填，不可省略 —— **不属收敛对象**）

- 本报告性质：**自审 + 机器门禁**（角色合并状态下，架构/开发/审核同属肉编器001号）。
- 本报告**不产生独立审核效力**；可机器判定的部分一律外化为可复现证据（6 条脚本，见 §二）。
- 拿不到证据的项一律标"**未实测**"，不折算通过（红线 V6 对自审同样适用）。
- 未经「申请独立复核阶段 5」口令，不发起独立复核（13.3 回调后的口径）。

---

## 一、判定与理由

### 判定：✅ **通过（3 项记录在案）**

**理由**（对照第三章三条判据）：

1. **目标达成** ✅ —— 08「验收一句话」（*侧栏能对话、能切模型、工作助手模式能读到当前项目和模式信息*）全部机器可复现：
   `verify_stage5.py` **44/44**（含验收 1~10 逐项）、`verify_stage5_stream.py` **18/18**、`test_ai.py` **28/28**、
   `verify_sidecar_bundle.py` **8/8**（发行态）、`cargo test` **40/40**。10 项验收标准无一项"未判定"。
2. **无致命漏洞** ✅ —— 红线 V1~V8 **0 命中**。凭据只进 Windows 凭据库（DB 全文件二进制搜索 + 逐表逐列 LIKE 双重确认搜不到明文）；
   consult 模式即使请求体硬塞上下文也拿不到任何用户数据（对照组：workspace 确实注入，证明是隔离生效而非链路断掉）；
   `ai_conversations` 只存元数据不存正文。
3. **无冗余垃圾** ✅ —— 无临时产物入库；`core/target`、`core/binaries`、`node_modules` 均已 gitignore；
   新增的 `tools/verify_sidecar_bundle.py` 是**验收工具**（有明确用途：发行态守护），非垃圾。

> 本轮**不是"零发现"** —— 修复过程中抓出并修掉了 **3 个真实缺陷**（详见 §二·2.4），其中 2 个是"只在特定路径复现、开发态全绿"的静默失真。

---

## 二、硬证据（**必须粘贴原文，不许转述**）

### 2.1 自动门禁

```
python tools/gate.py --stage 5 --build
```

```
  [PASS] S100 — [阶段5] 存在：ai/providers
  [PASS] S100 — [阶段5] 存在：ai/prompt
  [PASS] S120 — [阶段5] ai/providers 下存在 ['*.py'] 文件
  [PASS] A030 — ADR-001：system/build_sidecar.py 属构建脚本，豁免  @ system/build_sidecar.py
  [PASS] W100 — ui/src/utils/logger.ts 已被 ui/src/api/appsService.ts 引用（接线到位）  @ ui/src/utils/logger.ts
  [PASS] W100 — ui/src/utils/markdown.ts 已被 ui/src/components/AiSidebar.vue 引用（接线到位）  @ ui/src/utils/markdown.ts
  [PASS] W100 — ui/src/composables/useWidgets.ts 已被 ui/src/views/DashboardView.vue 引用（接线到位）  @ ui/src/composables/useWidgets.ts
  [PASS] B120 — externalBin 产物就绪：binaries/service → service-x86_64-pc-windows-msvc.exe
  [PASS] B131 — sidecar 发行产物不落后于源码：core/binaries/service-x86_64-pc-windows-msvc.exe
  [PASS] B132 — 开发态构建残渣 core/target/release/service.exe 不被使用（resolve_launcher 已改为源码优先）；建议删除以免误导
  [PASS] B134 — 打包脚本会把 ai/prompt/*.md 打进单文件（发行态 AI 可用）
  [PASS] B100 — cargo check 通过
  [PASS] B110 — 前端 typecheck 通过

✅ 门禁通过   FAIL=0  WARN=0  PASS=23
```

**门禁结论：0 FAIL / 0 WARN / 23 PASS**（含 `--build`）

> 本轮对门禁工具本身做了 2 处修改（**已重测，见上**）：
> ① 新增 **B134** 静态守护 —— 打包脚本必须把 `ai/prompt/*.md` 打进单文件（防发行态 AI 整体不可用）；
> ② `check_sidecar_staleness` 的"最新源码"扫描**纳入 `ai/prompt/*.md`** —— 此前只比 `.py`，
> 改了提示词不重打不会被发现。

### 2.2 阶段验收脚本（4 条，全部机器可复现）

```
python tools/verify_stage5.py
```
```
PASS  10e 未开放的 Provider 抛 not_implemented（不静默返回空）
PASS  10f 未知 Provider 报错（不静默兜底成某个默认模型）
合计 44/44 通过
```

```
python tools/verify_stage5_stream.py
```
```
  [PASS] 验收7 ★ consult 模式：模型侧拿不到任何用户数据（即使请求体硬塞）
  [PASS] 验收8 ★ workspace 模式：模型侧确实收到模式与项目（对照组）
  [PASS] 两模式的 system 提示词**不同**（证明真的分支，而非同一份）
====================================================================
端到端流式验证：PASS=18  FAIL=0
```

```
python tools/test_ai.py
```
```
  [PASS] 模板 consult_default 可加载
  [PASS] 模板 study_assistant 可加载
  [PASS] 模板 dev_assistant 可加载
  [PASS] 未传变量时原样保留 {{context}}
  [PASS] 传变量后替换成功
  [PASS] 拒绝目录穿越的模板名
====================================================================
结果：PASS=28  FAIL=0
```

```
python tools/verify_sidecar_bundle.py     # ★ 本轮新增：发行态回归
```
```
  [PASS] 打包 exe 启动并按 announce 协议回报端口（不依赖仓库源码）
         port=56901
  [PASS] 打包 exe /health 可用
  [PASS] 打包 exe 内含完整 ai 包（/ai/providers 返回 7 个注册项）
  [PASS] 打包 exe 凭据写入可用（ai.credentials 已入包）
  [PASS] ★ 打包 exe /ai/chat 能出流式内容（ai/prompt/*.md 已入包）
         chunk=30 首块=50ms 总=2464ms err=none
  [PASS] ★ 打包 exe 不再报「模板不存在」
  [PASS] 发行态 consult 的 system 提示词不含用户数据（红线 V2）
  [PASS] 打包 exe 对 /sys/process/* 返回 410 moved_to_core（ADR-001）
======================================================================
合计 8/8 通过
```

```
python tools/rust.py test
```
```
running 40 tests
test result: ok. 40 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.19s
```

```
node ./node_modules/vue-tsc/bin/vue-tsc.js --noEmit   （ui/ 下）
```
```
EXIT=0
```

### 2.3 红线检查

| 红线 | 结果 |
|------|------|
| V1 明文密钥 | ✅ 未命中（DB 全文件二进制 + UTF-16LE 变体 + 逐表逐列 LIKE 三重搜索均无 `sk-`） |
| V2 咨询模式读用户数据 | ✅ 未命中（源码硬塞对照实验，consult 侧零泄露） |
| V3 AI 自动改档案 | ✅ 未命中（阶段5 无写档案路径；档案写入属阶段7） |
| V4 插件默认权限 | ✅ 未命中（插件系统未开工；门禁 A031 在位） |
| V5 破坏性操作无确认 | ✅ 未命中 |
| V6 谎报 | ✅ 未命中（本报告所有数字均为本轮实测原文；未实测项一律显式标注） |
| V7 插件/UI 直连库 | ✅ 未命中（AI 只经 Tauri command，无 HTTP 直连；sidecar 不碰 SQLite） |
| V8 产物/数据库入库 | ✅ 未命中（`.gitignore` 覆盖 `target`/`binaries`/`*.db`） |

**红线命中：0**

### 2.4 本轮实际修复的 3 个缺陷（**这是本次审核最有价值的部分**）

| # | 缺陷 | 症状 | 根因 | 修法 |
|:-:|------|------|------|------|
| 1 | **`PW_SIDECAR_FORCE_DEV=1` 形同虚设**（L-044 残留） | 设了"强制源码"开关，实际仍拉起 `core/target/release/service.exe` 旧快照 | `resolve_launcher()` 的 `force_dev` 分支**只打日志、没有 return**，径直落到打包态分支 | 改为在候选脚本命中处**真的返回** `Launcher::Dev`；强制态找不到脚本时**报错而非静默降级** |
| 2 | **发行态 `/ai/chat` 整体不可用** | 安装版一提问就报「模板不存在：consult_default」；**开发态全绿** | `build_sidecar.py` 打包时**没有 `--add-data`** —— PyInstaller 不收集 `.md`，安装包里 `ai/prompt/` 是空的 | 显式 `--add-data <repo>/ai/prompt;ai/prompt`；`is_fresh()` 把 `ai/` 与 `system/win/` 纳入比对；门禁加 **B134** 守护 |
| 3 | **`ui.ai.*` 五个配置键未登记**（前端零调用） | 侧栏宽度/收起/Provider/模型/模式**写不进 core 的 config 表**（`ConfigService::set` 拒写未登记键）→ 验收 9 不成立 | 键只存在于前端 `localStorage`，core 侧 `KEYS` 漏登记；且前端从不调 `put_config`（`lsSet` 单写） | core 侧登记 5 键（`KEYS`/`expected_type`/`default_for` 三处）+ 契约 03 §3.1.1；前端加 `persist()` 双写（localStorage + `put_config`，core 不可达时静默降级） |

> **共同教训**（值得写进交接）：三者都是"**我改的地方生效了，我没改的地方没生效**"——
> 缺陷 1 是开关没接线、缺陷 2 是数据文件没进包、缺陷 3 是键没登记。
> 三者的症状都不指向真正的原因，且**开发态一律看不出来**。故本轮把"发行态可用"做成了脚本（`verify_sidecar_bundle.py`）+ 门禁（B134），
> 而不是靠"我记得"。

---

## 三、三条判据的核验要点（**只核这三条**）

| # | 判据 | 怎么判 | 结果 |
|:-:|------|--------|:----:|
| 1 | **目标达成** | 08「验收一句话」+ 10 项验收标准，达成即算实现 | ✅ |
| 2 | **无致命漏洞** | 红线 V1~V8 + 数据安全 + 不可恢复架构错误 | ✅ |
| 3 | **无冗余垃圾** | 死代码 / 临时产物 / 重复实现 / 无人消费的半成品（骨架预留不算） | ✅ |

### 三·附 强制动作：调用点检索（**不属收敛对象**）

| 符号 | 定义处 | 调用点（文件:行） | 结论 |
|------|--------|-------------------|------|
| `ai_chat`（Rust command） | `core/src/api/commands.rs:467` | `ui/src/stores/ai.ts:306` | ✅ 已接线 |
| `ai_cancel` | `core/src/api/commands.rs:486` | `ui/src/stores/ai.ts:343` | ✅ 已接线 |
| `ai_info` | `core/src/api/commands.rs:494` | `ui/src/stores/ai.ts:190` | ✅ 已接线 |
| `ai_set_credential` | `core/src/api/commands.rs:500` | `ui/src/views/SettingsView.vue:66` | ✅ 已接线 |
| `ai_delete_credential` | `core/src/api/commands.rs:510` | `ui/src/views/SettingsView.vue:86` | ✅ 已接线 |
| `ai_list_models` | `core/src/api/commands.rs:519` | `ui/src/views/SettingsView.vue:101` | ✅ 已接线 |
| `ai_preview_context` | `core/src/api/commands.rs:551` | `ui/src/stores/ai.ts:363` | ✅ 已接线 |
| `ai_permission_scope` | `core/src/api/commands.rs:536` | **无前端调用** | ⚠️ **未接线**（见 §四 记录在案 1） |
| `AI_STREAM_CHUNK` 发布 | `core/src/ai/mod.rs:158` | — | ✅ sidecar NDJSON 逐行转入事件 |
| `bridge_to_webview` | `core/src/event_bus/mod.rs:68` | `core/src/main.rs:56` | ✅ **L-017/L-032 闭环**：core 进程内事件 → webview |
| `listen('pw://event')` | `ui/src/api/eventBridge.ts:74` | `ui/src/App.vue:10`（`startEventBridge`） | ✅ 前端已订阅 |
| `on('AI_STREAM_CHUNK')` | `ui/src/stores/ai.ts:213` | `ui/src/stores/ai.ts:182`（`init()` → `bindEvents()`） | ✅ 增量渲染链路完整 |
| `persist()`（本轮新增） | `ui/src/stores/ai.ts:119` | `ai.ts:199,200`（初始选择重置）× 2 · `ai.ts:232`（setMode）· `ai.ts:240`（setProvider）· `ai.ts:250`（setModel）· `ai.ts:259`（toggleCollapsed）· `ai.ts:265`（setWidth） = **7 处** | ✅ 已接线（本轮补） |
| `build_ai_context`（红线 V2 唯一关口） | `core/src/scheduler/ai_context.rs` | `core/src/ai/mod.rs:92` · `core/src/ai/mod.rs:215` · `core/src/scheduler/mod.rs:23` | ✅ 已接线 |
| `AiSidebar` | `ui/src/components/AiSidebar.vue` | `ui/src/App.vue:5,39`（import + 渲染） | ✅ 已接线 |
| `service.exe` 打包数据（`--add-data`） | `system/build_sidecar.py:173` | 门禁 `B134` 静态守护 + `verify_sidecar_bundle.py` 5/6 项 | ✅ 已接线 |

- 全仓检索（`.rs` / `.ts` / `.vue` / `.py`），排除定义处本身；跨语言边界（Rust command ↔ 前端 invoke）两侧均已查。
- **唯一"零调用"项：`ai_permission_scope`** —— 已如实登记（见 §四），不折算为"功能成立"。

---

## 四、记录在案（**不阻塞，仅备查**）

| # | 事项 | 为什么不阻塞 |
|:-:|------|--------------|
| 1 | `ai_permission_scope` command **无前端调用**（权限提示实际走 store 的 `permissionText` 本地计算 + `ai_preview_context` 的 `usedScopes` 交叉核对；sidecar 侧 `/ai/scopes` 亦被验收 7c 覆盖） | 同一能力已有**真实可用**的路径，非"功能不存在"；该 command 属并列入口，删除或接线均可，**不影响 08 任何验收项** |
| 2 | **UI 侧无自动化测试运行器**（L-036 延续）：侧栏交互靠 `verify_stage5.py` 的 HTTP 端到端 + `vue-tsc` 类型检查覆盖，"侧栏拖拽宽度"的手感只能人眼确认 | 与阶段1~4 同源遗留；关键行为（持久化键读写、5 键契约一致）已被 `verify_stage5.py` 9a/9b/9c 机器断言 |
| 3 | **`localStorage` 与 core config 的一致性**：UI 只写不读（读源单一为 localStorage），若外部直接改 core config，UI 不会跟随 | 单机单用户场景下二者只在 UI 操作时变化；"只写不读"是刻意的（避免启动期与 core 时序耦合），已在契约 03 §3.1.1 注明 |

> `ai_conversations` 表（08 交付物）已存在于 `0001_init.sql`；**聊天正文不落库**，仅元数据。

---

## 五、阻塞项

| # | 阻塞项 | 阻塞了什么 | 完成判据 |
|:-:|--------|------------|----------|
| — | **无** | — | — |

> 阶段5 为 MVP 最后一块，通过后即进入 V2 阶段（6 学习成长 / 7 个人档案）。
> 阶段5 独立性定性：**"机器门禁通过 + 自审记录"**，与阶段1~4 一致。

---

## 六、下一步

**开发 Agent 下一步动作**：开阶段6（`docs/agent-dev/09-阶段指令-学习成长.md`）；开工前重跑 `python tools/gate.py --stage 6 --build`。

**送审前必须准备**：`python tools/gate.py --stage 6 --build`（有 FAIL 不许送审）

**触发口令**：「申请审核阶段 6」· 独立复核：「申请独立复核阶段 5」

---

*审核人：肉编器001号（监制） · 2026-09-13*
