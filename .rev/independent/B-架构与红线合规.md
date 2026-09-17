# 独立审核报告 B · 架构合规与红线

> 审核角色：独立审核员 B（未参与开发、未读评审史，结论仅来自本次自查）
> 审核对象：`C:\Users\baiyu\Desktop\Personal Workspace`（阶段1 代码）
> 约束：未修改任何既有文件，仅产出本报告。

## 一、ADR-001 是否真正遵守（含门禁能否绕过）

**代码层面：遵守。** `system/` 运行时只有 `service.py` 与 `build_sidecar.py`（构建脚本）。`service.py` 无任何 `win32*`/`ctypes`/`subprocess` 窗口或进程调用，且对已迁移的 `/sys/process/*`、`/sys/window/*`、`/internal/db/*` 一律返回 `410 moved_to_core`（service.py:49-55、103-112）。窗口/进程能力确实落在 Rust 侧：`core/src/window_manager/mod.rs`（含 `to_pixels`/`find_main_window`/`set_window_pos`）、`core/src/app_manager/mod.rs`（`launch` 占位）。ADR-001 文字要求成立。

**门禁 A030/A031 可绕过（制度漏洞）。** `gate.py::check_adr001` 只扫 `system/*.py`，且 `PY_PROCESS_LAUNCH_PATTERN`（gate.py:478-484）仅匹配 `subprocess.Popen/run/call/check_output/check_call`、`os.startfile/system/spawnl*/execv*`、`win32process/win32gui/win32api`、`ShellExecute*`、`CreateProcess*`。它漏掉了**等价实现**：
- **ctypes 调用 Win32**：`ctypes.windll.user32.SetWindowPos/EnumWindows/ShowWindow/FindWindow/SetForegroundWindow/GetWindowRect/MoveWindow` 均不在模式中——这正是 ADR-001 禁止的窗口控制"同类实现"，却能被门禁放过。
- `os.popen` 未覆盖（仅 `os.system/startfile`）。
- **动态构造**绕过正则：`getattr(ctypes.windll.user32, "Set"+"WindowPos")` 字面串不出现，门禁判 PASS。
- 检查域固定为 `system/`，未来 sidecar 子包或 core→Python 转发窗口操作（ADR-001 明文禁止）不被校验。

结论：当前代码干净，但门禁"检查点窄于规则"，阶段3 真正写窗口控制前必须补 `ctypes`/动态构造检测。

## 二、八条红线逐条结论

- **V1 明文密钥入库入码**：未命中。全源码 grep 仅在 `tools/gate.py` 的定义与 `node_modules` 噪声中见 secret 字样；`config.rs` 的 `ai.default_provider` 存空串、非密钥。无硬编码密钥。
- **V2 咨询模式读用户数据**：未命中/不适用。阶段1 无 AI/咨询模式代码（`ai/` 仅 README），功能层未核查。
- **V3 AI 自动改进度/档案**：未命中/不适用。同上，无相关模块。
- **V4 插件默认有权限**：未命中。`plugins/` 仅有 README、无源码；无权限授予代码。但仅 `event_bus/events.rs:19` 的 `PLUGIN_PERMISSION_DENIED` 占位，"默认拒绝"执行逻辑待阶段9 落实（当前可接受）。
- **V5 破坏性操作无二次确认**：未命中。阶段1 无结束进程/删文件/切模式；仅 `minimize_window`（无害）。
- **V6 谎报完成**：未核查（行为红线）。代码层无证据；门禁 `check_build` 会跑 `cargo check`/typecheck 收窄谎报空间，但最终以送审"编译/测试原文"证据判定。
- **V7 插件或 UI 直连数据库**：未命中。`ui/` 无 sqlite 引入（grep 仅 `node_modules`）；`system/service.py:103-112` 对 DB 请求返回 410。
- **V8 构建产物入库**：未命中。`.gitignore` 覆盖 `node_modules/`、`target/`、`dist/`、`*.db`、`core/binaries/`、`config/local.*.toml`、`*.key` 等；未发现被追踪产物。

## 三、单一写入者是否成立

**成立。** 唯一 `Db::open` 在 `core/src/state/mod.rs:32`（Rust）。UI 经 `configService.ts:25/43` → Tauri `invoke('get_config'/'put_config')` → `commands.rs:25-40` → `ConfigService` 写入；Python sidecar 直连 DB 一律 410。UI/Python 均不经手 SQLite 句柄。✓

## 四、config.rs 三处登记是否齐全

`config.rs` 登记键 12 个（`KEYS`:68-81）。独立核对三处：
- `KEYS`：12 项齐全；
- `expected_type`（:89-102）：逐项覆盖 12 键，**无键落到 `_ => "any"`**（且被测试 `every_registered_key_has_an_explicit_type`:174 锁死）；
- `default_for`（:117-133）：12 键均有默认值（`runtime.sidecar_port/http_port` 为 `Null`，测试显式允许）。

`set()` 用 `KEYS.contains(&key)` 拒绝未登记键（:41-43），**无键能绕过白名单**；`type_ok` 强制类型校验（:104-114）。三处登记齐全、无漏登、无静默兜底。✓ 完全合规。

## 五、死代码/未接线

- `core/src/app_manager/mod.rs`：`launch` 仅 `bail!("阶段2 实现")`，`validate_path` 纯函数，未接命令——骨架预留。
- `core/src/scheduler/mod.rs`：`ModeState`/`apply_mode` 占位 bail——骨架预留。
- `core/src/window_manager/mod.rs`：`to_pixels` 纯函数（暂未被调），`find_main_window`/`set_window_pos` bail；仅 `minimize_window` 接线——骨架预留。
- `core/src/event_bus/events.rs`：22 常量仅 `CONFIG_CHANGED` 被用，余为阶段2-9 占位——骨架预留。
- `ui/src/utils/logger.ts`：**提示称"死代码"，但实际已被 `client.ts:25` 与 `configService.ts:18` import 并调用，并非死代码**（独立更正提示）。

上述均符合 `13-验收清单 §4`"架子必须先立起来"的合规骨架预留，非违规。

## 六、最终判定

架构合规与红线方面**支持"阶段1 通过"**：ADR-001 代码遵守、八条红线零命中、单一写入者成立、config.rs 三处登记齐全无漏登、死代码均为合规骨架预留。

**唯一制度级建议（不阻塞阶段1，但须在阶段3 前修）**：门禁 `A031` 检查点窄于 ADR-001，漏掉 `ctypes` 等价实现与动态构造绕过；当前代码干净属侥幸，进入窗口控制真正实现前须补齐检测，否则阶段3 可能把窗口控制塞进 sidecar 的 ctypes 而门禁不报。另：编译态未由本审核独立复跑（环境受限），建议依 `HANDOFF §5` 跑 `gate.py --stage 1 --build` 补验。
