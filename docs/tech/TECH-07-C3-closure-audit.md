# TECH-07-C3 Closure Audit —— 收尾审计

> 日期：2026-09-16 · 范围：**只审 C3 收尾**，未进入 TECH-07-C4
> 结论：**12 项 checklist 全 PASS（其中 4 项含本审计内最小修复）**，四套件全绿
> 审计动作：只读审计 → 发现 4 个隐性缺陷 → **C3 必需的最小修复** → 重跑全部回归 + 新增真机取证

---

## 一、Checklist 执行结果

| # | 审计项 | 结论 | 说明 |
|---|---|---|---|
| 1 | C3 Adapter actuation 状态 | **PASS** | `boundary.ts` 段位 `actuate`；白名单 +`windows_place`/`apps_running`（均既有命令）；禁区含 `windows_close`/`apps_terminate`/`windows_activate`，adapter 源码零命中 |
| 2 | `lastSnapshot` 生命周期 | **PASS（含修复）** | 纯运行时缓存，无 SQLite / localStorage / `workspace.snapshot.last` 写入；**修复**：offline 时作废缓存（见 §二） |
| 3 | placement 调用频率 | **PASS** | pointermove 只做本地命令式预览；commit 仅 `pointerup`；一次交互恰好 1 次 `windows_place`；resize 走同一路径；**无需** debounce/throttle |
| 4 | pointerup / pointercancel / lostpointercapture | **PASS（含修复）** | **修复**：新增 cancel 路径（只清理、不摆位）+ 成对 detach（见 §三） |
| 5 | 8 向 resize geometry | **PASS** | 逐向推演全部正确；`nw` 真机取证 w↓ x↑ h↓ y↑ 四者同步（见 §四） |
| 6 | 坐标语义 | **PASS** | 基准 = 主显示器工作区（物理 px / virtual-screen）；与 D4/D5 真机换算一致；未扩展多显示器 |
| 7 | hwnd / pid 归属安全 | **PASS** | 归属 = 流水线 slots pid ∪ `apps_running`（当前模式 launchedAppIds）；无 title/exe/foreground/nearest 回退 |
| 8 | placement 后事实回流 | **PASS（含修复）** | **修复**：非 placed 时预览写回起始几何，Core facts 仍是唯一事实源（见 §五） |
| 9 | offline fail-closed | **PASS** | 5 条判据逐条真机验证（见 §六） |
| 10 | C3 验收基础设施 | **PASS（含加固）** | A2c 加严（commit 唯一 + 非 placed 回滚 + cancel 不提交）；D4/D5 目标收紧为「归属 + 标题=被拉起软件」；无 mock、无放宽容差、R 段真实子进程执行 |
| 11 | C3 代理修改 | **PASS（含修复）** | Content-Type 转发 + **修复** HTTPError 透传（业务错误不再伪装 `proxy_down`，见 §七） |
| 12 | dist 构建状态 | **PASS** + 1 项 DEFERRED | 三证据确认最新构建含 C3；`ui/dist/assets` 仍累积 587 个历史 chunk → 记为 housekeeping，未改 build config |
| 13 | C2 / C3 回归 | **PASS** | C3 27/27、C2 25/25、C1 16/16、TECH-02 11/11（均真实执行） |
| 14 | 视觉冻结状态 | **PASS** | 见 §九：interaction enabled, visual language preserved |

---

## 二、`lastSnapshot` 审计（只做运行时上下文）

**检查结论：**

- 实现 = `facts.ts` 的模块级 `let lastFacts`，**纯内存**；
- **不写 SQLite**（UI 红线 V7）、**不写 localStorage**、**不碰 `workspace.snapshot.last`**（该键只存在于 TECH-02 冻结域 `workspace/snapshot.ts`，runtime/ 目录零引用）；
- **不改 Snapshot v1**，不参与任何持久化链路；
- RunView **不消费** `lastSnapshot`（几何仍来自 `facts.value`），它只服务于 `placeWindow` 的归属校验 —— 不是 UI 的权威状态。

