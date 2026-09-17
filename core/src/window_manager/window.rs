//! 窗口查找 / 定位 / 激活（ADR-001：窗口控制 = Rust，`windows` crate）。
//!
//! 三个能力与 07 §1/§2/§3 一一对应。**所有 `hwnd` 对外都用 `isize`**，
//! 以免把 `*mut c_void` 泄漏到序列化层（JSON 里放指针类型既无意义也不安全）。
//!
//! ## 两个必须踩对的点
//! 1. **定位前先取消最大化**（07 §2）：`IsZoomed` 为真时直接 `SetWindowPos` 是**无效**的；
//! 2. **激活要绕过前台锁定**（07 §3）：Windows 不让后台进程随便抢前台，
//!    必须先 `AttachThreadInput` 把本线程与目标窗口线程的输入队列接上。

use windows::Win32::Foundation::{BOOL, HWND, LPARAM, RECT, TRUE};
// AttachThreadInput 在 System::Threading（不是 UI::Input::KeyboardAndMouse）
use windows::Win32::System::Threading::{AttachThreadInput, GetCurrentThreadId};
use windows::Win32::UI::WindowsAndMessaging::{
    BringWindowToTop, EnumWindows, GetClassNameW, GetForegroundWindow, GetWindowLongPtrW,
    GetWindowRect, GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId, IsIconic,
    IsWindowVisible, IsZoomed, SetForegroundWindow, SetWindowPos, ShowWindow, GWL_EXSTYLE,
    SW_MAXIMIZE, SW_MINIMIZE, SW_RESTORE, SWP_NOACTIVATE, SWP_NOZORDER, SWP_SHOWWINDOW,
    WS_EX_TOOLWINDOW,
};

use super::layout::PxRect;

/// 窗口信息（07 §1 的输出契约）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct WindowInfo {
    pub hwnd: isize,
    pub title: String,
    pub class_name: String,
    pub pid: u32,
    pub visible: bool,
    pub minimized: bool,
    pub maximized: bool,
    pub rect: Option<PxRect>,
    /// 面积（用于"取最大可见窗口作为主窗口"）
    pub area: i64,
}

fn hwnd_of(raw: isize) -> HWND {
    HWND(raw as *mut core::ffi::c_void)
}

fn is_tool_window(hwnd: HWND) -> bool {
    // WS_EX_TOOLWINDOW：托盘图标、工具提示这类不该被当成"主窗口"（07 §1）
    let ex = unsafe { GetWindowLongPtrW(hwnd, GWL_EXSTYLE) };
    (ex as u32 & WS_EX_TOOLWINDOW.0) != 0
}

fn text_of(hwnd: HWND) -> String {
    let len = unsafe { GetWindowTextLengthW(hwnd) };
    if len <= 0 {
        return String::new();
    }
    let mut buf = vec![0u16; (len + 1) as usize];
    let n = unsafe { GetWindowTextW(hwnd, &mut buf) };
    String::from_utf16_lossy(&buf[..n.max(0) as usize])
}

fn class_of(hwnd: HWND) -> String {
    let mut buf = [0u16; 256];
    let n = unsafe { GetClassNameW(hwnd, &mut buf) };
    String::from_utf16_lossy(&buf[..n.max(0) as usize])
}

fn rect_of(hwnd: HWND) -> Option<PxRect> {
    let mut r = RECT::default();
    if unsafe { GetWindowRect(hwnd, &mut r) }.is_err() {
        return None;
    }
    Some(PxRect { x: r.left, y: r.top, w: r.right - r.left, h: r.bottom - r.top })
}

fn describe(hwnd: HWND) -> WindowInfo {
    let mut pid = 0u32;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)) };
    let rect = rect_of(hwnd);
    let area = rect.map(|r| r.w as i64 * r.h as i64).unwrap_or(0);
    WindowInfo {
        hwnd: hwnd.0 as isize,
        title: text_of(hwnd),
        class_name: class_of(hwnd),
        pid,
        visible: unsafe { IsWindowVisible(hwnd) }.as_bool(),
        minimized: unsafe { IsIconic(hwnd) }.as_bool(),
        maximized: unsafe { IsZoomed(hwnd) }.as_bool(),
        rect,
        area,
    }
}

extern "system" fn enum_window_cb(hwnd: HWND, lparam: LPARAM) -> BOOL {
    let out = unsafe { &mut *(lparam.0 as *mut Vec<HWND>) };
    out.push(hwnd);
    TRUE
}

/// 是否算"可管理的顶层窗口"（07 §1 的过滤规则）。
fn is_candidate(hwnd: HWND) -> bool {
    if !unsafe { IsWindowVisible(hwnd) }.as_bool() {
        return false;
    }
    if is_tool_window(hwnd) {
        return false;
    }
    // 0 尺寸（或负）一律过滤 —— splash / 隐藏容器常见形态
    match rect_of(hwnd) {
        Some(r) if r.w > 0 && r.h > 0 => {}
        _ => return false,
    }
    // 无标题的多半是隐藏消息窗口
    !text_of(hwnd).trim().is_empty()
}

/// 枚举所有候选顶层窗口。
pub fn list_windows() -> Vec<WindowInfo> {
    let mut handles: Vec<HWND> = Vec::new();
    unsafe {
        let _ = EnumWindows(Some(enum_window_cb), LPARAM(&mut handles as *mut _ as isize));
    }
    handles
        .into_iter()
        .filter(|h| is_candidate(*h))
        .map(describe)
        .collect()
}

