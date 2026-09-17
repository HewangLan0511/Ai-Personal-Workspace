# PW-INTEGRATION-003 · Contract Freeze（契约冻结）

> 日期：2026-09-15 · 性质：**只冻契约，零业务实现**
> 遵守停止条件：不改业务代码 / 不改数据库 / 不做 migration / 不重构 Provider / 不接 Motion / 不做 Skin UI / 不做 View Transitions / 不实现"完成工作" / 不实现 Workspace Snapshot / 不实现 External Window Resize
> 证据口径：所有"实测"结论标注 `文件:行号`，来自本轮实际读码；所有"建议/契约"标注为冻结项或待定项
> 上游：`PW-INTEGRATION-001-架构审计.md`（真实架构）· `PW-INTEGRATION-002-preflight.md`（前置设计）

---

## 0. 覆盖对照

| 任务要求 | 本文档 |
|---|---|
| ① 三个产品决策落地情况 | §1 |
| ② WorkspaceSnapshot Contract（含恢复顺序/失效/拓扑/损坏/超时/中断/完成后状态，v1 vs v2） | §2 |
| ③ AI Provider Contract（canonical + 独立页与侧栏共读边界） | §3 |
| ④ ExternalWindowResize Contract | §4 |
| ⑤ UI-04 对接 Contract（八项逐项标记） | §5 |
| ⑥ Motion 第一批消费点 | §6 |
| ⑦ Toast 统一 Contract | §7 |
| ⑧ Core 缺口 | §8 |
| ⑨ 等待 UI Skill 的事项 | §9 |
| ⑩ 建议下一阶段施工顺序 | §10 |

**本轮产物**（均为新增，无一行业务代码改动）：

| 文件 | 类型 | 作用 |
|---|---|---|
| `docs/reviews/PW-INTEGRATION-003-contract-freeze.md` | 文档 | 本文件（唯一强制交付物） |
| `docs/contracts/workspace-snapshot.v1.schema.json` | schema 草案 | Snapshot v1 机器可读契约（`additionalProperties:false` 即 v2 越界门禁） |
| `docs/contracts/fixtures/*.json`（6 个） | contract fixture | 2 正向 + 4 反向（反例必须被拦） |
| `docs/contracts/fixtures/ai-provider-current.v1.valid.json` | contract fixture | Provider 五层契约的形态定义 |
| `tools/verify_contracts.py` | 静态验证工具 | 无第三方依赖；**6/6 符合预期**（见 §2.10） |

---

## 1. 三个产品决策落地情况

| # | 决策（本轮冻结） | 落地形态 | 状态 |
|---|---|---|---|
| 1 | Workspace Resize = **外部软件窗口** Resize（**不是**主应用窗口、**不是**布局编辑器槽位） | 复用现有 `windows_place` 通道，**零 Core 新增命令** | ✅ 已冻结 → §4 |
| 2 | Snapshot 第一阶段用 config 键 **`workspace.snapshot.last`**；**不做 migration 0009** | 键白名单登记 + JSON object 值；0009 保留给"历史/多快照" | ✅ 已冻结 → §2 |
| 3 | AI Provider canonical = **Core Config `ai.provider.current`** | 四层职责切分（canonical / cache / suggestion / transport） | ✅ 已冻结 → §3 |
| 4 | "完成工作" | 继续登记 **PD-001**，不实现、不发明按钮 | ✅ 已登记 |

**决策 3 的落地风险（本轮新发现，必须一并冻结）**：core 的 config 写入有**键白名单硬校验**，未登记的键会被直接拒绝：

```
core/src/db/config.rs:41-43
  if !KEYS.contains(&key) {
      anyhow::bail!("未登记的配置键：{key}（新增键必须先登记到 config.rs 的 KEYS）");
  }
```

因此 `workspace.snapshot.last` / `ai.provider.current` / `ai.model.current` 三个新键**必须三处齐登**（`KEYS` + `expected_type` + `default_for`），漏 `expected_type` 会静默变成"无类型校验"——这一点仓库已有专项单测锁死（`every_registered_key_has_an_explicit_type`，`config.rs:269-277`）。这属于**施工前提**，不登记则一切写入失败。

---

## 2. WorkspaceSnapshot Contract v1（冻结）

### 2.1 契约边界（先说"不做什么"）

| | v1 **承诺** | v1 **明确不承诺**（= v2 能力） |
|---|---|---|
| 份数 | 只保最近 **1** 份（`workspace.snapshot.last`） | 历史快照 / 多快照管理 / 快照列表 |
| 窗口身份 | 同一次运行（同一 `source.runId`）内按 `hwnd` 精确恢复 | 跨重启 hwnd 重认领（hwnd 是进程内 volatile） |
| Z 序 | 按 `zIndex` 近似序恢复（EnumWindows 返回序） | 精确 Z 序（需额外枚举策略） |
| 置顶 | **不恢复** `alwaysOnTop`（无法稳定读回，猜测会改变用户桌面） | 置顶属性恢复 |
| 拓扑 | 同拓扑精确恢复；拓扑变化 → 比例映射（L2） | 拓扑变化感知提示 / 逐屏选择 |
| 触发 | 仅 `enter_mode`（从"无模式"进入模式） | `before_switch` 也落盘 |

> **硬约束**：`schema.json` 顶层 `additionalProperties: false`，且 `x-pw-v2-forbidden` 列出 10 个禁止键名（`history` / `snapshots` / `hwndIdentity` …）。**往 v1 里偷塞 v2 字段会在门禁变红**（§2.10 已验证）。

### 2.2 数据模型（完整字段表）

