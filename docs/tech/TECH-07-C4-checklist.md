# TECH-07-C4 Checklist —— Workspace Snapshot Persistence / Restore

> 日期：2026-09-16 · 阶段状态：**实现已完成并通过验收（25/25 + 1 Deferred）**
> 验收证据：`tools/verify_tech07c4.py` → **25/25 通过，另有 1 项 Deferred（E：真实环境不可构造）**
> 回归基线：C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 · 契约套件全绿 · `cargo test config` 6/6
> 实现报告：`docs/tech/TECH-07-C4-report.md`
> 本文件是 C4 的判据台账：每项给出**目标 / 判据 / 代码现状 / 决策 / 状态**。

---

## 零、阅读结论（决定 C4 形状的四条代码事实）

1. **Snapshot v1 已经定稿在 TECH-02 冻结域**：`ui/src/workspace/snapshot.ts`
   （`capture()` / `restore()` / `validate()` / `WindowProbe` 注入点 / `guardrails`），
   配套 `docs/contracts/workspace-snapshot.v1.schema.json` + `tools/verify_contracts.py`。
   → **C4 不重新设计 schema**，只做「真实探针接线 + 持久化 + 受限执行」。
2. **`workspace.snapshot.last` 尚未登记**在 core `db/config.rs::KEYS` → 现在写入会被
   `ConfigService::set` 拒绝（`未登记的配置键`），且有两个测试锁死「KEYS / expected_type /
   default_for 三处必须齐登记」。→ **C4-03 需要一次最小 core 改动**（登记一个键，非重构、非新表、非迁移）。
3. **`WindowInfo` 无 exe 路径**（`core/src/window_manager/window.rs`：hwnd/title/class_name/pid/
   visible/minimized/maximized/rect/area）。→ v2 身份的 `exePath` **不能**从窗口事实拿，
   只能从登记证据链拿：`slots(pid→appId)` ∪ `apps_running(appId→pid)` → `apps_list.AppItem.path`。
   → 无登记证据的窗口**没有 exePath**，按 §6 不进 managed，也不伪造 exeName。
4. **core 无 corePid / runId / 版本出口**（`/health` 仅 `{"service":"pw-core"}`；
   `std::process::id()` 只在 `modes_capture_current` 内部用）。而 `validate()` **强制要求**
   `source.appVersion / source.corePid(≥1) / source.runId(非空)`。
   → 需要一个极小的 core 事实出口（候选：扩展 `/health` 加 `pid` + `started_at`；见 C4-01 决策 D-2）。

---

## 一、Checklist（C4-01 … C4-18）

### C4-01 Snapshot schema

- **目标**：冻结 Snapshot v1 结构，不重新设计。
- **判据**：产出的文档必须同时通过 `workspace-snapshot.v1.schema.json`、
  `ui/src/workspace/snapshot.ts::validate()`、`tools/verify_contracts.py::snapshot_invariants`。
- **现状**：v1 已存在（冻结域）。指令里的简化结构与 v1 的字段映射：

| 指令结构 | v1 实际字段 |
|---|---|
| `version` | `schemaVersion: 1`（const） |
| `createdAt` | `takenAt`（int ≥1） |
| `desktop.windows[]` | `desktop.windows[]`（≤200，hwnd 唯一） |
| `workspace.managed[]` | `workspace.managed[]`（`{appId, appName, pid, hwnd}`，hwnd 必须是 windows 子集） |
| `rect{left,top,width,height}` | `rectPx{x,y,w,h}`（整数，w/h ≥1）+ `rectNorm{x,y,w,h}`（0~1，需与 rectPx/work 一致） |
| `state` | `state{visible, minimized, maximized}`（三布尔） |
| `zOrder` | `zIndex`（int ≥1，越大越靠前） |
| — | 另有 `snapshotId`（`ws-YYYYMMDD-HHMMSS-xxxx`）、`trigger`（v1 仅 `enter_mode`）、`source`、`monitors[]` |

