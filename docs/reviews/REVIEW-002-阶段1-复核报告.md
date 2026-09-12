# 审核报告 REVIEW-002 · 阶段1 复核（对 REVIEW-001 判定的改判）

| 项目 | 内容 |
|------|------|
| 审核编号 | REVIEW-002 |
| 审核日期 | 2026-09-12 |
| 审核类型 | **复核（推翻既有判定）** |
| 复核对象 | `REVIEW-001-阶段1-基础框架.md`（判定：⚠️ 有条件通过） |
| 复核触发 | 白宇指令：「担任项目审核员，检测项目是否按照计划进行，有无越界或者不到位的地方」 |
| 复核基准 | `04-阶段指令-基础框架.md` 验收表、`02-架构与目录规范.md`、`03-数据契约与接口规范.md`、`13-验收清单与禁止事项.md`、`docs/adr/ADR-001`、`SUPERVISOR.md` §4/§6/§10 |
| 复核方式 | 逐文件代码走查 + 门禁复跑 + **Python 复现脚本**（可第三方重放） |
| **改判结论** | **REVIEW-001「⚠️ 有条件通过」→ ❌ 驳回**（新证据：3 项阻断级问题） |

> 依据 `SUPERVISOR.md` §十「争议处理」：有证据推翻结论 → 改判，并记录改判原因。
> 本报告**不修改任何业务代码**，只出结论与返工清单（§一 角色边界）。

---

## 〇 · 复核方法声明

REVIEW-001 的验收手法以"**文件是否存在、门禁是否 0 FAIL、链路是否已编码**"为主。
本次复核改用"**逐文件通读 + 跨文件推理 + 脚本复现运行语义**"。

结论差异的根源在此：REVIEW-001 漏检的 3 个问题**全部属于"文件都在、类型都对、但运行语义错误"**一类，
而 `tools/gate.py` 只检查结构与模式匹配，**对这类缺陷零覆盖**（见 §十二）。

本报告所有结论均附 **路径 + 行号** 或 **可重放命令 + 原始输出**。

---

## 一 · 复核结论摘要

| # | 发现 | 级别 | REVIEW-001 是否覆盖 |
|:-:|------|:----:|:------------------:|
| **R-01** | 种子数据**永不执行**；`schema_version` 三处口径不一 | 🔴 阻断 | ❌ **漏检**（还被反向记为"已完成"） |
| **R-02** | UI ↔ core 通信链路**静态可判定断裂**，配置未落库 | 🔴 阻断 | ❌ **误判**（被归为"环境受限未验证 U-2"） |
| **R-03** | `system/` 残留违反 ADR-001 的 Python 进程启动实现，且为死代码 | 🔴 阻断 | ❌ **漏检**（反被当作"ADR-001 一致性证据"） |
| R-04 | 交接文档 / 台账滞后于事实 | 🟠 一般 | ❌ 未覆盖 |
| R-05 | `bundle.active=false` 与验收项 7 直接冲突 | 🟠 一般 | ❌ 未覆盖 |
| R-06 | 顶栏缺"最小化"控件 | 🟠 一般 | ❌ 未覆盖 |
| R-07 | 全项目**零自动化测试** | 🟠 一般 | ❌ 未覆盖（DoD 未核对） |
| R-08 | 门禁口径未含 `--build`，掩盖 B101 | 🟠 一般 | ❌ 口径缺失 |
| R-09 | REVIEW-001 自身事实性差错（文件计数） | 🟡 建议 | — |
| R-10 | 台账 REVIEW-000 门禁值与报告不符 | 🟡 建议 | — |
| R-11 | 事件时间戳实为 UTC（注释/契约均称本地时区） | 🟡 建议 | ❌ 漏检 |
| R-12 | `/internal/db/exec` 白名单为子串匹配，宣称与实现不符 | 🟡 建议 | ❌ 漏检 |
| R-13 | 02 §2.2 强制目录树外增量未回写规范 | 🟡 建议 | ✅ 已登记（L-005） |