```
WorkspaceSnapshot v1                       ← config 值：workspace.snapshot.last（object）
├─ schemaVersion : 1
├─ snapshotId    : "ws-YYYYMMDD-HHMMSS-xxxx"
├─ takenAt       : epoch ms
├─ trigger       : "enter_mode"            ← v1 enum 仅此一项
├─ source        : { appVersion, corePid, runId }
│                    ↑ runId = hwnd 有效性的**边界**：换 runId 即视为 hwnd 全部失效
├─ monitors[]    : { index, primary, bounds{x,y,w,h}, work{x,y,w,h} }
│                    ↑ 与 `monitors_list` 输出同构（MonitorInfo：x/y/w/h + work_x/…）
├─ desktop       : { foregroundHwnd | null, windows[ WindowEntry ] }
│                    ↑ 进入模式前的"普通工作台"
└─ workspace     : { modeName, modeId, layoutName, monitor, launchedAppIds[], managed[] }
                     ↑ 退出时要收尾的对象

WindowEntry
├─ hwnd          : int（volatile）
├─ pid           : int
├─ exeName       : string        ← v1 必须（`process_image_name` 已有）
├─ exePath       : string|null   ← v1 尽力采集，允许 null
├─ appId         : int|null      ← 能按名匹配 apps 表则补
├─ title         : string ≤120   ← 截断，不存全文（体积 + 隐私）
├─ className     : string
├─ monitorIndex  : int
├─ rectPx        : {x,y,w,h}     ← 绝对物理像素（同拓扑时优先用它恢复）
├─ rectNorm      : {x,y,w,h}     ← 相对所属显示器 work 的归一化（拓扑变化时用它映射）
├─ state         : { visible, minimized, maximized }
└─ zIndex        : int ≥1

managedEntry : { appId, appName, pid, hwnd }   ← 全部可空（匹配不到就 null）
```

**为什么 `rectPx` 与 `rectNorm` 都要记**（契约裁决，不是冗余）：
- 现有两条通道吃不同的坐标系 —— `windows_place` 吃**绝对像素**（`commands.rs:222-237` → `place(hwnd, PxRect, …)`），布局通道吃**归一化**（`layout.rs:64-73` `to_pixels`）。
- 归一只记归一化会丢像素保真（同屏恢复出现 1-2px 漂移，07 验收口径是 ±2px）；只记像素则拓扑一变就废。
- 采集端**已有归一化实现可直接复用**：`modes_capture_current_inner` 已在做"像素 → 相对主屏 work 的归一化"（`commands.rs:529-532`），含 `clamp(0,1)` 与 `clamp(0.05,1)` 的边界钳制。

### 2.3 采集时机与"禁止覆盖"规则（关键裁决）

| 事件 | 持久快照 `workspace.snapshot.last` | 内存快照 `RunRecord.last_snapshot` |
|---|---|---|
| 无模式 → 进入模式 A | ✍️ **写入**（`trigger:"enter_mode"`） | — |
| 模式 A → 切换模式 B | ⛔ **禁止覆盖** | ✍️ 保持现状（`snapshot_before_switch`，`runner.rs:168-174`） |
| 退出模式（`mode_exit`） | 📖 **读取并恢复** → 成功后清除 | 既有行为不变 |

**为什么切换不覆盖**（这是本轮最重要的契约裁决）：
产品口径是"退出工作模式后恢复**进入工作模式前**的工作台"。若 A→B 切换时用 B 的进入态覆盖，那么退出 B 时会恢复到"A 的工作态"——那不是用户要的"普通工作台"。

因此两份快照**职责分离**：
- 持久快照 = 「回到普通工作台」（`enter_mode` 写，只此一份）
- 内存快照 = 「回到上一个模式」（`before_switch` 写，现有能力，`runner.rs:127-143`，本轮**不动**）

**为什么快照必须收录"进入前所有可见窗口"而不是只记模式的 appId 集合**：
布局应用会把槽位摆到**已运行**的窗口上（`apply.rs:102-121` `resolve_pid` 找运行中的 pid），也就是说 —— 用户原本开着的 VSCode 会被模式布局**挪走**。退出时若不还原这些窗口，用户桌面就永久错位。而那些被模式**拉起**的软件（`status:launched`）在进入前并不存在、退出时由 `kill_registered` 关掉，天然不在快照里。逻辑自洽。

### 2.4 持久化边界

| 问题 | 冻结结论 | 依据 |
|---|---|---|
| 谁写 | **core 独占** | 沿用"db 单一写入者"纪律 |
| 键 | `workspace.snapshot.last` | 决策 2 |
| 值类型 | **object**（不是 string 包 JSON） | `expected_type` 支持 `object`（`config.rs:146,151` 已有先例 `ui.dashboard.usage` / `mode.switch_memory`）。`ui.ai.*` 之所以用 string，是因为要与 localStorage 同构；快照是 core 独占、无 localStorage 孪生 → 不套用该约定 |
| 何时写 | `apply_mode` 流水线**动窗口之前**（第一步前置） | 快照必须在改变桌面前完成 |
| 写失败 | **不阻塞进入模式**（降级为现行为，记 WARN） | 快照是体验增强，不是前置条件 |
| 何时读 | `mode_exit`（`pipeline.rs:349`）内，**关完模式软件之后** | 顺序见 §2.5 |
| 容量 | ≤200 窗口；超出按面积取 Top N；title 截断 120 | 防 JSON 膨胀 |
| 隐私 | 只存窗口元数据；不存窗口内容、不存任何用户数据 | 红线 |

> 与 002 的差异：002 §2.4 把"config 键 vs 新表 0009"列为待决策；本轮**决策已下**（config 键），故此处为冻结结论。

### 2.5 恢复流程（顺序不可调换）

```
mode_exit(state)
  ① kill_registered —— 关掉「本模式自己拉起的」软件        ← 现有行为，不动（R-01）
  ② read_snapshot   —— 读 workspace.snapshot.last；缺失/损坏 → 走 L3
  ③ 逐窗口恢复（按 zIndex 升序：先铺底，后置顶）
       IsWindow 存活校验 → 失效则跳过并计 degraded（L1）
       坐标选择：rectPx 落在某显示器 work 内 → 用 rectPx；否则用 rectNorm 比例映射（L2）
       place(hwnd, rect, alwaysOnTop=false, maximized)
       步间 sleep 80ms                        ← 复用 apply.rs 的 STEP_DELAY，避免被系统丢弃
  ④ 状态复位（同上顺序）
       minimized:true  → SW_MINIMIZE
       maximized:true  → place 已内建"先还原后最大化"（window.rs:166-182）
       visible:false   → **不动**（不 ShowWindow，避免把用户关掉的窗口弹出来）
       foregroundHwnd 非 null → activate(foregroundHwnd)   ← 复用 window::activate
  ⑤ clear           —— 清除 workspace.snapshot.last（置 null）
  ⑥ publish         —— MODE_CHANGED 携带恢复结果（见 §2.7）
```

