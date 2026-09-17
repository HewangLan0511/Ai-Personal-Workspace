//! 显示器枚举与 DPI 感知（07 §4 多屏 + 验收项 7/8）。
//!
//! **DPI 感知必须最先声明**（07 §禁止事项）：进程启动时调用
//! `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)`，此后 Win32 返回的
//! 窗口/工作区坐标都是**物理像素**。若不声明，系统按 96 DPI 虚拟化坐标，
//! 125%/150% 缩放下的布局比例会整体偏小（验收项 8 会失败）。

use windows::Win32::Foundation::{BOOL, LPARAM, RECT, TRUE};
use windows::Win32::Graphics::Gdi::{
    EnumDisplayMonitors, GetMonitorInfoW, HDC, HMONITOR, MONITORINFO,
};
// MONITORINFOF_PRIMARY 在 WindowsAndMessaging，不在 Graphics::Gdi
use windows::Win32::UI::HiDpi::{
    SetProcessDpiAwarenessContext, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
};
use windows::Win32::UI::WindowsAndMessaging::MONITORINFOF_PRIMARY;

use super::layout::WorkArea;

/// 一块显示器的信息（`index` 即布局文件里的 `monitor` 字段）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct MonitorInfo {
    pub index: usize,
    pub x: i32,
    pub y: i32,
    /// 完整区域宽（含任务栏所占）
    pub w: i32,
    pub h: i32,
    /// 工作区（不含任务栏）—— 布局换算用的就是它
    pub work_x: i32,
    pub work_y: i32,
    pub work_w: i32,
    pub work_h: i32,
    pub primary: bool,
}

/// 声明 per-monitor DPI 感知。**应在创建任何窗口之前调用一次**。
///
/// 返回 `false` 表示声明失败（例如已被 manifest 声明过）——
/// 不算致命：若进程已具 DPI 感知，坐标依然正确。
pub fn enable_dpi_awareness() -> bool {
    unsafe { SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2).is_ok() }
}

extern "system" fn enum_monitor_cb(
    hmon: HMONITOR,
    _hdc: HDC,
    _rect: *mut RECT,
    lparam: LPARAM,
) -> BOOL {
    let out = unsafe { &mut *(lparam.0 as *mut Vec<HMONITOR>) };
    out.push(hmon);
    TRUE
}

/// 枚举全部显示器，按系统返回顺序编号（第 0 个即主显示器）。
pub fn list_monitors() -> Vec<MonitorInfo> {
    let mut handles: Vec<HMONITOR> = Vec::new();
    unsafe {
        let _ = EnumDisplayMonitors(
            None,
            None,
            Some(enum_monitor_cb),
            LPARAM(&mut handles as *mut _ as isize),
        );
    }

    handles
        .iter()
        .enumerate()
        .filter_map(|(index, &hmon)| {
            let mut mi = MONITORINFO {
                cbSize: std::mem::size_of::<MONITORINFO>() as u32,
                ..Default::default()
            };
            let got = unsafe { GetMonitorInfoW(hmon, &mut mi) };
            if !got.as_bool() {
                return None;
            }
            Some(MonitorInfo {
                index,
                x: mi.rcMonitor.left,
                y: mi.rcMonitor.top,
                w: mi.rcMonitor.right - mi.rcMonitor.left,
                h: mi.rcMonitor.bottom - mi.rcMonitor.top,
                work_x: mi.rcWork.left,
                work_y: mi.rcWork.top,
                work_w: mi.rcWork.right - mi.rcWork.left,
                work_h: mi.rcWork.bottom - mi.rcWork.top,
                primary: (mi.dwFlags & MONITORINFOF_PRIMARY) != 0,
            })
        })
        .collect()
}

/// 取第 `index` 块显示器的工作区。
///
/// 07 §4：**显示器不存在时降级到主显示器**（这里取第一块），由调用方记录警告。
/// 返回 `(工作区, 是否发生了降级)`。
pub fn work_area_of(index: usize) -> Option<(WorkArea, bool)> {
    let monitors = list_monitors();
    if monitors.is_empty() {
        return None;
    }
    let chosen = monitors.get(index);
    let degraded = chosen.is_none();
    // 降级：主显示器优先，其次第一块
    let m = chosen
        .or_else(|| monitors.iter().find(|m| m.primary))
        .or_else(|| monitors.first())?;

    Some((
        WorkArea { x: m.work_x, y: m.work_y, w: m.work_w, h: m.work_h },
        degraded,
    ))
}
