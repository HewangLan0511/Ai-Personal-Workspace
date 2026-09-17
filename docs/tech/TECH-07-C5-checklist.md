# TECH-07-C5 Checklist —— Workspace Layout Persistence（布局保存与应用）

> 日期：2026-09-16 · 阶段状态：**Checklist 已冻结（Phase 0~2 审计完成），未写实现**
> 目标（已冻结）：将 Run 页「保存布局」「恢复默认」两个 disabled 交互接入真实布局能力，形成工作模式内的布局闭环。
> 配套审计：`docs/tech/TECH-07-C5-audit.md`（含方向 A 冻结后的补充审计节）
>
> **已拍板（2026-09-16，白宇）**：

| 项目 | 决策 |
|---|---|
| C5 方向 | **A：布局保存/应用** |
| 两按钮 | **接通** |
| snapshot / layout 关系 | **双轨并存**（Layout=当前排布快速保存/应用；Snapshot=跨重启恢复契约） |
| windows_activate | **保持禁用** |
| mode_restore | **暂不收敛** |
| 一 app 多实例 / 多显示器 / exePath 扩展 | **不做**（C4-E Deferred 保持） |
| core 改动 | **能不改则不改** |

> **冻结边界**：不回退 C1~C4 验收结果；Token +0 / Animation +0 / 四 CSS hash 不变；
> 不改 `ui/src/workspace/snapshot.ts`（hash `604fe010e0d3f980`）与
> `docs/contracts/workspace-snapshot.v1.schema.json`；不新增 migration；能复用既有 command 就不新增。

---

## Phase 0：审计冻结

### C5-01 Run 页两个 disabled action 现状

- **当前代码位置**：`ui/src/views/RunView.vue` 头部 `run-head` 内：
  `<button class="pw-btn pw-btn--sm" disabled title="C3 放开（窗口控制）">恢复默认</button>`
  `<button class="pw-btn pw-btn--sm pw-btn--primary" disabled title="C3 放开（窗口控制）">保存布局</button>`
- **UI 入口位置**：run-head 右侧、布局/排列 seg 之后、时钟之前。
- **当前状态来源**：纯静态 `disabled`，**无任何 handler**（全文检索 `saveLayout`/`restoreLayout` 均 0 命中）；
  title 文案"C3 放开（窗口控制）"已过时（C3 实际只放开了 place，这两个按钮从未接线）。
  同排另有 5 个 disabled seg 按钮（自由/自动整理/聚焦/自动/手动）——**不在 C5 范围**，保持原样。
- **是否已有 placeholder handler**：无。
- **已有能力**：`snapBusy` 防重入模式（C4）可复用为 `layoutBusy`；`pw-btn`/`pw-chip` 原语齐备。
- **缺口判断**：只差接线（handler + 状态机 + 结果 chip）；无结构性障碍。
- **验收证据**：静态扫描确认接线后无新 token / 无新动画 / 无 @/api import。
- **风险登记**：接通时 title 文案要同步改（否则谎报状态来源）。

### C5-02 现有布局体系审计

