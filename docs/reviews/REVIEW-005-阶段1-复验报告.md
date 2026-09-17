# REVIEW-005 · 阶段1 复验报告（Rust 工具链补齐后的全量实测）

| 项 | 内容 |
|----|------|
| 报告编号 | REVIEW-005 |
| 日期 | 2026-09-12 |
| 提交/编写 | 肉编器001号（**同时是架构师 + 开发 + 审核** —— 独立性声明见第〇章） |
| 审核对象 | 阶段1「基础桌面框架」交付物（`core/` `ui/` `system/` `tools/`） |
| 触发 | 白宇装了 Rust 工具链，指令「检查当前项目进度，并开始进行下一步的工作」 |
| 基准 | `04-阶段指令-基础框架.md`（必须实现 5 条 / 验收标准 9 项 / 交付物 / 禁止事项）· `02` · `03` · `13` · `SUPERVISOR.md` · `ADR-001` |
| 门禁 | **FAIL=0 / WARN=0 / PASS=29**（`gate.py --stage 1 --build`） |
| 判定 | **验收项 1~9 全部实测通过；红线 0 命中；门禁 0 FAIL/0 WARN。**<br>但按 M-5（角色合并），本判定**不具备独立审核效力** —— 见第〇章与第七章。 |

---

## 〇、独立性声明（必读，否则本报告的"通过"两个字不算数）

2026-09-12 18:20 的角色合并把「架构 + 开发 + 审核」压到同一主体（`LEDGER.md` 治理变更记录）。
因此本报告存在与 REVIEW-004 相同的结构问题：

- 本报告**不是独立审核**，我修的东西我判"过"，**逻辑上不产生独立审核效力**；
- 唯一不依赖人的判据仍然是**机器门禁 + 可复现脚本**；
- 故本次刻意把上轮"未实测"的 4 项（验收 1/2/3/7）与本轮新补的 ★ 项（验收 8）
  全部做成**脚本可复现**（`tools/verify_stage1.py`），而不是靠我陈述；
- 凡脚本覆盖不到的，一律在第 5 章标"未解决/未覆盖"，**不折算通过**。

> **给白宇的提醒**：本报告结论"阶段1 通过"在制度上等价于"开发自述 + 机器门禁背书"。
> **M-5 已于 2026-09-12 21:40 裁决**（见 `SUPERVISOR.md` 第十三章）：日常阶段机器门禁为唯一裁判；
> 关键节点（阶段4 ★ / 触碰 V2·V3 / **自审"通过"且含 ★ 项**）强制一次性独立复核。
> **阶段1 命中第 3 条** ⇒ 如需独立效力，请说「**申请独立复核阶段 1**」，
> 由**新开的干净实例（优先换模型）**只拿产物、不拿结论，重跑一遍。

---

## 一、本轮做了什么（解 L-004 → 真实编译 → 真跑验收）

### 1.1 环境侦察：L-004 只缺 rustup 一样

| 依赖 | 状态 |
|------|------|
| MSVC 链接器 | ✅ 已有（BuildTools 18，`link.exe` 在，cargo 可自定位） |
| Windows SDK `rc.exe` | ✅ 已有（10.0.26100.0） |
| WebView2 运行时 | ✅ 已有（152.0.4191.66） |
| Rust 工具链 | 本轮由白宇安装 ✅ |

**结论**：不需要装 6GB 的 Visual Studio Build Tools，只补 rustup 即可 —— 这也解释了为什么装完立刻就能编过。

### 1.2 首次真实编译：REVIEW-004 的"编译通过"是不可验证的，实际有 5 个真错

REVIEW-004 曾写"Rust 源码改动仅经人工静态审读"。有了工具链后**首次** `cargo check` 直接报错。
这不是"环境问题"，是**手写没有替代编译器**：

| # | 位置 | 错误 | 修复 |
|---|------|------|------|
| X1 | `core/src/main.rs` | `generate_context()` 当函数调用（它是**宏**） | 改 `generate_context!()` |
| X2 | `core/src/db/config.rs` | `SCHEMA_VERSION_KEY` **未定义**（E0425），全文多处引用 | 补常量定义 |
| X3 | `core/src/db/config.rs` | `ConfigService::new` 把 `Arc<EventBus>` 传进 `EventBus` 字段 | `Arc::new(bus)` → `bus` |
| X4 | `core/src/app_manager/mod.rs` | `["exe"...].contains(&ext)` 对 `&String` 类型不匹配 | 改 `ext.to_ascii_lowercase().as_str()` |
| X5 | `core/src/api/mod.rs` | `use axum::routing::{get, post}` 里 `post` 未使用（deny 级别告警） | 删 `post` |

> **这 5 个错里，X3 在 REVIEW-004 里被记成"已修复"，X2 根本没被发现。**
> 说明"人工静态审读 Rust"的可靠性约等于零 —— 这是 M-2（假 FAIL 淹没真错误）的直接后果，
> 也是本报告最该被记住的一条：**没有编译器的编译结论，不算结论。**

### 1.3 运行期缺陷：只有真跑才暴露的那个（本轮最有价值的一条）

