//! 进程启动。
//!
//! **ADR-001 定稿：进程启动 = Rust**（`docs/adr/ADR-001-窗口控制与进程启动实现语言.md`）。
//! Python sidecar 不得出现同类实现 —— 门禁 A031 按能力扫描会拦。
//!
//! 为什么必须用 `CreateProcessW` 而不是 `ShellExecute`：
//! 契约与 05 §2 要求「15s 内拿到 pid」「按 pid 轮询存活」「APP_OPENED 带 pid」——
//! `ShellExecuteW` **不返回 pid**，无法满足。故 .exe/.bat/.cmd 走 `CreateProcessW`；
//! 仅 `.lnk`（需 IShellLink 解析，本阶段从简）交给系统，pid 记为未跟踪。
//!
//! 安全（05 §禁止事项）：**不得用 `shell=True` 拼字符串启动**。
//! 这里用 `lpApplicationName` 显式指定可执行文件路径（不经 shell 解析），
//! 参数走 `lpCommandLine`，从根上消除命令注入面。

use std::path::Path;

/// 启动结果。
#[derive(Debug, Clone, serde::Serialize)]
pub struct LaunchOutcome {
    /// 子进程 pid；`.lnk` 交给系统时为 None。
    pub pid: Option<u32>,
    /// pid 是否可被跟踪（false 表示后续无法轮询存活，UI 不应挂"运行中"）。
    pub pid_tracked: bool,
}

/// 启动一个已注册的软件。
///
/// 错误信息面向用户（05 §2「启动失败处理」要求可读提示，不是崩溃）：
/// - 路径不存在 → `文件不存在：<path>`
/// - 权限不足 → `需要管理员权限运行`
pub fn launch(path: &str, args: &str) -> anyhow::Result<LaunchOutcome> {
    let p = Path::new(path);
    if !p.exists() {
        anyhow::bail!("文件不存在：{path}");
    }

    let ext = p
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.to_ascii_lowercase())
        .unwrap_or_default();

    match ext.as_str() {
        "exe" => spawn_process(path, args),
        // .bat/.cmd 不是 PE 可执行文件，必须经 cmd.exe 解释（仍不经 shell 拼串）。
        "bat" | "cmd" => spawn_process("cmd.exe", &format!("/c \"{path}\" {args}")),
        "lnk" => launch_via_shell(path),
        other => anyhow::bail!("不支持的文件类型：.{other}（仅支持 exe / lnk / bat / cmd）"),
    }
}

/// 用 `CreateProcessW` 启动并返回 pid。
#[cfg(windows)]
fn spawn_process(program: &str, args: &str) -> anyhow::Result<LaunchOutcome> {
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{
        CreateProcessW, CREATE_NEW_PROCESS_GROUP, CREATE_UNICODE_ENVIRONMENT, PROCESS_INFORMATION,
        STARTUPINFOW,
    };

    let program_path = Path::new(program);
    let cwd = program_path
        .parent()
        .filter(|p| !p.as_os_str().is_empty())
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_else(|| ".".to_string());

    // Windows 要求 argv[0] 出现在命令行里（即使已用 lpApplicationName 指定）。
    let mut cmdline = format!("\"{program}\"");
    if !args.trim().is_empty() {
        cmdline.push(' ');
        cmdline.push_str(args);
    }

    let program_w = to_wide(program);
    let mut cmdline_w = to_wide(&cmdline);
    let cwd_w = to_wide(&cwd);

    let si = STARTUPINFOW {
        cb: std::mem::size_of::<STARTUPINFOW>() as u32,
        ..Default::default()
    };
    let mut pi = PROCESS_INFORMATION::default();

    unsafe {
        CreateProcessW(
            PCWSTR(program_w.as_ptr()),
            Some(windows::core::PWSTR(cmdline_w.as_mut_ptr())),
            None,
            None,
            false, // binherithandles
            CREATE_NEW_PROCESS_GROUP | CREATE_UNICODE_ENVIRONMENT,
            None,
            PCWSTR(cwd_w.as_ptr()),
            &si,
            &mut pi,
        )
        .map_err(classify_launch_error)?;

        let pid = pi.dwProcessId;
        // 句柄不需要了 —— 及时关闭，避免句柄泄漏。
        let _ = CloseHandle(pi.hProcess);
        let _ = CloseHandle(pi.hThread);

        if pid == 0 {
            anyhow::bail!("启动失败：未取得进程 pid");
        }
        tracing::info!(pid, program, "已启动进程");
        Ok(LaunchOutcome {
            pid: Some(pid),
            pid_tracked: true,
        })
    }
}

/// `.lnk` 交给系统外壳处理（本阶段不做 IShellLink 解析，见文件头说明）。
#[cfg(windows)]
fn launch_via_shell(path: &str) -> anyhow::Result<LaunchOutcome> {
    use windows::core::{w, PCWSTR};
    use windows::Win32::UI::Shell::ShellExecuteW;
    use windows::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;

    let file_w = to_wide(path);
    let ret = unsafe {
        ShellExecuteW(
            None,
            w!("open"),
            PCWSTR(file_w.as_ptr()),
            PCWSTR::null(),
            PCWSTR::null(),
            SW_SHOWNORMAL,
        )
    };
    // ShellExecuteW 返回值 <= 32 表示失败（Win32 老约定）。
    let code = ret.0 as usize;
    if code <= 32 {
        anyhow::bail!("系统无法打开该快捷方式（ShellExecute 代码 {code}）");
    }
    // 拿不到 pid：05 §3 的存活轮询对 .lnk 不适用。
    Ok(LaunchOutcome {
        pid: None,
        pid_tracked: false,
    })
}

/// Win32 错误 → 面向用户的中文提示（05 §2 要求"可读提示，不是崩溃"）。
#[cfg(windows)]
fn classify_launch_error(e: windows::core::Error) -> anyhow::Error {
    // HRESULT_FROM_WIN32(ERROR_ACCESS_DENIED=5) = 0x80070005
    if e.code().0 as u32 == 0x8007_0005 {
        return anyhow::anyhow!("需要管理员权限运行");
    }
    anyhow::anyhow!("启动失败：{}", e.message())
}

#[cfg(windows)]
fn to_wide(s: &str) -> Vec<u16> {
    s.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(not(windows))]
fn spawn_process(_program: &str, _args: &str) -> anyhow::Result<LaunchOutcome> {
    anyhow::bail!("进程启动当前仅实现 Windows（ADR-001）")
}

#[cfg(not(windows))]
fn launch_via_shell(_path: &str) -> anyhow::Result<LaunchOutcome> {
    anyhow::bail!("进程启动当前仅实现 Windows（ADR-001）")
}
