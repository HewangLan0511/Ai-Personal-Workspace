//! 应用布局的**编排层**：找窗口 → 算像素 → 定位 → 激活。
//!
//! 工程要求（07 §工程要求）在这里落地：
//! - 单窗口失败**不阻塞**其余窗口（发 `WINDOW_LAYOUT_FAILED` 后继续）；
//! - 定位失败自动重试 2 次、间隔 500ms（窗口可能还没初始化完）；
//! - 连续移动多个窗口，每次间隔 80ms（避免被系统丢弃）；
//! - 未启动的软件 → 该槽位**跳过**（07 验收项 9）。

use std::time::Duration;

use crate::event_bus::{WINDOW_LAYOUT_APPLIED, WINDOW_LAYOUT_FAILED};
use crate::state::AppState;

use super::layout::{layout_pixels, AiSidebar, PxRect, Rect, WorkArea};
use super::monitor::work_area_of;
use super::window;

/// 布局文件（契约 3.2.2）。
#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct Layout {
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub monitor: usize,
    pub slots: Vec<Slot>,
    #[serde(default, rename = "aiSidebar")]
    pub ai_sidebar: Option<AiSidebar>,
}

#[derive(Debug, Clone, serde::Deserialize, serde::Serialize)]
pub struct Slot {
    /// 软件名 —— 在 `apps` 表里按名匹配后取运行中的 pid
    pub app: String,
    pub rect: Rect,
    #[serde(default = "default_z")]
    pub z: i32,
    #[serde(default, rename = "alwaysOnTop")]
    pub always_on_top: bool,
    #[serde(default)]
    pub maximized: bool,
}

fn default_z() -> i32 {
    1
}