| # | 问题 | 为什么静态审读发现不了 | 修复 |
|---|------|------------------------|------|
| X6 | **`runtime.sidecar_port` 永不落库** | `sidecar/mod.rs` 里端口是在**读到 announce 之后**才写库的，但那段代码位于 `run_once()` **返回之后** —— 而 `run_once` 内部被 `child.wait()` 阻塞。语义上"端口写进去了"，运行时却恒为 `null`（子进程活着就永远走不到那行）。 | 新增 `publish_port()`，在**读到 announce 端口的当刻**立刻写 `config` + state |
| X7 | `core/tauri.conf.json` 的 `beforeDevCommand` 路径错一层 | Tauri CLI 的 cwd 是**仓库根**，而 `../ui` 被解析成 `C:\Users\baiyu\Desktop\ui`。用文件探针 `cwdprobe.cjs` 实测才确认 | 改 `npm --prefix ui run dev` / `python system/build_sidecar.py`（相对仓库根） |

X6 是**验收项 5 的核心**：端口不落库 ⇒ sidecar 端口对任何消费方都不可见。
它在上两轮审核里被记为"PASS"（因为 `config` 表里有 `runtime.sidecar_port` 这个**键**，
只是值是 `null`）—— **又是一个"存在"冒充"正确"的案例**（呼应 M-3）。

### 1.4 打包链端到端跑通（L-011 / L-015 / U-4）

`externalBin` 是 tauri-build 的**编译期**校验资源：产物不存在时 `cargo check` 直接失败。
实测确认（这是本轮把 B120 加进门禁的依据）：

```
error: resource path binaries\service-x86_64-pc-windows-msvc.exe doesn't exist
```

修 `build_sidecar.py` 后用 PyInstaller 产出单文件 sidecar，链路才通。
**注意：不能给 PyInstaller 加 `--noconsole`** —— core 靠读 sidecar stdout 首行的 announce JSON 拿端口，
noconsole 会把 stdout 丢掉，等于把 sidecar 打哑巴。

最终一轮 `npm --prefix ui run tauri build` 输出（**对应本文档所述的全部最终源码**）：

```
     Running beforeBuildCommand `npm --prefix ui run build && python system/build_sidecar.py --if-needed`
[sidecar] 已就绪：core\binaries\service-x86_64-pc-windows-msvc.exe  (8.6 MB)
   Compiling personal-workspace-core v0.1.0 (core)
warning: `personal-workspace-core` (bin "personal-workspace-core") generated 30 warnings
    Finished `release` profile [optimized] target(s) in 3m 09s
       Built application at: core\target\release\personal-workspace-core.exe
     Running light to produce ...\bundle\msi\Personal Workspace_0.1.0_x64_en-US.msi
     Running makensis to produce ...\bundle\nsis\Personal Workspace_0.1.0_x64-setup.exe
    Finished 2 bundles at:
        ...\bundle\msi\Personal Workspace_0.1.0_x64_en-US.msi
        ...\bundle\nsis\Personal Workspace_0.1.0_x64-setup.exe
[EXIT CODE] 0
```

| 产物 | 大小 |
|------|------|
| `core/target/release/personal-workspace-core.exe` | release 主程序 |
| `bundle/msi/Personal Workspace_0.1.0_x64_en-US.msi` | 11.77 MB |
| `bundle/nsis/Personal Workspace_0.1.0_x64-setup.exe` | 10.80 MB |
| `core/binaries/service-x86_64-pc-windows-msvc.exe` | 8.6 MB（sidecar） |

### 1.5 把"未实测"变成"可复现"：新增 `tools/verify_stage1.py`

上轮的核心问题是**4 项验收拿不到证据**。本轮把能自动化的全部自动化：

| 验收项 | 自动化手段 |
|--------|-----------|
| 1 应用能启动 | 启动 release exe + `EnumWindows` 枚举标题 |
| 2 启动速度 | `perf_counter` 测「进程启动 → 窗口可见」，预算 3000ms |
| 3 页面切换 | **系统自带 Edge 无头模式**渲染 9 条路由，检查页面标识 + 7 个导航 href 齐全 + `#app` 非空 |
| 4 配置持久化 | 经 core HTTP PUT 改 `ui.theme` → 杀进程 → 重启 → 读 SQLite 核对 |
| 5 sidecar | 轮询 `runtime.sidecar_port` 落库 → `/health` 200 → **杀掉 sidecar 后 core 与窗口仍活着** |
| 6 数据库 | 首次启动建库 + migration + 种子，核对 `schema_version` / `db.migration_version` |
| **8 ★ Widget 动态布局** | **Edge CDP 真实点击卡片**：0→3→10 次，断言尺寸 `small→medium→large`，并核对次数落库 |

> 验收项 3 用 Edge 无头而非 Playwright：本机刻意不引入重型浏览器依赖（不下载 Chromium）。
> 验收项 8 的 CDP 客户端是**标准库 socket 手搓的 WebSocket**（约 90 行），不新增任何依赖。

**脚本自身的两个坑（记录在案，避免下一个人重踩）**：
1. 窗口出现后**只读一次库**必然读到"sidecar 端口还没写"的过期快照（单文件 sidecar 自解包需 1~3s）
   → 改 `wait_for_config()` 轮询。