**三条红线**（写进契约，实施时不许变通）：
1. 恢复**只动快照登记过的 hwnd** —— 绝不按"同名软件"无差别操作（R-01 精神的自然延伸）。
2. 恢复过程**不杀进程** —— 杀进程只由 ① 的 `kill_registered` 负责，职责单一。
3. 恢复**不创建**新窗口/新进程 —— 快照只负责把"还在的"窗口摆回去。

### 2.6 降级链（L0–L4）

| 级别 | 场景 | 行为 | 判据 |
|---|---|---|---|
| **L0** | 全部有效 | 逐窗口 place + 状态复位 | — |
| **L1** | 部分 hwnd 失效（进程已退 / 窗口已关） | 跳过该窗口，计 `degraded:n`，UI 提示"N 个窗口已关闭，无法恢复" | 存活判据 v1 用 `windows_rect(hwnd)` 非 null（现有命令，`commands.rs:213-218`） |
| **L2** | 显示器拓扑变化 | `rectPx` 不在任何显示器 work 内 → 用 `rectNorm` 按当前 work 比例映射；仍超界则夹回工作区 | 复用 `apply.rs` 的 `degraded_monitor` 思路 + `layout.rs` 的像素换算 |
| **L3** | 快照缺失 / JSON 解析失败 / `schemaVersion` 不认 / 结构非法 | **不恢复**，仅退出模式 + 提示；**绝不猜、绝不清扫** | `config.get` 解析失败会落 `default_for(key)`（`config.rs:28-33`）→ 该键默认值取 `Null` → 自然走"无快照"路径，免费得到正确行为 |
| **L4** | 恢复超时（单窗口 15s / 总计 45s） | 中止，**保留已恢复部分**，计 `failed` | 与 pipeline 同口径；`apply.rs` 的重试是 2 次 × 500ms，单窗口上限远低于 15s |

### 2.7 恢复完成后的状态

| 对象 | 结束状态 |
|---|---|
| `workspace.snapshot.last` | `null`（L0/L1/L2 均清除；L3 也清除 —— 避免坏快照反复触发） |
| `RunRecord` | `current = None`、`launched[mode]` 清空、`previous` 保留（现有 `exit_mode` 行为，`pipeline.rs:367`） |
| `mode.current` | **不清**（承载"上次使用过的模式"，供一键恢复 V-10，`pipeline.rs:368-370`） |
| 事件 | 复用 `MODE_CHANGED`，payload 扩展恢复结果：`{ exited, closed, restore: { status: "ok"\|"partial"\|"skipped"\|"failed", restored, degraded, failed, tookMs } }` |
| 快照失败 | 不新增事件类型 —— 恢复是 `mode_exit` 的子步骤，其结果随 `MODE_CHANGED` 一并上报（避免事件面膨胀） |

> 事件名锚定实测：`MODE_CHANGED` / `WINDOW_LAYOUT_APPLIED` / `WINDOW_LAYOUT_FAILED` 均真实存在（`core/src/event_bus/events.rs:4-12`）。**不新增**恢复专用事件（避免契约面扩大）。

### 2.8 与现有资产的复用关系（避免重复造）

| 快照需要的能力 | 现有资产 | 复用方式 |
|---|---|---|
| 枚举可见主窗口 + 过滤壳窗口 | `modes_capture_current_inner`（`commands.rs:480-515`，含 `SHELL_PROCESSES` 黑名单 + 面积阈值） | 直接复用同一套过滤规则 |
| 窗口几何/状态读取 | `list_windows()` → `WindowInfo{hwnd,title,class_name,pid,visible,minimized,maximized,rect,area}`（`window.rs:26-37,115-125`） | 已有，无需扩展 |
| 像素 → 归一化 | `commands.rs:529-532` 的 clamp 归一化 | 直接复用 |
| 写位置 | `windows_place` / `window::place`（`window.rs:154-184`） | 已有 |
| 激活置前 | `window::activate`（`window.rs:190-216`，含 `AttachThreadInput` 绕前台锁） | 已有 |
| 显示器 work area | `work_area_of(index)` / `monitors_list`（`commands.rs:148-150`） | 已有 |

**结论**：这只缺"编排 + 落盘 + 按窗口恢复"三层，**不缺原子能力**（与 001/002 结论一致，本轮再次确认）。

### 2.9 已发现的实现偏差（登记在案，本轮不改）

| 偏差 | 位置 | 影响 |
|---|---|---|
| `windows_place` 的 `always_on_top` 参数**实际无效** | `window.rs:172-175`：`flags` 初值已含 `SWP_NOZORDER`，`if always_on_top { flags |= SWP_NOZORDER; }` 是重复置位（真置顶注释说"交给 activate 的 BringWindowToTop"） | 契约据此**不承诺**置顶恢复；参数保留但需在文档标注"当前为占位/无效" |
| `ai.active_profile` 是**写而不读**的投影 | 唯一写入在 `pipeline.rs:270`；全仓无从读取方 | 计入 §3 的第五处来源，降级为 suggestion 投影（见 §3.2） |
| `ai.default_provider` 是**活键**（非死键） | 三处消费者：`pluginHost.ts:117`、`agents.rs:352`、`settings.ts:23` | 改变了 Provider 收口设计（见 §3.1） |
| registry **无默认兜底** | `ai/service.py:94` `registry.get(req.provider)` 对未知 id（含 `""`）抛 `KeyError`；`registry.py:120-125` 亦然 | 002 §3.2 的"registry 默认（第一个 enabled）"**在代码中不存在**；插件/Agent 在 `ai.default_provider=""` 时 `ai.invoke` 必失败 → §8 缺口 C3 |