- **决策**
  - **D-1**：沿用冻结 v1，不新增/不改字段（改字段 = 动 TECH-02 冻结域 + 契约，禁止）。
  - **D-2（需最小 core 改动）**：`source` 三字段必须来自 core 真实事实。候选方案
    ① 扩展 `/health` 返回 `pid` + `started_at`（+ 可选 `version`），UI 组装
    `runId = "{pid}@{started_at}"`；② 新增一个只读命令。优先 ①（无新命令、无新表、无迁移）。
  - **D-3**：`trigger` 只有 `enter_mode` 合法；C4 的「保存当前状态」若要做，必须映射为
    `enter_mode`（否则 `validate()` 直接拒）。→ 需在 UI 语义上明确「保存」= 以当前模式口径采集。
- **最终决策**：D-1 沿用冻结 v1（hash `604fe010e0d3f980` 冻结，C4 零改动）；
  D-2 采用方案 ① —— `/health` 与 `ping` 返回 `{"service","pid","started_at"}`（C4-D1）。
- **状态**：**DONE**（S3 冻结域 hash 一致 + A 段 `workspace-snapshot.v1.schema.json` 契约校验 0 错误 + R 契约套件全绿）

### C4-02 Snapshot serialization

- **目标**：capture → serialize → validate → 写入。
- **判据**：序列化后字符串 `JSON.parse` + `validate().ok === true` 才允许进入写入；
  解析失败/`validate` 失败 → **不覆盖已有快照**。
- **现状**：core config 里已有「string 存 JSON」的同构先例（`ai.models.registry`、
  `widget.desktop.config`），默认值用 `""` 表示「从未写过」。
- **最终决策（与初版不同，理由见下）**：值类型登记为 **`object`**（不是 string），默认 `{}`。
  理由：① core `ConfigService::set` 按登记类型校验，而 `expected_type` 无 `"string 里装 JSON"`
  这种类型，登记成 string 会让"JSON 文本"与"普通字符串"无法区分；② 默认 `""` 与
  「未登记键必须有显式非 null 默认值」的测试不冲突，但 `{}`（空对象）语义更准
  （= 从未写过），且 `readSnapshot()` 可以靠 `Object.keys().length === 0` 判"无"。
- **状态**：**DONE**（S2/S4：capture 先 `validate()` 通过再 `putCore`；F 段：损坏值不被改写）

### C4-03 Core config persistence

- **目标**：第一版只用 `workspace.snapshot.last`，**不建新表 / 不新增迁移**。
- **判据**：`configService.put('workspace.snapshot.last', json)` 在 **Tauri 路径**成功
  （core 侧登记 + 类型校验通过），且 `get` 能读回同值。
- **现状**：键**未登记** → 现在 put 必失败；core `ConfigService::set` 三处登记要求
  （`KEYS` / `expected_type` / `default_for`）有两个测试锁死。
- **实际落地（3 处登记，≤15 行 Rust）**：
  1. `KEYS` += `"workspace.snapshot.last"`；
  2. `expected_type` => `"object"`；
  3. `default_for` => `serde_json::json!({})`。
  写入方是 **UI adapter**（C4-D2）经**严格** `putCore/getCore`（失败直接抛，**无 localStorage 降级**）。
- **状态**：**DONE**（S7a 三处登记齐备；`cargo test config` 6/6，含两个"三处必须齐登记"的锁死测试）

### C4-04 Restart persistence proof

- **目标**：证明快照跨 core 进程存活（不是 UI 内存、不是 localStorage）。
- **判据**：进程 A 写入 → **杀掉 A** → 进程 B 以**同一数据目录**启动 → 经 **B 的 HTTP/invoke**
  读到同 `snapshotId`；且该值在 `workspace.db` 的 `config` 表里有行（实证）。
- **现状**：C3 审计踩过的坑可直接复用：① `wait_core_port` 会读到旧库里残留的旧端口，
  重启场景必须等**新端口**（值变化 + /health）；② 同源码理代理要指向新端口。
- **状态**：**DONE**（B 段实证：SQLite `config` 表有行 → 杀 core → 新进程新端口读回同
  `snapshotId` `ws-20260916-174115-4612`，且新进程 `/health` 的 `pid@started_at` 与快照里的
  `runId` 不同 —— 证明"跨进程存活"而非 UI 内存/localStorage）

### C4-05 Snapshot capture