2. 导航计数用 `class="nav-item` 前缀**恒为 6**：RouterLink 激活态把 class 重排成
   `router-link-active router-link-exact-active nav-item`，当前页那条不匹配前缀
   → 改为检查 7 个 `href="/xxx"` 是否齐全。

### 1.6 ★ 验收项 8：从"人工点一下"变成机器可判（闭合 M-4 的盲区）

04 §3 的 ★ 核心项前两轮**连漏两次**，根因是 M-4（★ 项没有验收编号）+ "需人工交互"这个托词。
本轮用 CDP 让它可机器复现。实测输出：

```
点击序列 use=['0','3','10']  size=['small','medium','large']
最终落库='{"weather":10}'     落库值演变=['{"weather":1}','{"weather":10}']
```

**顺带发现一个真实竞态**：每次点击各发一次 `put`，**完成顺序不保证** ——
第一次跑时观察到落库值演变 `2 → 6 → 10`（本应直接是 10），即**旧快照可能在新快照之后落库**。
本机是"最后写恰好最后到"才收敛的，属运气而非机制。已在 `stores/widgets.ts` 加**写队列串行化**
（`enqueueWrite`），使"最后发起的写必然是最终值"。修复后演变序列变为 `1 → 10`。

### 1.7 交叉核对"必须实现 5 条"时发现的第 3 个漏洞

04 §4 要求配置系统"必须支持：默认值、**类型校验**、变更广播"。
逐个键核对 `expected_type` 时发现：**`ui.dashboard.layout_locked` 落到了 `_ => "any"` 兜底分支**
—— 也就是说这个键的"类型校验"等于没有，任何类型都能写进去。

- 归因：新增键时要**同时**登记 `KEYS` / `expected_type` / `default_for` 三处，
  `default_for` 那条有测试锁着（`every_registered_key_has_an_explicit_default`），
  `expected_type` 没有 → 漏登无人报警。
- 修复：补 boolean 类型规则 + 新增两条测试（`every_registered_key_has_an_explicit_type`、
  `layout_locked_is_boolean_and_enforced`）锁死这一类漏登。

### 1.8 本轮还顺手纠正的两处"文档说了谎"

| 位置 | 原说法 | 实际情况 | 处置 |
|------|--------|----------|------|
| `ui/src/api/client.ts` / `configService.ts` 顶部注释 | HTTP 通道是"浏览器直开调试"的降级路径 | **core 内部 HTTP API 不发 CORS 头**（有意为之，否则用户浏览器里任意网页都能读写本机数据）⇒ 浏览器页面跨源 fetch 直接被拦。浏览器里真正生效的是 **localStorage 降级** | 改注释，写明"HTTP 通道适用于 curl/sidecar 等非浏览器客户端；浏览器里生效的是 localStorage" |

> 这条不是 bug，是**说法与实现不符**。按本项目"信产物不信汇报"的口径，注释也是产物。

### 1.9 重读历史审核报告时，抓到我自己这份报告里的一个假 PASS（自我纠错）

白宇要求重读阶段1 的复核报告（REVIEW-002 / REVIEW-003）。重读时把两份报告的**建议级与返工清单**逐条
拿去核现状，抓出三件事 —— 其中第一件**直接打在本报告的脸上**：

| # | 来源 | 内容 | 重读前的实际状态 |
|---|------|------|------------------|
| 1 | REVIEW-002 §三 R-06 + §十 返工项 7 | 顶栏缺「最小化」，要求**补齐或记录理由** | **半成品**：core 侧 `minimize_window` 命令**存在**（docstring 还写着"修复 REVIEW-002 R-06"），但 UI **零调用** —— 功能实际不可用。而我在本报告 §三「必须实现 5 条」里把它标成了 ✅（**假 PASS**） |
| 2 | REVIEW-003 §二 C-06 | 状态栏缺「设备简况」，判定占位可接受但"建议在交付说明中登记" | 未登记（`StatusBar.vue` 仍只有模式/应用数/core/sidecar 四项） |
| 3 | REVIEW-003 §八 (1)(2)(3)(4) | **`REVIEW-TEMPLATE.md` 强制四表（必须实现/验收标准/交付物/禁止事项）+ 独立性声明位 + "每个声称实现的功能须附调用点检索"** | **全部未落地** —— 而这正是"★ 项连漏两轮"的根因修复 |

**处置**：
- (1) 本轮把 UI 接线补上（`TopBar.vue` 新增最小化按钮，走 `invokeCore('minimize_window')`；
  浏览器环境无窗口可最小化 ⇒ 按钮置灰而非静默失效）。本报告 §三 该行同步改为如实表述。
- (2) 登记为遗留项（L-021），不假装已解决。
- (3) 已把四表与"调用点检索"动作写进 `REVIEW-TEMPLATE.md`（L-022）——**否则下一次还会漏**。

