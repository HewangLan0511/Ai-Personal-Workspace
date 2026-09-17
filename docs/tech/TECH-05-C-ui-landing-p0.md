# TECH-05-C · 原型 UI 落地第一批（三个 P0）

> 日期：2026-09-16 · 性质：**实现**（Agent 模式）
> 上游：`docs/reviews/UI-TECH05-AUDIT.md`（TECH-05-A 审计）→ `docs/tech/TECH-05-B-ui-migration-plan.md`（TECH-05-B 迁移方案）→ 本文（TECH-05-C 落地）
> 本轮范围：**只做三个 P0**（P0-1 模型管理中心 / P0-2 个人档案 / P0-3 工作空间状态）。P1/P2 未开工。
> 证据口径：所有结论标注 `文件:行号`，来自本轮实测；**不引用未跑过的结论**。

---

## 零、五条结论先行

1. **三个 P0 全部落地**，且"数据来源唯一"这件事是**机器证明的**，不是"两边都写着 canonical"。
   最强的一条是**对象同一性**：`window.__pwModels.registry === window.__pwAiModel.registry`
   （模型管理页取数的那份 Registry，与 AI 侧栏取数的那份是**同一个 JS 对象**）——
   该断言与数据无关，**在空环境里也不会空转**。
2. **共享原语层建立**（TECH-05-B §零 结论 2 指出的缺口）——但它**不是第二套体系**：
   原语层**零自定义属性定义**、**零 `@keyframes` 声明**，消费 38 个既有变量且全部有定义。
   `verify_tech05c.py:T4a/T4c/T4d/T4f` 把这三条钉死。
3. **头像不碰数据库 schema**：走已登记的 config 键 `profile.avatar`
   （`ui/src/views/ProfileView.vue:62` ↔ `core/src/db/config.rs:122/179/239`），
   **新增迁移文件数 = 0**（仍止于 `0008_plugin_audit.sql`）。
4. **一批验收判据"有意扩张"**（4 处白名单 + 2 处基线 + 1 处判据精度修正），逐条登记在 §五，
   **不是静默放宽** —— 这是本项目既有的记账惯例（见 `LEDGER.md` 中 TECH-03-B/TECH-04 同款段落）。
5. **无冗余垃圾是逐项查过的**：主动清掉了原语层里 3 个"预留但零消费"的类
   （`pw-empty` / `pw-seg` / `pw-card--dashed`），并新增 `T4f` 机器守护防止长回来。

---

## 一、交付清单

### 新增（5 个文件）

| 文件 | 行数 | 说明 |
|------|-----:|------|
| `ui/src/views/ModelsView.vue` | 818 | **P0-1** 模型管理中心（路由 `/models`） |
| `ui/src/components/WorkspaceStatus.vue` | 262 | **P0-3** 工作空间状态栏 + 模式模板 |
| `ui/src/components/ui/primitives.css` | 541 | 共享原语层（**本项目第一套**，不是第二套） |
| `ui/src/components/ui/Pw{Button,Card,Chip,Drawer}.vue` | — | 4 个原语 SFC |
| `tools/verify_tech05c.py` | 666 | 本轮验收脚本（19 静态 + 10 动态 = **34 项**） |

### 修改（7 个文件）

| 文件 | 改动 |
|------|------|
| `ui/src/router/index.ts:69-71` | 新增 `/models` 路由（懒加载，**不进主导航**） |
| `ui/src/main.ts:15` | 引入 `primitives.css`（原语层单点入口） |
| `ui/src/views/SettingsView.vue:191` | 设置页新增「模型管理」入口（`/models?from=settings`） |
| `ui/src/views/ProfileView.vue` | **P0-2** 头部（头像/昵称/方向/签名/标签）+ 编辑卡 + 头像抽屉 |
| `ui/src/views/DashboardView.vue:5,42` | **P0-3** 在真实工作台首页挂载 `<WorkspaceStatus />` |
| `ui/src/composables/useCurrentModel.ts:53,82` | 只读验收句柄 `window.__pwAiModel`（证明对象同一性用） |
| `ui/src/styles/tokens.css:98-103,153-158` | 补齐 6 个原型用到而真实缺失的语义值（**同一个 tokens.css**） |
| `core/src/db/config.rs:122,179,239` | 登记 config 键 `profile.avatar`（**三处齐改**，否则 `ConfigService::set` 会 bail） |