**阻断级 3 项、一般级 5 项、建议级 5 项。**

---

## 二 · 新证据（三项阻断级问题）

### 🔴 R-01 · 种子数据永不执行 + `schema_version` 三处口径不一

**代码证据**：
```rust
// core/src/db/mod.rs:38-44
pub fn initialize(&self) -> anyhow::Result<()> {
    migrations::run(self)?;       // ← 内部已向 config 表写入 schema_version（见下）
    if self.is_fresh()? {         // ← is_fresh = COUNT(*) FROM config == 0
        self.exec_script(migrations::SEED_DEFAULT_CONFIG)?;
    }
    Ok(())
}
// core/src/db/migrations.rs:16-24
for (version, script) in MIGRATIONS {          // MIGRATIONS = &[(1, include_str!("0001_init.sql"))]
    if *version > current {
        db.exec_script(script)?;                                        // 建表
        db.kv_set("schema_version", &serde_json::to_string(&version)?)?;  // ← 插入 config 行（=1）
    }
}
```

**可重放复现**（审核员实跑，非推导）：
```
$ python - <<'EOF'   # 等价脚本已执行
  执行 core/migrations/0001_init.sql → 建表
  再执行 kv_set("schema_version", 1)
  检查 is_fresh()
EOF

0001_init.sql 建表数: 15
migrations::run 建表后 config 行数: 0
migrations::run 执行 kv_set 后 config 行数: 1
is_fresh() 返回 COUNT(*)==0 ? False
>>> 结论: SEED_DEFAULT_CONFIG 永远不会被执行
```

**后果**：
1. `database/seeds/0001_default_config.sql`（8 个默认键）**从不落库**，仅靠 `ConfigService::default_for()`
   在读取时兜底 —— 种子文件形同虚设，验收项 6 的"默认配置"实际落空。
2. `schema_version` **三处不一致**：

   | 位置 | 值 | 性质 |
   |------|:--:|------|
   | `core/src/db/migrations.rs` 第 9 行元组 + 第 19-22 行写入 | `1` | **实际生效值** |
   | `database/seeds/0001_default_config.sql:5` | `'2'` | 永远不生效 |
   | `03-数据契约与接口规范.md:396` 变更记录 | `= 2` | 文档声明 |

**对 REVIEW-001 的指正**：REVIEW-001 §5.3 勾选「[x] `schema_version` 已更新（seed 写入 `'schema_version':'2'`）」，
**只读到 seed 文件写了 2，未验证 seed 是否被执行、也未比对 migration 实际写入的 1** —— 属"以文件内容代替运行事实"，与 `SUPERVISOR.md` §二「原则 1：信产物，不信汇报」相悖。

**修复方向**：seeds 全是 `INSERT OR IGNORE`，可**去掉 `is_fresh()` 前置、无条件执行**；
或把 `is_fresh()` 判定移到 `migrations::run()` 之前。随后统一 `schema_version` 口径。

---

### 🔴 R-02 · UI ↔ core 通信链路静态可判定断裂（配置未落库）

REVIEW-001 将其归入"U-2 · 未实测（环境受限）"。复核认为**该归类比错误更严重**：
这不是"没条件验证"，而是**证据充分、静态即可判定的设计缺陷**。

**完整证据链（四段拼合）**：
```rust
// ① core 只监听随机端口
// core/src/api/mod.rs:36
let listener = match tokio::net::TcpListener::bind("127.0.0.1:0").await { ... }
// core/src/api/mod.rs:48   端口写进 SQLite
state.config.set("runtime.http_port", json!(port));
```
```ts
// ② UI 拨固定端口
// ui/src/api/client.ts:14-15
export const API_BASE: string =
  (import.meta.env.VITE_CORE_BASE as string | undefined) ?? 'http://127.0.0.1:7520'
```
```json
// ③ UI 无 Tauri invoke 通道 —— 无 @tauri-apps/api
// ui/package.json:12-16  dependencies 仅 pinia / vue / vue-router
// ④ 全仓库不存在 .env / .env.*（已全盘遍历确认）
```