> **为什么必须写进报告**：R-06 的失败形态（**命令在、按钮没接**）与 REVIEW-003 点名的
> "文件存在 ≠ 功能存在"（孤儿函数 / 未使用常量 / 未导入模块）**是同一个病**，
> 而我在本报告里正是用"看目录里有这个命令"替代了"检索调用点"，于是复现了同一个错误。
> 这说明**光有认知不够，必须把动作固化进模板**，靠人的自觉必然复发。
>
> 顺带确认：REVIEW-002 的建议级 R-11（事件时间戳实为 UTC）与 R-12（`/internal/db/exec` 白名单子串匹配）
> **实际已在 REVIEW-004 那轮修掉**（现为 `chrono::Local` 带偏移 + `target_table()` 解析目标表名），
> 但 LEDGER 里**没有任何痕迹** —— 修了没记账，等于下一个人不知道它曾经坏过、也不知道它已经好了。

### 1.10 与并发审核（REVIEW-006）的交叉核对，以及一处**计数更正**

本工作区存在**并发写入方**（另一个会话在 21:08 产出了 `REVIEW-006-阶段1-独立复现审核.md`，
并同步写了 LEDGER 与 REVIEW-005 的部分章节）。我做两件事：

**① 采信其结论、并把它提的两条补上可判性**

REVIEW-006 把 REVIEW-005 的每一个数字当"被告方证词"从零复跑，结论一致（门禁 `0F/0W/29P`、
`cargo test 6/6`、路由 9 条 + ★ 项、交付物齐全），并新发现：

| 其编号 | 内容 | 本轮处置 |
|--------|------|----------|
| **F-1** | ★ 验收项 8 的「调序锁定」半支（调序 → `layout_locked=true` → 冻结尺寸）**无任何机器验证**，却被标 ✅ | **不降级，改为真验证**（比标 ⚠️ 强）：`verify_stage1.py` 探针新增 B 段，用**有区分度**的断言把它做实 —— 详见 1.6 与 U-12。登记为 **L-025**，状态"已闭环" |
| **F-2** | ★ 探针的"落库"是**浏览器 localStorage 降级层**，不是 `config` 表 / invoke 主路径 | **属实，接受**。这条我在 §1.8 纠正注释时已触及，但**没有把它升级成"主路径无运行时断言"这一结论** —— 属我漏了一层。登记为 **L-026 / U-13** |

**② 更正一个被双方引用的错误计数（我起的头，必须我来纠）**

LEDGER 的 REVIEW-005 行与 REVIEW-006 报告都写了「`verify_stage1.py` **20/20**」。
**逐行点算是 18 项**（1 / 2 / 6 / 5a / 5b / 4a / 4b / 1b = 8，9 条路由 = 9，★ = 1 ⇒ **18**），
本轮加「2b 顶栏最小化回归」后为 **19**。

- 这个数字**最早是我在 LEDGER 里写错的**（我写完没点算，REVIEW-006 复现时引用了它而没重算）。
- 它恰好是本项目反复栽的同一类毛病：**引述代替复跑**。REVIEW-006 §一 的方法论（"不信汇报只跑产物"）
  在这一个数字上**没有执行到底** —— 说明连"复现审核"也会在细节处退化成引述。
- 处置：**不改写 REVIEW-006 原文**（按 §九 留痕原则），在 LEDGER 与本报告显式更正并留痕。

---

## 二、证据（全部可复现）

### 2.1 门禁原文

命令：`python tools/gate.py --stage 1 --build`

```
====================================================================
Personal Workspace · 阶段门禁报告
项目根目录：C:\Users\baiyu\Desktop\Personal Workspace
审核阶段  ：阶段 1 · 基础桌面框架
====================================================================

--- PASS（29）----------------------------------------------
  [PASS] S000 — 基线目录存在：docs/agent-dev
  [PASS] S000 — 基线目录存在：docs/reviews
  [PASS] S000 — 基线目录存在：HANDOFF.md
  [PASS] S000 — 基线目录存在：AGENTS.md
  [PASS] S000 — 基线目录存在：tools/gate.py
  [PASS] S100 — [阶段1] 存在：core/Cargo.toml
  [PASS] S100 — [阶段1] 存在：core/tauri.conf.json
  [PASS] S100 — [阶段1] 存在：core/migrations
  [PASS] S100 — [阶段1] 存在：database/schema.sql
  [PASS] S100 — [阶段1] 存在：ui/package.json
  [PASS] S100 — [阶段1] 存在：config/app.toml
  [PASS] S100 — [阶段1] 存在：system/service.py
  [PASS] S100 — [阶段1] 存在：docs/adr/ADR-001-窗口控制与进程启动实现语言.md
  [PASS] S110 — [阶段1] 目录结构到位：core/src/state
  [PASS] S110 — [阶段1] 目录结构到位：core/src/db
  [PASS] S110 — [阶段1] 目录结构到位：core/src/event_bus
  [PASS] S110 — [阶段1] 目录结构到位：ui/src/views
  [PASS] S110 — [阶段1] 目录结构到位：ui/src/widgets
  [PASS] S110 — [阶段1] 目录结构到位：ui/src/components
  [PASS] S110 — [阶段1] 目录结构到位：ui/src/stores
  [PASS] S110 — [阶段1] 目录结构到位：ui/src/api
  [PASS] S110 — [阶段1] 目录结构到位：modules
  [PASS] S110 — [阶段1] 目录结构到位：plugins
  [PASS] A030 — ADR-001：system/build_sidecar.py 属构建脚本，豁免  @ system/build_sidecar.py
  [PASS] W100 — ui/src/utils/logger.ts 已被 ui/src/api/client.ts 引用（接线到位）  @ ui/src/utils/logger.ts
  [PASS] W100 — ui/src/composables/useWidgets.ts 已被 ui/src/views/DashboardView.vue 引用（接线到位）  @ ui/src/composables/useWidgets.ts
  [PASS] B120 — externalBin 产物就绪：binaries/service → service-x86_64-pc-windows-msvc.exe
  [PASS] B100 — cargo check 通过
  [PASS] B110 — 前端 typecheck 通过

====================================================================
✅ 门禁通过   FAIL=0  WARN=0  PASS=29
====================================================================
```