- **当前代码位置**：
  - 表：`database/schema.sql` `layouts`（name/description/slots/monitor/ai_sidebar/is_builtin/created_at/updated_at）；
  - core：`scheduler/repository.rs::LayoutRepo`（list/get/**upsert 唯一写入口**，先写库后导出 JSON）、
    `window_manager/apply.rs::apply_layout`（应用）、`window_manager/layout.rs`（归一化坐标纯函数）；
  - 命令：Tauri `layouts_list / layout_get / layout_apply / db_layouts_list / db_layout_get / db_layout_upsert`；
    HTTP `GET/POST /api/v1/db/layouts`、`GET /api/v1/layouts`、`GET /api/v1/layouts/{name}`、
    `POST /api/v1/layouts/{name}/apply`；
  - UI 封装：`api/layoutService.ts`（list/monitors/apply/windowsList/place…）、
    `api/modeService.ts` 的 `dbLayouts()` / **`dbLayoutUpsert(name, description, slots, monitor)`**（Tauri+HTTP 双通道，已验收）；
  - 保存先例：`views/ModeView.vue:382 saveLayout()` → `dbLayoutUpsert`（编辑器手输 slots）。
- **当前 layout 是否已具备保存能力**：**具备，零 core 改动**。写入口 `db_layout_upsert` 已验收，
  UI 封装 `dbLayoutUpsert` 已存在；缺的只是"从真实受管窗口采集 slots"的 adapter 编排。
- **保存的数据结构（Layout v1，core `Slot` 口径）**：

```jsonc
// layouts.slots（core window_manager::Slot / ui layoutService::Slot）
{
  "name": "<布局名>",
  "monitor": 0,
  "slots": [
    { "app": "<apps.name 软件库名称>",        // ⚠️ 是名称不是数字 id（见下）
      "rect": { "x": 0..1, "y": 0..1, "w": 0..1, "h": 0..1 },  // 归一化，相对主屏工作区
      "z": 1,                                 // 叠放序，小者先摆
      "alwaysOnTop": false, "maximized": false }
  ]
}
```

  ⚠️ **对齐点**：core `resolve_pid(state, app_name)` 按 `apps.name` 大小写不敏感匹配 →
  `running.get(app.id)`。所以 slot 存的是**软件库名称**；C5-04 说的"保存 appId"在实现上
  映射为"pid → appId → apps_list.name"（UI 层可同时持有 id 做显示映射，落库字段是 name）。
- **与 Snapshot v1 的差异（禁止混用）**：

| 维度 | Layout v1（本阶段） | Snapshot v1（C4 冻结域） |
|---|---|---|
| 回答的问题 | "这类软件排成什么样好看"（模板） | "那一刻的工作区是什么状态"（实例） |
| 身份 | `apps.name`（软件库登记名） | hwnd+pid（同运行期）/ exePath（跨重启） |
| 几何 | 归一化 rect（相对主屏工作区，自适应 DPI/分辨率） | rectPx 物理像素 + rectNorm |
| 执行者 | core `apply_layout`（含 skip/重试语义） | adapter 受限执行器（C4） |
| 存储 | `layouts` 表 + 派生 JSON | core config `workspace.snapshot.last` |
| 契约 | 无 schema 冻结（slots 为自由 JSON，core 校验数组） | v1 schema + x-pw-v2-forbidden 冻结 |
| 恢复失败语义 | `skipped_not_running` / `skipped_no_window` / `failed`（core 产出） | `missing/invalid/ambiguous/unowned/offline/…`（adapter 产出） |

- **验收证据**：本节全部来自源码只读核对（文件/行号见"当前代码位置"）。
- **风险登记**：Layout 的 slots **没有 schema 冻结**（core 只校验 `slots.is_array()`）——
  C5 采集器必须**自己**保证产出结构合法（app 非空、rect 0..1、z ≥1），并在 adapter 层做
  `Number.isFinite` 护栏（C4-06 同款口径），不能指望 core 拦。

### C5-03 C4 snapshot 边界（双轨并存确认）

- **snapshot 负责**：跨重启恢复（exePath 身份）、实例状态复原、fail-closed、offline 拒绝。
  代码：`ui/src/workspace/runtime/snapshot.ts` + 冻结域 `ui/src/workspace/snapshot.ts`（不动）。
- **layout 负责**：当前 workspace 排布的快速保存/应用（模板语义），不做跨重启身份、不做 fail-closed
  之外的恢复契约。
- **双轨关系（已拍板并存）**：

```
Layout  ──apply_layout──▶  Run workspace arrangement（日常排布，快速、模板化、可反复套用）
Snapshot ──受限执行器──▶   Recovery contract（"回到那一刻"，跨重启、身份敏感、fail-closed）
```

- **禁止混用清单**：① 保存布局**不写** `workspace.snapshot.last`；② snapshot restore **不调**
  `layout_apply`；③ 两套结果 chip 文案分开（布局：placed/skipped/failed；快照：已恢复 N + skip 原因）；
  ④ 布局采集**不得**把 hwnd/pid 写进 slots（snapshot 才有实例身份）；⑤ 布局应用**不做**跨重启身份匹配。
- **验收证据**：C4 六套件回归全绿即证明 snapshot 边界未被触碰（S3 hash 冻结 + D 段行为不变）。
- **风险登记**：两条链路共用 `placeWindow`/core `windows_place` —— 并发触发（快照恢复进行中点布局应用）
  无互斥；C5 实施时用 UI 层 `busy` 状态互斥（与 C4 `snapBusy` 同款），不做 core 侧锁。

---

## Phase 1：设计确认（语义冻结，实施前不再改）

### C5-04 「保存布局」语义（冻结）

```
点击「保存布局」
  → 读取当前受管窗口 facts（belongsToMode && manageable && rect 非空）
  → 逐窗换算归一化 rect（相对主屏工作区，与 core arrange 换算基准一致）
  → 生成 slots（app=软件库名称, rect, z=枚举序+1, state→alwaysOnTop/maximized）
  → dbLayoutUpsert(name, description, slots, monitor=0)   // 唯一写入口
```

- **允许保存**：appId（经映射落库为 `apps.name`）、rect（归一化）、state（`alwaysOnTop`/`maximized`）、
  order（z 序）。
- **禁止保存**：hwnd、pid、任何运行实例身份、exePath、窗口标题。
- **名称策略**：默认 `run-<模式名>-<时间戳>`（避免覆盖既有布局；是否允许用户输入名称 = 实施时的小拍板项）。
- **空态**：受管窗口为 0 ⇒ 如实提示"没有可保存的受管窗口"，**不写库**（C4 空快照不覆盖的同款口径）。
- **状态机**：`idle → saving → saved（显示布局名）/ failed（如实透出错误）`。
- **验收证据**：保存后 `db_layouts_list`/`layout_get` 读回，slots 与 facts 采集值一致（app/rect/z 逐项对账）。
- **风险登记**：① 采集时窗口若正在拖拽中（interaction 未提交），rect 可能取到预览值 —— 实施时
  interaction 活跃期禁用按钮；② 归一化换算必须用 `monitors_list` 的**同一份** work area，
  且与 core `to_pixels` 的基准一致（含 aiSidebar 扣减口径 —— Run 场景无侧栏配置，传 `null`）。

### C5-05 「恢复默认」语义（冻结）

```
点击「恢复默认」
  → 取当前模式绑定布局名（RunModeFacts.layout / modes_list meta）
  → 未绑定 ⇒ 如实提示，零摆位
  → layout_apply(绑定布局名)          // core apply_layout：skip 语义内建
  → ApplyOutcome（placed/skipped_not_running/skipped_no_window/failed 逐 slot 明细）→ chip 如实透出
  → facts 回流确认（core windows_list 回读，不采信本地几何 —— C4 同款）
```

- **这不是 snapshot restore**：不做 exePath/hwnd 身份匹配、不读 `workspace.snapshot.last`、
  不做 fail-closed 恢复契约；失败语义 = core 的 skip，UI 只做如实投影。
- **禁止自动启动软件**：core `apply_layout` 对未运行 app 天然 `skipped_not_running`
  （源码已核对：`resolve_pid` 返回 None → 直接 skip，无 launch 路径）——**零新增代码即满足**。
- **not connected**：facts offline ⇒ 不发起 `layout_apply`（C3 placeWindow 的 fail-closed 同款，在 adapter 层判）。
- **状态机**：`idle → applying → done(全 placed) / partial(有 skip) / failed / offline`。
- **验收证据**：真实窗口位置改变 → 点击 → core `windows_list` 回读 rect 回到布局定义值；
  关掉一个 app 再应用 ⇒ 该 slot `skipped_not_running` 且其余照常。
- **风险登记**：① `layout_apply` 在 adapter FORBIDDEN —— 接通必须白名单化并**同步更新
  verify_tech07c3 的 FORBIDDEN 扫描判据**（判据更新≠放松：RunView 禁 @/api 仍然有效）；
  ② `apply_layout` 是**同步阻塞**调用（含 80ms 分步延时 + 重试），模式多槽位时 UI 要有 applying 态
  防重入；③ HTTP 通道下 `POST /api/v1/layouts/{name}/apply` 存在，验收覆盖 Tauri 主通道即可
  （同源验证构建下代理转发已由 C2/C3 代理承载）。

---

## Phase 2：边界检查

### C5-06 adapter 新增合规性

- **允许**：新增 `ui/src/workspace/runtime/layout.ts`（runtime/ 是唯一允许 import `@/api` 的邻接层，
  verify_tech02 T1b 只禁 `runtime/` 之外的 workspace 域 import）。
- **职责**（F0 冻结）：facts（受管窗口 + monitors + 模式绑定布局）→ layout projection（归一化 slots）→
  layout actions（saveLayout→dbLayoutUpsert、applyLayout→layout_apply）。
- **禁止**：`RunView` 出现任何 `@/api` import / tauri invoke / core 命令名（C1/C2 静态判据持续有效）；
  `workspace/` 冻结域其他文件被 import。
- **验收证据**：C2 套件 A1a/A1c + C3 套件 FORBIDDEN 扫描（更新后）全绿。
- **风险登记**：`runtime.ts`（TECH-02 冻结门面）与 `runtime/` 目录同名易混 —— 新文件走
  `workspace/runtime/layout.ts` 子路径，RunView import 用 `/index` 出口或子路径（与 C4 snapshot 同款写法）。

### C5-07 command 复用核对（结论：零新增）

| 需要的能力 | 既有命令 | 状态 |
|---|---|---|
| 读受管窗口 | `windows_list` | ✅ 复用 |
| 读显示器工作区 | `monitors_list` | ✅ 复用 |
| 读软件库名称 | `apps_list` | ✅ 复用 |
| 读模式绑定布局 | `modes_list` / `modes_current` | ✅ 复用 |
| **保存布局** | **`db_layout_upsert`**（Tauri）+ `POST /api/v1/db/layouts`（HTTP） | ✅ 复用（UI 封装 `dbLayoutUpsert` 已存在） |
| **应用布局** | **`layout_apply`**（Tauri）+ `POST /api/v1/layouts/{name}/apply`（HTTP） | ✅ 复用（仅 adapter 白名单化） |
| facts 回流确认 | `windows_list` | ✅ 复用 |

- **需要新增的 command：无。需要新增的 migration：无。需要改 core：无。**
- 唯一的"边界反转"：`layout_apply` 从 `boundary.ts::FORBIDDEN_COMMANDS` 移入 `ALLOWED_COMMANDS`
  （与 C3 把 `windows_place` 移入白名单同一先例），并同步更新 verify_tech07c3 判据。
- **风险登记**：`modes_capture_current`（adapter FORBIDDEN）与保存语义相邻但**不用**——它会建新
  work_mode，超出 C5 范围；审计已确认不引入。

### C5-08 门禁与视觉冻结

- **保持全绿**：C1 `verify_tech07c.py` 16/16 · C2 25/25 · C3 27/27 · C4 25/25 + 1 DEFER ·
  TECH-02 11/11 · 契约套件 exit 0 · `cargo test config` 6/6。
- **判据更新点（实施时）**：verify_tech07c3 的 FORBIDDEN 扫描清单移除 `layout_apply`
  （随白名单化）；其余 26 项 C4 判据、全部 C1/C2 判据**不动**。
- **视觉**：Token +0 / Animation +0 / 四 CSS hash 不变（`f329f50b…` / `e5e44af4…` /
  `2de660ce…` / `46d26e1b…`）；RunView 只加 handler/状态 chip（复用 pw-btn/pw-chip），
  改两按钮的 disabled 与 title。
- **环境前提**：`ui/dist` 必须以 `VITE_CORE_BASE=''` 同源验证构建（C4 踩坑，验收前必查）。
- **风险登记**：无。

---

## Phase 3：实施顺序（**审核通过后才执行**）

- **F0**：新建 `workspace/runtime/layout.ts`（facts → layout projection → layout actions）；
  `boundary.ts` 白名单化 `layout_apply`；导出 `workspaceAdapter.layout`；**不动 RunView**。
- **F1**：接通「保存布局」：handler + `idle/saving/saved/failed` 状态机 + 结果 chip
  （复用既有 pw-chip；空受管窗口 → 提示不写库）。
- **F2**：接通「恢复默认」：handler + `idle/applying/done/partial/failed/offline` 状态机 +
  ApplyOutcome 逐 slot 明细透出（skip 原因不压扁）。
- **F3**：真实验证（新 `tools/verify_tech07c5.py`，复用 C4 章法）：
  - **A 保存**：启动 charmap → 拖动窗口 → 保存 → （可关窗重开）→ `layout_get` 读回，
    slots 内容与采集时 facts 逐项一致（app/rect/z），无 hwnd/pid 字段；
  - **B 应用**：改变窗口位置 → 恢复布局 → core `windows_list` 回读 rect 回归；
  - **C fail-closed**：关闭 app → 应用 → `skipped_not_running`、0 启动、0 猜测、0 错误摆位；
    core 离线 → 不发起 apply（offline 如实显示）；未绑定布局 → 提示且零摆位；
  - **回归**：C1 16/16 · C2 25/25 · C3 27/27 · C4 25/25+1D · TECH-02 11/11 · 契约套件 ·
    cargo test config 6/6 · 视觉四 hash 不变。

---

## 决策区（回填记录）

| 日期 | 事项 | 决定 |
|---|---|---|
| 2026-09-16 | C5 目标 | **A：布局保存/应用**（白宇拍板） |
| 2026-09-16 | 两按钮 | 接通 |
| 2026-09-16 | snapshot/layout | 双轨并存 |
| 2026-09-16 | windows_activate | 保持禁用（前轮候选项 C5-08 REJECTED） |
| 2026-09-16 | mode_restore 收敛 | 暂不收敛（前轮候选项 C5-04 REJECTED） |
| 2026-09-16 | 一 app 多实例 / 多显示器 / exePath 扩展 | 不做（前轮候选项 C5-06/07/09 REJECTED） |
| 2026-09-16 | core 改动 | 能不改则不改（审计结论：**零 core 改动可达成**） |
| — | 布局命名策略（默认时间戳名 vs 用户输入） | **实施时小拍板** |