/// 单个槽位的执行结果。
#[derive(Debug, Clone, serde::Serialize)]
pub struct SlotOutcome {
    pub app: String,
    /// `placed` | `skipped_not_running` | `skipped_no_window` | `failed`
    pub status: String,
    pub hwnd: Option<isize>,
    pub rect: Option<PxRect>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ApplyOutcome {
    pub layout: String,
    pub monitor: usize,
    /// 目标显示器不存在 → 降级到主显示器（07 §4）
    pub degraded_monitor: bool,
    pub work: WorkArea,
    pub placed: usize,
    pub skipped: usize,
    pub failed: usize,
    pub slots: Vec<SlotOutcome>,
    pub took_ms: u128,
}

const STEP_DELAY: Duration = Duration::from_millis(80); // 07 §分步延时 50~100ms
const RETRY: usize = 2; // 07 §自动重试
const RETRY_DELAY: Duration = Duration::from_millis(500);

/// 应用一个布局。**同步阻塞**执行（含必要的延时），故调用方应放在阻塞线程里。
pub fn apply_layout(state: &AppState, layout: &Layout) -> anyhow::Result<ApplyOutcome> {
    let started = std::time::Instant::now();

    let (work, degraded) = work_area_of(layout.monitor)
        .ok_or_else(|| anyhow::anyhow!("未找到任何显示器（EnumDisplayMonitors 返回空）"))?;
    if degraded {
        tracing::warn!(
            requested = layout.monitor,
            "目标显示器不存在，已降级到主显示器"
        );
    }

    let rects = layout_pixels(
        &layout.slots.iter().map(|s| s.rect).collect::<Vec<_>>(),
        work,
        layout.ai_sidebar.as_ref(),
    );

    // ---- 1. 解析槽位 → 目标窗口 ----
    let mut outcomes: Vec<SlotOutcome> = Vec::new();
    // (z, hwnd, rect, slot)
    let mut planned: Vec<(i32, isize, PxRect, &Slot)> = Vec::new();

    for (i, slot) in layout.slots.iter().enumerate() {
        match resolve_pid(state, &slot.app) {
            None => outcomes.push(SlotOutcome {
                app: slot.app.clone(),
                status: "skipped_not_running".into(),
                hwnd: None,
                rect: None,
                reason: Some("软件未在运行（槽位跳过，不影响其余窗口）".into()),
            }),
            Some(pid) => match window::find_main_window(pid) {
                Some(info) => planned.push((slot.z, info.hwnd, rects[i], slot)),
                None => outcomes.push(SlotOutcome {
                    app: slot.app.clone(),
                    status: "skipped_no_window".into(),
                    hwnd: None,
                    rect: None,
                    reason: Some(format!("pid {pid} 在运行，但找不到可见的顶层窗口")),
                }),
            },
        }
    }

    // ---- 2. 定位（按 z 升序：先摆靠后的，最后摆要靠前的）----
    planned.sort_by_key(|(z, _, _, _)| *z);
    for (_, hwnd, rect, slot) in &planned {
        let mut last_err: Option<String> = None;
        let mut ok = false;
        for _ in 0..=RETRY {
            match window::place(*hwnd, *rect, slot.always_on_top, slot.maximized) {
                Ok(()) => {
                    ok = true;
                    break;
                }
                Err(e) => {
                    last_err = Some(e.to_string());
                    std::thread::sleep(RETRY_DELAY); // 窗口可能还没初始化完
                }
            }
        }
        if ok {
            outcomes.push(SlotOutcome {
                app: slot.app.clone(),
                status: "placed".into(),
                hwnd: Some(*hwnd),
                rect: Some(*rect),
                reason: None,
            });
        } else {
            let reason = last_err.unwrap_or_else(|| "未知失败".into());
            // 07 §工程要求：单窗口失败不阻塞 —— 发事件后继续
            let _ = state.bus.publish(
                WINDOW_LAYOUT_FAILED,
                serde_json::json!({
                    "layout": layout.name, "app": slot.app,
                    "stage": "place", "reason": reason, "recoverable": true
                }),
            );
            outcomes.push(SlotOutcome {
                app: slot.app.clone(),
                status: "failed".into(),
                hwnd: Some(*hwnd),
                rect: Some(*rect),
                reason: Some(reason),
            });
        }
        std::thread::sleep(STEP_DELAY);
    }

    // ---- 3. 激活 ----
    // 顺序：**按 z 升序**（先激活靠后的，最后激活靠前的）。
    // 契约 3.2.2 规定「z 越小越靠后」⇒ z 最大的应当**最后**激活，才会落在最上层。
    // （07 §3 原文对顺序存疑并注明"需实测确定"，实测结论见 window_manager/README。）
    for (_, hwnd, _, _) in &planned {
        if let Err(e) = window::activate(*hwnd) {
            let _ = state.bus.publish(
                WINDOW_LAYOUT_FAILED,
                serde_json::json!({
                    "layout": layout.name, "hwnd": hwnd,
                    "stage": "activate", "reason": e.to_string(), "recoverable": true
                }),
            );
        }
        std::thread::sleep(STEP_DELAY);
    }

    let placed = outcomes.iter().filter(|o| o.status == "placed").count();
    let skipped = outcomes.iter().filter(|o| o.status.starts_with("skipped")).count();
    let failed = outcomes.iter().filter(|o| o.status == "failed").count();
    let took_ms = started.elapsed().as_millis();

    // 契约 3.3：WINDOW_LAYOUT_APPLIED
    let _ = state.bus.publish(
        WINDOW_LAYOUT_APPLIED,
        serde_json::json!({
            "layout": layout.name, "monitor": layout.monitor,
            "placed": placed, "skipped": skipped, "failed": failed
        }),
    );

    Ok(ApplyOutcome {
        layout: layout.name.clone(),
        monitor: layout.monitor,
        degraded_monitor: degraded,
        work,
        placed,
        skipped,
        failed,
        slots: outcomes,
        took_ms,
    })
}

/// 软件名 → 运行中的 pid。
///
/// 先按名在 `apps` 表里找注册记录，再查它是否在 `running` 里（阶段2 的启动登记）。
/// 找不到运行时返回 `None`，由调用方按"槽位跳过"处理（07 验收项 9）。
fn resolve_pid(state: &AppState, app_name: &str) -> Option<u32> {
    let rows = state.apps.list(None, None).ok()?;
    let app = rows
        .iter()
        .find(|a| a.name.eq_ignore_ascii_case(app_name.trim()))?;
    state.running.get(app.id)
}