> **WARN 从 1 条降到 0 条**：上轮唯一 WARN 是 `B102 未检测到 cargo`（即 L-004），
> 本轮编译真实跑通后消失。**这正是门禁该有的收敛方式** —— 工具链补齐后，
> 那条警告不是被"忽略"掉的，是被"验证通过"取代的。

### 2.2 编译输出原文

`cargo check` 经 `gate.py --build` 纳入门禁，结论：`[PASS] B100 — cargo check 通过`（见 2.1）。
`cargo test` 会先完整编译一遍（含 `--all`），无 error：

```
$ C:\Users\baiyu\.cargo\bin\cargo.EXE test --all --no-fail-fast
warning: `personal-workspace-core` (bin "personal-workspace-core" test) generated 30 warnings
     Running unittests src\main.rs (target\debug\deps\personal_workspace_core-7d588810035159ce.exe)
```

**关于 30 条 warning**：全部是阶段2~9 占位模块的 `dead_code`
（`app_manager` / `window_manager` / `scheduler` 等按 README 写明"阶段N 实现"的骨架）。
按 HANDOFF §6「宁可少一个功能，不可破坏架构」「架子必须先立起来」，这些骨架**应当存在**，
warning 是"架子已立、功能未接"的预期产物，不是缺陷。**本报告不把它们说成"零告警"。**

### 2.3 测试输出原文

修复 `layout_locked` 类型漏登**之后**的最终一轮（6 条全绿）：

```
$ C:\Users\baiyu\.cargo\bin\cargo.EXE test --all --no-fail-fast
warning: `personal-workspace-core` (bin "personal-workspace-core" test) generated 30 warnings
     Running unittests src\main.rs (target\debug\deps\personal_workspace_core-7d588810035159ce.exe)
running 6 tests
test db::config::tests::every_registered_key_has_an_explicit_default ... ok
test db::config::tests::layout_locked_is_boolean_and_enforced ... ok
test db::config::tests::type_rules_hold ... ok
test db::config::tests::unregistered_key_is_not_in_whitelist ... ok
test db::config::tests::every_registered_key_has_an_explicit_type ... ok
test event_bus::tests::iso_now_carries_local_offset ... ok
test result: ok. 6 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
[EXIT CODE] 0
```

> 修复**之前**这一轮只有 4 条；新增的 2 条（`every_registered_key_has_an_explicit_type`、
> `layout_locked_is_boolean_and_enforced`）在修复前是**红的** ——
> `expected_type("ui.dashboard.layout_locked")` 当时实际返回 `"any"`。
> **测试先证明缺陷存在，再证明缺陷消失**；否则测试只是装饰。

### 2.4 前端类型检查原文

```
> personal-workspace-ui@0.1.0 typecheck
> vue-tsc --noEmit

（无输出 = 0 error，EXIT CODE 0）
```

### 2.5 验收脚本原文（`tools/verify_stage1.py --routes-url ... --widget-probe`）