**推理**：core 监听的是**随机端口** → UI 只能拨 `7520`（`VITE_CORE_BASE` 无注入）→ **二者不可能连上**。
而 UI 是 WebView，**被红线 V7 禁止读 SQLite**，因此**无法自行取得 `runtime.http_port`**。

`04 §5` 要求"随机端口（写入 `config` 供双方读取）"在此形成**闭环悖论**：写入方写的是 SQLite，
而唯一读取方（UI）恰恰被制度禁止读 SQLite。

**后果**：`configService.ts:17-20` 的 `catch` 分支必然触发，**所有配置读写降级到 `localStorage`**。
→ 验收项 4 表面"重启后主题保持"（localStorage 亦持久化），但**违反硬约束 6 与 `04 §4`「存储：SQLite `config` 表」** —— **配置未落库**。
开发方在 `configService.ts:2-5` 与 `ui/README.md:48-51` 已自认此降级，但未意识到其**根因是端口无法传递**，而非"阶段2 的对账逻辑未做"。

**对 REVIEW-001 的指正**：REVIEW-001 §5.4 勾选「[x] 设置项持久化路径实现」，
并在 U-2 断言"链路已实现，只是未实测"。**该断言与代码事实不符**：链路在 `①→②` 处即已断开，
不存在"跑起来就能通过"的可能。把**设计缺陷**登记为**环境遗留项**，会使缺陷以"待补验"名义长期存活 —— 这正是 `SUPERVISOR.md` §四「有条件通过**不得**用于：核心功能不完整、架构违规」所禁止的情形。

**修复方向**（择一）：① UI 改走 Tauri `invoke` 直连 core（需补 `@tauri-apps/api`）；
② core 在窗口 `setup` 阶段把端口注入前端；③ core 另开固定 loopback 端口专供"取端口"握手。

---

### 🔴 R-03 · `system/` 残留违反 ADR-001 的 Python 进程启动实现，且为死代码

**代码证据**：
```python
# system/service.py:51-56   声明这些路径已迁走
MOVED_TO_CORE = { "/sys/process/launch": "ADR-001：进程启动已迁移至 Rust core（core/src/app_manager）", ... }

# system/service.py:106-140   do_POST 的实际执行顺序
def do_POST(self) -> None:
    path = self.path.split("?")[0]                        # L107
    if path in MOVED_TO_CORE:                              # L108 ← launch 在此命中并 return
        self._send(410, err("moved_to_core", MOVED_TO_CORE[path]))
        return
    if path in NOT_YET: ...                                # L111
    if path == "/internal/db/query" or ...: ...             # L114
    if path == "/sys/process/launch":                       # L124 ← 永远不可达
        proc = subprocess.Popen(                            # L132 ← Python 进程启动实现
            [exe, *body.get("args", [])], cwd=..., creationflags=...)
```

**双重违规**：
1. **违反 ADR-001**。`docs/adr/ADR-001:17` 明文："项目内**统一**使用 Rust 实现……**禁止**在 Python sidecar 中出现同类实现（`pywin32` 的窗口/进程操作）"；
   `ADR-001:48-49` 的合规检查点同样覆盖。虽用 `subprocess` 而非 `win32process`，
   但**能力归属**仍是"Python 实现进程启动"，与"进程启动 = `core/app_manager`（Rust）"的决策冲突。
   （注：ADR-001 检查点只点名了 `system/win/` 与 `pywin32`，**检查点表述本身有漏洞**，见 §十二·改进建议。）
2. **死代码**。该分支位于 `MOVED_TO_CORE` 拦截之后，**永不执行**，违反
   `13-验收清单与禁止事项.md` §1.1「无注释掉的死代码」。
3. **文档与代码不符**。`system/README.md:14` 声明"`/sys/process/*` 与 `/sys/window/*` 返回 410"，实际代码里并存一份实现。