- **目标**：只记录「已确认存在 + 属于当前 Workspace」的窗口。
- **判据**（全部要机器可判）：
  1. `managed[]` 的每个 pid ∈ C3 已验证的归属证据集（slots pid ∪ `apps_running`）；
  2. 无证据的窗口**不进** `desktop.windows`（因为没有 exePath/exeName，写进去就是编造）；
  3. 代码零 `title` 匹配 / 零位置匹配 / 零前台窗口猜测（静态扫描 + 人工复核）；
  4. `probe.wired === true` 才产出快照（未接线 → `dryRun`，不产出占位快照）。
- **现状**：`WindowProbe` 接口已定（`source/monitors/windows/foregroundHwnd/workspace`），
  缺真实实现；`monitors` 可由 `monitors_list` 直接填；`state` 三布尔由 `WindowInfo` 直接填。
- **决策**
  - **D-4**：`foregroundHwnd` 恒为 `null`（C3 边界禁 `windows_activate`，且无前台查询命令；
    `null` 是诚实值，schema 允许）。
  - **D-5**：`zIndex` = `windows_list` 返回序 `index + 1`（契约本身即定义为「枚举序的近似 Z 序」），
    在报告与代码注释里明确它是**近似值**，不作为权威排序。
  - **D-6**：`exeName`/`exePath` 由 `AppItem.path` 派生（登记证据），拿不到就不采集该窗口。
- **状态**：**DONE**（A 段：真实受管窗口 → `managed=1`，`exePath=C:\Windows\System32\charmap.exe`
  来自登记链而非猜测；S4：capture 只取新鲜 `takeFacts()`，代码零 `lastSnapshot`）

### C4-06 Snapshot validation

- **目标**：写入前 + 恢复前都验证；失败即拒绝。
- **判据**：`validate()` 覆盖 `version / windows 数组 / rect 数值 / w>0 / h>0 / pid / hwnd 类型 /
  state 合法性`，外加 `NaN / Infinity / 负值 / 结构错误 / 未知版本 / 损坏 JSON` 的拒绝用例。
  每个用例必须落到「拒绝 + 保留原快照」而不是「猜一个值继续」。
- **现状**：`validate()` 已实现（冻结域），含 v2 越界字段黑名单、明文密钥扫描、跨字段不变量
  （rectNorm 一致性、hwnd 唯一、managed ⊆ windows、恰 1 个 primary monitor）。
- **决策**：C4 只补**执行侧的数值护栏**（`Number.isFinite` 等前置校验，防止 `Infinity` 走到底层），
  语义校验仍以冻结 `validate()` 为准（不复制一份第二实现）。
- **状态**：**DONE**（capture 侧：`validate()` 不过 → 不写、不覆盖；restore 侧：`invalid` →
  零摆位。F 段实证损坏快照被拒且**原值未被改写/删除**，D/G 段实证零摆位）

### C4-07 Window identity

- **目标**：v1 = `hwnd + pid`（当期实例）；v2 = `exePath`（跨重启候选）；`hwnd` 视为 volatile。
- **判据**：
  1. `runId` 变化 ⇒ 所有旧 hwnd 一律失效（不得按旧 hwnd 控制任何窗口）；
  2. 跨重启匹配只允许在「当前已归属的窗口」范围内按 exePath 找候选；
  3. 同 exe 多实例 ⇒ 无法唯一确定 ⇒ `skip(ambiguous)`（禁止挑第一个 / 挑最大 / 挑前台）。
- **现状**：冻结 `restore()` 在 `runId` 不匹配时已经把所有步降级为 `skip`
  （`mode: 'stale-hwnd'`）—— 与 §5 语义一致，可复用作 Layer 1 的判定。
- **决策**：**D-7** Layer 2（exePath 匹配）必须写在**冻结域之外**（`workspace/runtime/`），
  因为冻结 `restore()` 只认 same-run；不得修改冻结模块。
- **状态**：**DONE**（Layer 2 实现在 `workspace/runtime/snapshot.ts`，冻结域 hash 未变；
  C1 段同运行期走 hwnd+pid，C2 段跨重启走 exePath —— chip 如实显示匹配层）

### C4-08 Restore matching

- **目标**：两层匹配，且不越权。
- **判据**：
  - Layer 1（同 runId）：`hwnd + pid` 命中当前 facts 的窗口，且该窗口 `belongsToMode && manageable`；
  - Layer 2（跨重启）：候选集 = **当前已归属窗口**；按 exePath 匹配；候选数 ≠ 1 ⇒ `skip`；
  - 绝不全系统枚举「同 exe 窗口」；
  - `focus-window` 步骤一律 `skip`（C3 boundary 把 `windows_activate` 列入 FORBIDDEN）。