/// 按 pid 查找主窗口：取**面积最大**的可见窗口（07 §1）。
///
/// 无窗口时返回 `Ok(None)` —— 07 验收项 1 明确要求"无窗口时返回 null 不报错"。
pub fn find_main_window(pid: u32) -> Option<WindowInfo> {
    list_windows()
        .into_iter()
        .filter(|w| w.pid == pid)
        .max_by_key(|w| w.area)
}

/// 按标题关键词查找（大小写不敏感）。
pub fn find_by_title(keyword: &str) -> Vec<WindowInfo> {
    let kw = keyword.to_lowercase();
    list_windows()
        .into_iter()
        .filter(|w| w.title.to_lowercase().contains(&kw))
        .collect()
}

/// 取窗口当前像素矩形（验收复核用：定位后要比对实际位置）。
pub fn get_rect(hwnd: isize) -> Option<PxRect> {
    rect_of(hwnd_of(hwnd))
}

/// 定位窗口到指定像素矩形（07 §2）。
///
/// `maximized=true` 时先摆好位置再最大化（顺序反了会被最大化覆盖）。
pub fn place(
    hwnd: isize,
    r: PxRect,
    always_on_top: bool,
    maximized: bool,
) -> anyhow::Result<()> {
    let h = hwnd_of(hwnd);
    if h.0.is_null() {
        anyhow::bail!("无效的窗口句柄");
    }

    // ★ 关键：最大化/最小化的窗口必须先还原，否则 SetWindowPos 不生效（07 §2）
    if unsafe { IsIconic(h) }.as_bool() || unsafe { IsZoomed(h) }.as_bool() {
        unsafe { let _ = ShowWindow(h, SW_RESTORE); };
    }

    // SWP_NOZORDER：不动 z 序（z 序由 activate 阶段按布局的 z 值统一处理）
    // SWP_NOACTIVATE：定位不等于激活，避免每摆一个窗口就抢一次前台
    let mut flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW;
    if always_on_top {
        flags |= SWP_NOZORDER; // 置顶交给 activate 的 BringWindowToTop
    }

    unsafe { SetWindowPos(h, None, r.x, r.y, r.w, r.h, flags) }
        .map_err(|e| anyhow::anyhow!("SetWindowPos 失败：{e}"))?;

    if maximized {
        unsafe { let _ = ShowWindow(h, SW_MAXIMIZE); };
    }
    Ok(())
}

/// 激活窗口并置前（07 §3：处理前台锁定）。
///
/// 先 `AttachThreadInput` 把本线程与目标线程的输入队列**临时接上**，
/// 此时本线程对目标窗口调用 `SetForegroundWindow` 才会被系统接受。
pub fn activate(hwnd: isize) -> anyhow::Result<()> {
    let h = hwnd_of(hwnd);
    if h.0.is_null() {
        anyhow::bail!("无效的窗口句柄");
    }
    if unsafe { IsIconic(h) }.as_bool() {
        unsafe { let _ = ShowWindow(h, SW_RESTORE); };
    }

    unsafe {
        let target_thread = GetWindowThreadProcessId(h, None);
        let current_thread = GetCurrentThreadId();
        let attached = if target_thread != 0 && target_thread != current_thread {
            AttachThreadInput(current_thread, target_thread, true).as_bool()
        } else {
            false
        };

        let _ = BringWindowToTop(h);
        let _ = SetForegroundWindow(h);

        if attached {
            let _ = AttachThreadInput(current_thread, target_thread, false);
        }
    }
    Ok(())
}

/// 窗口是否已在前台（验收项 5 的判据）。
pub fn is_foreground(hwnd: isize) -> bool {
    unsafe { GetForegroundWindow().0 as isize == hwnd }
}

/// UTF-16 + NUL 结尾（Win32 W 系列 API 需要）。
#[cfg(windows)]
fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

/// 用系统默认程序打开文件 / 目录（06 §2 步骤⑤「打开文件入口」）。
///
/// 为什么放在窗口模块：它属"系统集成 + 拉起外部程序"，按 ADR-001 归 Rust。
/// **不用 `std::process::Command` 拼 `cmd /c start` 或 `explorer`** —— 那是 shell 拼串，
/// 路径里的特殊字符会变成注入面；`ShellExecuteW` 把路径当**参数**交给系统外壳，不参与命令解析。
pub fn open_path(path: &str) -> anyhow::Result<()> {
    if path.trim().is_empty() {
        anyhow::bail!("路径为空");
    }
    if !std::path::Path::new(path).exists() {
        anyhow::bail!("路径不存在：{path}");
    }
    use windows::core::{w, PCWSTR};
    use windows::Win32::UI::Shell::ShellExecuteW;
    use windows::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let p = to_wide(path);
    let ret = unsafe {
        ShellExecuteW(
            None,
            w!("open"),
            PCWSTR(p.as_ptr()),
            PCWSTR::null(),
            PCWSTR::null(),
            SW_SHOWNORMAL,
        )
    };
    // ShellExecuteW 返回值 <= 32 表示失败（Win32 老约定）
    let code = ret.0 as usize;
    if code <= 32 {
        anyhow::bail!("系统无法打开：{path}（ShellExecute 代码 {code}）");
    }
    Ok(())
}

/// 最小化（供"收起"用，非布局路径；阶段4 工作模式引擎可能用到）。
#[allow(dead_code)]
pub fn minimize(hwnd: isize) -> anyhow::Result<()> {
    let h = hwnd_of(hwnd);
    if h.0.is_null() {
        anyhow::bail!("无效的窗口句柄");
    }
    unsafe { let _ = ShowWindow(h, SW_MINIMIZE); };
    Ok(())
}