### 2.10 机器门禁（把"承诺"变成"判据"）

`tools/verify_contracts.py`（标准库，零依赖）对本轮 6 个 fixture 实测结果：

```
[反向] ai-provider-current.v1.invalid-secret.json        PASS  (拦截：secret-key:apiKey @ $.cache)
[正向] ai-provider-current.v1.valid.json                 PASS  (0 error)
[反向] workspace-snapshot.v1.invalid-norm-mismatch.json   PASS  (拦截：invariant:rectNorm-consistent @ $.desktop.windows[0])
[反向] workspace-snapshot.v1.invalid-v2-leak.json         PASS  (拦截：forbidden-v2-key:history @ $)
[反向] workspace-snapshot.v1.invalid-window-identity.json PASS  (拦截：required:exeName @ $.desktop.windows[0])
[正向] workspace-snapshot.v1.valid.json                   PASS  (0 error)
结果：6/6 符合预期
```

门禁覆盖的**跨字段不变量**（schema 表达不了的那部分）：
1. monitors 的 `index` 连续且唯一、**有且仅有一个** primary
2. 每个窗口的 `monitorIndex` 必须存在于 monitors
3. `rectNorm` 与 `rectPx` 必须一致（容差 0.02）—— 防止两套坐标各写各的
4. `foregroundHwnd` 要么 null，要么**必须在 windows 里**
5. hwnd 全局唯一
6. `managed[].hwnd` 必须是 `desktop.windows` 的子集
7. `workspace.monitor` 必须存在于 monitors
8. 全树禁止 10 个 v2 键名（v1 边界）
9. 全树禁止任何疑似明文密钥键（红线 V1）

---

## 3. AI Provider Contract v1（冻结）

### 3.1 事实来源实测（**五处**，比 002 多两处）

| # | 来源 | 位置 | 读/写 | 实测证据 |
|---|---|---|---|---|
| S1 | UI localStorage | `ui.ai.provider` / `ui.ai.model` | **读源**（UI 侧真相） | `stores/ai.ts:84-85,131-132` |
| S2 | core config 同名键副本 | `ui.ai.provider` / `ui.ai.model` | **只写不读**（注释明说"UI 的读源保持单一"） | `stores/ai.ts:108-125,199-200`；键已登记 `config.rs:96-97` |
| S3 | 模式 `aiProfile` | `work_modes.ai_profile` JSON `{provider, systemPromptKey, permissionScope}` | 进入模式时写 config | `pipeline.rs:270`（写 `ai.active_profile`）；`scheduler/repository.rs:28-40` |
| **S4** | **`ai.default_provider`** | config 键，默认 `""` | **被三处消费**：插件宿主 `ai.invoke`、外部 Agent `ai.invoke`、设置页 `defaultProvider` | `pluginHost.ts:117`、`agents.rs:352`、`settings.ts:23`；登记 `config.rs:77,140,198` |
| S5 | 请求级 `AiChatArgs.provider` | 必填字段 | 每次调用传入 | `core/src/ai/mod.rs:24-27,114`；UI 传值 `stores/ai.ts:308-309` |

**002 遗漏项纠正**：002 把 `ai.default_provider` 当作未提及的旧键。实测它是**无 UI 上下文调用者的活通道**（插件 / 外部 Agent / 设置页），必须纳入契约，否则收口后会打断插件与外部 Agent 的 `ai.invoke`。

### 3.2 canonical 冻结与五层结构

```
L0  能力真相（read-only，唯一的"有什么"）
    ai/providers/registry.py PROVIDERS（7 个：openai/deepseek/compatible/ollama/lmstudio + 2 占位）
        → core ai_info → UI 只读
    ★ 契约：canonical 不得指向 enabled=false 的 Provider（web-ai / user-agent）

L1  用户意图真相（canonical，唯一的"用什么"）  ← 决策 3
    core config：ai.provider.current / ai.model.current
    ★ 唯一写入口 = core config 写入（唯一事实来源）

L2  缓存（非真相）
    localStorage：ui.ai.provider / ui.ai.model
    ★ 职责：core 不可达时的 fallback 初值；**不得**作为写入目标之外的真相

L3  建议层（非真相）
    work_modes.ai_profile.provider（设计期意图）
    config ai.active_profile（运行期投影，当前写而不读）
    ★ 进入模式时作为"建议值"，需用户确认或显式策略才改 L1

L4  无 UI 调用者默认（非真相，独立回退层）
    config ai.default_provider
    ★ 消费者：pluginHost.ai.invoke / agents.ai.invoke / settings.defaultProvider

L5  传输参数（只传不决策）
    AiChatArgs.provider / model
    ★ 由 store 从 L1 注入；core 直通 sidecar，不做选择、不做兜底
```

### 3.3 解析优先级链（冻结）

```
请求显式传参（仅程序化调用；L5，caller 自负）
  > current（L1 用户意图，唯一 canonical）
  > 模式 aiProfile（L3 建议）
  > default_provider（L4 无 UI 调用者回退）
  > registry 第一个 enabled（L0 最后兜底 —— ⚠️ 当前**未实现**，见 §8 C3）
```

### 3.4 各层职责（允许 / 禁止）

| 层 | 负责 | **禁止** |
|---|---|---|
| L0 Registry | 有哪些 Provider/模型、凭据状态、能力元数据 | 不得知道"用户在用什么" |
| L1 **canonical** | 持久化 current；**校验请求 provider 合法**（不在 registry 或 enabled=false → 报错不发请求）；读模式 aiProfile | 不得决定 UI 展示形态 |
| L2 cache | 存 localStorage 供启动兜底 | **禁止**独立持久化真相（不得"以 localStorage 为准"） |
| L3 suggestion | 提供模式级建议值 | **禁止**直接改 L1 |
| L4 headless default | 为无 UI 调用者提供 provider | **禁止**影响 UI 会话的 canonical |
| L5 transport | 携带 `provider`/`model` 执行 | **禁止**做选择、禁止做 fallback 决策 |

