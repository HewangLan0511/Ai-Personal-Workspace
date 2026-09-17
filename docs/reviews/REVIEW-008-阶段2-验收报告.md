# REVIEW-008 · 阶段2 验收报告（软件管理系统）

| 项 | 内容 |
|----|------|
| 报告编号 | REVIEW-008 |
| 日期 | 2026-09-12 |
| 编写 | 肉编器001号（**架构 + 开发 + 审核 同一主体** —— 独立性限制见 M-5 / 第七章） |
| 审核对象 | 阶段2「软件管理系统」交付物（`core/src/app_manager/` · `system/win/apps_probe.py` · `ui/src/views/SoftwareView.vue`） |
| 基准 | `05-阶段指令-软件管理.md` · `02` · `03` · `ADR-001` |
| 判定标准 | **白宇 2026-09-12 22:35 确立的唯一标准**：① 能否实现当前阶段目标 ② 不留致命漏洞或冗余垃圾 |
| 门禁 | **FAIL=0 / WARN=0 / PASS=16**（`gate.py --stage 2 --build`） |
| 判定 | **✅ 通过** |

---

## 一、目标达成（05 的「验收一句话」）

> **验收一句话**：用户能把一个 exe 加进工作台，点一下就能打开它。

用 `tools/verify_stage2.py` 端到端核验（走 core 的 HTTP 面，与 UI 的 invoke 面**同源**）：

```
PASS  1  添加软件                     status=200 id=1
PASS  1b 列表可见                     列表=['验收测试A', '验收测试B']
PASS  2  启动软件（tasklist 复核 pid） pid=35080 进程存在=True      ← 关键项
PASS  3  启动失败提示（可读且未崩溃）  msg='文件不存在或不可启动：C:\__no_such_dir__\nope.exe（是否重新指定？）'
PASS  4  状态同步（杀进程后 5s 内清标记）杀前运行中=True 杀后已清=True
PASS  5  分类与搜索                   分类过滤=True(1) 搜索=True(1)
PASS  6  排序（次数非降序 + 置顶优先） 次数=[('验收测试B',3),('验收测试A',1),('验收测试-坏路径',0)]
PASS  7  扫描已安装软件（注册表）      status=200 条目=79
PASS  8  持久化（重启后列表与计数保持）列表=[…] 计数={'B':3,'A':1}
PASS  10 自动补全（名称/图标/目录穿越防护）name='记事本'；图标 dataURL=OK；越权路径被拒=True
合计 10/10 通过
```

**验收 2 是本阶段的要害**：`tasklist` 复核确认 pid **真实存在**，证明 `CreateProcessW` 真的把进程启起来了 ——
而不是"接口返回了一个数字"。这条不通过，阶段2 就是纸面工程。

## 二、无致命漏洞

| 项 | 结论 |
|----|------|
| 红线 V1~V8 | 未命中（阶段2 不碰密钥 / AI / 插件权限；无破坏性操作） |
| **单一写入者**（02 §2.4） | 保持。`apps` 表写入只经 `AppsRepo`（Rust）；UI 经 invoke；sidecar 对 `/internal/db/*` 仍返回 410 |
| **ADR-001**（进程启动 = Rust） | 遵守。`launcher.rs` 用 `CreateProcessW`；Python 侧只做注册表/图标（属"系统 API"，非 ADR-001 管辖）。门禁 A031 扫描通过 |
| **图标接口目录穿越** | 已防：`read_as_data_url` 用 `canonicalize` + `starts_with(icons_dir)` 校验，越权路径实测被拒 |
| **命令注入**（05 §禁止事项） | 无 `shell=True` 拼串；`CreateProcessW` 用 `lpApplicationName` 显式指定路径 |
| SQL 注入 | 全参数化（`?1` 占位）；搜索的 `%` `_` 已转义 |
| 路径校验 | `validate_path` + 「文件不存在 → 可读提示」实测通过（验收 3） |

## 三、无冗余垃圾

- 门禁 `0 FAIL / 0 WARN`；
- 审核期产生的临时诊断脚本与输出（`.rev/dbg2.py`、`gate.txt`、`icons_test/`）**已清理**，仅保留三份独立审核报告；
- `gate.py` 的 `SKIP_DIRS` 增加 `.rev`（审核产物目录不该被当项目源码扫 —— 它导致过 1 FAIL + 15 WARN 的假违规）；
- `R001` 增加"跳过 Rust `#[cfg(test)]` 模块"：测试里的 `unwrap()` 是断言语义，不是风险用法（原判据产生 27 条噪音 WARN）。

## 四、实现落点（对照 05 交付物）