### 验收脚本同步（3 个文件）

`tools/verify_model_registry.py` · `tools/verify_tech02_workspace.py` · `tools/verify_tech04.py` —— 改动逐条见 §五。

---

## 二、P0-1 模型管理中心：把「显示 == 调用」变成机器可判

### 2.1 数据来源为什么只有一个

```
bridge.getSharedRegistry()                     ← 模块级单例（ui/src/ai/model/bridge.ts:53）
   ├─ ui/src/views/ModelsView.vue:53           ← 本页取的就是它
   └─ ui/src/composables/useCurrentModel.ts    ← AI 侧栏（AiSidebar）取的也是它
                     │
                     └─ 两边都用同一个投影函数 resolveCurrentModel()
                        （ModelsView.vue:71 / useCurrentModel.ts 内部）
```

因此"本页显示的当前模型"与"AI 请求实际使用的 currentModel"**结构上不可能分叉**：
同一份 canonical、同一个投影函数、同一个对象。

### 2.2 明确没做的事（P0-1 禁止项 → 判据）

| 禁止项 | 判据 | 结果 |
|--------|------|:----:|
| 不许有第二份 MODELS / 自建清单 | 静态：源码无 `const MODELS` / `aiModel` | ✅ `T1c` |
| 不许把列表写进 localStorage | 静态：无 `localStorage` / `sessionStorage` | ✅ `T1c` |
| 列表不是页面 state | 静态：`models.value = registry.list()` + `registry.subscribe()` 重取 | ✅ `T1d` |
| 写口不许分散 | 静态：只经 `syncSelection()`（`:270`）/ `registry.setDefault()`（`:293`） | ✅ `T1e` |
| 不许出现第二个存密钥的地方 | 本页**不输入** API Key，只显示"是否已配置"+ 跳设置页 | ✅ 设计约束（见 §七） |

### 2.3 动态证据（跑在最终 dist 产物上）

| 编号 | 断言 | 实测 |
|:----:|------|------|
| `R2` | `__pwModels.registry === __pwAiModel.registry` | **True**（对象同一性，与数据无关） |
| `R3` | 当前模型卡 `data-current-key` == `registry.getDefault()` == `__pwModels.current()` | 三项一致（本环境无 canonical ⇒ 均空串，脚本**如实标注空转**并由 `R2` 兜底） |
| `R4` | 模型管理页 label == AI 侧栏 label（同一投影函数） | 两边均 `未配置`（一致） |
| `R5` | 计数文案 == `registry.list().length` | `暂无模型` == 0（**投影**，不是写死） |

> ⚠️ **空转声明**：headless 环境里没有 Tauri 后端，`registry.list()` 为 0、canonical 为空，
> 于是 `R3`/`R5` 是"两边都是空"的等价 —— 脚本把这一点**打进了 detail**（`空转: true`），
> 真正承重的是 `R2`。这是刻意设计，不是遗漏。

---

## 三、P0-2 个人档案：接既有能力，两套结构各自独立

### 3.1 接的是真实能力（不是本地 state）

- 基础字段 → `useProfileStore().saveBasic()`（`ProfileView.vue:179,252`）→ `profile_basic` 表；
- 扩展块 → `profileApi.skill*` / `project*` / `timeline*`（`:301,347,379`）→ 各自表。

原型的 `state.profile.fields` 与 `profileExts` **在本轮仍是两套独立结构**（`T2b`），
没有被合并成一个"档案对象"。

### 3.2 头像：不新增 DB 字段的落地方式

```
读：configApi.get<string>('profile.avatar', '')     ProfileView.vue:163
写：configApi.put('profile.avatar', next)           ProfileView.vue:285
登记：core/src/db/config.rs  KEYS:122 / expected_type:179 / default_for:239
```