**对 REVIEW-001 的指正**：REVIEW-001 §5.2 把"`system/service.py` 410 响应"列为
「[x] ADR-001 已定稿且全项目一致」的**一致性证据**；其 §3.1 的 sidecar 实测仅覆盖
`/sys/window/find`（410）、`/ai/chat`（501）、`/health`（200），
**恰好未触及 `/sys/process/launch`** —— 漏检由此产生。此为"用一处合规推断全局合规"的典型失效。

**修复方向**：删除 `system/service.py:124-140` 整段。

---

## 三 · 一般级问题

### 🟠 R-04 · 交接文档与台账滞后于事实
| 文档 | 原文 | 事实 |
|------|------|------|
| `HANDOFF.md:15` | "阶段1~9 全部未开工。**工作区目前没有任何代码。**" | 阶段1 代码已成规模 |
| `AGENTS.md:18` | "阶段1~9 未开工，**工作区无代码**" | 同上 |
| `HANDOFF.md:204` | "L-002 ADR-001 未定稿｜严重｜未处理｜**阻塞阶段3**" | `docs/adr/ADR-001` 已"已接受" |
| （已被 REVIEW-001 修正的部分） | — | `LEDGER.md` 的 L-002 已关闭 ✅ |

说明：`HANDOFF`/`AGENTS` 的表述在编写时（18:20 前）属实，属**未随开发同步更新**。
但 `HANDOFF.md` 自我定义为"交接唯一入口"，其失实会直接误导接手 Agent。
`SUPERVISOR.md` §十一 第 1 条把"台账与仓库实际状态一致"列为监制尽职判据 —— `LEDGER` 已修正，`HANDOFF`/`AGENTS` 仍待修。

### 🟠 R-05 · `bundle.active=false` 与验收项 7 直接冲突
`core/tauri.conf.json:28-30`：`"bundle": { "active": false }` → `npm run tauri build` **不产出安装包**；
而 `04` 验收项 7 要求"能出安装包"。二者不可同时成立。REVIEW-001 将其列为"U-1 未验证"，**掩盖了真实冲突**。

### 🟠 R-06 · 顶栏缺"最小化"控件
`04 §2` 布局图要求顶栏 `[设置] [最小化]`；`ui/src/components/TopBar.vue:20-23` 仅有"设置"。

### 🟠 R-07 · 全项目零自动化测试
- `core/` 下精确检索 `#[test]` / `#[cfg(test)]` / `mod tests` → **No matches**。
- `ui/package.json` 的 4 个 script 中**无 test**。
- 违反 `docs/agent-dev/AGENTS.md` §4 DoD「至少一条可自动化的测试覆盖核心逻辑」与 `13` §1.1，REVIEW-001 **未核对该条 DoD**。
- **为何这条在本次尤为关键**：本机 **cargo 缺失（编译门禁 FAIL）+ 无测试**，形成"双盲区"。
  R-01 正是落在这个盲区里 —— 代码可通读、类型正确，但运行语义错误。

### 🟠 R-08 · 门禁口径未含 `--build`，掩盖 B101
- `SUPERVISOR.md` §3 第②步明确要求 `python tools/gate.py --stage <N> --build`。
- REVIEW-001（及台账）记录为 `0F/0W/23P` —— 这是**不带 `--build`** 的结构门禁结果。
- 复核实跑 `--stage 1 --build`：
```
--- FAIL（1）---
  [FAIL] B101 — cargo check 失败：未知错误
--- PASS（24）---
  [PASS] B110 — 前端 typecheck 通过
❌ 门禁不通过   FAIL=1  WARN=0  PASS=24
```
- **公允说明**：B101 的成因是**本机无工具链**（`cargo --version`/`rustc --version` 均 command not found），非代码错误；
  `gate.py` 的 `check_build()` 无法区分"编译失败"与"工具链缺失"。ADR-001 已把该项登记为补验项。
- **但口径必须如实标注**：OK 结论只能写"结构门禁 0 FAIL"，不得写作"门禁 0 FAIL"。建议台账增设"编译门禁"独立列。