**发现的泄漏（已最小修复）：** core 不可达时旧缓存**不会失效** → core 重启后陈旧快照里的旧 hwnd 仍会被当成"当前事实"，actuation 可能作用到已不再归属的窗口。

修复（`facts.ts` + `actions.ts`）：

```ts
// facts.ts：offline 即作废缓存（纯运行时，恢复后下次采样自然重建）
if (connectivity === 'offline') lastFacts = null
else if (rawWinsR.status === 'fulfilled') lastFacts = facts

// actions.ts：无事实 / offline 时**不发起** windows_place（fail-closed）
if (!snap || snap.connectivity === 'offline') return { status: 'offline', ... }
```

---

## 三、Pointer 生命周期审计

| 路径 | 修复前 | 修复后 |
|---|---|---|
| pointerdown → move → **pointerup** | 提交 1 次（正常） | 不变 |
| 重复 pointerup | 已安全（`interaction=null` + 监听已摘） | 不变 |
| **pointercancel** | ❌ 无处理 → `interaction` 永久非空 → `refresh()` 早退（**facts 轮询被冻结**）+ 监听残留 | ✅ `cancelInteraction()`：清状态 + 摘监听 + 预览写回起始几何，**不发起摆位** |
| **lostpointercapture** | ❌ 无处理 | ✅ 同 cancel 路径（捕获丢失 ≠ 用户确认） |
| 开始新交互时旧状态残留 | ❌ 直接覆盖 | ✅ 先 `cancelInteraction()` 再开始 |
| setPointerCapture 抛错 | ✅ 已 try/catch（C3 修复） | ✅ **未被后续编辑破坏**（仍在 `try{}catch{}`，监听注册在其后） |

真机取证（`diag_t7c3.py` 场景 C）：`pointercancel` 后真实窗口 rect **零变化**，且**紧接着的下一
次拖拽正常生效**（x 323→414、y 259→304）—— 证明状态未卡死、监听不残留。

---

## 四、8 向 Resize Geometry 审计

逐向推演（`previewGeometry`）：E/S 只改 w/h；**W/NW/SW 改 width 时 `x = s.x + (s.w - w)` 同步**；
**N/NE/NW 改 height 时 `y = s.y + (s.h - h)` 同步**；MIN(0.04) clamp 后仍用同一公式，不会漂。

真机取证（场景 B，`nw` 手柄拖 +60,+40）：

```text
{'w':572,'x':140,'h':536,'y':140}  →  {'w':389,'x':323,'h':417,'y':259}
   w↓        x↑        h↓        y↑   —— 四项同步全部正确
```

未改任何视觉表现；仅确认 geometry 正确。

---

## 五、placement 后事实回流审计

链路仍是：`UI 手势 → adapter actuation → core windows_place → Windows → core windows_list/facts → projection → RunView`。

**发现的泄漏（已最小修复）：** 预览是命令式写 `el.style`；摆位**失败**时 facts 未变 → Vue 的
`:style` 绑定值前后相同 → **不触发 DOM 写入** → 请求几何滞留在屏幕上，视觉上变成"已确认几何"。

修复：`if (result.status !== 'placed') writeGeometry(it.el, it.start)`（工作区不可用时同样回滚）。
`PlacementResult.rect` 仍是 **requested** rect（仅用于 chip 的 title 提示，不参与任何几何展示）。

---

## 六、Offline Fail-Closed 审计（5 条判据）