- `core/migrations/*.sql` **本轮新增数 = 0**（仍止于 `0008_plugin_audit.sql`）——`T2c3`；
- 三处登记齐备由 `T2c2` 断言（漏一处 `ConfigService::set` 就会 bail，写不进去）；
- Esc 取消编辑：由 `PwDrawer` 原语自己管（`ProfileView` 挂 `keydown` 兜底），`T2d` 断言。

---

## 四、P0-3 工作空间状态：只经门面，零真实控制

### 4.1 唯一来源

`WorkspaceStatus.vue:40` 只 `import ... from '@/workspace/runtime'`，
**不 import** `workspace/store` / `workspace/layout`（`T3a` + `verify_tech02_workspace.py:T1b`）。
用到的门面入口：`getCurrent / getApps / getLayout / updateStatus / listTemplates / saveTemplate /
prepareWorkspace / subscribe / snapshot.status`（9 个，`T3b`）。

### 4.2 禁止项逐条（P0-3）

| 禁止项 | 判据 | 结果 |
|--------|------|:----:|
| 不启动/关闭真实软件 | `cycleStatus()` 只调 `updateStatus()`（`:100`），Toast 明写"仅状态演示，未启动真实软件" | ✅ `T3c` |
| 不移动/缩放真实窗口 | 源码无 `moveWindow`/`setWindowPos`/`resizeWindow` 等 | ✅ `T3c` |
| 不执行真实流程 | 无 `exec(`/`spawn(`/`ShellExecute`/`launchApp`/`killProcess` | ✅ `T3c` |
| 不做真实快照恢复 | `snapshot.status().recovery.executable` **恒为 false**，界面如实显示"接口就绪 / 执行侧未放开" | ✅ `R9`（实测 `False`） |

### 4.3 动态证据

| 编号 | 断言 | 实测 |
|:----:|------|------|
| `R6` | 状态块在**真实工作台首页**渲染 | 状态栏存在；恢复行 = `恢复能力：不可恢复：probe-not-wired / no-workspace` |
| `R7` | 目标/模式文案 == `workspaceRuntime.getCurrent()` | 双向一致 |
| `R8` | 模板卡数 == `listTemplates().length` | DOM 3 == runtime 3（**非空转**） |
| `R9` | `executable === false` | **False** |
| `R10` | **S2**：路由切换后壳层节点身份保持、页面节点换新、未整页 reload | `mainSame:true sideSame:true pageChanged:true boot:'tech05c-probe'` |

> `R10` 自带**反向对照**：`pageChanged` 必须为 `true`（页面节点**必须**换新）。
> 没有这条对照，"什么都没变"也能骗过"壳层身份保持"。
> 另外 `R10` 刻意用**页内 SPA 导航**（点真实 `RouterLink`）而不是 `Page.navigate`：
> 后者是整页加载，拿它问"壳层是否被重建"是**无效问题**（首版就踩了这个坑，报告如实留痕）。

---

## 五、验收判据的显式扩张（**不是静默放宽**）