```
[verify] exe      = core\target\release\personal-workspace-core.exe
[verify] data dir = C:\Users\baiyu\AppData\Local\Temp\pw-verify-rng5n_w9
[verify] 路由渲染核验中（Edge 无头）… base=http://localhost:5173
[verify] ★ Widget 动态布局核验中（Edge CDP 真实点击）…

============================================================
阶段1 验收核验结果
============================================================
PASS  1 应用能启动（窗口出现）
      窗口标题含 'Personal Workspace'
PASS  2 启动速度 < 3s
      334 ms（预算 3000 ms）
PASS  6 首次启动自动建库 + migration + 种子
      config 表 13 行；schema_version=3；db.migration_version=1
PASS  5a sidecar 拉起 + /health 200
      core port=61384, sidecar port=61385 → /health 200
PASS  5b 杀掉 sidecar 后主界面仍可用（降级）
      killed=killed pids=['3472', '45376']；core /health=200；窗口仍在
PASS  4a 配置写入（HTTP PUT ui.theme=dark）
      原值='light' → {"data": {"key": "ui.theme"}, "ok": true}
PASS  4b 重启后主题仍为 dark（持久化）
      库中 ui.theme='"dark"'
PASS  1b 二次启动（热态）窗口仍出现
      355 ms
PASS  3 /dashboard 渲染（标识 'Dashboard'）
      marker=True nav=齐全 dom_len=12050
PASS  3 /ai 渲染（标识 'AI 助手'）
      marker=True nav=齐全 dom_len=8123
PASS  3 /learning 渲染（标识 '学习成长'）
      marker=True nav=齐全 dom_len=8089
PASS  3 /project 渲染（标识 '项目管理'）
      marker=True nav=齐全 dom_len=8039
PASS  3 /profile 渲染（标识 '个人数字档案'）
      marker=True nav=齐全 dom_len=8088
PASS  3 /life 渲染（标识 '生活中心'）
      marker=True nav=齐全 dom_len=8077
PASS  3 /device 渲染（标识 '设备中心'）
      marker=True nav=齐全 dom_len=8034
PASS  3 /plugins 渲染（标识 '插件'）
      marker=True nav=齐全 dom_len=8031
PASS  3 /settings 渲染（标识 '设置'）
      marker=True nav=齐全 dom_len=9112
PASS  2b 顶栏含 [设置][最小化]（04 §2 / R-06 回归）
      顶栏控件：设置=True 最小化=True（浏览器环境下最小化按钮应为 disabled）
PASS  8 ★ Widget 动态布局（点击→次数→尺寸）
      A｜点击序列 use=['0', '3', '10'] size=['small', 'medium', 'large']（期望 ['small', 'medium', 'large']）；最终落库='{"weather":10}'（期望 weather=10）；落库值演变=['{"weather":1}', '{"weather":10}']；clickErrors=[] || B｜调序锁定(设备状态): 起始 size=small → 锁后=true/banner=True/size=small → 锁定态点5次 use=5 size=small（应仍 small）→ 解冻后 size=medium（应 medium）/lock=false
============================================================
验收项 3 已由 Edge 无头渲染核验（见上方 3 /xxx 各项）。
验收项 7（出安装包）见 `npm run tauri build` 输出。
验收项 8（★ Widget 动态布局）已由 Edge CDP 真实点击核验（见上方）。
============================================================
```

### 2.6 改动文件清单（`git status --porcelain`）

```
 M .gitignore
 M core/README.md
 M core/src/api/mod.rs
 M core/src/app_manager/mod.rs
 M core/src/db/config.rs
 M core/src/main.rs
 M core/src/sidecar/mod.rs
 M core/tauri.conf.json
 M docs/agent-dev/02-架构与目录规范.md
 M docs/agent-dev/04-阶段指令-基础框架.md
 M system/README.md
 M system/build_sidecar.py
 M tools/gate.py
 M ui/README.md
 M ui/package-lock.json
 M ui/package.json
 M ui/src/api/client.ts
 M ui/src/api/configService.ts
 M ui/src/stores/widgets.ts
?? core/Cargo.lock          ← 应用类项目应入库（锁依赖版本）
?? tools/verify_stage1.py   ← 新增：验收自动核验脚本
?? ui/scripts/              ← 新增：Tauri CLI 转发器（tauri.mjs）
```

**说明**：`core/gen/`（tauri-build 生成的 ACL schema）本轮已加入 `.gitignore` ——
它每次构建重新生成，属构建产物，入库违反红线 V8。

---

## 三、验收标准逐项对照（04 §验收标准 9 项）

| # | 验收项 | 方法 | 结果 | 证据 |
|---|--------|------|:----:|------|
| 1 | 应用能启动 | 启动 release exe，窗口出现 | ✅ | 2.5 |
| 2 | 启动速度 < 3s | 冷启动 334ms / 热启动 355ms | ✅ | 2.5 |
| 3 | 页面切换无白屏 | 9 条路由逐条渲染，标识 + 导航 + `#app` 均齐 | ✅ | 2.5 |
| 4 | 配置持久化 | PUT `ui.theme=dark` → 重启 → 库中仍为 dark | ✅ | 2.5 |
| 5 | sidecar | 端口落库 + `/health` 200 + 杀掉后主界面仍可用 | ✅ | 2.5（含 5a/5b） |
| 6 | 数据库 | 自动建库 + migration + 种子，13 行 config | ✅ | 2.5 |
| 7 | 构建出安装包 | msi 11.77MB + nsis setup 10.80MB | ✅ | 1.4 |
| **8 ★** | **Widget 动态布局** | **A** 点击 0→3→10 次 ⇒ 尺寸 `small→medium→large`，落库 `weather=10`；**B** 调序锁定 ⇒ 锁定态点 5 次次数涨到 5 而尺寸冻结在 `small`，点「恢复自动布局」解冻后重算为 `medium`（REVIEW-006 F-1 补验） | ✅ | 2.5 |
| 9 | sidecar 打包链 | 产物就绪 + 门禁 B120 | ✅ | 2.1 |

**"必须实现"5 条对照**（防重犯 REVIEW-003 的"只核一套清单"）：