| # | 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | Core 正常 → placement 可执行 | PASS | D4/D5：`before≠after` 且方向/幅度正确 |
| 2 | Core 停止 → placement 不得伪成功 | PASS | 场景 D：断连后 0 窗口、手势无目标；`placeWindow` 侧 offline 直接返回 |
| 3 | Core 停止 → UI 不得继续伪造 connected | PASS | D8：`coreDead=True`，hint=未连接，`wins=0`，双采样 `frozen=True` |
| 4 | Core 停止 → 不得控制任何 fallback window | PASS | 场景 F：断连期间的拖拽在 core 恢复后 rect 与断连前**完全一致**（无任何摆位落地） |
| 5 | Core 恢复 → Observe 可恢复 | PASS | 场景 E：新端口 50755，投影重现（20 个真实窗口），hint 不再显示未连接 |

C2 已修的 `coreDead` / `frozen` 判据**未被 C3 改坏**（D8 仍在用，且本审计再跑一次仍 PASS）。
**新增修复**：断连后作废上一次摆位结果（chip 的陈旧「✓ 已摆位」不再展示 —— 陈旧成功 = 假成功）。

---

## 七、C3 代理修改审计

`tools/verify_tech07c2.py::ProxyHandler`（**仅验证环境**，Tauri 正式路径走 invoke，不受影响）：

| 检查 | 结果 |
|---|---|
| 只属验证代理 | ✅ tools/ 下，非产品代码 |
| GET 行为未破坏 | ✅ C2 25/25（真实执行）、C1 16/16 回归通过 |
| POST JSON Content-Type 透传 | ✅ C3 D4/D5 真实摆位成功即证据 |
| 不吞真实 Core 错误 | ✅ **本审计修复**：新增 `HTTPError` 分支，按 core 原始状态码 + body 透传 |
| 415 不再被包装成 proxy_down | ✅ 修复前 415 → 502 `proxy_down`（UI 误判 offline）；修复后如实透传 |

---

## 八、验收基础设施审计（verify_tech07c3.py）

- 产品断言**零删除**，本审计**加严**两处（不增加检查项，保持 27 项）：
  - A2c：commit 唯一 **+ 非 placed 必须回滚预览 + cancel 路径不得提交**；
  - D4/D5：手势目标从「第一个 is-managed」收紧为「**归属（is-managed）且标题=本次真实拉起的软件**」，
    确保"控制到的正是被归属的那个窗口"，detail 打印 `target=ok` 作为证据。
- 无 title-only **控制**判据：title 仅用于确认被控窗口身份与（observe 侧）等待窗口出现；
  控制入口仍是 `.run-win.is-managed`（归属派生）。
- 无 mock placement success：D4/D5 判据 = core `/api/v1/windows` 的真实 rect 变化。
- 未把 requested rect 当 after rect：`after` 全部来自 core 轮询读取。
- 未放宽误差掩盖错误：D4 ±40px / D5 ±60px 自 C3 起未改；实测 D4 实际 +126 vs 期望 +126（精确命中）。
- 无引用旧输出文本造假绿：全部断言为实时执行。
- comments stripping（`strip_comments`）不误伤代码：本轮新增的回滚/cancel 代码均不在注释行，断言仍命中。
- C2 25/25 回归为**真实子进程执行**（R 段 exit=0 + 汇总解析）。

---

## 九、Visual 冻结审计

- RunView 布局零改动（run-head / run-status / run-stage / appbar / minimap 原样）；
- Sidebar、AI Sidebar、appbar、minimap、status bar **均未改动**；
- 窗口卡片语言未变（仍 `--surface-1` + `--border-subtle` + `--radius-card` + `--shadow-card`）；
- 交互只新增：bar 的 `cursor: grab`、8 个透明缩放热区（hover 用既有 `--brand-200`）；
- **Token +0**（hash 冻结四文件一致）、**Animation +0**（静态扫描无 keyframes/animation/transition）、无硬编码色值；
- DOM identity 保持（D7：stage/head/appbar/minimap 全 true）。

> 结论记录：**interaction enabled, visual language preserved.**

---

## 十、Runtime / Validation / Visual 汇总