**"任何页面不得自行持久化 provider/model"** —— 写 current 必须经过统一入口（`stores/ai.ts` 的 `setProvider`/`setModel` 改为写 L1）。

### 3.5 独立 AI Assistant 页 ↔ 右侧 AI Sidebar 共读边界（**只定义接口，不实现会话共享**）

现状：AI 状态在 `stores/ai.ts` 单例 store 中，`AiSidebar.vue` 是当前唯一宿主。UI-04 将新增独立 AI 页 —— 两个宿主必须读**同一个** canonical state。

```
【读接口】只读，两个宿主共用
  getAiCanonical(): { provider: string, model: string, apiBase: string }
  数据源：L1（config ai.provider.current / ai.model.current）
  变更传播：订阅 core 的 CONFIG_CHANGED（键前缀 ai.）→ 两个宿主即时同步
  ★ 契约：独立页与 Sidebar **不得各自维护一份 provider 真相**（这是本项冻结的核心）

【写接口】唯一写口
  setAiCanonical({ provider?, model? }): void
  行为：写 L1 → 广播 CONFIG_CHANGED → L2 缓存同步更新
  ★ 契约：任何宿主切 Provider，另一宿主**无需刷新页面**即看到新值

【缓存降级】
  core 不可达时：getAiCanonical() 返回 L2 缓存值 + `stale: true`；写入只落 L2 并记录待同步
  ★ 契约：降级期间两个宿主仍读同一份（L2），不得一个读 L1 一个读 L2

【会话层（本轮仅定义边界，不实现）】
  ConversationRef = { conversationId: string, owner: 'sidebar' | 'assistant-page' }
  规则 1（流式互斥）：同一时刻**至多一个** conversationId 持有流式写权；
                      stream 进行中，另一宿主发起 → 拒绝并提示（不是静默排队）
  规则 2（历史不共享）：两个宿主默认各自独立的消息历史
  规则 3（显式接管）：若将来需要共享，只允许通过显式"接管会话"动作，不得隐式同步
  ★ 本轮**不实现**上述三条 —— 只冻结接口边界，避免 UI-04 期间两边各写一套
```

### 3.6 迁移映射（现有代码 → 目标，供后续施工参照）

| 现有 | 目标 |
|---|---|
| `stores/ai.ts` 启动只读 localStorage（`ai.ts:131-132`） | 启动**先读 L1**，core 不可达才落 L2 |
| `persist()` 同时写 L2 + L1 副本（`ai.ts:119-125`） | 写 L1 为准，L2 只作下沉缓存（写序反转） |
| `loadProviders()` 用 L2 值（`ai.ts:193-202`） | 用 L1 值；失效时回退 registry 第一个 enabled |
| `pluginHost.ts:117` / `agents.rs:352` 读 `ai.default_provider` | **保持不变**（L4 是合法独立层），但需在 L4→L0 之间补兜底（§8 C3） |
| `pipeline.rs:270` 写 `ai.active_profile` | 保留为 L3 运行期投影；**要么**补上读取方，**要么**登记为待清理（当前无读取方） |

---

## 4. ExternalWindowResize Contract v1（冻结）

> 决策 1 已冻结口径：**外部软件窗口** Resize。主应用窗口 resize **不做**；布局编辑器槽位拖拽属前端交互，另行处理。

### 4.1 现状技术勘察

| 问题 | 实测结论 | 证据 |
|---|---|---|
| `windows_place` 接收什么 geometry | `windows_place(hwnd: i64, rect: **PxRect{x,y,w,h 全 i32 物理像素}**, always_on_top?: bool, maximized?: bool) -> PxRect` | `commands.rs:222-237` |
| 内部实现 | `place()`：若 `IsIconic`/`IsZoomed` 先 `SW_RESTORE` → `SetWindowPos(flags = SWP_NOZORDER\|SWP_NOACTIVATE\|SWP_SHOWWINDOW)` → 可选 `SW_MAXIMIZE` | `window.rs:154-184` |
| 是否已有最小/最大尺寸约束 | **没有**。`place` 是 `SetWindowPos` 直通，Core 侧不 clamp | `window.rs:172-178` |
| resize 后如何同步 geometry | 唯一回读手段是 `windows_rect(hwnd)`（`commands.rs:213-218`）；07 验收口径为 ±2px | `windows_rect` |
| Workspace Engine 是否有窗口状态模型 | **有，但不完整**：`SlotResult{app, appId, status, pid, reason, retriable}` —— 有 `pid`、**无 hwnd/rect** | `runner.rs:31-42` |
| 布局通道是否有窗口状态 | **有且更完整**：`ApplyOutcome.slots[].{app, status, hwnd, rect, reason}`（`SlotOutcome`） | `apply.rs:48-71` |
| 是否可复用现有窗口布局通道 | **可以**。`layoutService.place()` 已在 UI 侧包好 `windows_place`，只需扩展参数透传 | `ui/src/api/layoutService.ts:142-150` |

**结论**：**零 Core 新增命令**。Resize 完全走既有 `windows_place` 通道（UI 侧已有 `layoutService.place()` 封装）。

### 4.2 冻结的 Resize 契约

