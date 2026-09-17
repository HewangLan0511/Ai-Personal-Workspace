//! 系统进程列表与结束进程 —— 11 §B3。
//!
//! CPU% 用 `GetProcessTimes` 两次快照差分（与任务管理器同口径：占总核容量的百分比）。
//! 结束进程直接复用 `app_manager::status::terminate`（阶段2 已实现并验收），
//! **二次确认由 API 层强制**（`confirm != true` 一律 400，红线 V5）。

#![cfg(windows)]

use std::collections::HashMap;
use std::time::Instant;

use windows::Win32::Foundation::CloseHandle;
use windows::Win32::System::ProcessStatus::{EnumProcesses, GetProcessMemoryInfo, PROCESS_MEMORY_COUNTERS};
use windows::Win32::System::Threading::{
    GetProcessTimes, OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_WIN32,
    PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::Foundation::HANDLE;

#[derive(Debug, Clone, serde::Serialize)]
pub struct ProcInfo {
    pub pid: u32,
    /// 进程名（exe 文件名，小写）
    pub name: String,
    /// 工作集内存（字节）
    pub mem_bytes: u64,
    /// CPU 占用百分比（0~100·核数口径），首次快照为 0
    pub cpu_percent: f64,
}

fn filetime_u64(ft: &windows::Win32::Foundation::FILETIME) -> u64 {
    ((ft.dwHighDateTime as u64) << 32) | ft.dwLowDateTime as u64
}

/// 取进程可执行文件名（不含路径）。life 前台采样器也复用此函数。
pub fn process_image_name(pid: u32) -> Option<String> {
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let mut buf = [0u16; 1024];
        let mut len = buf.len() as u32;
        let r = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_WIN32,
            windows::core::PWSTR(buf.as_mut_ptr()),
            &mut len,
        );
        let _ = CloseHandle(handle);
        r.ok()?;
        if len == 0 {
            return None;
        }
        let full = String::from_utf16_lossy(&buf[..len as usize]);
        let name = full.rsplit(['\\', '/']).next().unwrap_or(&full).to_string();
        Some(name.to_lowercase())
    }
}

/// 进程快照器：跨调用差分算 CPU%。
pub struct ProcessScanner {
    /// pid → 上次 (kernel+user) 时间（100ns 单位）
    times: HashMap<u32, u64>,
    /// 上次快照的墙钟时刻
    wall: Option<Instant>,
    cores: f64,
}

impl ProcessScanner {
    pub fn new() -> Self {
        Self {
            times: HashMap::new(),
            wall: None,
            cores: std::thread::available_parallelism().map(|n| n.get()).unwrap_or(1) as f64,
        }
    }

    /// 枚举全部用户可见进程并计算 CPU%（差分；首次快照 cpu=0 属预期）。
    pub fn snapshot(&mut self) -> Vec<ProcInfo> {
        let now = Instant::now();
        let mut pids = [0u32; 8192];
        let mut needed: u32 = 0;
        unsafe {
            if EnumProcesses(pids.as_mut_ptr(), std::mem::size_of_val(&pids) as u32, &mut needed)
                .is_err()
            {
                return Vec::new();
            }
        }
        let count = (needed as usize / std::mem::size_of::<u32>()).min(pids.len());
        let d_wall = self.wall.map(|w| now.duration_since(w).as_secs_f64());
        let mut cur_times: HashMap<u32, u64> = HashMap::with_capacity(count);
        let mut out = Vec::with_capacity(count);

        for &pid in &pids[..count] {
            if pid == 0 {
                continue;
            }
            let (name, mem, proc_time) = match probe(pid) {
                Some(v) => v,
                None => continue, // 系统保护进程等打不开，跳过
            };
            cur_times.insert(pid, proc_time);
            let cpu = match (d_wall, self.times.get(&pid)) {
                (Some(dw), Some(prev)) if dw > 0.0 && *prev > 0 => {
                    let d = proc_time.saturating_sub(*prev) as f64;
                    // proc_time 单位 100ns；d_wall 秒 → 折算占单核比例再乘核数口径
                    (d / (dw * 10_000_000.0) / self.cores * 100.0).clamp(0.0, 100.0)
                }
                _ => 0.0,
            };
            out.push(ProcInfo { pid, name, mem_bytes: mem, cpu_percent: cpu });
        }
        self.times = cur_times;
        self.wall = Some(now);
        out.sort_by(|a, b| b.cpu_percent.total_cmp(&a.cpu_percent).then(b.mem_bytes.cmp(&a.mem_bytes)));
        out
    }
}

/// 打开进程读 名称 + 工作集 + 累计 CPU 时间。
fn probe(pid: u32) -> Option<(String, u64, u64)> {
    unsafe {
        let handle: HANDLE = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid).ok()?;
        let result = (|| {
            let mut buf = [0u16; 1024];
            let mut len = buf.len() as u32;
            QueryFullProcessImageNameW(
                handle,
                PROCESS_NAME_WIN32,
                windows::core::PWSTR(buf.as_mut_ptr()),
                &mut len,
            )
            .ok()?;
            let full = String::from_utf16_lossy(&buf[..len as usize]);
            let name = full.rsplit(['\\', '/']).next().unwrap_or(&full).to_lowercase();

            let mut pmc = PROCESS_MEMORY_COUNTERS::default();
            let _ = GetProcessMemoryInfo(
                handle,
                &mut pmc,
                std::mem::size_of::<PROCESS_MEMORY_COUNTERS>() as u32,
            );
            let mem = pmc.WorkingSetSize as u64;

            let mut creation = Default::default();
            let mut exit = Default::default();
            let mut kernel = Default::default();
            let mut user = Default::default();
            let total = if GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user)
                .is_ok()
            {
                filetime_u64(&kernel) + filetime_u64(&user)
            } else {
                0
            };
            Some((name, mem, total))
        })();
        let _ = CloseHandle(handle);
        result
    }
}
