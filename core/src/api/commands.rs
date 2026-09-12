//! Tauri commands：UI 经 invoke 调用的桥接层（与 `/api/v1` 等价，双通道）。
//!
//! **UI 侧首选本通道**（见 `ui/src/api/configService.ts`）：
//! Tauri invoke 不经过 HTTP，因此**不受 core 随机端口影响** —— 这是 REVIEW-002 R-02
//! 「UI ↔ core 端口链路断裂」的根因修复。契约 3.4 允许 UI 走 Tauri command 或 `/api/v1`，
//! 此处选定 command 通道为主路径。

use std::sync::Arc;

use serde_json::Value;
use tauri::State;

use crate::state::AppState;

/// 探活命令：UI 判断 core 是否在线（替代浏览器环境下的 `/health`）。
///
/// 修复（REVIEW-002 R-02 配套）：invoke 通道下 UI 无法用 HTTP 探活，
/// 故提供一个零参数、零副作用的 liveness 探针。
#[tauri::command]
pub fn ping() -> &'static str {
    "pw-core"
}

#[tauri::command]
pub fn get_config(state: State<'_, Arc<AppState>>, key: String) -> Value {
    state.config.get(&key)
}

#[tauri::command]
pub fn put_config(
    state: State<'_, Arc<AppState>>,
    key: String,
    value: Value,
) -> Result<Value, String> {
    state
        .config
        .set(&key, value)
        .map(|old| old)
        .map_err(|e| e.to_string())
}

/// 最小化主窗口（04 §2 顶栏「最小化」按钮，修复 REVIEW-002 R-06）。
///
/// 只暴露这一个无参数动作，不把任意窗口操作放给前端。
#[tauri::command]
pub fn minimize_window(window: tauri::WebviewWindow) -> Result<(), String> {
    window.minimize().map_err(|e| e.to_string())
}