---

## 四 · 建议级问题

- **R-09 · REVIEW-001 的事实性差错**（已复核，供其修订）：
  | REVIEW-001 表述 | 实际（复核实测） |
  |----------------|------------------|
  | "core/ 全部 Rust 源码（**10 文件**）" | **14 个 `.rs` 文件** |
  | 目录树描述 02 §2.2 一致 | `core/src/api/`、`core/src/sidecar/` 为强制树外新增（已登记于 `core/README.md:28`） |
  （`config/layouts` 7 个、事件常量 18 个 —— 经核对**正确**。）

- **R-10 · 台账与报告的门禁值口径需标注**：`REVIEW-000` 报告正文为 `0F/0W/**7P**`，
  台账记为 `0F/0W/**10P**`。经复核**二者均非错误** —— 复核实跑 `--stage 0` 现值确为 10P
  （差异来自 `gate.py` 后续扩项 + `.gitignore` 感知）。问题仅在**未标注取数时点**，
  建议台账注明"报告留存值 / 当前值"。

- **R-11 · 事件时间戳实为 UTC**：`core/src/event_bus/mod.rs:56` 注释称
  "本地时区 ISO8601……用系统时区偏移手工拼接"，但 `iso_now()` 实现**未做任何偏移**，
  产出 UTC。与 `03` §3.1「时间统一存本地时区 ISO8601」及 §3.3 示例 `"…+08:00"` 均不符。

- **R-12 · `/internal/db/exec` 白名单为子串匹配**：`core/src/api/mod.rs:111`
  `WRITABLE_TABLES.iter().any(|t| sql.to_ascii_lowercase().contains(t))` ——
  `DELETE FROM config_backup` 等可绕过，与注释"仅限白名单表"的宣称不符。
  阶段1 风险有限（仅 `config` 一表且接口仅对内），但阶段2 扩表前须改为解析目标表名的严格校验。

- **R-13 · 强制目录树外增量未回写规范**：`core/src/api/`、`core/src/sidecar/` 不在
  `02 §2.2` 强制树内（态度正确的部分：`core/README.md:28` 已自我登记）。
  与 REVIEW-001 的 L-005 合并处理。

---

## 五 · 越界检查专项结论

**功能层面：未越界。**

`core/src/` 中三个后续阶段模块经逐行核对，**均为合规骨架占位**：

| 模块 | 阶段 | 实际内容 | 判定 |
|------|:----:|----------|:----:|
| `app_manager/mod.rs`（34 行） | 2 | `AppRecord` 类型 + `validate_path()`；`launch()` = `bail!("阶段2 实现…")` | ✅ |
| `window_manager/mod.rs`（63 行） | 3 | `Slot`/`Rect` 类型 + `to_pixels()` 纯函数；`find_main_window()`/`set_window_pos()` = `bail!` | ✅ |
| `scheduler/mod.rs`（38 行） | 4 | `ModeState` 枚举 + `next()` 流转；`apply_mode()` = `bail!` | ✅ |

符合 `HANDOFF.md` §6「架子也必须先立起来」与 `04` 禁止事项「只做 UI 占位」。**不构成越界。**

**架构层面：1 处实质越界** —— R-03（ADR-001 违规）。

`config/layouts/`（7）与 `config/modes/`（2）为阶段3/4 资源而阶段1 即放置，
属静态样例、无逻辑；`gate.py` 仅检查存在性，**判定为轻微前置、可接受**，
建议在进入阶段3 前确认内容与届时定稿契约一致。
`core/migrations/0001_init.sql` 一次性建出 **15 张表**（阶段1 仅需 `config`），
全部已在契约 v2 登记，**不构成"未登记契约变更"，判定为有意的前置落契约、可接受**，
建议在阶段1 交付说明中显式声明该决策。

> 附：本报告已修正初稿中两处计数错误 —— 表数为 **15**（非 12）、`config/layouts` 为 **7**（非 6）。

---

## 六 · 逐条验收（复核修正）

