//! 运行状态检测（05 §3）。
//!
//! 检测方式：**按 pid 轮询存活**（05 §3 指定）。进程退出即发 `APP_CLOSED`，
//! UI 据此取消"运行中"标记。
//!
//! 这里只持有"事实"（谁在跑、pid 多少），不解释其意义 —— 02 §2.3 对 core 的约束。

use std::collections::HashMap;
use std::sync::Mutex;

/// 运行中的软件：`appId → pid`。
#[derive(Default)]
pub struct RunningApps {
    inner: Mutex<HashMap<i64, u32>>,
}

impl RunningApps {
    pub fn new() -> Self {
        Self::default()
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, HashMap<i64, u32>> {
        // 与 Db 一致：锁中毒意味着持锁线程崩溃，重启进程即可恢复。
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    /// 登记一次启动。
    pub fn mark(&self, app_id: i64, pid: u32) {
        self.lock().insert(app_id, pid);
    }

    /// 主动注销（例如用户点了"结束"）。
    pub fn forget(&self, app_id: i64) -> Option<u32> {
        self.lock().remove(&app_id)
    }

    /// 取当前记录快照（appId → pid）。
    pub fn snapshot(&self) -> HashMap<i64, u32> {
        self.lock().clone()
    }

    pub fn get(&self, app_id: i64) -> Option<u32> {
        self.lock().get(&app_id).copied()
    }

    /// 清理已退出的进程，返回**本次新发现退出**的 appId 列表。
    ///
    /// 调用方据此发布 `APP_CLOSED`（05 §3）。
    pub fn reap_exited(&self) -> Vec<i64> {
        let mut guard = self.lock();
        let dead: Vec<i64> = guard
            .iter()
            .filter(|(_, pid)| !is_alive(**pid))
            .map(|(id, _)| *id)
            .collect();
        for id in &dead {
            guard.remove(id);
        }
        dead
    }
}

/// 按 pid 判断进程是否仍存活。
#[cfg(windows)]
pub fn is_alive(pid: u32) -> bool {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{
        GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };

    /// 进程仍在运行时的退出码（Win32 `STILL_ACTIVE`）。
    const STILL_ACTIVE: u32 = 259;

    unsafe {
        // 打不开句柄 = 进程已不存在（或权限不足，此时保守判为"不存活"）。
        let handle = match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            Ok(h) => h,
            Err(_) => return false,
        };
        let mut code: u32 = 0;
        let queried = GetExitCodeProcess(handle, &mut code).is_ok();
        let _ = CloseHandle(handle);
        queried && code == STILL_ACTIVE
    }
}

#[cfg(not(windows))]
pub fn is_alive(_pid: u32) -> bool {
    // 非 Windows 平台本阶段不提供进程能力（ADR-001 仅 Windows）。
    false
}

/// 结束一个进程（06 §3 `exclusive` 切换策略需要）。
///
/// ⚠️ **安全边界**：本函数只负责"结束给定 pid"，**不判断该进程是否由模式拉起**。
/// 那个判断必须由调用方（`scheduler` 的 `RunRecord`）完成 —— 见 REVIEW-010 **R-01**：
/// 无差别地关闭"同名软件"会把用户自己开的程序一起关掉，是体验灾难。
#[cfg(windows)]
pub fn terminate(pid: u32) -> anyhow::Result<()> {
    use windows::Win32::Foundation::CloseHandle;
    use windows::Win32::System::Threading::{OpenProcess, TerminateProcess, PROCESS_TERMINATE};

    unsafe {
        let handle = OpenProcess(PROCESS_TERMINATE, false, pid)
            .map_err(|e| anyhow::anyhow!("打开进程失败（可能已退出）：{e}"))?;
        let r = TerminateProcess(handle, 0);
        let _ = CloseHandle(handle);
        r.map_err(|e| anyhow::anyhow!("结束进程失败：{e}"))
    }
}

#[cfg(not(windows))]
pub fn terminate(_pid: u32) -> anyhow::Result<()> {
    anyhow::bail!("进程结束当前仅实现 Windows（ADR-001）")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reap_removes_dead_and_keeps_alive() {
        let running = RunningApps::new();
        // 当前进程自身一定存活（拿自己的 pid 当"活样本"）。
        let me = std::process::id();
        running.mark(1, me);
        // 一个几乎不可能存在的 pid（Windows pid 不会到 u32::MAX-1）。
        running.mark(2, u32::MAX - 1);

        let dead = running.reap_exited();
        assert_eq!(dead, vec![2], "应只清理掉不存在的那个");
        assert_eq!(running.get(1), Some(me), "存活进程必须保留");
        assert_eq!(running.get(2), None);
    }
}
