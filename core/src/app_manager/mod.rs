//! 软件管理（阶段2 交付范围）。
//!
//! **ADR-001**：进程启动 = Rust（`CreateProcessW`，见 `launcher.rs`）。
//! 注册表扫描与图标提取归 Python sidecar（05 §禁止事项：不在 UI 线程做注册表扫描）。
//!
//! 子模块：
//! - `repository` —— `apps` 表 CRUD + 排序（core 是唯一写入者）
//! - `launcher`   —— 进程启动（`CreateProcessW` / `ShellExecuteW`）
//! - `status`     —— 按 pid 轮询存活（05 §3）
//! - `files`      —— 文件选择器（05 §1 添加方式一，零新依赖）

mod files;
mod icon;
mod launcher;
mod repository;
mod status;

pub use files::pick_executable;
pub use icon::read_as_data_url as read_icon_data_url;
pub use launcher::launch;
pub use repository::{AppInput, AppPatch, AppsRepo};
pub use status::{is_alive, terminate, RunningApps};

use std::path::Path;

/// 校验路径是否为可启动目标（05 §2 注册校验）。
pub fn validate_path(path: &str) -> bool {
    let p = Path::new(path);
    if !p.exists() {
        return false;
    }
    match p.extension().and_then(|e| e.to_str()) {
        Some(ext) => ["exe", "lnk", "bat", "cmd"].contains(&ext.to_ascii_lowercase().as_str()),
        None => false,
    }
}

/// 启动一个**已注册**的软件。
///
/// **HTTP（`/api/v1/apps/{id}/launch`）与 Tauri（`apps_launch`）两个入口共用这一份逻辑**
/// —— 双通道只允许入口不同，不允许各写一套（否则必然漂移）。
///
/// 流程（05 §2）：
/// 校验路径 → 已在运行则跳过（不重复拉起）→ 启动 → 记录 running → 累加 launch_count → 发 `APP_OPENED`。
pub fn launch_registered(
    state: &crate::state::AppState,
    id: i64,
) -> anyhow::Result<serde_json::Value> {
    let app = state
        .apps
        .get(id)?
        .ok_or_else(|| anyhow::anyhow!("软件不存在：id={id}"))?;

    // 05 §2「已在运行 → 不要重复拉起」（"激活已有窗口"是阶段3 的窗口能力）。
    if let Some(pid) = state.running.get(id) {
        if is_alive(pid) {
            return Ok(serde_json::json!({
                "appId": id, "pid": pid, "alreadyRunning": true, "pidTracked": true
            }));
        }
        state.running.forget(id);
    }

    if !validate_path(&app.path) {
        anyhow::bail!("文件不存在或不可启动：{}（是否重新指定？）", app.path);
    }

    let outcome = launch(&app.path, &app.args)?;
    if let Some(pid) = outcome.pid {
        state.running.mark(id, pid);
    }
    state.apps.touch_launch(id)?;

    // 契约 3.3：APP_OPENED { appId, pid, hwnd }。hwnd 属阶段3 能力，此处为 null。
    let _ = state.bus.publish(
        crate::event_bus::APP_OPENED,
        serde_json::json!({
            "appId": id, "pid": outcome.pid, "hwnd": serde_json::Value::Null, "name": app.name
        }),
    );

    Ok(serde_json::json!({
        "appId": id,
        "pid": outcome.pid,
        "pidTracked": outcome.pid_tracked,
        "alreadyRunning": false,
    }))
}

/// 结束一个**由模式拉起**的软件（06 §3 `exclusive` 切换策略）。
///
/// **安全约束（REVIEW-010 R-01）**：调用方必须先确认该进程属于"模式拉起的"
/// （查 `scheduler::RunRecord::launched_by`），本函数只按 `running` 登记取 pid 并结束，
/// **不做归属判断** —— 否则会把用户自己开的程序一起关掉。
pub fn kill_registered(state: &crate::state::AppState, app_id: i64) -> anyhow::Result<()> {
    let pid = state
        .running
        .forget(app_id)
        .ok_or_else(|| anyhow::anyhow!("该软件未在运行（无 pid 登记），无需结束"))?;
    status::terminate(pid)?;
    tracing::info!(app_id, pid, "已结束模式拉起的软件");
    // 契约 3.3：APP_CLOSED
    let _ = state.bus.publish(
        crate::event_bus::APP_CLOSED,
        serde_json::json!({ "appId": app_id, "pid": pid, "byMode": true }),
    );
    Ok(())
}

/// 启动运行状态轮询（05 §3：默认 5s）。
///
/// 进程退出即发 `APP_CLOSED`，UI 据此取消"运行中"标记。
/// 用独立线程而非 tokio 任务：`is_alive` 是阻塞式 Win32 调用，
/// 放进异步 executor 会占住 worker 线程（05 §禁止事项的同类问题）。
pub fn spawn_status_watcher(state: std::sync::Arc<crate::state::AppState>) {
    const INTERVAL: std::time::Duration = std::time::Duration::from_secs(5);
    std::thread::spawn(move || loop {
        std::thread::sleep(INTERVAL);
        for app_id in state.running.reap_exited() {
            tracing::info!(app_id, "检测到软件已退出");
            let _ = state.bus.publish(
                crate::event_bus::APP_CLOSED,
                serde_json::json!({ "appId": app_id }),
            );
        }
    });
}