| 文件 | 改动 | 为什么不是放宽 |
|------|------|----------------|
| `verify_model_registry.py:T6b` | `WIRING_ALLOWED` 增加 `views/ModelsView.vue` | 该规则的本意是"不许任意文件乱接新层"。模型管理页是 TECH-03-A 注释里就点名的"将来的模型管理页"，**它就是**该写 canonical 的那一处 |
| `verify_model_registry.py:T6b2` | 新增 `WRITE_ALLOWED = {views/ModelsView.vue}` | 规则被**划清适用面**而非放松：只读消费方（AiSidebar / useCurrentModel / stores/ai）**仍逐字扫描写方法**；管理页必须能写，否则功能就是假的 |
| `verify_tech02_workspace.py:T1c` | 消费者白名单增加 `WorkspaceStatus.vue` | 本条的本意是"不许绕过门面 / 不许散落多处各读一份"，不是"只允许固件页" |
| `verify_tech04.py:T3g` | 同上（与 `T1c` 同源判据） | 同上 |
| `verify_tech04.py:T4a` | 路由基线增加 `/models` | 页面清单基线**有意演进**；差异会打进 detail，逐项可核对 |
| `verify_tech04.py:T4b` | 视图基线增加 `ModelsView.vue`（16 个） | 防"顺手删/搬"静默通过 |
| `verify_tech04.py:T4c` | **判据精度修正**：由裸文本 `"@keyframes" in text` 改为正则 `@keyframes\s+[A-Za-z_-]`（只匹配真实 at-rule 声明） | 原判据会被"注释里写明本文件零 keyframes"的**自述**误伤（本轮实测的假失败）。改后**仍能抓到任何真实新增的关键帧**，且 `kf == ['styles/base.css']` 不变 |
| `verify_stage7.py:348-355` | 前置由 `schema_version == 9` 改为 `>= 9` | **修过期前置**：契约版本单调递增，TECH-04 已升到 12（stage9 当时已按同口径改为 `>= 11` 并记账，stage7/8 漏改）。该断言表达的是"迁移 0006 已生效"，与任何产品行为断言无关 |
| `verify_stage8.py:225-228` | 前置由 `schema_version == 10` 改为 `>= 10` | 同上（迁移 0007 已生效） |

> 口径：`T4c` 的修正属**假失败修复**（"脚本红但产品对"不许用放松断言变绿 —— 这里是**修脚本**，
> 且修完立刻验证它仍有区分度）。其余 6 条属"边界有意扩张"，已在台账留痕。

---

## 六、机器证据

### 6.1 构建与类型

| 项 | 结果 |
|----|------|
| `vue-tsc --noEmit` | **0 error**（用真正的 `vue-tsc` 入口；用裸 `tsc` 会因解析不了 `.vue` 而产 27 条同源假报，报告留痕） |
| `vite build` | **rc=0**，产物含 `ModelsView-*.js` / `DashboardView-*.js` / `PwDrawer|PwChip-*.js` |
| Tauri release 产物 | `core/target/release/personal-workspace-core.exe` **rc=0**，并**重新嵌入**最终 `ui/dist`（见 §七 产物口径） |

### 6.2 TECH 验收（全部跑在最终 `ui/dist` 上，Edge headless + CDP）

| 脚本 | 结果 |
|------|------|
| `verify_contracts.py` | rc=0 |
| `verify_model_registry.py` | **32/32** |
| `verify_tech01.py` | **9/9** |
| `verify_tech03b.py` | **81/81** |
| `verify_tech04.py` | **44/44** |
| `verify_tech05c.py`（本轮新增） | **34/34** |
| `verify_tech02_workspace.py` | **11/11** |
| `verify_skin_engine.py` | **12/12** |
| `perf_tech01_22.py` | 14 场景全跑通，**longtask 全 0**，`error` 全 `null` |

### 6.3 阶段 E2E（真实 release 产物）

见 §八（本轮执行记录）。

---

## 七、边界如实声明

1. **headless 环境没有 Tauri 后端**：`R3`/`R5`/`R6`/`R7` 里的"空值等价"已在 detail 标注空转；
   承重判据是 `R2`（对象同一性）与 `T1a/T1b/T1d/T1e`（接线形态）。
2. **密钥面仍只有一处**：本页**不输入** API Key。全应用唯一密钥面是「设置 → AI」，
   模型管理页只显示"是否已配置"并提供跳转 —— 避免出现第二个存密钥的地方。
3. **模型管理页不进主导航**：入口在设置页（`SettingsView.vue:191`），返回按钮按 `?from=` 回来源。
   这与原型 UI-06 的定位一致（设置 → AI 与模型），也不抢 AI 侧栏的入口。
