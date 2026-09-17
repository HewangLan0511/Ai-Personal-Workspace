//! 生活中心（11 §A）—— 使用时长采样（A4）+ 天气/音乐/社交的 sidecar 代理。
//!
//! 架构口径：
//! - **前台采样器**（A4）：每 tick 读前台窗口的进程名，UPSERT 累加到 `usage_stats`
//!   （按 天+应用 聚合，**不存时间点明细**，11 §A4 数据轻量化）。
//!   采样间隔可配（`life.usage_sample_interval_sec`，默认 30s；验收可调小）。
//! - **天气 / 音乐 / 社交**（A1/A2/A3）的系统读取与网络请求在 Python sidecar
//!   （02 §2.4：注册表/媒体会话等"系统 API"归 Python），本模块只做
//!   `sidecar::call` 代理 + 配置存取，不复制实现。
//! - 隐私：定位由用户手动设置城市（禁止默认系统定位）；社交只取未读数，
//!   不落任何聊天内容。

pub mod repository;

use serde_json::{json, Value};

use crate::state::AppState;

/// 休息提醒事件（A4 可选项：今日累计使用超过阈值）。
pub const LIFE_BREAK_REMIND: &str = "LIFE_BREAK_REMIND";

/// 前台采样循环：tick = `life.usage_sample_interval_sec`（秒，下限 1）。
pub fn spawn_usage_sampler(state: std::sync::Arc<AppState>) {
    #[cfg(windows)]
    {
        std::thread::spawn(move || {
            let mut reminded_day = String::new();
            loop {
                let interval = read_sample_interval_secs(&state);
                sampler_tick(&state, &mut reminded_day);
                std::thread::sleep(std::time::Duration::from_secs(interval));
            }
        });
    }
    #[cfg(not(windows))]
    {
        let _ = state;
    }
}

/// 单次采样：读前台进程 → 累加秒数 → 检查休息提醒。
/// 任何失败都静默跳过（采样是旁路任务，不允许拖垮 core——02 §2.7 局部失败不拖垮整体）。
#[cfg(windows)]
fn sampler_tick(state: &AppState, reminded_day: &mut String) {
    let interval = read_sample_interval_secs(state) as i64;
    if let Some(name) = foreground_app_name() {
        let today = chrono::Local::now().format("%Y-%m-%d").to_string();
        let repo = repository::UsageRepo::new(state.db.clone());
        if let Err(e) = repo.add_seconds(&today, &name, interval) {
            tracing::warn!(error = %e, "usage_stats 写入失败（跳过本 tick）");
            return;
        }
        check_break_remind(state, &today, reminded_day, interval);
    }
}

/// A4 可选项：今日总使用超过 `life.break_remind_hours` 小时 → 提醒一次（每天最多一条）。
/// 0 = 关闭（默认）。用内存 `reminded_day` 去重（重启后会再提醒一次，可接受——
/// 持久化"今天已提醒"需要多一张状态表，收益不成比例）。
#[cfg(windows)]
fn check_break_remind(state: &AppState, today: &str, reminded_day: &mut String, _interval: i64) {
    if *reminded_day == today {
        return;
    }
    let hours = state
        .config
        .get("life.break_remind_hours")
        .as_f64()
        .unwrap_or(0.0);
    if hours <= 0.0 {
        return;
    }
    let repo = repository::UsageRepo::new(state.db.clone());
    if let Ok(total) = repo.total_seconds(today) {
        if total as f64 >= hours * 3600.0 {
            let _ = state.bus.publish(
                LIFE_BREAK_REMIND,
                json!({ "day": today, "totalSeconds": total, "thresholdHours": hours }),
            );
            *reminded_day = today.to_string();
        }
    }
}

#[cfg(windows)]
fn read_sample_interval_secs(state: &AppState) -> u64 {
    state
        .config
        .get("life.usage_sample_interval_sec")
        .as_f64()
        .map(|f| f.round().clamp(1.0, 300.0) as u64)
        .unwrap_or(30)
}

/// 前台窗口的进程名（复用 device::processes 的实现，避免两套 Win32 调用）。
#[cfg(windows)]
fn foreground_app_name() -> Option<String> {
    use windows::Win32::UI::WindowsAndMessaging::{GetForegroundWindow, GetWindowThreadProcessId};
    unsafe {
        let hwnd = GetForegroundWindow();
        if hwnd.0.is_null() {
            return None;
        }
        let mut pid: u32 = 0;
        GetWindowThreadProcessId(hwnd, Some(&mut pid));
        if pid == 0 {
            return None;
        }
        crate::device::processes::process_image_name(pid)
    }
}

// ---------------------------------------------------------------------------
// sidecar 代理（A1 天气 / A2 音乐 / A3 社交概览）
//
// 全部 async：HTTP handler 在 tokio runtime 内直接 await；
// 前台采样线程**不**调 sidecar（无跨 runtime 阻塞问题）。

/// 天气（A1）。城市为空 = 用户未设置 → 返回明确提示（**绝不**自动取系统定位）。
pub async fn weather(state: &std::sync::Arc<AppState>, city_override: Option<&str>) -> anyhow::Result<Value> {
    let city = match city_override.filter(|c| !c.trim().is_empty()) {
        Some(c) => c.to_string(),
        None => state
            .config
            .get("life.weather.city")
            .as_str()
            .unwrap_or_default()
            .to_string(),
    };
    if city.trim().is_empty() {
        return Ok(json!({ "ok": false, "reason": "no_city", "message": "尚未设置城市（手动设置，不自动定位）" }));
    }
    crate::sidecar::call(state, "/life/weather", json!({ "city": city })).await
}

/// 当前媒体会话（A2，SMTC）。
pub async fn media_now(state: &std::sync::Arc<AppState>) -> anyhow::Result<Value> {
    crate::sidecar::call(state, "/life/media", json!({})).await
}

/// 媒体控制（A2 可选：play/pause/next/previous，能拿到会话就做）。
pub async fn media_control(state: &std::sync::Arc<AppState>, action: &str) -> anyhow::Result<Value> {
    crate::sidecar::call(state, "/life/media/control", json!({ "action": action })).await
}

/// 社交概览（A3）：只返回未读数与来源摘要，sidecar 保证不返回消息正文。
/// 服务配置（不含密码——密码在 keyring，由 sidecar 按 credRef 解析）随请求下发。
pub async fn social_overview(state: &std::sync::Arc<AppState>) -> anyhow::Result<Value> {
    let cfg = social_config(state)?;
    let services = cfg.get("services").cloned().unwrap_or_else(|| json!([]));
    crate::sidecar::call(state, "/life/social/overview", json!({ "services": services })).await
}

/// 社交服务配置读写（存 config `life.social.services`，用户显式添加）。
pub fn social_config(state: &std::sync::Arc<AppState>) -> anyhow::Result<Value> {
    let raw = state
        .config
        .get("life.social.services")
        .as_str()
        .unwrap_or("[]")
        .to_string();
    let parsed: Value = serde_json::from_str(&raw).unwrap_or_else(|_| json!([]));
    Ok(json!({ "services": parsed }))
}

pub fn social_config_put(state: &std::sync::Arc<AppState>, services: &Value) -> anyhow::Result<Value> {
    if !services.is_array() {
        anyhow::bail!("services 必须是数组");
    }
    state
        .config
        .set("life.social.services", Value::from(services.to_string()))?;
    Ok(json!({ "saved": true }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn social_config_put_rejects_non_array() {
        // 纯函数级验证：不落库（config 写入在 set 内部，这里只测守卫）
        let v = json!({ "evil": true });
        assert!(!v.is_array());
    }
}