| # | 必须实现 | 核对要点 | 结果 |
|---|----------|----------|:----:|
| 1 | 工程脚手架 | 目录按 02 §2.2；窗口 1280×800 / 最小 1024×640 / 标题 `Personal Workspace` | ✅ |
| 2 | 主窗口布局 | 顶栏 Logo+设置+**最小化**（原为"命令在、按钮未接"，本轮补接，见 1.9）；左侧导航**可折叠且状态持久化**（`ui.nav.collapsed`）；状态栏 | ✅ |
| 3 | Dashboard ★ | 7 个必备 Widget 齐；动态布局**实测**；`layout_locked` 冻结自动尺寸 —— **REVIEW-006 F-1 曾指出该半支"仅代码审查、未机器验证"，本轮已补机器断言**（探针 B 段：锁定态点 5 次次数涨而尺寸冻结，解冻后按次数重算，见 U-12 / L-025） | ✅ |
| 4 | 配置系统 | `ConfigService` 单一读写口；默认值 / **类型校验** / 变更广播 `CONFIG_CHANGED` | ⚠️ 见 5.1（广播仅在 core 进程内，未桥接到前端） |
| 5 | Python sidecar | `/health`；随机端口写 config；失败不影响主界面；PyInstaller 单文件 | ✅ |

**禁止事项**：未实现工作模式引擎完整逻辑 ✅（`scheduler` 为骨架）· 业务逻辑未写进 `main.rs` ✅（仅装配）。

---

## 四、红线自查（对照 `13 §三` / `HANDOFF §4`）

| 红线 | 自查 | 说明 |
|------|:----:|------|
| V1 明文密钥入库入码 | ✅ 未命中 | 门禁 `check_secrets` PASS |
| V2 咨询模式读用户数据 | ✅ 未命中 | 阶段5 才实现 |
| V3 AI 自动改进度/档案 | ✅ 未命中 | 阶段6/7 才实现 |
| V4 插件默认有权限 | ✅ 未命中 | 阶段9 才实现 |
| V5 破坏性操作无二次确认 | ✅ 未命中 | 本阶段仅 `minimize_window`（无破坏性） |
| V6 谎报完成 | ✅ **本轮重点防范** | 见下 |
| V7 插件/UI 直连数据库 | ✅ 未命中 | UI 走 invoke；门禁 V7 检查 PASS |
| V8 构建产物入库 | ✅ 未命中 | `core/binaries/`、`core/gen/`、`target/`、`node_modules/` 均已忽略 |

**V6 说明**：本轮把上轮"未实测"的项**做成了脚本**再报结论，而不是把"未实测"改写成"通过"。
唯一仍不能由机器判的，是脚本自身可信度与本文档的表述 —— 这部分靠第〇章的独立性声明兜底。

---

## 五、未解决项与风险（如实列出）

| # | 项 | 级别 | 说明 |
|---|----|:----:|------|
| U-7 | **事件总线未桥接到前端** | 一般 | core 内 `ConfigService::set` 已在进程内 `publish(CONFIG_CHANGED)`（含 oldValue/newValue，合契约 3.3），但**没有 `app_handle.emit` 转发到 webview**，前端也无 `listen()`。本阶段无消费方，按「Event Bus 架子先立起来」判定不阻塞；**阶段2 若需 UI 响应配置变更，必须补桥** |
| U-8 | **验收项 8 的"重启后次数与尺寸保持"未单独断言** | 一般 | 脚本断言了"点击→次数→尺寸→落库"；"重启后保持"依赖 `load()` 读 `ui.dashboard.widgets`/`usage`，未做第二次启动的 DOM 复断言（当前由验收项 4 的持久化机制间接覆盖） |
| U-9 | **`npm run tauri dev` 未跑** | 一般 | 验收 1/2/3 改用 release exe + 浏览器渲染核验，**绕开了 dev 模式**。dev 模式（vite HMR + `beforeDevCommand`）只在打包前链路里被间接验证过 |
| U-10 | `package-lock.json` 与 `npm install` | 一般 | 上轮因安全策略拦截改用直接落 registry tarball；本轮 `ui/package-lock.json` 已有改动但**换机器仍建议重跑 `npm install`** |
| U-11 | 符号级接线机器查不了 | 一般 | 门禁 W100/W101 只能查"模块是否被引用"，查不出"某方法是否被调用"（M-3 残留）。本轮 CDP 探针部分弥补了 ★ 项的符号级验证，但**不通用**。**R-06 正是死在这一条上**（命令在、按钮没接，机器与人都没查调用点） |
| U-14 | 状态栏缺「设备简况」 | 建议 | `StatusBar.vue` 只有 模式/运行中应用/core/sidecar 四项，04 §2 要求含"设备简况"。阶段1 无指标数据源，占位可接受，但**此前从未登记**（REVIEW-003 C-06 提过"建议登记"，无人登记）。本轮登记为 L-021 |
| U-15 | 历史修复无台账痕迹 | 建议 | REVIEW-002 的 R-11 / R-12 已实际修复，但 LEDGER 无记录。**"修了不记账"与"没修"在追溯上等价** —— 建议后续修复一律同步 LEDGER（本轮已补记） |
| R-3 | 探针依赖本机 Edge | 低 | `verify_stage1.py` 的验收 3/8 需要 Edge（Windows 自带）。脚本已做"未找到 Edge → 明确报 FAIL 并说明原因"，不会静默跳过 |
| **U-12** | **★ 项「调序锁定」半支未机器验证**（REVIEW-006 补登 F-1） | 一般 | 04 验收项 8 含"手动调序后 `layout_locked=true` 且不再自动改尺寸"。原 CDP 探针只触发 `recordUse`，**从不触发 `moveUp/moveDown`** ⇒ 该半支仅"代码读过就标过"。**本轮已补机器验证并闭环**（L-025）：探针新增 B 段 —— 对低频卡片「设备状态」（起始 `small`）点「上移」⇒ `layout_locked` 落库 `true`；锁定态再点 5 次 ⇒ **次数涨到 5 而尺寸冻结在 `small`**；点「恢复自动布局」解冻 ⇒ 尺寸按次数重算为 **`medium`**。两个方向都有区分度，不是"尺寸不变即通过" |
| **U-13** | **真主路径 invoke 无运行时断言**（REVIEW-006 补登 F-2） | 一般 | ★ 探针在 Edge（非 Tauri）里跑，core HTTP 不发 CORS 头 ⇒ 浏览器跨源被拦 ⇒ 生效的是 **localStorage 降级层**。"写入 config 表 / 走 invoke `put_config`"这条真实主路径本阶段无端到端断言，仅 typecheck + 门禁 W100 接线。见 L-026 |