4. **产物口径**：`core/tauri.conf.json` 的 `frontendDist = ../ui/dist` 是**编译期嵌入**，
   且 cargo 不追踪 `dist` 变化（实测：dist 更新后 `cargo build` 1.56s 直接 Finished，未重编译）。
   本轮处置 = 最终 `vite build` 之后 `touch core/src/main.rs` + `cargo build --release`
   （253s），强制重嵌入 → 保证"最终产物里的 UI"与 `ui/dist` 完全一致。
   ⚠️ **如实声明**：Tauri 2 把资产 **Brotli 压缩**后嵌入，实测所有 UI 明文探针
   （`data-pw-*` / chunk 文件名 / 中文文案）在 exe 里**全 0 命中**，
   因此**无法从外部用字节比对证明嵌入新鲜度** —— 该结论建立在
   "重编译时序（exe 08:39 > dist 08:35）+ 编译期嵌入"这一**结构性**保证上，不是字节级证据。
5. **`@keyframes` 结论的依据是"声明"而非"文本出现"**：`primitives.css` 与 `PwDrawer.vue`
   的注释里写明了"本文件零 @keyframes"，因此文件中**存在该字符串**；
   实测**没有任何真实的 `@keyframes` 声明**（全局真实声明仍只有 `base.css` 一处）。

---

## 八、本轮执行记录（阶段 E2E，真实 release 产物）

方法：**顺序**跑（不并行背靠背 —— 验收脚本可信度清单 §9c：并行会因抢 Edge/资源产生偶发假失败）。
`verify_stage1.py` 额外给了 `--routes-url`（起静态服务供 `ui/dist`）跑 UI 路由项。

| 脚本 | 批跑 | 单跑复核 | 结论 |
|------|------|----------|------|
| `verify_stage1.py` | **19 PASS / 0 FAIL** | — | ✅ 启动 529ms（预算 3000）· 建库 `schema_version=12`/`migration_version=8` · **9 条路由全部无白屏且导航齐全** · ★ Widget 真实点击（use 0→3→10，size small→medium→large，落库 `{"weather":10}`） |
| `verify_stage2.py` | **10/10** | — | ✅ |
| `verify_stage3.py` | 8 PASS / 1 FAIL | **9/9 通过**（item 5 `foreground=True`） | ⚠️ **偶发假失败**：批跑时 Win32 前台激活被抢（`SetForegroundWindow` 前台锁），单跑稳定通过 |
| `verify_stage4.py` | **13/13** | — | ✅ |
| `verify_stage5.py` | **44/44** | — | ✅ |
| `verify_stage5_stream.py` | rc=0 | — | ✅ |
| `verify_stage6.py` | 36 PASS / 1 FAIL | **37/37 通过** | ⚠️ **偶发假失败**：5d 的 `命中=None` 是**请求报错**（`data_of` 语义：`ok≠true` ⇒ `None`），非"命中了提醒"。已用一次性直探脚本（真实 exe + 12 步 HTTP）复现全链路正常：PUT 关开关 → `check` 返回 `[] / ok:true`；对象形态/非法值被类型校验拒绝且**不污染状态**。单跑 37/37（与台账基线一致） |
| `verify_stage7.py` | 28/29（前置红） | **29/29 通过** | ✅ 修过期前置后与台账基线一致 |
| `verify_stage8.py` | 20/21（前置红） | **21/21 通过** | ✅ 同上 |
| `verify_stage9.py` | **29/29** | — | ✅（批跑器未匹配其输出格式，脚本自身 rc=0） |
| `test_ai.py` | rc=0 | — | ✅ |
| `verify_sidecar_bundle.py` | **8/8** | — | ✅ 发行态 |

**结论**：阶段验收 **12/12 套通过**。两处批跑红经单跑复核为资源争抢假失败（§9c 处置口径：
**不删断言、不放松判据**，报告写清"批量 N/M，单跑全绿"）。两处前置红属**过期断言**，
已按 TECH-04 同类口径修正并记账。

### 门禁

`gate.py --stage 9 --build` = **0 FAIL / 0 WARN / PASS 28+**（含编译门禁）。

> 首轮门禁曾 **FAIL=4**，全部来自我自己的一次性诊断脚本
> （`tools/_run_build.py` / `tools/_run_typecheck.py` 硬编码了用户绝对路径，命中 A020）。
> 按"收尾零残留"处置：**已删除全部 `tools/_*` 临时产物与日志**，
> 复跑门禁归零。这是"临时诊断脚本当场删"的实例，不是产品缺陷。

