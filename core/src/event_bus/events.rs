//! 事件名常量：全项目唯一来源（禁止散落魔法字符串，02 §2.6）。
//! 值与 docs/agent-dev/03-数据契约与接口规范.md §3.3 一一对应。

pub const MODE_CHANGED: &str = "MODE_CHANGED";
pub const MODE_APPLY_PROGRESS: &str = "MODE_APPLY_PROGRESS";
pub const MODE_APPLY_FAILED: &str = "MODE_APPLY_FAILED";
pub const APP_REGISTERED: &str = "APP_REGISTERED";
pub const APP_OPENED: &str = "APP_OPENED";
pub const APP_CLOSED: &str = "APP_CLOSED";
pub const WINDOW_LAYOUT_APPLIED: &str = "WINDOW_LAYOUT_APPLIED";
pub const WINDOW_LAYOUT_FAILED: &str = "WINDOW_LAYOUT_FAILED";
pub const AI_REQUEST: &str = "AI_REQUEST";
pub const AI_STREAM_CHUNK: &str = "AI_STREAM_CHUNK";
pub const AI_RESPONSE: &str = "AI_RESPONSE";
pub const LEARNING_PROGRESS_UPDATED: &str = "LEARNING_PROGRESS_UPDATED";
pub const PROFILE_UPDATED: &str = "PROFILE_UPDATED";
pub const PLUGIN_LOADED: &str = "PLUGIN_LOADED";
pub const PLUGIN_ERROR: &str = "PLUGIN_ERROR";
pub const PLUGIN_PERMISSION_DENIED: &str = "PLUGIN_PERMISSION_DENIED";
pub const CONFIG_CHANGED: &str = "CONFIG_CHANGED";
pub const DEVICE_METRICS_UPDATED: &str = "DEVICE_METRICS_UPDATED";
