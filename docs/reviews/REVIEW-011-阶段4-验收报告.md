# REVIEW-011 · 阶段4 验收报告（工作模式引擎 ★ 核心）

| 项 | 内容 |
|----|------|
| 报告编号 | REVIEW-011 |
| 日期 | 2026-09-12 |
| 编写 | 肉编器001号（**架构 + 开发 + 审核 同一主体** —— 独立性限制见 §六） |
| 审核对象 | 阶段4「工作模式引擎」交付物（`core/src/scheduler/` · `ui/src/views/ModeView.vue` · `ModeBar.vue`） |
| 基准 | `06-阶段指令-工作模式引擎.md`（★ 全项目最高优先级）· `02` · `03` · `ADR-001` |
| 判定标准 | 白宇 2026-09-12 22:35 唯一标准 + **23:26「严格审核，不能遗漏任何功能和致命漏洞」** |
| 逐条矩阵 | [`REVIEW-010`](REVIEW-010-阶段4-功能与验收矩阵.md)：**43 功能 + 13 判据 + 5 禁止 + 9 交付物 + 8 漏洞**，全部回填 |
| 门禁 | **FAIL=0 / WARN=0 / PASS=14**（`gate.py --stage 4 --build`） |
| 判定 | **✅ 通过**（含 3 项明确未实测，已单列，未混入通过项） |

---

## 一、目标达成（06 的「验收一句话」）

> **验收一句话**：把"软件 + 文件 + 布局 + AI"打包成可一键进入的环境。

`tools/verify_stage4.py`：**13/13 PASS**

```
V-01 创建模式（4 软件）        id=1 apps=[VT-Dx,VT-Si,VT-Wv,VT-Cc]；重启后仍在
F-08 复制模式                  副本名='验收模式A 副本'，不继承 autoApply
V-02 一键进入（<20s）          launched=4 / 存活 4/4 / **1.70s**
V-02b 窗口排列（4 槽全排）      arranged=4
V-09 状态显示                  running='验收模式A'
V-05 幂等                      launched=0 already=4
V-03 进度可见                  轨迹=validating→launching→waiting_ready→arranging→opening_files→loading_ai→done
V-03b 进度含每项结果            4 项 launched 齐全
V-08 布局持久化                写库 ✓；窗口 h=720 = 工作区 1440/2
V-04 容错                      成功 2 / 失败 1；原因可读 + retriable=true
V-07 切换 additive             policy=additive closed=[] 旧软件保留
V-06 可取消                    cancelled=true state=cancelled
V-10 恢复                      configured='验收模式A切换'；未自动应用；restore 成功
```

**方法论**：不采信接口自述 —— 每次都回读 `/api/v1/apps/running` 与 `/api/v1/windows?pid=`
交叉验证"进程/窗口真的在"。V-02 的"1.70s"尤其说明问题：串行启动 4 个软件不可能达到。

---

## 二、无致命漏洞