- **决策**：**D-8** 冻结 `restore()` 产出的 plan 只当**意图**（其 `executable` 恒 `false` 是冻结语义），
  C4 的执行器在 `workspace/runtime/` 内**重新校验每一步**（归属 / runId / 拓扑 / offline）后才允许下发。
- **状态**：**DONE**（执行前对每个 target 再查一次实时 facts（存在 + 归属 + pid 未变）；
  `focus-window` 一律 skip；C2 段附加断言：**未归属**的同标题同 exe 窗口零摆位）

### C4-09 Restore geometry

- **目标**：复用 C3 已验证的 `windows_place`，不新增 placement API。
- **判据**：恢复动作必须经 `workspaceAdapter.actions.placeWindow` → core `windows_place`；
  禁止直接改 RunView DOM 假装恢复；成功后用 `windows_list` 的真实 rect 对齐 UI（facts 回流）。
- **现状**：`layoutApi.place(hwnd, rect, maximized)` 已支持 `maximized` 形参。
- **决策**
  - **D-9**：`state.maximized === true` ⇒ 以 `maximized` 形参下发（走既有能力，不新 API）；
  - **D-10**：`state.minimized === true` ⇒ `skip(state_unsupported)`（v1 不通过摆位改变最小化态；
    core `place()` 会自动 restore，但 C4 不主动做语义外的状态纠正）。
- **状态**：**DONE**（恢复统一走 `workspaceAdapter.actions.placeWindow` → core `windows_place`，
  无新 placement API；最小化窗口按 D-10 skip；成功后由 facts 回流对齐真实 rect ——
  C1/C2 的"实际 rect"都来自 `windows_list` 而非本地几何）

### C4-10 Restore failure handling

- **目标**：单窗失败不炸整体；每个 skip 有明确原因。
- **判据**：结果结构必须能表达 `restored[]` 与 `skipped[]`，skip reason 至少覆盖
  `missing` / `invalid` / `ambiguous` / `unowned` / `offline` / `placement_failed`
  （C4 另加 `activate_not_allowed` / `state_unsupported` / `no_exe_path` / `timeout`）；
  用例：A 成功 + B/C/D 各类失败 ⇒ 返回 A 成功且 B/C/D 各有原因，整体 `ok`（非 failed）。
- **最终 reason 集合**：`missing` / `invalid` / `ambiguous` / `unowned` / `offline` /
  `placement_failed` / `timeout` / `skipped`（`skipped` 承载 C4-10 的
  `activate_not_allowed` / `state_unsupported` / `no_exe_path` 三类语义，保留原词以便对照）。
- **状态**：**DONE**（D 段 `missing`、F 段 `invalid`、G 段 `offline` 均实证零摆位；
  chip 文案如实列出 skip 原因，不压成一句"恢复失败"）

### C4-11 Offline fail-closed

- **目标**：严格继承 C3。
- **判据**：core offline ⇒ restore **零** actuation（`placeWindow` 一次都不调用），
  结果明确 `offline`；不得以 `lastSnapshot` / `lastFacts` / 旧 projection 继续控制窗口。
- **现状**：C3 已在 `placeWindow` 内实现「无快照 / offline → 不下发」；facts 侧 offline 即作废缓存。
- **判据补充**：restore 必须取**当次新鲜 facts**（`snapshot()` 结果）的 connectivity 作为依据，
  不复用任何缓存快照。
- **状态**：**DONE**（restore 首步即 `takeFacts()`，offline ⇒ 立刻 `fail-closed` 返回；
  G 段实证：core 被杀 → chip `已恢复 0 个窗口（未执行） · 跳过 1：offline`，零摆位）

### C4-12 Topology handling

- **目标**：拓扑变化后不出现明显错误；不做智能布局。
- **判据**：
  - 当前工作区存在 ⇒ 正常恢复；
  - 快照 rect 落在当前不可用区域 ⇒ 做**最小安全修正**（clamp 进当前主显示器工作区）；
  - 修正后必须仍在工作区内且 `w/h ≥ 最小值`，**不允许**恢复到完全不可见位置；
  - 多显示器：**仅主显示器基准**（与 C3 一致），不做跨屏重构。