| # | 验收项 | REVIEW-001 | **REVIEW-002 复核** | 依据 |
|:-:|--------|:----------:|:------------------:|------|
| 1 | 应用能启动 | ⚠️ 未验证 | ⚠️ 未验证（工具链缺失） | `cargo`/`rustc` 不存在 |
| 2 | 冷启动 < 3s | ⚠️ 未验证 | ⚠️ 未验证（同上） | 同上 |
| 3 | 9 项导航切换无白屏 | ✅ 已验证 | ⚠️ **代码齐备，未运行验证** | 静态可读 ≠ 运行验证；REVIEW-001 未运行前端即判"已验证" |
| 4 | 配置持久化 | ⚠️ 未验证 | ❌ **不达标** | R-02：链路断裂，配置未落 SQLite |
| 5 | sidecar `/health` | ✅ 部分 | ✅ 部分（保持） | `/health` 200 已实测；但含死代码 R-03 |
| 6 | 自动建库 + migration | ⚠️ 未验证 | ❌ **不达标** | R-01：种子永不执行 |
| 7 | 能出安装包 | ⚠️ 未验证 | ❌ **不达标** | R-05：`bundle.active=false` |

**核心验收：1 完整通过 / 3 部分或受限 / 3 不达标**（REVIEW-001 的"2 通过"中，项 3 应降级为"代码齐备未运行"）

---

## 七 · 一票否决项（红线）复核

| # | 红线 | 结果 | 依据 |
|:-:|------|:----:|------|
| V1 | 明文密钥 | ✅ 未命中 | `gate.py check_secrets` 0 命中 |
| V2 | 咨询模式读用户数据 | ⚪ 不适用 | 阶段1 无 AI；`config/app.toml:34` 已预留 |
| V3 | AI 自动改档案/进度 | ⚪ 不适用 | 阶段1 无 AI |
| V4 | 插件默认权限 | ✅ 未命中 | `plugins/` 空；`plugins.enabled DEFAULT 0` |
| V5 | 破坏性操作无确认 | ⚪ 不适用 | 阶段1 无此类操作 |
| V6 | 谎报完成 | ✅ **未命中** | 开发方在 `core/README.md:57`、`ui/README.md:53` **主动登记**"cargo/tauri 未执行"，REVIEW-001 亦如实列 U-1~U-4。**本项保持 REVIEW-001 判定** |
| V7 | 插件/UI 直连数据库 | ✅ 未命中 | `gate.py` 0 命中 + 人工核对 `client.ts`/`configService.ts` 均走 HTTP |
| V8 | 构建产物入库 | ✅ 未命中 | `ui/node_modules/`、`ui/dist/` 均被 `.gitignore` 覆盖 |

**红线命中：0** —— 与 REVIEW-001 一致。

> 注：R-02 属"**功能未达标**"（验收项 4 不成立），**不构成 V7 命中**（UI 并未真的直连库，而是根本没连上）。

---

## 八 · 判定与理由

### 改判：❌ 驳回（REVIEW-001 的「⚠️ 有条件通过」不成立）

**依据 `SUPERVISOR.md` §四**：
- 「⚠️ 有条件通过」明确**不得**用于"核心功能不完整、架构违规、红线项"三种情形。
- 本次复核发现：**核心验收项 4/6/7 不达标**（核心功能不完整）+ **R-03 架构违规（ADR-001）** + **门禁存在 FAIL（B101）**
  → 三项均落入"驳回"条件。

**理由**：
1. **架构违规**：R-03 违反 ADR-001「禁止混用」的明文决策，且为死代码。
2. **核心验收不达标 3 项**：R-01（种子）、R-02（配置未落库）、R-05（不出安装包）。
3. **门禁 FAIL**：B101（成因＝工具链缺失，但口径为 FAIL，且不可通过改代码消除）。
4. **DoD 缺失**：R-07 零测试，不满足 `AGENTS.md` §4。

