//! 文件选择器（05 §1 添加方式一：选择可执行文件）。
//!
//! **为什么不引入 `tauri-plugin-dialog` / `rfd`**：项目禁止事项要求
//! 「不要引入需要联网才能运行的依赖」，而本机 npm 侧已被安全策略拦过一次。
//! `GetOpenFileNameW`（comdlg32，windows crate 自带）即可满足，零新依赖。
//!
//! 线程约束：Windows 的模态对话框应在 UI 线程调用。Tauri 的**同步** command
//! 默认就在主线程执行，正合此要求 —— 故本命令刻意写成同步函数，不要改成 async。

/// 弹出"选择可执行文件"对话框，返回用户选中的绝对路径；取消则返回 None。
#[cfg(windows)]
pub fn pick_executable(title: &str, initial_dir: Option<&str>) -> anyhow::Result<Option<String>> {
    use windows::core::PCWSTR;
    // 通用对话框在 Win32::UI::Controls::Dialogs（不是 UI::Shell）
    use windows::Win32::UI::Controls::Dialogs::{
        GetOpenFileNameW, OPENFILENAMEW, OFN_EXPLORER, OFN_FILEMUSTEXIST, OFN_NOCHANGEDIR,
        OFN_PATHMUSTEXIST,
    };

    // 过滤串格式：说明\0模式\0说明\0模式\0\0（双 NUL 结尾）
    let filter: Vec<u16> = "可执行文件 (*.exe;*.lnk;*.bat;*.cmd)\0*.exe;*.lnk;*.bat;*.cmd\0\
                            所有文件 (*.*)\0*.*\0\0"
        .encode_utf16()
        .collect();
    let title_w: Vec<u16> = title.encode_utf16().chain(std::iter::once(0)).collect();

    // 输出缓冲：Windows 要求 nMaxFile 包含结尾 NUL。
    const MAX: usize = 4096;
    let mut file_buf = vec![0u16; MAX];
    if let Some(dir) = initial_dir.filter(|d| !d.is_empty()) {
        // 预填初始目录（会被对话框当作默认目录提示）。
        let dir_w: Vec<u16> = dir.encode_utf16().collect();
        let n = dir_w.len().min(MAX - 1);
        file_buf[..n].copy_from_slice(&dir_w[..n]);
    }

    let mut ofn = OPENFILENAMEW {
        lStructSize: std::mem::size_of::<OPENFILENAMEW>() as u32,
        lpstrFilter: PCWSTR(filter.as_ptr()),
        lpstrFile: windows::core::PWSTR(file_buf.as_mut_ptr()),
        nMaxFile: MAX as u32,
        lpstrTitle: PCWSTR(title_w.as_ptr()),
        // OFN_NOCHANGEDIR：否则对话框会把进程 cwd 改到用户浏览的目录
        Flags: OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_PATHMUSTEXIST | OFN_NOCHANGEDIR,
        ..Default::default()
    };

    let ok = unsafe { GetOpenFileNameW(&mut ofn) }.as_bool();
    if !ok {
        // 用户取消（或对话框打开失败）—— 都不是错误。
        return Ok(None);
    }

    let len = file_buf.iter().position(|&c| c == 0).unwrap_or(0);
    if len == 0 {
        return Ok(None);
    }
    Ok(Some(String::from_utf16_lossy(&file_buf[..len])))
}

#[cfg(not(windows))]
pub fn pick_executable(_title: &str, _initial_dir: Option<&str>) -> anyhow::Result<Option<String>> {
    anyhow::bail!("文件选择器当前仅实现 Windows")
}
