//! 桌面小组件独立窗口（阶段9，12 §B）。
//!
//! 窗口与进程控制归 Rust（ADR-001）。小组件是**独立 Tauri 窗口**
//! （label = `desktop-widget`），内容复用 UI 构建产物：加载
//! `index.html?pwWindow=desktop-widget`，前端按该查询参数挂载无侧栏的
//! 组件宿主（复用构建产物，不为小组件单开一个前端工程）。
//!
//! 持久化（契约 v11 配置键）：
//! - `widget.desktop.enabled`：是否开启（重启自动恢复）；
//! - `widget.desktop.config`：`{ x, y, w, h, alwaysOnTop }`。
//!
//! 边界回写策略：窗口**关闭时**落盘一次（CloseRequested），拖动/缩放过程
//! 不落盘 —— 否则每次鼠标移动都写 SQLite + 广播 CONFIG_CHANGED，得不偿失。
//! UI 可在小部件拖动结束显式调 `desktop_widget_save_bounds` 补存。

use serde_json::{json, Value};
use std::sync::Arc;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

use crate::state::AppState;

pub const WIDGET_LABEL: &str = "desktop-widget";
const ENABLED_KEY: &str = "widget.desktop.enabled";
const CONFIG_KEY: &str = "widget.desktop.config";

/// 默认几何：贴右侧摆放（主屏逻辑坐标粗估，用户可拖动后自动记忆）。
const DEFAULT: (i32, i32, f64, f64) = (900, 120, 360.0, 520.0);

pub fn is_enabled(state: &AppState) -> bool {
    state.config.get(ENABLED_KEY).as_bool().unwrap_or(false)
}

fn widget_config(state: &AppState) -> Value {
    // 契约：widget.desktop.config 是 string（JSON 字符串）。存取都走字符串，解析失败回空对象。
    let raw = state.config.get(CONFIG_KEY);
    let s = raw.as_str().unwrap_or("{}");
    serde_json::from_str::<Value>(s).unwrap_or_else(|_| json!({}))
}

fn set_widget_config(state: &AppState, cfg: &Value) -> anyhow::Result<()> {
    state.config.set(CONFIG_KEY, Value::from(cfg.to_string()))?;
    Ok(())
}

pub fn status(state: &AppState) -> Value {
    let open = state
        .app
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .as_ref()
        .and_then(|app| app.get_webview_window(WIDGET_LABEL))
        .is_some();
    let cfg = widget_config(state);
    json!({
        "enabled": is_enabled(state),
        "open": open,
        "bounds": {
            "x": cfg.get("x").and_then(Value::as_i64).unwrap_or(DEFAULT.0 as i64),
            "y": cfg.get("y").and_then(Value::as_i64).unwrap_or(DEFAULT.1 as i64),
            "w": cfg.get("w").and_then(Value::as_f64).unwrap_or(DEFAULT.2),
            "h": cfg.get("h").and_then(Value::as_f64).unwrap_or(DEFAULT.3),
        },
        "alwaysOnTop": cfg.get("alwaysOnTop").and_then(Value::as_bool).unwrap_or(false),
    })
}

/// 取 AppHandle；HTTP 面可能在 Tauri setup（WebView2 主窗口初始化，秒级）完成前
/// 被调用 —— 这里**等待注入**而不是立刻报错（10s 上限，超时才失败）。
fn wait_app_handle(state: &AppState, timeout: std::time::Duration) -> anyhow::Result<tauri::AppHandle> {
    let deadline = std::time::Instant::now() + timeout;
    loop {
        let handle = state
            .app
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .clone();
        if let Some(app) = handle {
            return Ok(app);
        }
        if std::time::Instant::now() >= deadline {
            anyhow::bail!("应用尚未就绪（AppHandle 未注入，等待 {timeout:?} 超时）");
        }
        std::thread::sleep(std::time::Duration::from_millis(100));
    }
}

/// 打开小组件窗口。已开着则幂等返回。
pub fn open(state: &Arc<AppState>) -> anyhow::Result<Value> {
    let app = wait_app_handle(state, std::time::Duration::from_secs(10))?;
    if app.get_webview_window(WIDGET_LABEL).is_some() {
        return Ok(json!({ "open": true, "alreadyOpen": true }));
    }

    let cfg = widget_config(state);
    let x = cfg.get("x").and_then(Value::as_f64).unwrap_or(DEFAULT.0 as f64);
    let y = cfg.get("y").and_then(Value::as_f64).unwrap_or(DEFAULT.1 as f64);
    let w = cfg.get("w").and_then(Value::as_f64).unwrap_or(DEFAULT.2);
    let h = cfg.get("h").and_then(Value::as_f64).unwrap_or(DEFAULT.3);
    let always_on_top = cfg.get("alwaysOnTop").and_then(Value::as_bool).unwrap_or(false);

    // 无边框小部件：拖动由前端 drag-region 承担（core:window:allow-start-dragging）。
    WebviewWindowBuilder::new(
        &app,
        WIDGET_LABEL,
        WebviewUrl::App("index.html?pwWindow=desktop-widget".into()),
    )
    .title("桌面小组件")
    .inner_size(w, h)
    .position(x, y)
    .resizable(true)
    .decorations(false)
    .always_on_top(always_on_top)
    .build()?;

    state.config.set(ENABLED_KEY, json!(true))?;
    Ok(json!({ "open": true, "label": WIDGET_LABEL }))
}

