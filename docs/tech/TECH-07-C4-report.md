# TECH-07-C4 报告 —— Workspace Snapshot Persistence / Restore

> 日期：2026-09-16
> 判据台账：`docs/tech/TECH-07-C4-checklist.md`（C4-01 … C4-18 全 DONE）
> 验收脚本：`tools/verify_tech07c4.py` → **25/25 通过，另有 1 项 Deferred（E：真实环境不可构造）**
> 回归：C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 · 契约套件 exit 0 · `cargo test config` 6/6
> 范围：只做 C4。未进入 C5，未做皮肤 / 多显示器 / 智能布局 / 视觉改动。

---

## 一、C4 做了什么（一句话）

把「工作区状态」从"只在内存里活着"变成"能落库、能跨 core 重启读回、且只能在严格边界内还原"，
**不改 Snapshot v1 契约、不改冻结域、不动视觉**。

三条语义边界贯穿全程：

| 概念 | 含义 | C4 里的体现 |
|---|---|---|
| **Facts** | 描述**现在**（core 实时事实） | `takeFacts()`，每次 capture/restore 现取 |
| **Snapshot** | 记录**过去**（某一刻的状态） | v1 文档，落 `workspace.snapshot.last` |
| **Restore** | 试着把**现在**拉回**过去** | 两层匹配 + 逐窗重新校验 + 受限摆位 |

---

## 二、Core 侧改动（最小，4 处，无新表 / 无迁移 / 无新命令）

| 文件 | 改动 | 目的 |
|---|---|---|
| `core/src/api/mod.rs` | 新增 `STARTED_AT_MS`（OnceLock）、`mark_started_now()`、`started_at_ms()`、`identity_facts()`；`/health` 由 `{"service"}` 改为 `{"service","pid","started_at"}` | 给 `source` 三字段提供**真实**事实出口（C4-D1）。保留 `service` 字段以兼容既有调用 |
| `core/src/api/commands.rs` | `ping()` 返回值由 `"pw-core"` 改为 `identity_facts()` 的 JSON 字符串 | Tauri 主路径也能拿到 core 身份，**不新增命令**（唯一消费方 `checkConnection` 忽略返回值） |
| `core/src/main.rs` | tracing 初始化后、建窗/起服务前调用 `api::mark_started_now()` | `started_at` 是进程启动时刻，不是首次调用时刻 |
| `core/src/db/config.rs` | `KEYS` += `"workspace.snapshot.last"`；`expected_type` => `"object"`；`default_for` => `{}` | 唯一持久化落点，三处登记齐备（两个测试锁死这条约束） |

**为什么类型登记成 `object` 而不是 string**：初版 checklist 写的是"JSON 文本存 string"。
落地时发现 `expected_type` 没有"字符串里装 JSON"这种类型，登记成 string 会让"快照"和
"普通字符串"在 core 侧无法区分；`{}`（空对象）作为"从未写过"的默认值语义也更准。
`cargo test config` 6/6 通过（含 `every_registered_key_has_an_explicit_type` /
`every_registered_key_has_an_explicit_default` 两个锁死测试）。

---

## 三、UI 侧改动（新增 2 文件，改 4 文件，冻结域零改）

| 文件 | 改动 |
|---|---|
| `ui/src/workspace/runtime/snapshot.ts`（**新增**） | C4 的适配器：真实探针 → 冻结 `capture()` → 校验 → 原子写；读 → 校验 → 两层匹配 → 受限执行 |
| `ui/src/api/systemService.ts`（**新增**） | `coreIdentity()`（Tauri→`ping` / 浏览器→`/health`）、`appVersion()` |
| `ui/src/api/configService.ts` | 新增**严格** `getCore` / `putCore`：失败即抛，**无 localStorage 降级**（C4-D2 明确禁止拿本地副本当持久化证据） |
| `ui/src/workspace/runtime/index.ts` | 导出 `windowSnapshot: {capture, restore, status, currentRunId}` + 类型 |
| `ui/src/workspace/runtime/boundary.ts` | 白名单 += `ping`（只读身份，非 actuate） |
| `ui/vite.config.ts` | `define.__PW_APP_VERSION__`（来自 package.json，供 `source.appVersion`） |
| `ui/src/views/RunView.vue` | 状态栏加 1 个既有 `pw-chip`（`run-snap-chip`）+ 2 个既有 `pw-btn`（`run-snap-save` / `run-snap-restore`），**零新 token / 零动画 / 零硬编码色** |

冻结域 `ui/src/workspace/snapshot.ts` **hash 未变**（`604fe010e0d3f980`）—— C4 只在其外接线。

### 关键实现决策

- **runId = `{pid}@{started_at}`**，全部来自 core 自报事实，**零随机、零虚构、不写库**。
  换 runId ⇒ 所有旧 hwnd 一律失效（这是 v1 契约里 hwnd 的有效性边界）。
- **exePath 只能从登记链拿**：`slots(pid→appId)` ∪ `apps_running(appId→pid)` → `apps_list.AppItem.path`。
  `WindowInfo` 本身没有 exe 路径，拿不到证据的窗口**不进快照**（不编造）。