- **现状**：C3 的 `placeWindow` 已 clamp 归一化坐标到 `[0,1]`×工作区；C4 处理的是**物理 rectPx**
  的 clamp（历史坐标 vs 当前工作区）。
- **状态**：**DONE —— 且真实验收抓到一个实现缺陷并已修**：初版 `safeRect()` 的上界是
  `wa.x + wa.w - MIN_VISIBLE`，只保证"露出一角"（H 段实测跨界 rect `x=2440,w=572` 原样落到
  `x=2440`，工作区右边界 2560 → 只有 120px 可见）。已改为**完整可见**口径：
  装得下 ⇒ `x ∈ [wa.x, wa.x + wa.w - w]`（H 段实测修正到 `x=1988`，整窗在界内）；
  装不下（工作区比窗口还小）⇒ 退化为"至少 MIN_VISIBLE 像素可见"。
  只动位置、不改尺寸 —— 保持"最小修正"。

### C4-13 Corrupted snapshot handling

- **目标**：损坏即拒绝，保留原快照。
- **判据**：覆盖 `空串 / 非法 JSON / 未知 schemaVersion / 缺字段 / 负宽高 / NaN / Infinity /
  windows 非数组 / managed ⊄ windows` ⇒ 一律「拒绝 + 保留原有有效快照 + 返回原因」，
  **不得**部分修复或按可用字段猜着恢复。
- **状态**：**DONE**（F 段实证：`desktop` 改成字符串 → `invalid` + 零摆位 + **损坏值原样保留**
  （恢复流程不改写、不删除）；空值/缺字段同样落到 `invalid`，与冻结 `validate()` 同一判据）

### C4-14 Timeout handling

- **目标**：restore 必须有限结束，禁止无限等待与后台常驻 watcher。
- **判据**：整体 timeout（建议 ≤ 10s）+ 单窗口等待上限；超时窗口 → `skip(timeout)`；
  代码中零 `while(true)` / 零永久定时器；静态扫描 + 运行时用例（核心超时后仍返回结果）。
- **状态**：**DONE**（`restoreSnapshot({timeoutMs})` 默认 10s，逐窗检查 `deadline`，超时 →
  `skip(timeout)` 后继续/返回；代码零 `while(true)`、零常驻 watcher —— 快照读写都是一次性调用）

### C4-15 UI projection

- **目标**：最小状态投影，不是 UI redesign。
- **判据**：只允许在既有 RunView 状态栏（`.run-status`）加最小元素：
  「保存当前状态 / 恢复上次状态」两个 `pw-btn`（既有原语）+ 一个结果 `pw-chip`；
  新增 `data-pw` 便于验收；**零新 Token / 零新动画 / 零新布局**；
  结果文案必须映射 C4-10 的原因集合（如实展示 skip 原因，不只说"失败"）。
- **状态**：**DONE**（RunView 状态栏加 `run-snap-chip` + `run-snap-save` / `run-snap-restore`
  两个既有 `pw-btn`；S6a 静态：零新 token / 零动画 / 零硬编码色 / 无新样式文件；
  文案含匹配层与 skip 原因，例如 `快照：已恢复 0 个窗口（同运行期） · 跳过 1：missing`）

### C4-16 Real external-window validation

- **目标**：真实 core + 真实外部窗口 + 真重启。
- **判据（D 段，非 mock）**：
  1. 真实 core + mode_apply 拉起真实软件（charmap）→ 捕获 → **core 重启后仍能读回**同 snapshotId；
  2. 同 runId 恢复：移动真实窗口后 capture → 再次 restore → 真实 rect 被还原（before≠after 且回到快照值）；
  3. 跨重启（新 runId）恢复：exePath 唯一候选 ⇒ 真实 rect 被还原；多实例或无法归属 ⇒ `skip` 且**窗口未被移动**；
  4. 损坏快照 ⇒ 拒绝 + 原快照仍在 + 零 actuation；
  5. offline ⇒ 零 actuation + 明确 offline 结果；
  6. 拓扑修正：工作区变化后恢复的坐标仍可见（在有效工作区内）。