/// 关闭小组件窗口（幂等）。边界的最终落盘在 CloseRequested 事件里完成。
pub fn close(state: &Arc<AppState>) -> anyhow::Result<Value> {
    let app = wait_app_handle(state, std::time::Duration::from_secs(10))?;
    if let Some(window) = app.get_webview_window(WIDGET_LABEL) {
        persist_bounds(&window, state);
        window.close()?;
    }
    state.config.set(ENABLED_KEY, json!(false))?;
    Ok(json!({ "open": false }))
}

/// 显式保存边界（UI 拖动结束后调用；x/y 为逻辑坐标，w/h 为逻辑尺寸）。
pub fn save_bounds(state: &AppState, x: f64, y: f64, w: f64, h: f64) -> anyhow::Result<Value> {
    let mut cfg = widget_config(state);
    cfg["x"] = json!(x);
    cfg["y"] = json!(y);
    cfg["w"] = json!(w);
    cfg["h"] = json!(h);
    set_widget_config(state, &cfg)?;
    Ok(json!({ "saved": true }))
}

/// 更新 alwaysOnTop（即时作用于已开窗口）。
pub fn set_always_on_top(state: &AppState, on: bool) -> anyhow::Result<Value> {
    let mut cfg = widget_config(state);
    cfg["alwaysOnTop"] = json!(on);
    set_widget_config(state, &cfg)?;
    if let Some(window) = state
        .app
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .as_ref()
        .and_then(|app| app.get_webview_window(WIDGET_LABEL))
    {
        window.set_always_on_top(on)?;
    }
    Ok(json!({ "alwaysOnTop": on }))
}

/// 几何读取 + 落盘的公共实现（Window 与 WebviewWindow 都有这三个读取方法）。
struct Geometry {
    x: i32,
    y: i32,
    w: u32,
    h: u32,
    scale: f64,
}

trait HasGeometry {
    fn geometry(&self) -> Geometry;
}

impl HasGeometry for tauri::Window {
    fn geometry(&self) -> Geometry {
        let pos = self.outer_position().unwrap_or_default();
        let size = self.inner_size().unwrap_or_default();
        Geometry {
            x: pos.x,
            y: pos.y,
            w: size.width,
            h: size.height,
            scale: self.scale_factor().unwrap_or(1.0),
        }
    }
}

impl HasGeometry for tauri::WebviewWindow {
    fn geometry(&self) -> Geometry {
        let pos = self.outer_position().unwrap_or_default();
        let size = self.inner_size().unwrap_or_default();
        Geometry {
            x: pos.x,
            y: pos.y,
            w: size.width,
            h: size.height,
            scale: self.scale_factor().unwrap_or(1.0),
        }
    }
}

/// 从窗口实例读当前几何并写入 config（关闭/显式保存共用）。
fn persist_bounds<W: HasGeometry>(window: &W, state: &AppState) {
    let g = window.geometry();
    let mut cfg = widget_config(state);
    // 物理像素 → 与 save_bounds 统一存逻辑近似值（除以当前缩放因子）。
    let scale = g.scale.max(0.01);
    cfg["x"] = json!((g.x as f64 / scale) as i64);
    cfg["y"] = json!((g.y as f64 / scale) as i64);
    cfg["w"] = json!(g.w as f64 / scale);
    cfg["h"] = json!(g.h as f64 / scale);
    let _ = set_widget_config(state, &cfg);
}

/// 关闭前的最后落盘钩子（main.rs 的 on_window_event 里对小组件窗口调用）。
/// Builder::on_window_event 给的是 `&Window`；close() 路径给 WebviewWindow —— 两者都实现了 HasGeometry。
pub fn on_close_requested(window: &tauri::Window, state: &AppState) {
    persist_bounds(window, state);
}

/// 启动时按 `widget.desktop.enabled` 自动恢复（setup 里调用；失败不阻塞启动）。
pub fn auto_open_if_enabled(state: &Arc<AppState>) {
    if is_enabled(state) {
        if let Err(e) = open(state) {
            tracing::warn!(error = %e, "小组件自动恢复失败（不阻塞启动）");
        }
    }
}
