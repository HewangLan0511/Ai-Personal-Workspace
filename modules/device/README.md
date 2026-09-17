# device/ —— 设备中心模块（阶段8 · 11 §B）

> 代码在 `core/src/device/`。只管理电脑（11 §B1），手机/平板归后续版本。
> 核心模块形态交付，插件迁移归阶段9（同 `modules/life/README.md` 的口径说明）。

## 职责边界

| 能力 | 位置 | 依据 |
|------|------|------|
| 硬件指标（CPU/内存/磁盘） | `core/src/device/metrics.rs`，纯 Win32 API | 本机能力归 Rust（ADR-001）；**不引第三方 crate**（crates.io 本机不可达 + Win32 直调更贴合项目口径） |
| 指标环形缓冲 + `DEVICE_METRICS_UPDATED` | `core/src/device/mod.rs::spawn_device_watcher` | 默认 2s 可配（下限 1s）；**不落库**（11 §B2） |
| 进程列表（CPU% 跨请求差分） | `core/src/device/processes.rs`（`EnumProcesses` + `GetProcessTimes`） | 11 §B3 |
| 结束进程 | `app_manager::terminate` 复用 + `confirm` 强制校验 | 红线 V5 双保险 |
| 模式健康度 | `core/src/device/mod.rs::mode_health` | 11 §B4 轻实现（见下） |

## 不变量

1. **kill 双保险**：UI 弹窗（第一道）+ API `confirm != true` 一律 400（第二道）；core 拒绝结束自身进程。
2. **高频线**：指标间隔 clamp 到 ≥1s（11 §禁止事项"CPU 采集 < 1s 影响性能"）；缓冲上限 600 点。
3. **不落库**：指标历史只在内存（最近 5 分钟），重启即清 —— 11 §B2 明示。

## API（双通道同源）

| Tauri command | HTTP | 说明 |
|---------------|------|------|
| `device_metrics` | GET `/api/v1/device/metrics` | 当前值 + history 环形缓冲 |
| `device_processes` | GET `/api/v1/device/processes` | 进程列表（按 CPU 排序） |
| `device_process_kill` | POST `/api/v1/device/processes/kill` | `{pid, confirm:true}` |
| `device_mode_health` | GET `/api/v1/device/mode-health` | 模式健康度 |

## B4 模式健康度的口径声明（如实）

11 §B4 的原始口径是"启动耗时统计 + 超时提示"，但阶段4 的 `LaunchOutcome` **没有把
per-app 启动耗时落库**，本阶段无可消费的数据源 —— 与其编造指标，改用两个真实事实：
软件历史**启动次数**（`apps.launch_count`，阶段2）+ 该软件**今日实际使用秒数**
（`usage_stats`，本阶段）。若后续要补"启动耗时"，需在 launcher 落库耗时数据，
届时本端点扩展即可（接口已预留 `apps` 数组结构）。

## GPU / 温度

Windows 上没有免驱动的通用 WMI 通道（各厂商接口互不兼容）。11 说"能拿到就拿"
—— 本阶段**如实不提供**这两个指标，UI 不展示假数据。

## 验收步骤（`tools/verify_stage8.py`）

1. `GET /device/metrics`：cpu ∈ [0,100]、mem_total > 0、disks 非空；与 psutil 对照（±30%）。
2. 2s 后二次请求 → history 增长（环形缓冲推进）。
3. `GET /device/processes` 非空、含 core 自身进程。
4. kill：core 起一个受控子进程 → `confirm:false` → 400；`confirm:true` → 进程退出。
