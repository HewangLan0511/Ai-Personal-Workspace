//! 软件管理（阶段2 交付范围）。
//!
//! ADR-001：进程启动 = Rust（CreateProcessW）。当前为接口占位，
//! 注册 / 启动 / 状态检测 / 图标提取在阶段2 按指令 05 实现。

use std::path::Path;

/// 软件注册记录（契约 3.2.3 的入库形态，字段对齐 apps 表）。
#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub struct AppRecord {
    pub name: String,
    pub path: String,
    #[serde(default)]
    pub args: String,
    pub icon: Option<String>,
    #[serde(rename = "type")]
    pub kind: Option<String>,
    pub category: Option<String>,
}

/// 启动软件：返回 pid。阶段2 实现（指令 05 / ADR-001）。
pub fn launch(_record: &AppRecord) -> anyhow::Result<u32> {
    anyhow::bail!("阶段2 实现：CreateProcessW 启动（ADR-001 已定稿为 Rust 方案）")
}

/// 检查路径是否为可启动目标（注册校验用）。
pub fn validate_path(path: &str) -> bool {
    let p = Path::new(path);
    p.exists()
        && matches!(
            p.extension().and_then(|e| e.to_str()).map(|e| e.to_ascii_lowercase()),
            Some(ref ext) if ["exe", "lnk", "bat", "cmd"].contains(ext)
        )
}