| 风险 | 结论 |
|------|------|
| **R-01 误杀用户进程** | `RunRecord::launched_by` 是**唯一**依据；`mode_exit` / `exclusive` 只遍历登记内 appId，**绝不按进程名杀**。UT `launched_registry_is_per_mode` 锁死 |
| R-02 软删模式仍可 apply | `get/list` 均过滤 `deleted_at`；UT 覆盖 |
| R-03 布局名路径穿越 | `upsert` 与 `load_layout` 双处拒绝 `..` `/` `\`；UT 覆盖 |
| R-04 取消后残留任务 | 协作式取消（各步检查）；非法状态流转被 `can_transition` 拒绝并告警 |
| R-05 幂等不完整 | 幂等只跳过**启动**，`wait_ready` 仍等窗口就绪 → 不会重复拉起 |
| R-06 并发写竞争 | 结果统一经 `ModeSession::record`（Mutex）；状态经 `transition`（单锁） |
| R-07 use_count 误计 | 仅在 `!cancelled` 的完成路径调用 `touch_used` |
| R-08 config 键未登记 | `mode.current` / `mode.switch_memory` / `ai.active_profile` 三处齐备；UT 锁死 |
| 红线 V1~V8 | 未命中（不碰密钥/AI/插件；**唯一的破坏性动作是 `exclusive` 结束进程，且限定在登记内**） |
| ADR-001 | 遵守：进程/窗口能力全在 Rust；`system/` 无同类实现（门禁 A031 通过） |

---

## 三、无冗余垃圾

- 门禁 `0 FAIL / 0 WARN`；编译仅剩 10 条 warning，**全部是阶段5~9 的骨架常量**（`AI_*` / `PLUGIN_*` / `LEARNING_*` 等，属条例允许的"架子先立起来"）；
- 清掉了 `unused_imports`、`unused_must_use`、`dead_code`（`overlaps` 标注理由保留）；
- 诊断脚本 `.rev/dbg4.py` 用完即删。

---

## 四、测试

`cargo test --all` → **38 passed / 0 failed**（阶段3 的 20 条 + **阶段4 新增 18 条**）：

| 模块 | 条数 | 覆盖 |
|------|:----:|------|
| `scheduler::state` | 8 | 前进合法 / **跳步拒绝** / **同阶段进度推进允许** / 终态不可流转 / 任意可取消 / Failed 只从 Validating / 部分失败落 Done / 进度文案 |
| `scheduler::runner` | 4 | 取消令牌跨克隆可见 / **非法流转被拒** / **launched 登记按模式隔离**（R-01） / 切换快照与 previous |
| `scheduler::repository` | 6 | CRUD 往返（**含 JSON 字段二次解析**）/ **软删不可见**（R-02）/ 副本命名与不继承 autoApply / 非法策略与重名拒绝 / use_count 与时间 / 布局 upsert（**含路径穿越拒绝**） |

前端 `vue-tsc --noEmit` → 0 error。

---

## 五、开发中抓到的真实缺陷（都是**警告/测试**先暴露的）

按"严格审核"要求，把过程如实记录 —— 这些不是"写对了"，是**先写错再被抓住**：

| # | 缺陷 | 如何暴露 | 性质 |
|---|------|----------|------|
| 1 | `apps` / `slots` 等存在 TEXT 列的 JSON **只解析一层** → 读出来永远是空数组 | `repository` 单测失败 | **真 bug**（功能静默失效） |
| 2 | 状态机 `can_transition` 只判"rank 更大" → **跳步放行** | 单测 `skipping_steps_is_rejected` | 真缺陷（状态机形同虚设） |
| 3 | 修 #2 时改严成"必须相邻" → **同阶段进度推进被误拒**（进度事件全废） | 运行日志 `非法的状态流转已忽略 from=Launching{done:0} to=Launching{done:1}` | **真 bug**（自伤回归） |
| 4 | `exit_mode` 清空 `mode.current` → **"上次使用"永久丢失**，V-10 无法通过 | 验收 V-10 失败 | 真 bug |
| 5 | `ApplyOutcome` 字段名 camelCase/snake_case 混用（`alreadyRunning` vs `arrange_note`） | 诊断脚本输出 | 真缺陷（前端读 undefined） |
| 6 | `session.record` 从未被调用 → **进度面板的 slots 恒为空** | 编译警告 `method record is never used` | 真 bug |
| 7 | `ApplyState::Failed` 从未被构造 → 校验失败时 UI 停在 `validating` 的僵尸态 | 编译警告 `variant Failed is never constructed` | 真 bug |
| 8 | `snapshot_before_switch` 从未被调用 → 06 §3 的切换快照没做 | 编译警告 | 功能缺失 |
| 9 | `autoApply` 只存字段、**未接线**到启动流程 | 写 README 时自查 | 功能缺失（F-34 不完整） |
| 10 | 验收脚本用内置 `quad` 布局（slots 是 VSCode/Chrome/…）与测试软件名不匹配 | S4 V-02b 失败 | **脚本问题**（非产品缺陷，已实测换布局后正常） |

> #6/#7/#8 是**编译期警告**抓出来的 —— 印证了"把警告当噪音会漏掉真问题"。
> #10 说明：**验收失败 ≠ 产品有 bug**，必须先定位到底是哪一层的问题。

---

## 六、明确未覆盖项（不藏着，也不打折判定）

| # | 项 | 风险 | 说明 |
|---|----|:----:|------|
| N-1 | **`exclusive` / `ask` 未端到端实测** | **中** | 代码与单测齐备（策略解析、记忆读写、`kill_registered` 的 R-01 约束），但没跑"真的关掉 A 的软件"。**`exclusive` 是唯一会结束用户进程的路径，建议优先补测** |
| N-2 | 文件入口（openTargets）未端到端实测 | 低 | 代码路径完整（`open_targets` → `ShellExecuteW`），失败只发事件不中断 |
| N-3 | `autoApply` 自动进入未实测 | 低 | 已接线（`main.rs` `.setup()` 延时 1.5s）；因"每次启动都会拉起软件"不适合放进自动化验收 |

这三项**不影响阶段4 通过**（06 的 10 项验收标准未要求，且 `exclusive` 原文标注"可选"），
但按要求**单独列出**，不混进通过项。

---

## 七、判定与独立性

按唯一标准：**① 目标达成 ✅（13/13 实测）② 无致命漏洞 ✅ ③ 无冗余垃圾 ✅** ⇒ **阶段4 通过**。

**证据链**（任何人可复跑）：门禁 `0F/0W/14P` · `cargo test` `38/38` · `verify_stage4.py` `13/13` · `vue-tsc` `0 error`。

**独立性（M-5）**：本判定由"同一主体 + 机器门禁 + 可复现脚本"作出，**不构成外部第三方独立审核**。

> **建议走一次独立复核**：阶段4 是 06 明令的 ★ 核心，也是 SUPERVISOR 第十三章点名的
> "关键节点（阶段4 ★）强制一次性独立复核"的适用对象。若要执行，口令为
> **「申请独立复核阶段 4」** —— 届时会另起全新上下文实例，只接收产物、不接收本报告结论。

---

*机器可判部分以 `tools/gate.py`、`tools/verify_stage4.py`、`cargo test` 的**可复跑输出**为准。*
