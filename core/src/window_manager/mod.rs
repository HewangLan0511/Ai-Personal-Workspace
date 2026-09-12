//! 窗口管理（阶段3 交付范围）。
//!
//! ADR-001：窗口控制 = Rust（windows crate）。
//! 实现要点已固化在指令 07（本文件不重复，只列硬约束）：
//! - 布局用 0~1 归一化坐标，core 换算像素（契约 3.2.2）
//! - per-monitor DPI aware（否则高分屏坐标全错）
//! - 最大化窗口先 SW_RESTORE 再 SetWindowPos
//! - 单窗口失败不阻塞（发 WINDOW_LAYOUT_FAILED 后继续）
//! - 归一化→像素换算必须是纯函数（可单测）

/// 布局槽位（契约 3.2.2 slots 元素）。
#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct Slot {
    pub app: String,
    pub rect: Rect,
    #[serde(default = "default_z")]
    pub z: i32,
    #[serde(default)]
    pub always_on_top: bool,
    #[serde(default)]
    pub maximized: bool,
}

fn default_z() -> i32 {
    1
}

#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

/// 归一化坐标 → 像素坐标（纯函数，阶段3 将配完整单测）。
/// 输入为工作区像素尺寸与归一化 rect；AI 侧栏启用时先扣除侧栏宽度。
pub fn to_pixels(
    rect: &Rect,
    work_area: (i32, i32, i32, i32), // x, y, w, h（不含任务栏）
    sidebar_width: f64,              // 0.0~1.0，0 表示无侧栏
) -> (i32, i32, i32, i32) {
    let (wx, wy, ww, wh) = work_area;
    let available_w = (ww as f64 * (1.0 - sidebar_width)).round() as i32;
    let px = wx + (rect.x * available_w as f64).round() as i32;
    let py = wy + (rect.y * wh as f64).round() as i32;
    let pw = (rect.w * available_w as f64).round() as i32;
    let ph = (rect.h * wh as f64).round() as i32;
    (px, py, pw, ph)
}

/// 按 pid 查找主窗口（阶段3 实现：EnumWindows + 过滤不可见/工具窗口/零尺寸）。
pub fn find_main_window(_pid: u32) -> anyhow::Result<*mut core::ffi::c_void> {
    anyhow::bail!("阶段3 实现：EnumWindows 查找主窗口（指令 07）")
}

/// 定位窗口（阶段3 实现：先取消最大化，再 SetWindowPos）。
pub fn set_window_pos(
    _hwnd: *mut core::ffi::c_void,
    _rect: (i32, i32, i32, i32),
) -> anyhow::Result<()> {
    anyhow::bail!("阶段3 实现：SetWindowPos（指令 07）")
}