- **状态**：**DONE（8/9 绿 + 1 Deferred）** —— 见报告"真实证据"一节：
  A / B / C1 / C2 / D / F / G / H 全绿；**E（Ambiguous）真实环境不可构造 → Deferred**，
  结构性证据：① `apps.path` 是 UNIQUE（一 appId 一 exePath）；② 归属 pid = `slots` ∪
  `apps_running`，两者都是一 app 一 pid，手工多开的第二个实例拿不到归属证据
  （实测 `apps_running` 仍为 `{'1': 14568}`，UI 受管窗口数 = 1）。该分支保留为防御性代码。

### C4-17 Regression

- **目标**：不破坏既有基线。
- **判据**：`verify_tech07c3.py 27/27`、`verify_tech07c2.py 25/25`、`verify_tech07c.py 16/16`、
  `verify_tech02_workspace.py 11/11`、`verify_contracts.py`（契约套件）全绿 + 新增 C4 套件全绿。
- **状态**：**DONE**（C4 套件 R 段逐条跑：C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 ·
  契约套件 exit 0；core 侧 `cargo test config` 6/6）
- **踩坑记录（重要）**：C2/C3 验收要求 `ui/dist` 是 **`VITE_CORE_BASE=''` 的同源验证构建**。
  C4 中途用普通 `npm run build` 重建过一次 dist，导致 C2 的 D2「真实窗口 → adapter → RunView
  显示」红灯（UI 去连默认 7520 端口，跨源被拦）。**以后重建 dist 必须带同源环境变量**。

### C4-18 Visual freeze

- **目标**：视觉零变化。
- **判据**：Token +0（四 CSS hash 冻结一致）、Animation +0（静态扫描）、RunView 布局零改动、
  DOM identity 保持、无硬编码色值、无 styles 目录新文件。
- **状态**：**DONE**（四 CSS hash 与 C1/C2/C3 基线完全一致：`tokens.css f329f50bddd31d59` ·
  `motion-tokens.css e5e44af4aa807d38` · `primitives.css 2de660ce01c2c7d5` ·
  `base.css 46d26e1bc27716a7`；RunView 静态扫描 token/动画/硬编码色均为 0，styles 目录无新文件）

---

## 二、本阶段的红线自检（实现后逐条对照）

- [x] 不杀进程 / 不 TerminateProcess / 不 Close（S1a 静态扫描零命中：快照模块无
      `windows_activate` / `windows_close` / `apps_terminate` / `apps_launch` / `TerminateProcess` / `taskkill`）
- [x] 不启动软件（缺窗口 = `skip(missing)`；模块内零 launch 调用 —— 验收脚本里拉起 charmap
      是**脚本扮用户**，不是产品代码）
- [x] 不改 TECH-02 冻结域（`ui/src/workspace/snapshot.ts` hash `604fe010e0d3f980` 与 C4 开工一致）
- [x] 不新建 SQLite 表 / 迁移（db 模块文件集合未变，只登记一个 config 键）
- [x] 不做 `windows_place` 重构（复用 C3 `placeWindow`）
- [x] 不按标题 / 位置 / 前台窗口猜测身份与归属（身份只走 hwnd+pid / exePath；`foregroundHwnd` 恒 `null`）
- [x] 不把 `lastFacts` 自动持久化；不把持久化快照当 live facts（Live Facts ≠ Snapshot）
- [x] 不引入新动画 / 新 Token / 新视觉语言 / 新页面

---

## 三、待确认项 —— 已拍板（C4-D1 … C4-D4）

1. **C4-01 D-2**：✅ 允许。`/health` 与 `ping` 同时返回 `{"service","pid","started_at"}`
   （`api/mod.rs` 加 `identity_facts()`；`ping` 由 `&'static str` 改为返回同一 JSON 字符串，
   让 Tauri 主路径也能拿到 core 身份，不新增命令）。
2. **C4-03**：✅ 接受由 UI adapter 经 `put_config` 写 `workspace.snapshot.last`，
   但必须用**严格**通道（`putCore/getCore`，失败即抛、无 localStorage 降级）。
3. **C4-05 D-4 / D-5**：✅ 接受 `foregroundHwnd=null` 与「zIndex = 枚举序近似值」两个诚实降级。
4. **C4-09 D-10**：✅ 最小化窗口 `skip`（C4 不还原、不激活、不改状态）。