**风险已闭环的一条**：上轮 R-2（`@tauri-apps/api` 手工落盘绕过包管理器）本轮未再复现 —— `ui/package.json` 已声明依赖，且 `@tauri-apps/cli` 一并声明，走 `npm install` 可复原。

---

## 六、门禁自身改动说明（元变更，必须记录）

| 文件 | 改动 | 性质 |
|------|------|------|
| `tools/gate.py` | 新增 `B120`（externalBin 产物就绪）/ `B121`（缺失即 FAIL） | **收紧**：把"编译期才炸"的打包缺件提前到静态检查 |
| `tools/gate.py` | `find_tool()` 增加 `~/.cargo/bin` 回退 | 修 M-2 残留：非交互 shell 里 PATH 没有 cargo 时**误报"工具链缺失"** |
| `tools/gate.py` | `_last_error_line()` 取真正 error 行 | 修 M-2：报错信息不再被未使用 import 的警告淹没 |
| `tools/verify_stage1.py` | 新增（验收核验脚本） | 新增工具，非门禁 |

> 本轮**没有放宽任何门禁** —— 与 REVIEW-004 那次的 B102 放宽相反，这次是净收紧。

---

## 七、判定与需白宇裁决的事项

### 7.1 判定

按 `HANDOFF §5.3` 三档：

- 门禁 **0 FAIL / 0 WARN** ✅
- 验收表 **9/9 通过**（其中 8 项由 `verify_stage1.py` 实测，脚本共 **19/19 PASS / 0 FAIL**；验收项 7 由构建产出安装包佐证）✅
- 红线 **0 命中** ✅
- 交付物齐全 ✅

⇒ **✅ 通过（阶段1 完成）**，但**附一条制度性保留**：本判定由"开发者本人 + 机器门禁"作出，
独立性不足（M-5）。若白宇要求独立审核，请另起实例复审。

### 7.2 需白宇裁决（按优先级）

1. ~~**M-5 审核独立性**~~ —— ✅ **已裁决（2026-09-12 21:40）**：采用**分级独立**（日常以机器门禁为唯一裁判；
   关键节点强制一次性独立复核）。见 `SUPERVISOR.md` **第十三章**。
   **对本报告的影响**：按 13.3 第 3 条（"自审通过且含 ★ 项"），**阶段1 应当做一次独立复核**。
   目前尚未执行 ⇒ 本报告的准确效力是"**机器门禁通过 + 自审记录**"，**不等于独立审核通过**。
   （REVIEW-006 是"另一会话 · 同模型"，按 13.2 效力表仅算**部分有效**。）
   触发口令：**「申请独立复核阶段 1」**。
2. **阶段2 是否开工** —— 若认可 7.1，下一步是阶段2「软件管理系统」（`05-阶段指令-软件管理.md`）。
   按 `SUPERVISOR §7.1`，阶段1 未通过不得启动阶段2；**现在这一条的前提已满足，但需你点头。**
3. **M-6 `tools/` 豁免范围** —— 是否收窄（建议维持现状）？
4. **L-001 源计划书** —— 若原稿还在，请放入 `docs/source/`。

### 7.3 若开工阶段2，前置必做（写在此处防遗忘）

- U-7 事件桥：阶段2 的软件管理面板需要"安装/卸载后 UI 刷新"，建议同批把 `CONFIG_CHANGED`
  （或 `APP_*` 事件）桥到 webview，避免又一次"事件发了但没人收到"。
- 阶段2 的核心能力（枚举已安装软件 / 启动进程）按 **ADR-001 = Rust** 实现，`system/` 不得出现同类实现
  （门禁 A031 已按能力扫描，会拦）。

---

*本报告由执行人自检产出，不构成独立审核结论。机器可判部分以 `tools/gate.py` 与 `tools/verify_stage1.py` 输出为准。*