```
ExternalWindowResize Contract v1

【通道】复用 windows_place（不新增命令）
  UI → layoutService.place(hwnd, rect, opts) → invoke('windows_place', {hwnd, rect, alwaysOnTop, maximized})
  HTTP 备用：POST /api/v1/windows/{hwnd}   （已在 layoutService 内做双通道）

【坐标裁决】
  同显示器拓扑内：传**绝对像素 PxRect**
  跨/变拓扑：由调用方先把 rectNorm 按当前 work 折算为像素再传
  ★ Core 永远只吃像素 —— 归一化换算是调用方职责（与 apply.rs 的 layout_pixels 同一分工）

【最小/最大尺寸】
  ★ 契约不承诺最小尺寸。Core 不加 clamp（保持 SetWindowPos 语义单纯）
  ★ 若目标应用自身通过 WM_GETMINMAXINFO 拒绝，SetWindowPos 结果由系统决定 —— 契约视为
    "调用成功"，真实性由调用方 `windows_rect` 回读校验
  ★ UI 若要保证可读尺寸，由 UI 侧 clamp 后传入（与 AiSidebar 宽度 clamp 280~720 同一风格，ai.ts:262-266）

【几何同步（写后校验收敛）】
  写：place → 读：windows_rect → 比对
  容差：±2px（沿用 07 验收项 2 口径）
  不一致 → 重试（沿用 apply.rs 的 2 次 × 500ms）→ 仍不一致则上报失败，不静默

【步间节流】
  连续 resize 每步间隔 ≥80ms（复用 apply.rs 的 STEP_DELAY，window.rs 之后被系统丢弃的风险）

【maximized 语义】
  maximized:true → 内部先还原、摆位、再 SW_MAXIMIZE（顺序不可反，window.rs:166-182 已内建）
  ★ 契约：maximized 为 true 时 rect 仍必须给（作为还原态目标位置）

【alwaysOnTop】
  ★ 当前参数**实际无效**（window.rs:172-175 重复置位 SWP_NOZORDER）
  ★ 契约：v1 不承诺置顶；该参数保留但标注为"未生效占位"，实现时不得依赖它
```

### 4.3 与 UI-04 的接口边界

| UI-04 提出 | 我方响应 |
|---|---|
| "工作模式窗口 Resize" 交互设计 | **等 UI Skill 确认交互**（拖拽把手位置、实时预览 vs 松手生效、最小尺寸） |
| 需要的能力 | ✅ 已就绪：`windows_place` + `windows_rect` + `monitors_list` + `layoutService.place()` |
| Core 是否需要改动 | **否**（除非 UI 要求"实时连续 resize"且需要批量命令——当前为逐次 invoke，若拖拽产生高频调用需评估节流，属 UI 侧） |

---

## 5. UI-04 对接 Contract（八项逐项标记）

> 标记口径：`already supported` 已有能力可直接接 · `needs contract` 需先定数据契约 · `core gap` 缺底层能力 · `UI-only` 纯前端 · `waiting for UI Skill` 视觉未定

| # | UI-04 项 | 标记 | 依据 / 契约要点 |
|---|---|---|---|
| 1 | **Learning Goal**（学习目标入口） | `already supported` + `needs contract` | 15 个 `learning_*` 命令齐备（`commands.rs:697-866`）；**需定**：跳转定位约定 `?goal=<id>`（纯前端）；用 `learning_goal_get` 拉单目标 |
| 2 | **Device Navigation**（导航设备入口） | `already supported` + ⚠️ 红线 | `device_metrics/processes/mode_health` 齐备（`commands.rs:1180-1209`）；**红线 V5 不可弱化**：`device_process_kill` 必须保留"UI 弹窗 + `confirm:true`"双闸，新入口复用不得绕过 |
| 3 | **Independent AI**（独立助手页） | `needs contract` | 数据面完整（`ai_chat` + `AI_STREAM_CHUNK`/`AI_RESPONSE`）；**契约已冻结见 §3.5**（canonical 共读 / 流式互斥 / 历史不共享 / 显式接管）；`core gap` = 无 |
| 4 | **External Window Resize** | `already supported` + `waiting for UI Skill` | 通道完备（§4）；等 UI 确认交互；**Core 无缺口** |
| 5 | **Profile Extension**（档案扩展接口） | `needs contract` + `core gap`（小） | 22 个 `profile_*` 命令齐备；**缺口**：`profile_basic` 只有 `name/direction/interests/motto`（`0001_init.sql:88-95`），**无扩展列**。最小方案：config 键 `profile.ext.*`（零迁移）。**契约需定**：扩展字段的键值约定 + 展示形态 |
| 6 | **Life Plugin Area**（生活插件区域） | `needs contract` | `life_*` 命令齐备（`commands.rs:1112-1178`）；**需定**：life 区域容纳"插件卡片"用哪套机制（复用 dashboard widget 机制 vs life 专属 slot）—— 建议先定契约再动手 |
| 7 | **Homepage Responsive** | `UI-only` | widget 布局来自 config `ui.dashboard.*`（`config.rs:72-74`）；`core gap` = 无 |
| 8 | **Scroll Experience** | `UI-only` + ⚠️ 交叉红线 | 纯前端；⚠️ 与 S2 局部更新纪律交叉：滚动容器**不得**引入 remount（S2 验收项要求 scrollTop 不变；`overflow-anchor:none` 已有先例，见 TECH-01 Test1 的修复） |

**八项归总**：`already supported` 3 项（1/2/4）· `needs contract` 4 项（1/3/5/6）· `core gap` 1 项（5，小且可绕过）· `UI-only` 2 项（7/8）· 全部 8 项均含 `waiting for UI Skill` 的视觉面。

---

## 6. Motion 第一批消费点 Contract（只定义，不接线）

> 立场不变：**不因为"底座已建成"就全量改页面**。只接"有明确收益且不改视觉"的点位。
> 本轮约束：**不新增 Motion token / 不改 Skin / 不启用 View Transitions**。