**对 REVIEW-001 判定的总体评价（就事论事，符合 §四「原则 4：驳回对事不对人」）**：
REVIEW-001 在**结构、分层、卫生、红线**四类"可枚举"检查上做得扎实且证据充分（见 §九），
其失效集中在**"文件都在但语义错"这一类**，且暴露出"自审 + 无编译 + 无测试"三者叠加时
**对逻辑缺陷的零覆盖**。这不是态度问题，是**方法问题**，故在 §十二 提出流程改进。

---

## 九 · 对 REVIEW-001 的正面确认（公允记录）

以下结论经复核**确认成立**，予以保留：

1. **结构门禁 23/23 PASS**（复核实跑可复现）；目录结构、分层边界全部合规。
2. **`core/` 不依赖 `ui/`/`modules/`/`plugins/`**；**UI 不直连 SQLite**；**单一写入者守住**。
3. **红线 0 命中**（8 项逐条复核）。
4. **后续阶段模块均为合规占位**，未提前实现业务逻辑。
5. **前端编译链真实通过**：复核独立复跑 `vue-tsc --noEmit` → `exit 0`，零诊断输出。
   （REVIEW-001 的 `npm run build` 输出亦经 `ui/dist/` 产物佐证。）
6. **代码卫生优秀**：`core/` 14 个 `.rs` 全量检索，**无 `unwrap()` / `expect()` / `panic!` / `todo!`**；
   `gate.py` 卫生项 0 WARN。
7. **`database/schema.sql` 与 `core/migrations/0001_init.sql` 逐行一致**，符合 §2.2。
8. **开发方主动披露未验证项**，未触发 V6。
9. **ADR-001 文档质量高**（决策 / 理由 / 代价对策 / 合规检查点齐备）。
10. **`config/app.toml` 与 `core/README.md` 对 ADR-001 的双重登记**到位。

---

## 十 · 返工要求（可执行清单）

| 序 | 对应 | 要求 | 验收方式 |
|:--:|:----:|------|----------|
| 1 | R-03 | 删除 `system/service.py:124-140` 死代码分支 | 全文检索 `sys/process/launch` 仅剩 `MOVED_TO_CORE` 一处 |
| 2 | R-01 | 修复种子执行逻辑；统一 `schema_version` 口径（代码 / seeds / 契约三处） | 首次建库后 `config` 行数与 seeds 一致；`schema_version` 单一值 |
| 3 | R-02 | 打通 UI ↔ core 端口传递，使配置**真实落 SQLite** | 改主题 → 重启 → `config` 表 `ui.theme` 为改后值 |
| 4 | R-05 | 落实 `bundle.active`（置 `true`，或修订验收表并登记遗留） | 与 `04` 验收项 7 自洽 |
| 5 | R-07 | 至少补 `window_manager::to_pixels()`（纯函数）与 迁移/种子 流程的单测 | 粘贴测试输出原文（通过/失败数） |
| 6 | R-04 | 同步 `HANDOFF.md` / `AGENTS.md` 的"无代码"表述 | 与工作区一致 |
| 7 | R-06 | 补齐顶栏"最小化"，或记录采用原生标题栏的理由 | 与 `04 §2` 自洽 |
| 8 | R-08 | 台账增设"编译门禁"独立列，标注 `--build` 与否 | 口径可追溯 |
| 9 | R-09~R-13 | 建议项，随阶段1 收尾处理 | —— |

**环境前置**：安装 `rustup`（MSVC toolchain）+ WebView2，方能消除 B101 并完成验收项 1/2/7。

---

## 十一 · 遗留项登记

