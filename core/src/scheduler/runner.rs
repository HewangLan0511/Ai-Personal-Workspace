//! 运行时会话、取消令牌与"模式拉起的软件"登记。
//!
//! ## 为什么必须单独记"模式拉起的软件"（06 §4）
//! 模式**只应管理自己拉起的**。若退出/切换模式时无差别地关闭"同名软件"，
//! 会把用户自己开的程序一起关掉 —— 那是体验灾难（REVIEW-010 **R-01**）。
//! 故此处的登记是"能不能关"的**唯一依据**，不是可选优化。

use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use super::state::ApplyState;

/// 取消令牌。`Arc<AtomicBool>`：任意线程置位，流水线在各步之间检查。
#[derive(Clone, Default)]
pub struct CancelToken(Arc<AtomicBool>);

impl CancelToken {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn cancel(&self) {
        self.0.store(true, Ordering::SeqCst);
    }
    pub fn is_cancelled(&self) -> bool {
        self.0.load(Ordering::SeqCst)
    }
}

/// 单个软件在本次应用中的结果。
#[derive(Debug, Clone, serde::Serialize)]
pub struct SlotResult {
    pub app: String,
    #[serde(rename = "appId")]
    pub app_id: Option<i64>,
    /// `launched` | `already_running` | `failed` | `arranged` | `skipped_cancelled`
    pub status: String,
    pub pid: Option<u32>,
    pub reason: Option<String>,
    /// 06 §2「可重试」：UI 据此决定是否显示"重试"按钮
    pub retriable: bool,
}

/// 阶段轨迹的一条记录（F-38「步骤清单」/ 验收 V-03）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct HistoryEntry {
    pub phase: String,
    /// Unix epoch 毫秒（用绝对时间便于跨进程拼接日志）
    #[serde(rename = "tsMs")]
    pub ts_ms: u128,
}

/// 一次模式应用的会话：进度状态 + 取消令牌 + 每项结果 + **阶段轨迹**。
pub struct ModeSession {
    pub mode_id: i64,
    pub mode_name: String,
    state: Mutex<ApplyState>,
    cancel: CancelToken,
    slots: Mutex<Vec<SlotResult>>,
    /// 走过的阶段序列。
    ///
    /// **为什么必须有**：apply 全程可能只有 1 秒出头，外部按 50ms 轮询**必然抓不全**中间态。
    /// 让会话自己记轨迹，UI 的"步骤清单"与验收的"进度可见"才有稳定依据
    /// —— 靠轮询碰运气是不合格的实现。
    history: Mutex<Vec<HistoryEntry>>,
}

impl ModeSession {
    pub fn new(mode_id: i64, mode_name: impl Into<String>) -> Self {
        Self {
            mode_id,
            mode_name: mode_name.into(),
            state: Mutex::new(ApplyState::Idle),
            cancel: CancelToken::new(),
            slots: Mutex::new(Vec::new()),
            history: Mutex::new(Vec::new()),
        }
    }

    pub fn cancel_token(&self) -> CancelToken {
        self.cancel.clone()
    }

    pub fn state(&self) -> ApplyState {
        self.state.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// 阶段轨迹（按时间顺序）。
    pub fn history(&self) -> Vec<HistoryEntry> {
        self.history.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    /// 状态流转。**非法流转会被忽略并记 WARN** —— 保证状态机不被写乱。
    ///
    /// 每次成功流转都会追加一条 `history`（同阶段重复推进只记一次）。
    pub fn transition(&self, next: ApplyState) -> bool {
        let mut guard = self.state.lock().unwrap_or_else(|e| e.into_inner());
        if !guard.can_transition(&next) {
            tracing::warn!(from = ?*guard, to = ?next, "非法的状态流转已忽略");
            return false;
        }
        let phase = next.step_name().to_string();
        *guard = next;
        drop(guard);

        let mut h = self.history.lock().unwrap_or_else(|e| e.into_inner());
        // 同一阶段只记首次进入（进度推进如 `Launching{done:1}` → `{done:2}` 不重复记）
        if h.last().map(|e| e.phase.as_str()) != Some(phase.as_str()) {
            let ts_ms = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|d| d.as_millis())
                .unwrap_or(0);
            h.push(HistoryEntry { phase, ts_ms });
        }
        true
    }

    pub fn record(&self, r: SlotResult) {
        self.slots.lock().unwrap_or_else(|e| e.into_inner()).push(r);
    }

    pub fn slots(&self) -> Vec<SlotResult> {
        self.slots.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }
}

/// 全局运行记录：当前模式 + 各模式拉起的软件 + 上一条快照。
#[derive(Default)]
pub struct RunRecord {
    inner: Mutex<RunInner>,
}

#[derive(Default)]
struct RunInner {
    /// 全局唯一当前模式（06 §4）
    current: Option<String>,
    /// 上一个模式（用于"回到上一个模式"，06 §3 要求切换前保存快照）
    previous: Option<String>,
    /// `modeName → 该模式拉起的 appId`（**R-01 的唯一依据**）
    launched: HashMap<String, Vec<i64>>,
    /// 最近一次切换前的快照：`(modeName, appIds)`
    last_snapshot: Option<(String, Vec<i64>)>,
}

impl RunRecord {
    /// 登记"这些软件是 `mode` 拉起的"。
    pub fn mark_launched(&self, mode: &str, app_ids: &[i64]) {
        let mut g = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let entry = g.launched.entry(mode.to_string()).or_default();
        for id in app_ids {
            if !entry.contains(id) {
                entry.push(*id);
            }
        }
    }

