//! 硬件指标采集 —— 纯 Win32 API（11 §B2），不引第三方 crate。
//!
//! 依据 02 §2.4 / ADR-001：本机系统能力归 Rust。CPU 用 `GetSystemTimes` 两次
//! 采样差分；内存用 `GlobalMemoryStatusEx`；磁盘用 `GetLogicalDrives` +
//! `GetDiskFreeSpaceExW`。GPU/温度在 Windows 上没有免驱动的通用 WMI 通道
//! （11 说"能拿到就拿"）—— **如实不提供**，不造假数据。

#![cfg(windows)]

use std::time::{SystemTime, UNIX_EPOCH};

use windows::Win32::Storage::FileSystem::{
    GetDiskFreeSpaceExW, GetLogicalDrives, GetLogicalDriveStringsW,
};
use windows::Win32::System::SystemInformation::{GlobalMemoryStatusEx, MEMORYSTATUSEX};
// GetSystemTimes 在 0.59 里归 Threading 模块（与 GetProcessTimes 同处）
use windows::Win32::System::Threading::GetSystemTimes;

/// 一次系统级指标快照。
#[derive(Debug, Clone, serde::Serialize)]
pub struct MetricsPoint {
    /// Unix 毫秒
    pub ts: i64,
    /// CPU 总占用百分比 0~100
    pub cpu: f64,
    /// 已用内存（字节）
    pub mem_used: u64,
    /// 物理内存总量（字节）
    pub mem_total: u64,
    /// 各磁盘占用
    pub disks: Vec<DiskUsage>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct DiskUsage {
    /// 如 "C:"
    pub letter: String,
    pub total_bytes: u64,
    pub free_bytes: u64,
}

/// CPU 采样的上一次 `GetSystemTimes` 值（差分求百分比）。
#[derive(Default)]
pub struct CpuSample {
    pub last_idle: u64,
    pub last_total: u64,
}

fn filetime_u64(ft: &windows::Win32::Foundation::FILETIME) -> u64 {
    ((ft.dwHighDateTime as u64) << 32) | ft.dwLowDateTime as u64
}

/// 采集 CPU%（需要调用方持有上次采样；两次调用间隔越短抖动越大）。
pub fn cpu_percent(sample: &mut CpuSample) -> f64 {
    unsafe {
        let mut idle = Default::default();
        let mut kernel = Default::default();
        let mut user = Default::default();
        if GetSystemTimes(
            Some(&mut idle as *mut _),
            Some(&mut kernel as *mut _),
            Some(&mut user as *mut _),
        )
        .is_err()
        {
            return 0.0;
        }
        let idle = filetime_u64(&idle);
        // kernel 时间**包含** idle，故总时间 = kernel + user，忙 = 总 - idle。
        let total = filetime_u64(&kernel) + filetime_u64(&user);
        let d_total = total.saturating_sub(sample.last_total);
        let d_idle = idle.saturating_sub(sample.last_idle);
        sample.last_total = total;
        sample.last_idle = idle;
        if d_total == 0 {
            return 0.0;
        }
        let pct = (d_total - d_idle) as f64 / d_total as f64 * 100.0;
        pct.clamp(0.0, 100.0)
    }
}

/// 内存占用（`dwMemoryLoad` 是系统口径的使用百分比；这里返回字节数供 UI 自行换算）。
pub fn memory() -> (u64, u64) {
    unsafe {
        let mut ms = MEMORYSTATUSEX::default();
        ms.dwLength = std::mem::size_of::<MEMORYSTATUSEX>() as u32;
        if GlobalMemoryStatusEx(&mut ms).is_err() {
            return (0, 0);
        }
        (ms.ullTotalPhys - ms.ullAvailPhys, ms.ullTotalPhys)
    }
}

/// 枚举本地盘符并读占用（软驱/不可达盘符自动跳过）。
pub fn disks() -> Vec<DiskUsage> {
    let mut out = Vec::new();
    unsafe {
        let drives = GetLogicalDrives();
        if drives == 0 {
            return out;
        }
        // GetLogicalDriveStringsW 拿到 "C:\\\0D:\\\0..." 形式的列表，直接用它对齐盘符。
        let mut buf = [0u16; 512];
        let n = GetLogicalDriveStringsW(Some(&mut buf));
        if n == 0 || n as usize > buf.len() {
            return out;
        }
        let mut root = String::new();
        for &unit in &buf[..n as usize] {
            if unit == 0 {
                if root.len() >= 2 {
                    push_disk(&mut out, &root);
                }
                root.clear();
            } else {
                root.push(char::from_u32(unit as u32).unwrap_or('\0'));
            }
        }
        if root.len() >= 2 {
            push_disk(&mut out, &root);
        }
        let _ = drives; // bitmask 仅用于判断"有盘符"，实际列表以 DriveStrings 为准
    }
    out
}

fn push_disk(out: &mut Vec<DiskUsage>, root: &str) {
    let letter = root.chars().next().unwrap_or('?').to_ascii_uppercase().to_string();
    // 已记录过就跳过（防重复）
    if out.iter().any(|d| d.letter == letter) {
        return;
    }
    let mut total: u64 = 0;
    let mut free: u64 = 0;
    let wide: Vec<u16> = root.encode_utf16().chain(std::iter::once(0)).collect();
    let pc = windows::core::PCWSTR(wide.as_ptr());
    unsafe {
        if GetDiskFreeSpaceExW(pc, None, Some(&mut total), Some(&mut free)).is_ok() && total > 0 {
            out.push(DiskUsage { letter, total_bytes: total, free_bytes: free });
        }
    }
}

/// 当前时间 Unix 毫秒。
pub fn now_ms() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0)
}