- **原子持久化**：`validate()` 通过 → `putCore` 单键覆盖。成功即已落库，失败即未落库，没有"半写"；
  任何一步失败都**不覆盖**已有快照。
- **诚实降级**：`foregroundHwnd` 恒 `null`（无真实前台事实，不猜）；`zIndex` = 枚举序 `index+1`
  （近似 Z 序，代码与 UI 都不把它当权威排序）。

---

## 四、Restore 的两层匹配与失败语义

```
restore()
 ├─ 0) 取当次新鲜 facts；offline ⇒ 立刻 fail-closed（零 actuation）
 ├─ 1) 读快照：none / invalid ⇒ 拒绝（invalid 保留原值，不改写不删除）
 ├─ 2) runId 相同？
 │     ├─ 是 → Layer 1：hwnd + pid（复用冻结 restore() 的 plan 作**意图**）
 │     └─ 否 → Layer 2：exePath，只在**当前已归属窗口**里找唯一候选
 └─ 3) 逐窗执行：超时检查 → 最小化 skip → 执行前再校验（存在/归属/pid 未变）
              → safeRect 拓扑修正 → placeWindow（C3 既有能力）→ 记 restored / skipped
```

- `focus-window` 步骤一律 skip（C3 边界把 `windows_activate` 列为 FORBIDDEN，C4 不恢复前台焦点）。
- 最小化窗口 skip（C4-D4：不还原、不激活、不改状态）。
- 整体 timeout 10s，逐窗检查 deadline，超时 → `skip(timeout)` 后继续，绝不无限等待。
- skip reason 集合：`missing` / `invalid` / `ambiguous` / `unowned` / `offline` /
  `placement_failed` / `timeout` / `skipped`。UI chip 如实列出，不压成一句"恢复失败"。

---

## 五、真实证据（Real）—— 非 mock

全部在**真实 core 进程 + 真实外部窗口（charmap.exe）+ 真实重启 + 真实 Edge 页面**上跑，
窗口 rect 一律以 core `windows_list` 回读为准（不采信本地几何）。

| # | 场景 | 证据 |
|---|---|---|
| **A** | Capture | chip `快照：已保存 1 个窗口`；`snapshotId=ws-20260916-174115-4612`；`managed=1`；`exePath=C:\Windows\System32\charmap.exe`（来自登记链）；`workspace-snapshot.v1.schema.json` 契约校验 **0 错误** |
| **B** | Persistence（跨进程） | SQLite `config` 表确有该行 → **杀掉 core** → 新进程**新端口**读回同一 `snapshotId`；新进程 `/health` 的 `pid@started_at` = `4604@…` ≠ 快照里的 `46120@…` ⇒ 证明是"跨进程读回"，不是内存/localStorage |
| **C1** | 同运行期恢复（hwnd+pid） | 把窗口挪到 `(+210,+130)` → 恢复 → 真实 rect 回到 `{'x':18,'y':80,'w':572,'h':536}`；chip `已恢复 1 个窗口（同运行期）` |
| **C2** | 跨重启恢复（exePath） | 重启后 apply 重新登记 → **受管窗口是新 hwnd（70144，旧 2298012）** → 挪走 → 恢复 → 回到快照 rect；chip 显示 `（跨重启）`；**附加断言：未归属的同标题同 exe 窗口零摆位** |
| **D** | Missing | 杀掉全部 charmap → 恢复 → chip `已恢复 0 个窗口（同运行期） · 跳过 1：missing`，**零摆位** |
| **F** | Corrupted | 把 `desktop` 改成字符串 → chip `…跳过 1：invalid`，**零摆位**，且**损坏值原样保留**（恢复流程不改写、不删除） |
| **G** | Offline | 杀 core → 恢复 → chip `已恢复 0 个窗口（未执行） · 跳过 1：offline`，零摆位，不碰陈旧缓存 |
| **H** | Topology | 快照 rect `x=2440,w=572`（工作区右边界 2560，**确实跨界**）→ 恢复后 `x=1988` —— 整窗在界内 |

### 真实验收抓到并修掉的一个实现缺陷（H）

初版 `safeRect()` 的上界写成 `wa.x + wa.w - MIN_VISIBLE`，只保证"露出一角"。
H 段实测：跨界 rect `x=2440` 原样落到 `x=2440`，窗口只剩 120px 可见 —— 与 C4-12
"修正后必须仍在工作区内…不允许恢复到完全不可见位置"不符。

已改为**完整可见**口径：装得下 ⇒ `x ∈ [wa.x, wa.x + wa.w - w]`；
装不下（工作区比窗口还小）⇒ 退化为"至少 `MIN_VISIBLE` 像素可见"。只动位置、不改尺寸。

---

## 六、Deferred（真实环境不可构造）—— 只有 1 项

**E：Ambiguous（同 exePath 多候选 ⇒ ambiguous 且零摆位）**

先试了三条构造路线，都不成立（每条都有实测证据）：