```text
Runtime
  lastSnapshot runtime-only ................ YES（offline 即作废，零持久化）
  placement 高频调用 ....................... NO（pointermove 仅本地预览，commit 仅 pointerup 一次）
  pointer lifecycle ........................ PASS（cancel/lostcapture 已覆盖，重复 up 安全）
  8-way resize ............................. PASS（nw 真机取证 w↓x↑h↓y↑）
  coordinate semantics ..................... PASS（主显示器工作区，物理 px）
  ownership safety ......................... PASS（slots ∪ apps_running，零猜测回退）
  facts round-trip ......................... PASS（非 placed 回滚，facts 为唯一事实源）
  offline fail-closed ...................... PASS（5/5 判据真机通过）

Validation
  C3 .............. 27/27
  C2 .............. 25/25
  TECH-07-C ....... 16/16
  TECH-02 ......... 11/11
  audit 取证脚本 ... 6/6（A 基线 / B nw / C cancel / D 断连 / E 恢复 / F 无偷摆）

Visual
  Token ................. +0
  Animation ............. +0
  Visual baseline ....... unchanged（四 CSS hash 冻结一致）
  DOM identity .......... preserved
```

---

## 十一、本审计期间的改动（全部为 C3 必需的最小修复）

| 文件 | 改动 |
|---|---|
| `ui/src/workspace/runtime/facts.ts` | offline 时作废 `lastFacts`（禁止陈旧快照当事实） |
| `ui/src/workspace/runtime/actions.ts` | 无快照 / offline 时不发起 `windows_place`（fail-closed） |
| `ui/src/views/RunView.vue` | 新增 `cancelInteraction` / `detachInteraction` / `writeGeometry`；pointercancel + lostpointercapture 清理；非 placed 回滚预览；offline 时作废陈旧 chip；开始新交互前先清理旧状态 |
| `tools/verify_tech07c2.py` | 代理转发 Content-Type（C3）+ **HTTPError 如实透传**（本审计） |
| `tools/verify_tech07c3.py` | A2c 加严；D4/D5 目标收紧为「归属 + 标题」并打印证据 |
| `tools/diag_t7c3.py` | 重写为审计取证脚本（A–F 六场景，非 27 项套件） |

**未改：** core 全部 Rust 代码、视觉基线四 CSS、UI-FUSION-STANDARD、layoutService、TECH-02 冻结域。

---

## 十二、Known deferred items（如实记录，不在本任务处理）

1. **`WindowInfo` 仍无 `exe` 字段**：core 未提供进程映像路径，`RunWindowFacts.exe` 恒 `null`（如实缺口，需 core 侧新增字段，属后续阶段）。
2. **`ui/dist/assets` 历史 chunk 累积**：当前 **587** 个文件，`index.html` 仅引用 2 个（1 js + 1 css）。不影响运行，记为 **housekeeping** —— 本任务**未**改 build config。
3. **多显示器未支持**：C3 已验证的坐标语义仅限**主显示器工作区**基准；跨显示器摆放属未来增强，本审计**未**扩展为多显示器重构。
4. **预览未 clamp 到工作区边界**：`x + w` 可 > 1（Windows 允许跨屏/部分出屏），当前行为保留，未改。
5. **offline / failed 二分依赖 `error.code`**：core 业务错误码透传后可进一步细化（如区分 400/404/500），当前按 proxy_down/network/timeout 归 offline，其余归 failed。
6. **`apps_running` 是 5s watcher**：core 重启后注册表需重建，短暂窗口内已存在窗口可能不判归属（observe 侧表现；actuation 因 offline 作废缓存而 fail-closed，不构成误操作风险）。
7. **`PlacementResult.rect` 是 requested rect**（非 core 确认值）：仅用于 chip 的 title 提示，不参与几何展示；若未来展示，须改为 facts 读取值。

---

## 十三、停止点

本任务只做 C3 收尾审计：**未进入 TECH-07-C4**，未新增功能、未做 UI redesign、未新增 Token/动画、
未扩展 core、未做 Snapshot/Restore、未引入 Close/Kill/Terminate 路径。
