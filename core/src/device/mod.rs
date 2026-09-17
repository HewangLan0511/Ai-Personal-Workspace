//! 设备中心（11 §B）—— 硬件指标（B2）+ 进程管理（B3）+ 模式健康度（B4）。
//!
//! 架构口径：
//! - 指标采集 = 本机系统能力，归 Rust（02 §2.4 / ADR-001），纯 Win32 API（见 [`metrics`]）。
//! - 指标历史 = **内存环形缓冲，不落库**（11 §B2"历史曲线只保留最近 5 分钟"）。
//! - 每 tick 发 `DEVICE_METRICS_UPDATED`（事件常量阶段4 已预留，本阶段接线）。
//! - 刷新间隔可配（`device.metrics_interval_sec`，默认 2s；下限 1s，11 §禁止事项）。

pub mod metrics;
pub mod processes;

use std::collections::VecDeque;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value};

use crate::event_bus::DEVICE_METRICS_UPDATED;
use crate::state::AppState;

/// 环形缓冲覆盖的时间窗（11 §B2：最近 5 分钟）。
const HISTORY_WINDOW_SECS: u64 = 300;
/// 缓冲上限（防止异常小的间隔撑爆内存）。
const HISTORY_CAP_MAX: usize = 600;

pub struct DeviceState {
    pub cpu_sample: Mutex<metrics::CpuSample>,
    pub history: Mutex<VecDeque<metrics::MetricsPoint>>,
    pub scanner: Mutex<processes::ProcessScanner>,
}

impl DeviceState {
    pub fn new() -> Self {
        Self {
            cpu_sample: Mutex::new(metrics::CpuSample::default()),
            history: Mutex::new(VecDeque::new()),
            scanner: Mutex::new(processes::ProcessScanner::new()),
        }
    }
}

impl Default for DeviceState {
    fn default() -> Self {
        Self::new()
    }
}

/// 采集一次指标：算 CPU% → 快照内存/磁盘 → 进环形缓冲 → 发事件。
/// 返回本次快照（供 HTTP 拉取口径与 tick 口径共用同一函数，避免两套数据）。
pub fn collect_once(state: &AppState) -> metrics::MetricsPoint {
    let (cpu, (mem_used, mem_total)) = {
        let mut s = state
            .device
            .cpu_sample
            .lock()
            .unwrap_or_else(|e| e.into_inner());
        (metrics::cpu_percent(&mut s), metrics::memory())
    };
    let point = metrics::MetricsPoint {
        ts: metrics::now_ms(),
        cpu,
        mem_used,
        mem_total,
        disks: metrics::disks(),
    };

    let interval = read_interval_secs(state);
    let cap = ((HISTORY_WINDOW_SECS / interval.max(1)) as usize).clamp(16, HISTORY_CAP_MAX);
    let mut h = state
        .device
        .history
        .lock()
        .unwrap_or_else(|e| e.into_inner());
    h.push_back(point.clone());
    while h.len() > cap {
        h.pop_front();
    }
    drop(h);

    let _ = state.bus.publish(
        DEVICE_METRICS_UPDATED,
        json!({ "cpu": point.cpu, "memUsed": point.mem_used, "memTotal": point.mem_total }),
    );
    point
}

/// 当前指标 + 最近 5 分钟历史（HTTP GET /api/v1/device/metrics）。
pub fn metrics_snapshot(state: &AppState) -> Value {
    let current = collect_once(state);
    let history: Vec<metrics::MetricsPoint> = state
        .device
        .history
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .iter()
        .cloned()
        .collect();
    serde_json::to_value(&history)
        .map(|h| json!({ "current": current, "history": h }))
        .unwrap_or_else(|_| json!({ "current": current, "history": [] }))
}

/// 进程列表（11 §B3）。CPU% 为跨请求差分。
pub fn process_list(state: &AppState) -> Vec<processes::ProcInfo> {
    state
        .device
        .scanner
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .snapshot()
}

/// 结束进程。**`confirm != true` 直接拒绝**（红线 V5：破坏性操作必须二次确认——
/// UI 弹窗是第一道，API 强制 `confirm:true` 是第二道，防绕过 UI 直打接口）。
pub fn kill_process(_state: &AppState, pid: u32, confirm: bool) -> anyhow::Result<()> {
    if !confirm {
        anyhow::bail!("需要 confirm=true（结束进程是破坏性操作）");
    }
    if pid == std::process::id() {
        anyhow::bail!("拒绝结束 core 自身进程");
    }
    crate::app_manager::terminate(pid)
}

/// B4 模式健康度（轻实现）。
///
/// 11 的原始口径是"启动耗时统计 + 超时提示"，但阶段4 的 `LaunchOutcome` **没有把
/// per-app 启动耗时落库**，无数据源可消费——与其编造指标，不如用可复现的两个事实
/// 做替代口径：软件的**历史启动次数**（apps.launch_count，阶段2）与该软件**今日实际
/// 使用秒数**（usage_stats，本阶段）。per-app 启动耗时记录在 `modules/device/README.md`。
pub fn mode_health(state: &AppState) -> Value {
    let modes = crate::scheduler::ModeRepo::new(state.db.clone()).list().unwrap_or_default();
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let apps = state.apps.list(None, None).unwrap_or_default();

    let usage: std::collections::HashMap<String, i64> = crate::db::Db::query_json(
        &state.db,
        "SELECT app_name, seconds FROM usage_stats WHERE day = ?1",
        &[Value::from(today.as_str())],
    )
    .unwrap_or_default()
    .into_iter()
    .filter_map(|row| {
        let name = row.get("app_name")?.as_str()?.to_string();
        let sec = row.get("seconds")?.as_i64()?;
        Some((name, sec))
    })
    .collect();

    let out: Vec<Value> = modes
        .iter()
        .map(|m| {
            let apps_json: Vec<Value> = m
                .open_targets
                .iter()
                .map(|t| {
                    let exe = t
                        .path
                        .rsplit(['\\', '/'])
                        .next()
                        .unwrap_or(&t.path)
                        .to_lowercase();
                    let launch_count = apps
                        .iter()
                        .find(|a| a.path.eq_ignore_ascii_case(&t.path))
                        .map(|a| a.launch_count)
                        .unwrap_or(0);
                    json!({
                        "name": t.label.clone().unwrap_or_else(|| exe.clone()),
                        "launchCount": launch_count,
                        "usedSecondsToday": usage.get(&exe).copied().unwrap_or(0),
                    })
                })
                .collect();
            json!({ "modeId": m.id, "modeName": m.name, "apps": apps_json })
        })
        .collect();
    json!({ "modes": out })
}

fn read_interval_secs(state: &AppState) -> u64 {
    state
        .config
        .get("device.metrics_interval_sec")
        .as_f64()
        .map(|f| f.round().clamp(1.0, 60.0) as u64)
        .unwrap_or(2)
}

/// 后台采集循环：默认 2s（可配），每 tick 采集 + 发事件。非 Windows 平台空转降级。
pub fn spawn_device_watcher(state: Arc<AppState>) {
    #[cfg(windows)]
    {
        std::thread::spawn(move || loop {
            let interval = read_interval_secs(&state);
            let _ = collect_once(&state);
            std::thread::sleep(Duration::from_secs(interval));
        });
    }
    #[cfg(not(windows))]
    {
        let _ = state;
    }
}