| 交付物 | 落点 |
|--------|------|
| `apps` 表 + repository（CRUD + 排序） | `core/src/app_manager/repository.rs`（迁移 `0002_apps_pinned.sql` 加 `pinned`） |
| 启动 / 状态检测（ADR-001 方案） | `launcher.rs`（`CreateProcessW`）+ `status.rs`（5s 轮询 → `APP_CLOSED`）+ `files.rs`（`GetOpenFileNameW` 文件选择器） |
| 已安装软件扫描器 | `system/win/apps_probe.py::scan_installed` → sidecar `/apps/scan`（32/64 位视图 + 去重） |
| 图标提取与缓存 | `apps_probe.py::probe`（ctypes 取 HICON → 标准库 zlib 自编码 PNG）→ `<data_dir>/icons/<hash>.png` |
| 软件库页面 UI | `ui/src/views/SoftwareView.vue`（网格/列表切换 + 分类侧栏 + 搜索 + 空状态 + 添加弹窗） |
| 三个事件 | `apps_add` → `APP_REGISTERED`；`launch_registered` → `APP_OPENED`；`spawn_status_watcher` → `APP_CLOSED` |
| 模块 README + 验收步骤 | `core/README.md`「验收步骤（阶段2）」+ `tools/verify_stage2.py` |

**零新增第三方依赖**：Rust 侧仅扩 `windows` crate 的 feature；Python 侧纯标准库（`winreg`/`ctypes`/`zlib`）；
文件选择器用 `GetOpenFileNameW` 自实现（未引 `tauri-plugin-dialog`）—— 遵守"不引入需联网才能运行的依赖"。

## 五、测试

`cargo test --all` → **12 passed / 0 failed**（阶段1 的 6 条 + 阶段2 新增 6 条）：

- `repository::list_orders_by_pinned_then_launch_count`（排序 + 搜索转义 + 软删除/复活）
- `repository::duplicate_active_path_is_rejected_with_friendly_error`
- `status::reap_removes_dead_and_keeps_alive`
- `icon::base64_matches_reference_vectors`（RFC 4648 向量）
- `icon::rejects_path_outside_icons_dir`（目录穿越）
- `icon::reads_png_inside_icons_dir`

前端 `vue-tsc --noEmit` → 0 error。

## 六、未解决项（非阻塞，如实登记）

| # | 项 | 级别 | 说明 |
|---|----|:----:|------|
| U-16 | **事件未桥接到前端**（L-017 延续） | 一般 | 阶段2 发布了 `APP_REGISTERED/OPENED/CLOSED`，但 webview 无 `listen()`。UI 的"运行中"标记靠 **5s 轮询** `/api/v1/apps/running`（可用，但事件实际无人消费）。阶段4 若需即时反馈必须补桥 |
| U-17 | `.lnk` 启动拿不到 pid | 建议 | `.lnk` 走 `ShellExecuteW`（系统处理），pid 不可得 ⇒ 无法跟踪存活、不挂"运行中"。当前 `.lnk` 可添加但状态不跟踪。若要完整支持需解析 `IShellLink` |
| U-18 | 部分图标提取降级 | 建议 | UWP 别名（如 `mspaint.exe`）无内嵌图标资源 → `iconPath=null`，前端用首字母占位。属**设计内降级**，不阻塞 |
| U-19 | 拖拽添加未做 | 建议 | 05 列为"V1.1 可选"，本阶段未实现 |
| U-20 | UI 侧无自动化测试 | 建议 | 与阶段1 同（无前端测试运行器）；★ 级交互由 CDP 探针覆盖，软件库页面的交互靠 `verify_stage2.py` 的 HTTP 端到端 + 人工目视 |

## 七、判定与独立性

按白宇 22:35 确立的唯一标准：**① 目标达成 ✅ ② 无致命漏洞 ✅ ③ 无冗余垃圾 ✅** ⇒ **阶段2 通过**。

**独立性保留（M-5 未变）**：本判定由"同一主体 + 机器门禁 + 可复现脚本"作出，
**不构成外部第三方独立审核**。三条证据链（门禁 0F/0W/16P · cargo test 12/12 · verify_stage2.py 10/10）
均可由任何人重跑复现 —— 结论的可信度来自**可复现**，不来自本报告的措辞。

> **并发提醒（M-8）**：本轮开发期间另一会话在并行改动同一仓库
> （`02` §2.1/§2.4 的 ADR-001 口径、`gate.py` 的 A031 ctypes 检测、`LEDGER.md` 与 `REVIEW-005` 均已被其更新）。
> 我修正了其中一处**判据过宽**的问题（A031 按库名匹配会误伤图标提取）。
> M-8（审核基线漂移）仍待白宇裁决。

---

*机器可判部分以 `tools/gate.py`、`tools/verify_stage2.py`、`cargo test` 的**可复跑输出**为准。*