| 优先级 | 业务动作 | Motion primitive | 契约要点 | 等 UI-04？ |
|:---:|---|---|---|:---:|
| 1 | **Workspace Cinema**（进入/退出工作模式） | `startCinema()` + `whenInteractive`(240ms Gate) + `notifyResize` | 订阅 `MODE_CHANGED` / `MODE_APPLY_PROGRESS`；timeline 锚点不变（80/160/240/560ms）；**Resize 触发 `notifyResize` → 取消空间动画 + 快收敛** | ✅ **等**（布局级动画依赖 UI-04 工作模式页定稿） |
| 2 | **Drag / Resize** | `claim('drag')`（Conflict Guard）+ `runInterruptible` | ① AiSidebar 宽度拖拽（`.ai-resizer` 已存在）：**不等**，改动面小、零视觉变化；② LayoutView 槽位拖拽 + 外部窗口 Resize：**等** UI Skill 确认交互 | 部分等 |
| 3 | **Page Transition** | `createPageTransitionHooks`（**已接线** `App.vue`） | 剩余工作**仅是文档 + 回归**：把 `:key="$route.path"` 的 remount 语义与 S2 边界写清；`?motion=novt` 回归 | ❌ 不等 |
| 4 | **Toast** | `claim('overlay')` + `runInterruptible` | **必须先统一浮层（§7）**，否则一次接线只覆盖 1/3 实现 | ✅ 等（视觉会变） |
| 5 | **Modal / Drawer** | `claim('overlay')` + `runInterruptible` | Modal 两套重复实现且**均无 enter/leave**；Drawer **真缺失**（不造） | ✅ 等 |
| 6 | 其他局部状态（loading / empty / 列表项进出） | 只用 token（`--mt-dur-quick` / `--mt-stagger`），**不引入新 primitive** | — | ✅ 等 |

---

## 7. Toast / 浮层统一 Contract（冻结）

### 7.1 现状（实测）

| 实现 | 位置 | 计时 | 动画 |
|---|---|---|---|
| ModeView toast | `ModeView.vue`（`notify()` / `.mv-toast`） | 4000ms | 无（v-if 直切） |
| SoftwareView toast | `SoftwareView.vue`（同款 `notify()`，逻辑逐字复制） | 4000ms | 无 |
| SettingsView saved-toast | `SettingsView.vue` + `base.css` | 无 | 无 |
| degraded-banner | `base.css` | 常驻 | 无 |
| Modal ×2 | ModeView `mv-modal*` / SoftwareView `apps-modal*`（类名交叉复用 → 复制痕迹） | — | **无 enter/leave** |
| Drawer | **不存在** | — | — |
| ContextMenu | **不存在** | — | — |

### 7.2 冻结契约

```
【canonical Toast = 现有 ModeView / SoftwareView 行为】
  理由：已是主流用法（2/3 处）、逻辑最完整、行为已被用户感知
  默认：4000ms 自动消失；单条文本

  语义入口（宿主无关）
    notify({ level: 'info'|'success'|'warn'|'error', text, sticky?, dedupeKey?, action? })
  宿主
    PwfToastHost —— 单例，挂 App 根部，**全局只此一个**
  队列
    同 dedupeKey 覆盖；不同 key 最多堆叠 N 条（N 由 UI-04 定，契约留空）
  优先级
    注册 Conflict Guard 'overlay'

【迁移映射】
  ModeView.notify / SoftwareView.notify  → 语义入口（行为不变，纯替换）
  SettingsView.saved-toast               → level:'success' 短 toast
  degraded-banner                        → **不并入**（常驻系统状态，语义不属于瞬时反馈），
                                           独立为 PwfBanner

【Modal】
  语义入口：宿主 open/close + 内容 slot；业务只发"打开什么"的语义
  统一行为：mask click 关闭（现状两处均为 @click.self）/ Esc 关闭 / focus 陷阱
  优先级：Conflict Guard 'overlay'
  ★ 形态由组件决定 —— 这是未来 Skin 能换组件形态的前提

【Drawer / ContextMenu】
  本轮**不实现**。待 UI-04 明确需求后按同一 overlay 优先级纳入同一 Host
```

---

## 8. Core 缺口清单

| # | 缺口 | 性质 | 说明 / 处置 |
|---|---|---|---|
| C1 | 快照「采集 → 落盘 → 恢复」编排 | **真缺口**（设计已冻结 §2） | 窗口原子能力齐备（§2.8），缺编排层 |
| C2 | 三个新 config 键未登记 | **施工前提**（不是缺口） | `workspace.snapshot.last` / `ai.provider.current` / `ai.model.current` 必须三处齐登（`KEYS`+`expected_type`+`default_for`），否则 `config.set` 直接 bail（`config.rs:41-43`） |
| C3 | registry 最后兜底**未实现** | **真缺口（小）** | `registry.get("")` / 未知 id 抛 `KeyError`（`ai/service.py:94`、`registry.py:120-125`）；导致 `ai.default_provider=""` 时插件与外部 Agent 的 `ai.invoke` **必失败**。修复：在 L4→L0 之间补"取第一个 enabled" |
| C4 | `profile_basic` 无扩展列 | **小缺口（可绕过）** | `0001_init.sql:88-95`；最小方案 config 键 `profile.ext.*`，零迁移 |
| C5 | `ai.active_profile` 写而不读 | **待清理项** | 唯一写入 `pipeline.rs:270`，无读取方；登记为 L3 投影或后续清理 |
| C6 | `windows_place` 的 `alwaysOnTop` 无效 | **偏差登记** | `window.rs:172-175`；不阻塞任何冻结项 |
| — | 主应用窗口 resize / position 命令 | **不列为缺口** | 决策 1 已冻结口径为"外部软件窗口"，主应用 resize **不做** |
| — | 精确 Z 序 / 跨重启 hwnd 重认领 | **能力边界（v2）** | 非缺口，属 §2.1 声明的 v1 不承诺项 |
| — | "完成工作" | **产品设计项 PD-001** | 按指令不列为缺口、不发明按钮 |

---

## 9. 等待 UI Skill 的事项

### 9.1 视觉实现冻结范围（UI-04 期间我方不碰）

| 文件 / 页面 | 冻结原因 |
|---|---|
| `LearningView.vue` | 学习目标入口 |
| `NavSide.vue` | 导航设备入口 |
| 新增独立 AI 助手页 | 新页面 |
| `ModeView.vue` / `ModeBar.vue` | 工作模式窗口 Resize + Cinema 定稿依赖 |
| `ProfileView.vue` | 档案扩展接口 |
| `LifeView.vue` | 生活插件区域 |
| `DashboardView.vue` + `widgets/*` | 首页响应式 |
| 所有 view 的滚动容器样式 | 页面滚动体验 |

### 9.2 可并行安全区（我方现在就能动，零视觉冲突）

