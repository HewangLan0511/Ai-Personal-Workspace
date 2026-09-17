//! 窗口管理（阶段3 交付范围）。
//!
//! **ADR-001：窗口控制 = Rust**（`windows` crate）。`system/` 下不得出现同类实现
//! —— 门禁 A031 按**能力名**扫描会拦（`SetWindowPos` / `EnumWindows` / …）。
//!
//! 子模块：
//! - `layout`  —— 归一化 → 像素（**纯函数**，07 §工程要求「可脱离系统单测」）
//! - `monitor` —— 显示器枚举 / 工作区 / DPI 感知（07 §4）
//! - `window`  —— 查找 / 定位 / 激活（07 §1/§2/§3）
//! - `apply`   —— 编排：槽位 → 窗口 → 定位 → 激活 + 重试 + 事件（07 §工程要求）
//!
//! ## 硬约束（不可省）
//! 1. 进程启动时必须先 `enable_dpi_awareness()`，否则高分屏坐标全错；
//! 2. 定位前先 `SW_RESTORE`（最大化窗口直接 `SetWindowPos` 无效）；
//! 3. 激活必须走 `AttachThreadInput`（否则被前台锁定挡住）。

mod apply;
mod layout;
mod monitor;
mod window;

// 只 re-export 外部（api / main）真正用到的符号，避免制造 unused_imports 噪音。
// 布局相关的内部类型（Rect / WorkArea / AiSidebar 等）留在各自模块内，
// 同 crate 需要时用 `layout::X` / `monitor::X` 引用即可。
pub use apply::{apply_layout, Layout};
pub use layout::PxRect;
pub use monitor::{enable_dpi_awareness, list_monitors, work_area_of};
pub use window::{
    activate, find_by_title, find_main_window, get_rect, is_foreground, list_windows, open_path,
    place,
};

use std::path::{Path, PathBuf};

/// 布局目录：优先环境变量 `PW_LAYOUTS_DIR`，其次仓库内的 `config/layouts`。
///
/// 打包态布局随安装包分发时改由 `PW_LAYOUTS_DIR` 指定（阶段3 先用开发态路径）。
pub fn layouts_dir() -> PathBuf {
    if let Some(dir) = std::env::var_os("PW_LAYOUTS_DIR") {
        return PathBuf::from(dir);
    }
    for rel in ["../config/layouts", "config/layouts"] {
        let p = Path::new(rel);
        if p.is_dir() {
            return p.to_path_buf();
        }
    }
    PathBuf::from("config/layouts")
}

/// 内置布局名单（`config/layouts/*.json` 的文件名，不含扩展名，排序稳定）。
pub fn list_builtin_layouts() -> Vec<String> {
    let dir = layouts_dir();
    let mut names: Vec<String> = match std::fs::read_dir(&dir) {
        Ok(entries) => entries
            .filter_map(Result::ok)
            .filter_map(|e| {
                let p = e.path();
                if p.extension().and_then(|x| x.to_str()) == Some("json") {
                    p.file_stem().and_then(|s| s.to_str()).map(str::to_string)
                } else {
                    None
                }
            })
            .collect(),
        Err(_) => Vec::new(),
    };
    names.sort();
    names
}

/// 读取一个内置布局。
pub fn load_layout(name: &str) -> anyhow::Result<Layout> {
    // 布局名来自用户输入 → 必须挡住 `../` 这类路径穿越
    if name.is_empty()
        || name.contains("..")
        || name.contains('/')
        || name.contains('\\')
    {
        anyhow::bail!("非法的布局名：{name}");
    }
    let path = layouts_dir().join(format!("{name}.json"));
    let text = std::fs::read_to_string(&path)
        .map_err(|e| anyhow::anyhow!("读取布局失败（{}）：{e}", path.display()))?;
    let mut layout: Layout = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("解析布局失败（{}）：{e}", path.display()))?;
    if layout.name.is_empty() {
        layout.name = name.to_string();
    }
    Ok(layout)
}
