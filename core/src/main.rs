//! 装配层：只负责模块组装与启动顺序，禁止业务逻辑（见 docs/agent-dev/AGENTS.md 禁止事项）。
//!
//! 启动顺序：
//! 1. AppState（数据库 + 事件总线 + 配置服务）
//! 2. 本地 HTTP 服务（/api/v1 与 /internal，契约见 docs/agent-dev/03-数据契约与接口规范.md）
//! 3. Python sidecar（媒体/性能/AI，ADR-001 后不再承载窗口与进程控制）
//! 4. Tauri 窗口

mod api;
mod app_manager;
mod db;
mod event_bus;
mod scheduler;
mod sidecar;
mod state;
mod window_manager;

use std::sync::Arc;

use crate::state::AppState;

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    let app_state = Arc::new(AppState::initialize()?);

    api::spawn_server(app_state.clone());
    sidecar::spawn_and_watch(app_state.clone());

    tauri::Builder::default()
        .manage(app_state)
        .invoke_handler(tauri::generate_handler![
            api::commands::ping,
            api::commands::get_config,
            api::commands::put_config,
            api::commands::minimize_window,
        ])
        .run(tauri::generate_context())
        .map_err(|err| anyhow::anyhow!("tauri 启动失败: {err}"))?;

    Ok(())
}
