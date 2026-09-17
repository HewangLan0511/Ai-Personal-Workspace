# HANDOFF.md —— Personal Workspace 项目交接总入口

> **如果你是一个刚接手本项目的 Agent，这是你该读的第一个文件。**
> 读完本文件，你只需要再读 3 个文档就能开工。
> 最后更新：2026-09-15 · 维护人：项目监制（肉编器001号）

---

## 0. 30 秒搞清楚状况

| 问题 | 答案 |
|------|------|
| 这是什么项目 | **Personal Workspace** —— 一个本地优先、AI 增强、插件可扩展的个人智能工作空间 |
| 目标是解决什么 | 让电脑从"工具集合"变成"以任务目标为中心、自动组织软件/窗口/AI/信息"的调度中心 |
| 现在的阶段 | **阶段0~9 全部 ✅ 通过，项目阶段全部收官**（阶段1 REVIEW-005 / 阶段2 REVIEW-008 / 阶段3 REVIEW-009 / **阶段4 ★ 核心 REVIEW-011** / **阶段5 REVIEW-013** / **阶段6 REVIEW-014** / **阶段7 REVIEW-015** / **阶段8 REVIEW-016** / **阶段9 REVIEW-017**）。<br>后续工作 = 维护 / 遗留项清理 / 白宇提出的新需求（无预设阶段指令）。 |
| 工作区已有 | **完整可编译可运行的代码**：`core/`（Rust 核心，Tauri 2.x：框架 / 软件库 / 窗口管理 / 工作模式引擎 / AI 转发与事件桥 / 学习成长与项目 / 个人数字档案 / 生活中心与设备中心 / **插件宿主与权限网关 / 外部 Agent 网关 / 桌面小组件**）、`ui/`（Vue3 + TS，含模式/软件/布局 + AI 侧栏 + 学习页/项目页/档案页/生活页/设备页/**插件管理页/小组件窗口**）、`plugins/`（示例插件×2：番茄钟 / 音乐）、`system/`（Python sidecar，PyInstaller 单文件）、`ai/`（Python：Provider 抽象 + 提示词 + 上下文装配）、`tools/gate.py`（门禁）、`tools/verify_stage{1..9}.py` + `verify_stage5_stream.py` + `verify_sidecar_bundle.py`（验收自动核验）、`docs/plugin-dev-guide.md`（插件开发指南）。 |
| 谁负责审核 | 监制「肉编器001号」。**未经审核通过，不得进入下一阶段。** |
| 你现在该做的 | 读 `docs/reviews/LEDGER.md` 确认阶段0~9 全部通过 → **无预设待办阶段**；接新需求时先跑基线（`gate.py --stage 9 --build` 应 0F/0W）再动代码；遗留项清单见 LEDGER |

**当前进度唯一真相来源**：`docs/reviews/LEDGER.md`（不是任何人嘴里的进度）

### ⚖️ 审核规则已收敛（2026-09-12 22:32 / 22:35，白宇指令）—— **务必先读**

这是本项目最容易踩的制度坑：**规则本体一度停留在旧版严格口径，而台账已收敛**。
现 `SUPERVISOR.md` 已同步，口径如下：

| 项 | 现行口径 |
|----|----------|
| **验收唯一标准** | **目标达成 + 无致命漏洞（红线/数据安全/不可恢复架构错误）+ 无冗余垃圾**。硬判据（门禁 0 FAIL + 验收脚本全 PASS + 红线未命中）满足即判通过 |
| **不逐条抠验收表** | 看阶段指令的「目标」与「验收一句话」，达成即算实现 |
| **不主动挖掘** | 不再逐项检索建议级问题。**只有阻塞下一阶段的才登记**，其余"记录在案·不处理" |
| **报告收敛** | 报告只写 3 项：**判定+理由 / 硬证据 / 阻塞项**。不写长篇分析、不做历史数字对账 |
| **独立复核** | **仅白宇口令「申请独立复核阶段 N」时执行**，不自动发起、不阻塞推进。阶段4 已裁定**豁免**（见治理记录 2026-09-13） |
| **"有条件通过"档** | 已停用。统一写"通过（N 项记录在案）" |
| **仍严的区域** | ①**§三·附 强制调用点检索**（零调用 = 未接线 = 功能不成立，是唯一能兜住"存在≠功能"的机制）②**§〇 独立性声明位**（标注效力等级）③**红线 V1~V8**（一票否决不商量）④**V6 谎报**（做不到的必须写"未实测"，冒充已验证 = 驳回） —— **这四项不属收敛对象** |

---

## 1. 你现在的具体任务

如果你是被叫来"继续开发"的，你的任务是：

```
当前任务 = PW-INTEGRATION 整合阶段 · 已完成 003 Contract Freeze ✅（只冻契约，零业务实现）
          （报告 docs/reviews/PW-INTEGRATION-003-contract-freeze.md · 契约门禁
            tools/verify_contracts.py 6/6 · schema docs/contracts/workspace-snapshot.v1.schema.json）
          上一节点 = PW-INTEGRATION-002 Preflight（只设计）· 001 整合前架构审计（只分析）
冻结口径 = ①Workspace Resize = 外部软件窗口（复用 windows_place，零 Core 新增命令）
          ②Snapshot 持久化走 config 键 workspace.snapshot.last（零 migration，0009 留后）
          ③AI Provider canonical = core config ai.provider.current（localStorage 降缓存）
          ④"完成工作" 登记 PD-001，不实现
下一步   = **等产品侧确认 UI-04**（UI Skill 正在做真实体验优化）。期间只做"安全区"：
          config 三键登记 / AI current 读写投影 / 快照采集骨架 / 契约门禁纳回归 / docs。
          UI-04 交付后按 IP1 浮层统一 → IP2 Provider 收口 → IP3 Motion → IP4 Skin → IP5 快照
          → IP6 双通道 → IP7 安全加固 推进；IP8 只设计不编码
接新需求时 = 先跑基线 `python tools/gate.py --stage 9 --build`（应 0F/0W）· `cargo test`(86/86) ·
             回归四件套 `tools/verify_tech01.py`(9/9) · `verify_skin_engine.py`(12/12) ·
             `perf_tech01_22.py`(14 窗口 0 Long Task) · `verify_contracts.py`(6/6)
```

### PW-INTEGRATION 已冻结内容（一句话）

**边界设计优秀但底座空转，先把边界冻成可校验的契约再动代码** —— Motion/Skin 底座
（验收 9/9、12/12 全过）在业务层**零消费**；浮层三套自造；核心链路进入侧全 REAL、
退出恢复仅内存。003 把四决策转成 Contract：Snapshot v1（schema + 正反 fixture +
`additionalProperties:false` 的 v2 越界判据）、AI Provider 五层
（canonical/cache/suggestion/headless-default/transport）、ExternalWindowResize
（零 Core 新增）、Toast 统一形态。**契约已冻结，等 UI-04 定稿后进入 IP1。**

### TECH-01 已交付内容（一句话）

**UI 有了统一的地基，Skin 未来只换皮不换骨** —— Design Token 分层
（Foundation→Semantic→Legacy 桥接，存量样式零改动接入）+ Motion Runtime
（四 Guard + Interactive Gate + Page Transition latest-wins + Workspace Cinema 原语 +
VT 渐进增强），Duration 与 Intensity 解耦、安全规则固化不可被 Skin 绕过。
验收 9/9（Edge headless + CDP 实测）。组件规约见 `docs/tech/motion-runtime.md` §五。

### 阶段9 已交付内容（一句话 · 已审核通过）

**插件与外部能力进入工作空间，但权限收口在 core** —— 插件 JS 跑在无同源沙箱 iframe（V7 结构级保证），
manifest 声明权限、默认零权限（V4）、一切能力经 core 网关并审计；桌面小组件是独立 Tauri 窗口；
外部 Agent 走 core 网关，`mode.switch` 逐次强制 confirm（V5）。★ 判据「新增插件零核心代码改动」
由番茄钟/音乐两个示例插件不改一行 core 实测通过。开发指南见 `docs/plugin-dev-guide.md`。

### 阶段8 已交付内容（一句话）

**电脑的物理环境与使用习惯纳入工作空间** —— 天气（手动城市、绝不自动定位）+
前台使用时间采样聚合（`usage_stats` 三列表）+ SMTC 音乐（可选依赖，缺失即降级）+
社交概览（仅未读数，密码走 keyring）+ 纯 Win32 设备指标/进程管理/结束进程双闸（红线 V5）。
生活/设备以 core 模块交付，插件化迁移是阶段9 范围（12 §验收11）。

### 阶段7 已交付内容（一句话）

**AI/系统只建议，用户拍板入档** —— 档案四表 + 待确认建议队列（部分唯一索引防刷屏）+
4 类采集触发点 + 分组技能条形图/竖向时间线 UI + Markdown 导出（只含已确认条目）。
红线 V3 由"表级边界 + 四表快照比对"落实；红线 V2 由 core `is_data_allowed` + sidecar
`assemble` 双闸落实，两侧均有机器证据。

### 阶段6 已交付内容（一句话）

**AI 规划，用户执行，系统提醒** —— 目标/路线/更新三表 + 严格 JSON 路线生成与降级 +
提醒调度（阈值 30 天可配、7 天冷却、可关闭）+ 项目 CRUD 与「绑工作模式 / 挂学习目标」联动。
**AI 建议不写库**（红线 V3）由函数边界保证，并由 `tools/verify_stage6.py` 验收项 6 端到端断言。

### ⚠️ 接手第一步（**勿跳步**）

```bash
python tools/gate.py --stage 9 --build        # 先确认当前基线 0F/0W
python tools/rust.py test                     # 预期 86/86（阶段9 新增 9 个）
python tools/rust.py build --release          # 验收脚本要跑 release 产物
python tools/verify_stage9.py                 # 阶段9 验收 11 组（自起 core + mock Agent）
```

阶段5 收尾时暴露的三个"静默失真"缺陷（详见 `REVIEW-013` §2.4）已经修完并留了机器守护：

| 缺陷 | 守护方式 |
|------|----------|
| `PW_SIDECAR_FORCE_DEV=1` 形同虚设（开关没接线） | `core/src/sidecar/mod.rs` 改为**真的 return**；强制态找不到脚本时**报错而非静默降级** |
| 发行态 `/ai/chat` 报「模板不存在」（`.md` 没进包） | `build_sidecar.py` 加 `--add-data`；门禁 **B134** 静态守护；`tools/verify_sidecar_bundle.py` 发行态实测 |
| `ui.ai.*` 五键未登记 → 前端零调用 | core `config.rs` 登记三处 + 契约 03 §3.1.1；前端 `persist()` **双写**（localStorage + `put_config`） |

> 💡 **为什么这件事值得写在最显眼处**：本项目 **Python 侧有 PyInstaller 快照、Rust 侧有 release 二进制，
> 两层都有滞后**。「改了源码」≠「改了被测物」—— 阶段5 排查时踩到的正是这个：
> 我加的反制开关**因为没接线而根本没生效**，症状与它要防的 bug 一模一样。
> **任何"验收/测试"都必须在最终产物上跑一次**，别拿开发态的绿色当交付证据。

**ADR-001 已定稿**（`docs/adr/ADR-001-窗口控制与进程启动实现语言.md`）：窗口控制与进程启动 = **Rust**，Python 不得再实现一份。
门禁 `A031` 按**能力名**扫描 `system/`（只匹配 `SetWindowPos`/`EnumWindows`/`CreateProcess` 等**具体 API 名**，
**不**按 `user32`/`shell32`/`ctypes` 这类库名匹配 —— 否则会误伤图标提取等正当用途）。

> 事件总线已桥接到前端（阶段5 补完，L-017/L-032 闭环）：core `event_bus/mod.rs::bridge_to_webview` ← `main.rs:56`，
> 前端 `api/eventBridge.ts` 订阅 `pw://event`。**后续阶段的实时 UI 反馈直接复用这条链路**，别再各写一套轮询。

---

## 2. 必读顺序（只有 3 份）

| 顺序 | 文件 | 为什么必须读 |
|:----:|------|--------------|
| 1 | `docs/agent-dev/AGENTS.md` | **最高优先级指令**。十条硬约束、五步工作流、审核关卡（第7章）。冲突时以它为准。 |
| 2 | `docs/agent-dev/02-架构与目录规范.md` | 强制目录树、分层红线、Rust/Python 边界、命名规范。不看就写必然违规。 |
| 3 | `docs/agent-dev/03-数据契约与接口规范.md` | 数据库表、JSON Schema、事件总线、接口契约。改数据前必须对照。 |

### 按需查阅
| 需要什么 | 查哪个 |
|----------|--------|
| 项目背景、目标、范围边界 | `docs/agent-dev/01-项目上下文.md` |
| 当前阶段的详细要求 | `docs/agent-dev/04` ~ `12` 按阶段号 |
| 交付前自检 | `docs/agent-dev/13-验收清单与禁止事项.md` |
| 审核规则（我会怎么审你） | `docs/reviews/SUPERVISOR.md` |
| 进度与遗留项 | `docs/reviews/LEDGER.md` |

> 阶段指令文件号 ≠ 阶段号，注意对照：
> 阶段1=`04` · 阶段2=`05` · 阶段3=`07` · 阶段4=`06`★ · 阶段5=`08` · 阶段6=`09` · 阶段7=`10` · 阶段8=`11` · 阶段9=`12`
> （阶段3 与阶段4 顺序被特意互换：窗口管理是模式引擎的依赖）

---

## 3. ⚠️ 环境与已知的坑（新 Agent 最容易栽在这里）

### 3.1 这台机器的 shell 环境不完整
部分 Unix 工具**不可用**：`grep`、`head`、`find`、`rm` 均会失败（PATH 落到 Windows 自带程序或 shim 损坏，报 `dirname: command not found`）。

**应对**：
- 读文件用内置文件读取工具，不要用 `cat`/`head`
- 搜索文件/内容用内置的 Glob / Grep 工具，不要用 `find` / `grep` 命令
- 建文件、改文件用内置写入/编辑工具，不要用 `echo >` / `sed`
- **删文件用 Python 的 `shutil.rmtree` / `os.remove`**，不要用 `rm`（会失败）
- `ls`、`mkdir`、`printf`、`python`、`wc` 是正常的

### 3.2 Python 解释器路径（已验证可用）
```
C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe
```
开发时如需环境隔离，在 `.workbuddy/binaries/python/envs/default` 下建 venv，不要污染全局。

### 3.3 项目自身的 Windows 特性坑
| 坑 | 说明 |
|----|------|
| DPI 缩放 | 应用必须声明 per-monitor DPI aware（v2），否则高分屏下所有窗口坐标全错 |
| 前台锁定 | `SetForegroundWindow` 常失败，需 `AttachThreadInput` 配合 |
| 最大化状态 | 窗口处于最大化时 `SetWindowPos` 无效，必须先 `SW_RESTORE` |
| 32/64 位注册表 | 扫已安装软件需分别读 `KEY_WOW64_64KEY` / `KEY_WOW64_32KEY` |
| 路径转义 | Windows 路径在字符串里注意反斜杠，别和正则转义打架 |

### 3.4 工作区约定
- **`.workbuddy/` 目录不可删除**，里面是项目记忆与配置。
- 项目记忆日志：`.workbuddy/memory/YYYY-MM-DD.md`（**只追加，不覆盖**）
- 长期项目约定：`.workbuddy/memory/MEMORY.md`
- GitHub 风格的忽略规则已配好（`.gitignore`），别把 `node_modules` / `target` / `*.db` 提交进去（红线 V8）。

---

## 4. 红线速览（命中即驳回，没有商量余地）

| # | 红线 |
|---|------|
| V1 | 明文密钥进入代码或数据库 |
| V2 | 咨询模式（AI Consult）能读取任何用户数据 |
| V3 | AI 自动修改学习进度或个人档案（未经用户确认） |
| V4 | 插件默认拥有权限 |
| V5 | 破坏性操作（结束进程/删文件/切模式）无二次确认 |
| V6 | 编译/测试失败却声称完成（谎报） |
| V7 | 插件或 UI 直接访问数据库 |
| V8 | 构建产物 / 数据库文件进入版本库 |

### 三条最容易被忽略、但后果最重的铁律
1. **单一写入者**：SQLite 只由 Rust core 写。UI、modules、plugins、Python sidecar 一律不写。
   Python 需要数据 → 调 core 的 `http://127.0.0.1:<port>/internal/db/*`。
2. **AI 只建议，用户来确认**：学习进度、个人档案，AI 不得自动改。
3. **插件默认零权限**，且插件架构是否成功的判据是"**新增插件零核心代码改动**"。

---

## 5. 送审规则（这套制度会真的驳回你）

### 5.1 送审前自跑门禁
```bash
python tools/gate.py --stage <N> --build
```
- 有 FAIL → **别送审**，先修。
- 只有 WARN → 可以送审，但要在报告里逐条说明为何可接受。

### 5.1.1 功能验收自跑核验（阶段1 已建，阶段2 起照此扩展）
```bash
# 需要先起前端：npm --prefix ui run dev
python tools/verify_stage1.py --exe core/target/release/personal-workspace-core.exe \
       --routes-url http://localhost:5173 --widget-probe
```
它会自动跑：启动/耗时/建库/sidecar/持久化/9 条路由渲染/★Widget 点击。
**这一类"把验收做成脚本"是本项目的硬要求** —— 口头"我点过了"不算证据（红线 V6）。

阶段6 的对应脚本（**不需要起前端**，只需 release 产物）：
```bash
python tools/rust.py build --release
python tools/verify_stage6.py            # 覆盖 09 §验收标准 8 项；--keep 可保留临时数据目录
```
它自起 core（开发态拉 sidecar）+ 三个 mock Provider（`tools/ai_mock.py --reply roadmap|fenced|invalid`），
从 core 的 `/api/v1` 面打进去。**不采信接口自述**：验收项 6 直接读 DB 文件做全表快照比对（AI 是否偷偷写了库）。

### 5.2 送审证据（七项，缺一即退回）
1. 改动文件清单（路径 + 新增/修改）
2. **编译输出原文**（粘贴，不许写"编译通过"四个字）
3. **测试输出原文**（通过/失败数量，粘贴）
4. 可复现的编号验收步骤
5. 自检结果（对照 `13-验收清单与禁止事项.md` 逐条勾选）
6. 未解决项与风险（**没有也必须写"无"**）
7. 遗留项

### 5.3 判定三档
- ✅ **通过** —— 门禁 0 FAIL、验收表全过、红线 0 命中、交付物齐全
- ⚠️ **有条件通过** —— 核心项全过，非核心遗留 ≤3 项且不阻塞下游
- ❌ **驳回** —— 门禁有 FAIL / 核心验收未过 / 红线命中 / 谎报 / 验收步骤无法复现

### 5.4 触发
对监制说：**「申请审核阶段 N」**

> 监制**不会替你改业务代码**。它只出报告要求返工——这是审核独立性的前提。

### 5.5 独立复核（与上者不同，别混）
角色合并状态下，"自审"不具备独立效力。需要独立效力时说：**「申请独立复核阶段 N」**。

- 由**新开的干净实例**执行，**优先换一个模型**（换上下文只解决一半，换权威才换掉盲区）；
- 只交付**产物**（仓库 + 阶段号），**不交付任何既有结论**；
- 规则见 `SUPERVISOR.md` 第十三章。

> ⚠️ **22:32 回调**：独立复核**仅在白宇明确下口令时执行**，监制**不自动发起、不因此阻塞阶段推进**。
> 未做独立复核的阶段，定性标注为「**机器门禁通过 + 自审记录**」—— 这是**效力标注**，不是阻塞项。
> **阶段4 已由白宇裁决豁免**（2026-09-13，治理记录在案）。

---

## 6. 阶段地图（不要跳阶段）

```
MVP（必须按序全部完成）—— ✅ 已全部通过（阶段0~5）
  阶段1 基础桌面框架   → 04-阶段指令-基础框架.md        ✅ REVIEW-005
  阶段2 软件管理       → 05-阶段指令-软件管理.md        ✅ REVIEW-008
  阶段3 窗口管理       → 07-阶段指令-窗口管理.md        ✅ REVIEW-009
  阶段4 工作模式引擎 ★ → 06-阶段指令-工作模式引擎.md   ✅ REVIEW-011  ← 全项目最高优先级
  阶段5 AI 助手        → 08-阶段指令-AI助手.md          ✅ REVIEW-013
─────────────────────────────────────────────
V2 —— 当前进度：✅ 全部通过（收官）
  阶段6 学习成长 + 项目 → 09-阶段指令-学习成长.md      ✅ REVIEW-014
  阶段7 个人档案       → 10-阶段指令-个人档案.md        ✅ REVIEW-015
V3 —— ✅ 全部通过（收官）
  阶段8 生活 + 设备    → 11-阶段指令-生活与设备.md      ✅ REVIEW-016
  阶段9 插件 + 小组件  → 12-阶段指令-插件与小组件.md    ✅ REVIEW-017（2026-09-13）
─────────────────────────────────────────────
项目阶段全部完成（0~9）。后续 = 维护 + 遗留项 + 新需求。
```

**优先级铁律**：宁可少一个功能，不可破坏架构。
插件接口、Provider 抽象、Event Bus、单一写入者——这四样**即使功能不做，架子也必须先立起来**。

---

## 7. 冷启动自检（答不出来说明你没真读，先回去读）

接手的 Agent 请在开始写代码前，能回答出这三问：

1. 数据库的**唯一写入者**是谁？UI 层要读写数据该走什么路径？
2. 为什么**阶段3（窗口管理）排在阶段4（工作模式引擎）之前**？
3. 插件默认拥有权限吗？判断"插件架构是否设计成功"的标准是什么？

参考答案分别在：`02-架构与目录规范.md` 2.4 / `LEDGER.md` 阶段总表下方注 / `12-阶段指令-插件与小组件.md` 设计目标。

---

## 8. 交接检查单

### 交接方（原 Agent）已交付
- [x] `docs/agent-dev/` 15 份开发指令（AGENTS + 01~13 + README）
- [x] `docs/reviews/` 监制制度（章程 / 台账 / 报告 / 模板）
- [x] `tools/gate.py` 自动门禁（已做对抗性验证）
- [x] `.gitignore`
- [x] 本文件 `HANDOFF.md`
- [x] 项目记忆 `.workbuddy/memory/2026-09-12.md`

### 接手方（新 Agent）需确认
- [ ] 读完 `AGENTS.md` / `02` / `03`
- [ ] 跑通 `python tools/gate.py --stage 0`，确认输出 `FAIL=0`
- [ ] 确认 `docs/reviews/LEDGER.md` 是进度真相来源
- [ ] 认领第 5 章的送审规则与第 4 章红线
- [ ] 能回答第 7 章的三个自检问题
- [ ] 向白宇/监制报到，说明你从哪个阶段开始接手

### 未决遗留项（接手方注意）
| ID | 描述 | 级别 | 状态 |
|----|------|:----:|------|
| L-001 | **两份源计划书 txt 已丢失**，需求追溯链断裂。建议在 `docs/source/` 归档（若白宇手上还有原稿） | 一般 | 未处理（待白宇） |
| L-017 / L-032 | **事件总线未桥接到前端**（core 进程内广播了，webview 收不到） | 一般 | ✅ **已闭环**（阶段5：core `event_bus/mod.rs::bridge_to_webview` ← `main.rs:56`，前端 `api/eventBridge.ts` 订阅 `pw://event`；`AI_STREAM_CHUNK` 增量渲染链路已验） |
| L-018 / U-8 | 验收项 8 的"重启后次数与尺寸保持"未单独断言 | 建议 | 登记待办（不阻塞） |
| L-044 / L-045 / L-046 | **阶段5 的三个"静默失真"缺陷**：①`force_dev` 开关没接线 ②发行态 `ai/prompt/*.md` 没进包 ③`ui.ai.*` 键未登记 + 前端零调用 | **重要** | ✅ **全部已关闭**（2026-09-13，REVIEW-013 §2.4）；已留机器守护：门禁 **B134** + `tools/verify_sidecar_bundle.py`（发行态 8/8） |
| M-5 | **审核独立性**：角色合并后"我改的代码我审"逻辑上不可满足 | **制度** | ✅ **已裁决（2026-09-12 21:40）**：分级独立 —— 日常阶段机器门禁为唯一裁判；关键节点一次性独立复核。见 `SUPERVISOR.md` 第十三章。<br>⚠️ **22:32 回调**：关键节点独立复核改为**仅白宇口令时触发**，不自动执行、不阻塞推进。**阶段4 已裁决豁免**（2026-09-13） |

> 上表只列"接手方必须知道"的项；完整清单（含已关闭项与条例缺陷 M-1~M-8）见 `docs/reviews/LEDGER.md`。
> **ADR-001 已定稿（Rust）**，原 HANDOFF 里"L-002 未处理 · 阻塞阶段3"的说法已过时。
>
> **阶段1~5 的独立效力状态**：定性统一为「**机器门禁通过 + 自审记录**」，**不构成阻塞**，可推进阶段6。
> 如需独立效力，下口令「申请独立复核阶段 N」即可（13.3 已回调为口令触发，不自动执行）。

---

## 9. ★ 复制粘贴给新 Agent 的开场白

把下面整段发给要接手的 Agent（任何模型都适用）：

```text
你现在接手一个已有项目，作为开发 Agent。请严格按以下步骤执行，不要凭猜测动手。

【第一步 · 建立上下文】
工作目录：C:\Users\baiyu\Desktop\Personal Workspace
请依次完整读取并理解：
  1. HANDOFF.md                        ← 交接总入口，先读这个
  2. docs/agent-dev/AGENTS.md          ← 最高优先级指令（含十条硬约束 + 审核关卡）
  3. docs/agent-dev/02-架构与目录规范.md ← 强制目录结构与分层红线
  4. docs/agent-dev/03-数据契约与接口规范.md ← 数据表 / JSON / 事件 / 接口契约
  5. docs/reviews/LEDGER.md            ← 项目进度唯一真相来源

【第二步 · 确认理解】
读完后，先回答下面三个问题再动手，不要跳过：
  Q1 数据库的唯一写入者是谁？UI 层读写数据该走什么路径？
  Q2 为什么"窗口管理"排在"工作模式引擎"之前？
  Q3 插件默认拥有权限吗？判断插件架构设计是否成功的标准是什么？
回答完，再输出一句你对当前项目状态的理解。

【第三步 · 出计划，等我确认】
说明你打算从哪个阶段开始、要改哪些文件、数据结构长什么样（5 行以内）。
我确认后再写代码。

【第四步 · 开发时的硬约束】
- 技术栈已定：Tauri 2.x + Vue3 + TS（前端）+ Rust（核心调度）+ Python（系统调用/AI sidecar）+ SQLite
- 模块化：Core + Modules + Plugins 三层，核心代码不得 import 任何插件
- 单一写入者：SQLite 只由 Rust core 写，Python 通过 core 的 /internal/db/* 接口访问
- 不绑定单一模型：AI 必须走 Provider 抽象层，禁止在业务代码里写死某模型的 HTTP 请求
- API Key 一律进系统凭据库，禁止明文进代码/数据库/git
- 所有配置必须可持久化，禁止"只存在内存里"

【第五步 · 铁定不能碰的红线】
V1 明文密钥入库入码 / V2 咨询模式能读用户数据 / V3 AI 自动改学习进度或档案 /
V4 插件默认有权限 / V5 破坏性操作无二次确认 / V6 谎报完成 /
V7 插件或 UI 直接访问数据库 / V8 构建产物或数据库文件进仓库

【第六步 · 环境提醒（这台机器有坑）】
- grep / head / find / rm 命令不可用，会报 dirname: command not found
  → 请用内置的文件读写/搜索工具；删文件用 Python 的 shutil.rmtree
- Python 解释器：C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe
- .workbuddy/ 目录不可删除
- 项目目录含空格，命令里必须加引号

【第七步 · 交付与送审】
- 开工前先自跑门禁：python tools/gate.py --stage <N> --build，有 FAIL 不许送审
- 交付时必须提供七项证据（改动清单 / 编译输出原文 / 测试输出原文 /
  可复现验收步骤 / 自检结果 / 未解决项【没有也要写"无"】/ 遗留项）
- 本项目设监制审核，未经审核通过不得进入下一阶段
- 送审说：「申请审核阶段 N」
- 注意：ADR-001（窗口控制与进程启动）= **Rust**，已定稿（`docs/adr/ADR-001`）。
- 当前状态：**阶段0~9（MVP + V2 + V3）全部审核通过，项目阶段收官**（阶段9 REVIEW-017：gate 0F/0W/22P · `verify_stage9.py` 29/29 · cargo test 86/86）。
  接新需求先跑基线：`python tools/gate.py --stage 9 --build`（应 0F/0W）。插件开发看 `docs/plugin-dev-guide.md`。
- 验收脚本一并跑：`python tools/verify_stage9.py`（阶段9 十一组，自起 core + mock Agent）、
  `python tools/verify_stage8.py`（阶段8 八组）、
  `python tools/verify_stage5.py`（开发态 44/44）与
  `python tools/verify_sidecar_bundle.py`（**发行态** 8/8）—— 后者专门守"只在打包后炸"的坑。

现在开始第一步。
```

---

## 9.1 ★ 复制粘贴给「独立复核实例」的开场白

需要独立效力时（规则见 `SUPERVISOR.md` 第十三章），把下面整段发给一个**新开的、干净的**实例
（优先换一个模型）：

```text
你现在担任一个已有项目的【独立复核方】。你与该项目此前的开发者/审核者不是同一实例。

【最重要的一条】
不要引用、不要相信、也不要去读任何既有审核报告的"结论/判定"部分。
你的结论只能来自你自己跑出来的产物。如果你在文档里看到别人给出的数字，
请重新跑一遍并自己点算——本项目的实证记录表明：一次错误计数曾被后续"复现审核"照抄下来。

【第一步 · 建立上下文】
工作目录：C:\Users\baiyu\Desktop\Personal Workspace
依次读取：
  1. HANDOFF.md                            ← 交接总入口
  2. docs/agent-dev/AGENTS.md              ← 最高优先级指令
  3. docs/agent-dev/02-架构与目录规范.md
  4. docs/agent-dev/03-数据契约与接口规范.md
  5. docs/reviews/LEDGER.md                ← 只看"遗留项登记"，不看判定结论
  6. docs/reviews/SUPERVISOR.md 第十三章   ← 你要遵守的独立复核规则
  7. docs/reviews/templates/REVIEW-TEMPLATE.md ← 报告必须按它写（含四套清单 + 调用点检索）

【第二步 · 跑，而不是读】
① python tools/gate.py --stage <N> --build      ← 留原始输出
② 该阶段的验收核验脚本（阶段1：tools/verify_stage1.py --routes-url http://localhost:5173 --widget-probe）
③ 自己点算 PASS/FAIL 数量，不要抄任何人的计数

【第三步 · 按四套清单逐条核（缺一套即判定无效）】
「必须实现」/「验收标准」/「交付物」/「禁止事项」——四张表都要出结论。
只核"验收标准"是导致 ★ 核心项连漏两轮的原因。

【第四步 · 强制调用点检索】
对每个被声称"已实现"的功能符号，附出它的调用点（文件:行）。
零调用 = 未接线 = 该功能不成立，不得因为"文件里有这段代码"记为通过。
跨语言边界（Rust command ↔ 前端 invoke）必须两侧都查。

【第五步 · 产出】
写 docs/reviews/REVIEW-<N>-独立复核.md，首部声明独立性。
你【不得】修改任何业务代码，只出报告。

【环境提醒】
- grep / head / find / rm 不可用，用内置文件工具与 Python
- Python：C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe
- .workbuddy/ 目录不可删除；项目路径含空格，命令要加引号

现在开始第一步。
```

---

## 10. 交接的本质

交接不是把文件甩过去。容易丢的是三样**隐形知识**，本文件已全部固化：

| 隐形知识 | 固化位置 |
|----------|----------|
| 现在真正到哪一步了 | `docs/reviews/LEDGER.md` + 第 6 章 |
| 哪些坑会让人白干半天 | 第 3 章（环境坑 + Windows 特性坑） |
| 哪些事做了会被打回 | 第 4 章红线 + 第 5 章送审规则 |

**三条交接原则**：
1. **单一入口** —— 新 Agent 只需要知道 `HANDOFF.md`，其余靠它索引。
2. **可验证** —— 第 7 章的三问 + 第 5.1 节的门禁命令，能验证新 Agent 是否真接手了。
3. **状态外置** —— 进度写在台账里，不依赖任何一个 Agent 的记忆。**换 Agent 不换状态。**

---

*本文件是项目交接的唯一入口。修改本文件必须告知白宇。*