- `core/`：三个 config 键登记；快照采集函数骨架（不接线、不落盘）；AI current 读写投影
- `tools/`：契约门禁纳入回归编排；三件套回归（`verify_tech01` 9/9 · `verify_skin_engine` 12/12 · `perf_tech01_22` 14 窗口 0 Long Task）
- `docs/`：S2 边界与 remount 语义文档
- `ui/src/motion/`：引擎内部增强（不动消费方）

### 9.3 交接口径

UI-04 交付后我方做 **"接线 not 重画"**：只加 Motion token 与契约调用，不改视觉实现。若发现必须改视觉，先提方案等确认。

---

## 10. 建议下一阶段施工顺序

### 10.1 依赖关系

```
契约冻结（本轮） ─┬─→ config 键登记 ──→ 快照落盘 ──→ 恢复降级链（IP5）
                  ├─→ canonical 读写投影 ──→ UI store 收口（IP2）
                  ├─→ 统一浮层（IP1）──→ Toast/Modal 接 overlay Motion
                  └─→ UI-04 定稿 ──→ Cinema 接线（IP3）
```

### 10.2 排期

**A. UI-04 进行期间（只做安全区，零视觉冲突）**
1. `core`：三个 config 键三处齐登（**最小前置，不到 20 行**，且解锁后续全部写入）
2. `core`：AI current 读写投影（新增 get/set，零 UI 改动）+ L4→L0 兜底（补 C3）
3. `core`：快照采集函数骨架（不接线、不落盘，仅让 `verify_contracts` 的 fixture 有真实数据源可对）
4. `tools`：契约门禁纳入回归编排（`verify_contracts` + 三件套）
5. `docs`：S2 边界与 remount 语义文档

**B. UI-04 交付后（按序）**

| 阶段 | 目标 | 涉及 | DB | UI | Core | Motion | Skin | 验收标准 | 风险 |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|---|---|
| **IP1** | 浮层统一（Toast/Modal 组件 + overlay Motion） | `ui/src/components/` · 3 处迁移 | ✗ | ✔ | ✗ | ✔ | ✗ | 三套 toast 收敛为 1；行为等价（4000ms）；degraded-banner 不动 | 3 处行为差异需逐一比对（低） |
| **IP2** | AI Provider 收口（canonical 落地 + service 层） | `stores/ai.ts` · `core/db/config.rs` | ✗ | ✔ | ✔ | ✗ | ✗ | 启动读 core；切 Provider 两宿主即时同步；L2 仅缓存 | 读源反转可能影响启动时序（中） |
| **IP3** | Motion 业务消费（Cinema 接真实链路 → Drag/Resize → 局部 token 化） | `App.vue` · `ModeView` · `AiSidebar` | ✗ | ✔ | ✗ | ✔ | ✗ | Cinema 复用 240ms Gate；`?motion=novt` 回归通过；局部更新不 remount（S2） | 布局级动画依赖 UI 定稿（中） |
| **IP4** | Skin 产品入口（Settings 选择器 + config 持久化） | `SettingsView.vue` · `motion/skin.ts` | ✗ | ✔ | ✗ | ✗ | ✔ | 切 skin 不触发 render/scene（12/12 回归保持） | Settings 视觉冻结中（低） |
| **IP5** | Workspace 退出恢复（快照落盘 + 恢复降级链） | `core/scheduler/` · `core/db/config.rs` | ⚠️ **仅 config 键，无 migration** | ✔ | ✔ | ✗ | ✗ | v1 schema fixture 全过；L0-L4 逐级可复现；恢复只碰登记 hwnd | 涉及真实窗口操作（**高**，需真实桌面验收） |
| **IP6** | core 双通道同源试点（严格限 3 模块） | `core/src/api/` | ✗ | ✗ | ✔ | ✗ | ✗ | 试点模块 command 与 HTTP 行为逐字段一致 | 最大重构风险点（**高**，须严格限范围） |
| **IP7** | 安全加固（插件桥 origin 校验 + sidecar 契约校验） | `ui/src/plugin/` · `core/src/plugins/` | ✗ | ✔ | ✔ | ✗ | ✗ | 恶意 origin 被拒；非法 payload 被拒 | 可能影响现有示例插件（中） |
| **IP8** | "完成工作" | — | — | — | — | — | — | **只设计，不编码**（PD-001） | — |

> **每阶段前后各跑一轮现成回归防线**：`verify_tech01.py`（9/9）· `verify_skin_engine.py`（12/12）· `perf_tech01_22.py`（14 窗口 / 0 Long Task）· `verify_contracts.py`（6/6）。

### 10.3 需要产品侧裁决的事项

| # | 事项 | 影响 |
|---|---|---|
| 1 | Toast 堆叠上限 N（§7.2 留空） | UI 视觉，等 UI-04 |
| 2 | 崩溃后残留快照的处置：下次启动**自动恢复** / 仅提示 / 静默丢弃？（§2.1 已定"不自动应用"，但"提示"是 UI 项） | 产品口径 |
| 3 | `ai.active_profile` 补读取方还是登记清理（§8 C5） | 施工范围 |

---

## 附录 · 停止条件核对

| 禁止项 | 状态 |
|---|:---:|
| 业务重构 | ✅ 未做（0 个业务文件改动） |
| DB migration | ✅ 未做（无 migration 文件新增） |
| Provider 重构 | ✅ 未做 |
| Motion 接线 | ✅ 未做（仅契约表） |
| Skin 实现 | ✅ 未做 |
| Toast 重构 | ✅ 未做（仅契约） |
| Workspace Resize 实现 | ✅ 未做（仅勘察 + 契约） |
| Workspace Snapshot 实现 | ✅ 未做（仅 schema/fixture/文档） |
| View Transition | ✅ 未启用 |
| "完成工作"实现 | ✅ 未做（PD-001 保持登记） |

**本轮新增文件**：1 份报告 + 1 份 schema + 6 个 fixture + 1 个静态验证工具。**无一行业务代码改动。**

---

*契约已冻结，等待产品侧确认 UI-04 后进入 IP1。*