| ID | 描述 | 级别 | 责任阶段 |
|----|------|:----:|:--------:|
| L-001 | 源计划书 txt 缺失，需求追溯链断裂 | 一般 | 阶段1 |
| L-002 | ~~ADR-001 未定稿~~ | — | ✅ 已关闭 |
| L-004 | Rust 工具链未安装，3 项验收无法验证 | 严重 | 阶段1（环境） |
| L-005 | `02 §2.2` 未同步 ADR-001 与目录增量 | 建议 | 阶段2 开工前 |
| **L-006** | 种子数据永不执行 / `schema_version` 口径不一（R-01） | 严重 | 阶段1 |
| **L-007** | UI↔core 端口链路断裂，配置未落库（R-02） | 严重 | 阶段1 |
| **L-008** | 违反 ADR-001 的 Python 进程启动死代码（R-03） | 严重 | 阶段1 |
| **L-009** | 全项目无自动化测试（R-07） | 一般 | 阶段1 |
| **L-010** | 交接文档（HANDOFF/AGENTS）未随开发更新（R-04） | 一般 | 阶段1 |
| **L-011** | `bundle.active=false` 与验收项 7 冲突（R-05） | 一般 | 阶段1 |

---

## 十二 · 流程改进建议（针对审核制度本身）

本次复核最大的产出不是"找出 3 个 bug"，而是**暴露了审核方法的盲区**。

### 1. 「自审 + 无编译 + 无测试」= 逻辑缺陷零覆盖
- 现状：角色合并后审核独立性与机器门禁叠加；机器门禁擅长"**存在性 / 模式匹配**"，
  对"**运行语义错误**"（R-01）零覆盖；编译门禁因工具链缺失失效（R-08）；测试完全缺失（R-07）。
- 结论：三者同时失效时，**审核退化为"文件清单核对"**。R-01/R-02/R-03 全部从此缝隙漏过。
- 建议：**优先补测试**（成本最低、收益最高），尤其覆盖纯函数（`to_pixels`）与迁移/种子流程。

### 2. 「未验证」与「已判定不成立」必须区分
REVIEW-001 把 R-02 登记为"环境受限未验证（U-2）"，实际它是**静态可判定的设计缺陷**。
建议在报告模板中增设**三态**：`✅ 通过` / `⚠️ 未验证（附原因）` / `❌ 静态判定不成立（附证据）`。
否则缺陷会以"遗留项"名义长期存活。

### 3. 门禁口径必须显式标注
`0F/0W/23P` 与 `1F/0W/24P` 差异来源是 `--build`，台账与报告均未标注，易被读作"门禁全绿"。
建议台账增设"结构门禁 / 编译门禁"两列。

### 4. ADR 的"合规检查点"需覆盖同类实现的所有形态
`ADR-001:48-49` 只点名 `system/win/` 与 `pywin32`，导致 `service.py` 里的 `subprocess.Popen`
**在字面上绕过了检查点**。建议修订为按**能力**而非**库名**定义（如"任何在 sidecar 中创建进程的实现"）。

### 5. 「抽样验证」不能替代「全量通读」
REVIEW-001 的 sidecar 实测抽样了 3 个端点，恰好漏掉出问题的那一个。
建议：对**同一模块的所有分支**做全量枚举，而非抽样。

> 以上 5 条建议**不影响本次判定**，属制度层改进，供白宇决策。

---

## 十三 · 下一步

1. **开发方**按 §十 清单返工，建议顺序：`R-03 → R-01 → R-02 → R-05 → R-07 → R-04/R-06 → 其余`。
2. 安装 Rust 工具链，消除 B101。
3. 重跑 `python tools/gate.py --stage 1 --build`，要求 **0 FAIL**。
4. 备齐 `SUPERVISOR.md` §五 七项证据（含**编译输出原文**与**测试输出原文**）。
5. 说「**申请审核阶段 1**」，走完整送审流程 → 出具 `REVIEW-003`。

**当前进度定位**：阶段1 **未完成、未通过**；阶段2~9 未开工。
阶段2（软件管理）**不得启动** —— `SUPERVISOR.md` §7.1 第 1 条：「未经审核通过，不得进入下一阶段」。

---

*审核人：肉编器001号（项目审核员） · 2026-09-12*
*本报告全部结论均附可复现证据（文件路径 + 行号 / 命令 + 原始输出）；*
*涉及运行的结论已标注验证方式；未能运行的项均已明示"未验证 + 原因"，无一项冒充已验证。*
