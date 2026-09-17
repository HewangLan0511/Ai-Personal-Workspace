# scheduler —— 工作模式引擎（阶段4 · ★ 全项目核心）

> **06-阶段指令-工作模式引擎**：把"软件 + 文件 + 布局 + AI"打包成**可一键进入的环境**。
> 06 原文：*"这是全项目唯一的创新点。这个做不好，其余模块做得再漂亮也没意义。"*

---

## 状态机（06 §2）

```
Idle ──→ Validating ──→ Launching ──→ WaitingReady ──→ Arranging
                                                            │
                                                            ▼
                        Done ←── LoadingAI ←── OpeningFiles
                         ▲
                         │（部分失败仍走完全程，只带 failed 计数）
   Validating ──→ Failed（校验失败：流程未开始）
   任意非终态 ──→ Cancelled
```

`ApplyState` 是**单一枚举**（06 §禁止事项：不得用一堆布尔变量表达流程状态）。
合法性由 `ApplyState::can_transition` 强制，非法流转被拒并记 `WARN`：

| 规则 | 说明 |
|------|------|
| 终态不可再流转 | `Done` / `Failed` / `Cancelled` 之后不能被"复活" |
| 任意非终态可取消 | 06「可取消」 |
| 只有 `Validating` 能进 `Failed` | 校验失败 = 流程未开始；其余失败走 `Done{failed:n}` |
| **同阶段内推进 = 进度更新** | `Launching{done:1}` → `{done:2}` 必须允许，否则进度事件全被拒 |
| 跨阶段必须**相邻** | 防跳步（`Idle → Arranging` 会被拒） |

---

## 模块

| 文件 | 职责 |
|------|------|
| `state.rs` | 状态机（纯逻辑，8 条单测） |
| `repository.rs` | `work_modes` / `layouts` 持久化（**DB 是唯一真相**；布局写库后导出 JSON） |
| `runner.rs` | 会话（进度 + 取消令牌 + 每项结果 + **阶段轨迹**）、运行记录（**模式拉起的软件**） |
| `pipeline.rs` | 七步流水线：校验 → 并发启动 → 等待就绪 → 排列 → 开文件 → 载 AI → 更新状态 |
| `mod.rs` | 模块出口与布局文件定位 |

---

## 关键设计

### 1. 并发启动（不是串行 for）
每个软件一个线程 + `mpsc` 收集，单软件 15s 超时（`recv_timeout`）。
实测 4 个软件 **1.70s** —— 串行不可能达到（06 验收要求 < 20s）。

### 2. 等待就绪用轮询，不用固定 sleep
`wait_ready` 每 300ms 轮询 `find_main_window(pid)`，20s 上限，返回**已就绪的子集**（partial）。
06 §技术要点明确点名："不要用固定 `sleep(5)` 糊过去"。

### 3. 「模式只管理自己拉起的软件」——**这是最危险的一条**
`RunRecord` 记录 `modeName → appId[]`。`mode_exit` 与 `exclusive` 切换**只遍历这份登记**，
**绝不按进程名去杀**。否则会把用户自己打开的程序一起关掉（REVIEW-010 **R-01**）。

### 4. 进度轨迹由会话自己记，不靠外部轮询
apply 全程可能只有 1 秒出头，外部按 50ms 轮询**必然抓不全**中间态。
`ModeSession::history` 记录走过的阶段 —— UI 的"步骤清单"与验收的"进度可见"以它为依据。

### 5. 数据库是唯一真相
布局编辑走 `LayoutRepo::upsert`（唯一写入口）：**先写库**，成功后导出 `config/layouts/<name>.json`。
导出失败只记 `WARN` —— JSON 是派生品。

---

## API（Tauri command / HTTP 同源）

| 命令 | HTTP | 说明 |
|------|------|------|
| `modes_list` | `GET /api/v1/modes` | 模式列表（过滤软删除） |
| `modes_add` / `modes_update` / `modes_delete` | `POST/PUT/DELETE /api/v1/modes[/{id}]` | CRUD |
| `modes_duplicate` | `POST /api/v1/modes/{id}/duplicate` | 复制（不继承 autoApply） |
| **`mode_apply`** | `POST /api/v1/modes/{id}/apply` | ★ 一键进入 |
| `mode_cancel` | `POST /api/v1/mode/cancel` | 取消 |
| `mode_progress` | `GET /api/v1/mode/progress` | 进度 + 每项结果 + **阶段轨迹** |
| `modes_current` | `GET /api/v1/mode/current` | `running`（本次）/ `configured`（上次使用） |
| `mode_restore` | `POST /api/v1/mode/restore` | 一键恢复上次使用的模式 |
| `mode_exit` | `POST /api/v1/mode/exit` | 退出（关闭**模式拉起的**软件） |
| `modes_remember_switch` | `POST /api/v1/mode/remember` | 记住 `ask` 策略选择 |
| `db_layouts_list` / `db_layout_upsert` | `GET/POST /api/v1/db/layouts` | 布局（DB 为真相） |

---

## 验收步骤

```bash
cd core && cargo build --release && cd ..

# 06 的 10 项验收标准 → 13 条机器判据
python tools/verify_stage4.py

# 状态机 / 仓储 / 会话的单测
cd core && cargo test scheduler
```

`verify_stage4.py` 用 4 个**经典 Win32 GUI**（dxdiag / msinfo32 / winver / colorcpl）做被测程序，
每次都回读 `/api/v1/apps/running` 与 `/api/v1/windows?pid=` 交叉验证 ——
**不采信接口自述的"我启动了"**。

---

## 已知限制

- **文件入口未端到端实测**（代码完整，验收未构造真实目录）。
- **`exclusive` / `ask` 未端到端实测**（代码与单测齐备）。`exclusive` 是唯一会结束用户进程的路径，
  **建议优先补测**。
- `autoApply`：字段、向导勾选与**启动时自动进入**（`main.rs` 的 `.setup()`，延时 1.5s）均已接线；
  但"自动进入"本身未做端到端实测（会在每次启动时拉起软件，不适合放进自动化验收）。