1. **同 path 登记两个 app** → `apps_add` 返回 **400**（`apps.path` 是 **UNIQUE**）；
2. **core 重复 launch 同一 app** → 返回 `alreadyRunning`，同一 pid，不会多开；
3. **手工多开第二个实例**（脚本扮用户）→ 第二个 pid **拿不到归属证据**：
   实测 `apps_running` 仍为 `{"1": 14568}`，`slots` 只有一条，UI 受管同标题窗口 = 1。

**结构性原因**：① `apps.path` UNIQUE ⇒ 一 appId 一 exePath；
② 归属 pid = `slots` ∪ `apps_running`，两者都是**一 app 一 pid**。
也就是说：**在当前架构下，同一个 exePath 不可能同时存在两个受管候选**。

**处理方式**：该分支保留为**防御性代码**（`skip(ambiguous)` + 零摆位），其语义由 S 段静态项覆盖；
不在真实环境伪造场景充绿。**若未来放开"一 app 多实例"的归属证据（例如 slots 允许一 app 多 pid），
这项必须回到 Real 重验。**

同时记录一个**未处理的观察**（不属 C4 范围，未动）：exePath 比较是大小写敏感的 `===`。
Windows 路径大小写不敏感，若将来出现 `C:\Windows\...` 与 `c:\windows\...` 两条登记，
会被当成两个不同 exe。当前 `apps.path` UNIQUE 用 BINARY 排序，理论上可同时存在。
→ 留给后续阶段（非 C4 缺陷）。

---

## 七、安全 / 权限边界

- 快照模块静态扫描零命中：`windows_activate` / `windows_close` / `apps_terminate` /
  `apps_launch` / `TerminateProcess` / `taskkill` —— **不关窗、不杀进程、不启动软件**。
- 零 `localStorage` / `sessionStorage` / `indexedDB` —— 持久化只走 Core config。
- 恢复的候选集**只可能是"当前已归属"的窗口**，禁止全系统按 exe 搜索。
- 每次摆位前**重新校验**（存在 / 归属 / pid 未变），`placeWindow` 自身还有 C3 的归属校验兜底。
- 未新增命令（`ping` 复用）、未新增表/迁移、未放宽 `boundary.ts` 的 actuate 边界（`ping` 是只读）。

---

## 八、回归

| 套件 | 结果 |
|---|---|
| `tools/verify_tech07c3.py` | **27/27** |
| `tools/verify_tech07c2.py` | **25/25** |
| `tools/verify_tech07c.py` | **16/16** |
| `tools/verify_tech02_workspace.py` | **11/11** |
| `tools/verify_contracts.py` | exit 0 |
| `cargo test config` | **6/6** |
| `tools/verify_tech07c4.py`（新增） | **25/25 + 1 Deferred** |

**踩坑（写进 checklist 备忘）**：C2/C3 验收要求 `ui/dist` 是 **`VITE_CORE_BASE=''` 的同源验证构建**。
C4 中途用普通 `npm run build` 重建过一次 dist，导致 C2 D2 红灯（UI 去连默认 7520 端口 → 跨源被拦）。
**以后重建 dist 必须带该环境变量。**

---

## 九、视觉冻结

四个视觉基线文件 hash 与 C1/C2/C3 完全一致：

```
tokens.css          f329f50bddd31d59
motion-tokens.css   e5e44af4aa807d38
primitives.css      2de660ce01c2c7d5
base.css            46d26e1bc27716a7
```

RunView 静态扫描：token 0 / 动画 0 / 硬编码色 0 / styles 目录无新文件。
C4 的 UI 是**状态投影**（一个 chip + 两个既有按钮），不是 UI redesign。

---

## 十、Real / Mock / Deferred 清单（按 §28 要求）

- **Real（20 项 + 5 个既有套件）**：S1a/S1b/S2/S2b/S3/S4/S5/S6a/S6b/S7a/S7b/S7c 静态 12 项（真实源码扫描，
  含 hash 冻结）+ A / B / C1 / C2 / D / F / G / H 真实环境 8 项；R 段 5 个既有套件真实执行。
- **Mock（0 项）**：C4 没有用任何 mock 顶替 Real。损坏快照（F）与"窗口消失"（D/G）是
  **构造输入/构造环境**，不是 mock 执行路径 —— 模块、core、窗口、摆位链路全是真的。
- **Deferred（1 项）**：E（Ambiguous）—— 真实环境不可构造，已给出三条构造路线的实测失败证据 +
  两条结构性原因；该分支保留为防御性代码。

---

## 十一、不做（留给后续）

- 智能布局 / 多显示器跨屏重构（C4 只做主显示器基准的最小安全修正）。
- 一 app 多实例的归属证据（会直接决定 E 能否回到 Real）。
- 快照历史 / 多份快照 / 自动快照触发（v1 `trigger` 只有 `enter_mode`）。
- 最大化态的语义化恢复、Z 序真实还原、前台焦点恢复（均属 C4 明令不做）。
- C5 及以后的任何内容。