    /// 某模式拉起的 appId（**只返回模式自己拉起的**）。
    pub fn launched_by(&self, mode: &str) -> Vec<i64> {
        self.inner
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .launched
            .get(mode)
            .cloned()
            .unwrap_or_default()
    }

    /// 把 `from` 模式拉起的软件登记到当前快照（06 §3：切换前必须保存快照）。
    pub fn snapshot_before_switch(&self, from: &str) {
        let mut g = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        let ids = g.launched.get(from).cloned().unwrap_or_default();
        g.last_snapshot = Some((from.to_string(), ids));
        g.previous = Some(from.to_string());
    }

    /// 最近一次切换前的快照（"回到上一个模式"用）。
    pub fn last_snapshot(&self) -> Option<(String, Vec<i64>)> {
        self.inner
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .last_snapshot
            .clone()
    }

    pub fn previous(&self) -> Option<String> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner()).previous.clone()
    }

    pub fn current(&self) -> Option<String> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner()).current.clone()
    }

    pub fn set_current(&self, mode: Option<&str>) {
        let mut g = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        if let Some(prev) = g.current.clone() {
            if Some(prev.as_str()) != mode {
                g.previous = Some(prev);
            }
        }
        g.current = mode.map(str::to_string);
    }

    /// 清空某模式的登记（该模式退出后）。
    pub fn clear(&self, mode: &str) {
        let mut g = self.inner.lock().unwrap_or_else(|e| e.into_inner());
        g.launched.remove(mode);
        if g.current.as_deref() == Some(mode) {
            g.current = None;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cancel_token_is_visible_across_clones() {
        let t = CancelToken::new();
        let t2 = t.clone();
        assert!(!t2.is_cancelled());
        t.cancel();
        assert!(t2.is_cancelled(), "克隆出来的令牌应看到取消状态");
    }

    /// 状态机保护：非法流转被忽略，合法流转生效。
    #[test]
    fn session_rejects_illegal_transition() {
        let s = ModeSession::new(1, "开发模式");
        assert!(s.transition(ApplyState::Validating));
        // 跳过中间步骤 → 应被拒
        assert!(!s.transition(ApplyState::Done { failed: 0 }));
        assert_eq!(s.state(), ApplyState::Validating);
        assert!(s.transition(ApplyState::Launching { done: 0, total: 1 }));
        assert!(s.transition(ApplyState::Cancelled));
        assert!(!s.transition(ApplyState::Idle), "终态不可回退");
    }

    /// R-01：`launched_by` 只返回该模式自己拉起的软件。
    #[test]
    fn launched_registry_is_per_mode() {
        let r = RunRecord::default();
        r.mark_launched("开发模式", &[1, 2, 3]);
        r.mark_launched("学习模式", &[4]);
        assert_eq!(r.launched_by("开发模式"), vec![1, 2, 3]);
        assert_eq!(r.launched_by("学习模式"), vec![4]);
        assert!(r.launched_by("不存在的模式").is_empty());
        // 重复登记不产生重复项
        r.mark_launched("开发模式", &[2, 5]);
        assert_eq!(r.launched_by("开发模式"), vec![1, 2, 3, 5]);
    }

    /// 06 §3：切换前必须留下快照，且 previous 指向切换来源。
    #[test]
    fn switch_keeps_snapshot_and_previous() {
        let r = RunRecord::default();
        r.set_current(Some("A"));
        r.mark_launched("A", &[10, 11]);
        r.snapshot_before_switch("A");
        r.set_current(Some("B"));

        assert_eq!(r.current().as_deref(), Some("B"));
        assert_eq!(r.previous().as_deref(), Some("A"));
        assert_eq!(r.last_snapshot(), Some(("A".to_string(), vec![10, 11])), "快照应保留 A 拉起的软件");
    }

    #[test]
    fn clear_removes_mode_registry() {
        let r = RunRecord::default();
        r.mark_launched("A", &[1]);
        r.set_current(Some("A"));
        r.clear("A");
        assert!(r.launched_by("A").is_empty());
        assert!(r.current().is_none());
    }
}
