//! 模式应用的状态机（06 §2 的七步流水线）。
//!
//! 06 §禁止事项明确要求：**不得用一堆布尔变量表达流程状态**。
//! 故这里用**单一枚举**承载"当前在哪一步、进度多少"，且终态显式区分
//! `Done` / `Failed` / `Cancelled` ——
//! 三者语义不同，绝不能靠 `is_done && !has_error` 这种布尔组合去推。
//!
//! ```text
//! Idle → Validating → Launching → WaitingReady → Arranging → OpeningFiles → LoadingAi → Done
//!                  ↘ Failed                                   （任一状态）↘ Cancelled
//! ```
//!
//! **注意 `Done { failed }` 与 `Failed { reason }` 的区别**：
//! - `Done { failed: 2 }` = 流程走完了，但其中 2 个软件启动失败（06 §2「失败不中断」）；
//! - `Failed { reason }` = **校验阶段**就失败，整个流程根本没开始（06 §2 步骤①「提前暴露问题」）。

use serde::Serialize;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "phase", rename_all = "snake_case")]
pub enum ApplyState {
    Idle,
    Validating,
    Launching { done: usize, total: usize },
    WaitingReady { ready: usize, total: usize },
    Arranging { done: usize, total: usize },
    OpeningFiles { done: usize, total: usize },
    LoadingAi,
    /// 流程完成；`failed > 0` 表示"完成但有失败项"（06 状态图里的 `Failed(部分失败) → Done`）
    Done { failed: usize },
    /// 校验失败，流程未开始
    Failed { reason: String },
    Cancelled,
}

impl ApplyState {
    /// 阶段序号（用于合法性校验与进度显示）。
    fn rank(&self) -> u8 {
        match self {
            ApplyState::Idle => 0,
            ApplyState::Validating => 1,
            ApplyState::Launching { .. } => 2,
            ApplyState::WaitingReady { .. } => 3,
            ApplyState::Arranging { .. } => 4,
            ApplyState::OpeningFiles { .. } => 5,
            ApplyState::LoadingAi => 6,
            ApplyState::Done { .. } => 7,
            // Failed / Cancelled 是"旁路终态"，不参与"前进"
            ApplyState::Failed { .. } => 100,
            ApplyState::Cancelled => 101,
        }
    }

    /// 给 UI / 日志用的稳定阶段名（不随进度变化）。
    pub fn step_name(&self) -> &'static str {
        match self {
            ApplyState::Idle => "idle",
            ApplyState::Validating => "validating",
            ApplyState::Launching { .. } => "launching",
            ApplyState::WaitingReady { .. } => "waiting_ready",
            ApplyState::Arranging { .. } => "arranging",
            ApplyState::OpeningFiles { .. } => "opening_files",
            ApplyState::LoadingAi => "loading_ai",
            ApplyState::Done { .. } => "done",
            ApplyState::Failed { .. } => "failed",
            ApplyState::Cancelled => "cancelled",
        }
    }

    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            ApplyState::Done { .. } | ApplyState::Failed { .. } | ApplyState::Cancelled
        )
    }

    /// 人类可读的进度文案（06 §2「进度可视」要求 UI 能显示"正在启动 X (2/4)"）。
    /// 返回 `(阶段名, 已完成, 总数)`；`total == 0` 表示该阶段无计数。
    pub fn progress(&self) -> (&'static str, usize, usize) {
        match self {
            ApplyState::Launching { done, total } => ("正在启动软件", *done, *total),
            ApplyState::WaitingReady { ready, total } => ("等待窗口就绪", *ready, *total),
            ApplyState::Arranging { done, total } => ("排列窗口", *done, *total),
            ApplyState::OpeningFiles { done, total } => ("打开文件入口", *done, *total),
            other => (other.step_name(), 0, 0),
        }
    }

    /// 合法流转校验。
    ///
    /// 规则：
    /// 1. 终态**不可**再流转（防止 Done 之后被"复活"）；
    /// 2. 任意非终态都能进 `Cancelled`（06「可取消」）；
    /// 3. 只有 `Validating` 能进 `Failed`（校验失败 = 流程未开始）；
    /// 4. **同一阶段内的推进是"进度更新"，不是流转** —— 必须允许
    ///    （如 `Launching{done:1}` → `Launching{done:2}`，F-21「进度可视」依赖它）；
    /// 5. 跨阶段只能**走到紧邻的下一阶段**，不得跳步。
    ///
    /// ⚠️ 第 5 条必须是"相邻"而不是"rank 更大"—— 后者会把 `Idle → Arranging`
    /// 这种跳步也放过；但第 4 条同样不能漏，否则进度事件全被拒（本模块第二版踩过）。
    pub fn can_transition(&self, next: &ApplyState) -> bool {
        if self.is_terminal() {
            return false;
        }
        if matches!(next, ApplyState::Cancelled) {
            return true;
        }
        if matches!(next, ApplyState::Failed { .. }) {
            return matches!(self, ApplyState::Validating);
        }
        match (self.rank(), next.rank()) {
            (_, b) if b >= 100 => false, // Failed/Cancelled 已在上方处理
            (a, b) if a == b => true,    // 同阶段：进度推进
            (a, b) => b == a + 1,        // 跨阶段：必须相邻
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn forward_path_is_legal() {
        let path = [
            ApplyState::Idle,
            ApplyState::Validating,
            ApplyState::Launching { done: 0, total: 2 },
            ApplyState::WaitingReady { ready: 0, total: 2 },
            ApplyState::Arranging { done: 0, total: 2 },
            ApplyState::OpeningFiles { done: 0, total: 1 },
            ApplyState::LoadingAi,
            ApplyState::Done { failed: 0 },
        ];
        for w in path.windows(2) {
            assert!(w[0].can_transition(&w[1]), "{:?} → {:?} 应合法", w[0], w[1]);
        }
    }

    /// 06 §禁止事项「不要用一堆布尔变量表达流程状态」的配套：跳步必须被拒。
    ///
    /// 注意区分两件事：
    /// - **跨阶段跳步**（`Idle → Arranging`）→ 拒绝；
    /// - **同阶段进度推进**（`Launching{done:0} → {done:1}`）→ **允许**，它是进度更新而非流转，
    ///   F-21「进度可视」依赖它。
    #[test]
    fn skipping_steps_is_rejected() {
        let idle = ApplyState::Idle;
        assert!(!idle.can_transition(&ApplyState::Arranging { done: 0, total: 1 }));
        assert!(!idle.can_transition(&ApplyState::Done { failed: 0 }));

        let launch = ApplyState::Launching { done: 0, total: 1 };
        assert!(!launch.can_transition(&ApplyState::Arranging { done: 0, total: 1 }), "不得跳过等待就绪");

        // 同阶段推进 = 进度更新，必须允许
        assert!(
            launch.can_transition(&ApplyState::Launching { done: 1, total: 1 }),
            "同阶段的进度推进不应被当作非法流转（否则进度事件全被拒）"
        );
        assert!(ApplyState::WaitingReady { ready: 0, total: 3 }
            .can_transition(&ApplyState::WaitingReady { ready: 2, total: 3 }));
    }

    #[test]
    fn terminal_states_cannot_transition() {
        for term in [
            ApplyState::Done { failed: 0 },
            ApplyState::Failed { reason: "x".into() },
            ApplyState::Cancelled,
        ] {
            assert!(term.is_terminal());
            assert!(!term.can_transition(&ApplyState::Idle));
            assert!(!term.can_transition(&ApplyState::Cancelled), "终态不可再被取消");
        }
    }

    /// 06「可取消」：任意非终态都能被取消。
    #[test]
    fn any_non_terminal_can_be_cancelled() {
        for s in [
            ApplyState::Idle,
            ApplyState::Validating,
            ApplyState::Launching { done: 1, total: 4 },
            ApplyState::WaitingReady { ready: 1, total: 4 },
            ApplyState::Arranging { done: 0, total: 4 },
            ApplyState::OpeningFiles { done: 0, total: 1 },
            ApplyState::LoadingAi,
        ] {
            assert!(s.can_transition(&ApplyState::Cancelled), "{s:?} 应可取消");
        }
    }

    /// Failed 只能从 Validating 进（校验失败 = 流程未开始）。
    #[test]
    fn failed_only_from_validating() {
        assert!(ApplyState::Validating.can_transition(&ApplyState::Failed { reason: "布局不可读".into() }));
        assert!(!ApplyState::Launching { done: 0, total: 1 }
            .can_transition(&ApplyState::Failed { reason: "x".into() }),);
        assert!(!ApplyState::Idle.can_transition(&ApplyState::Failed { reason: "x".into() }));
    }

    /// 部分失败用 `Done { failed: n }` 表达，而不是 Failed（06 状态图）。
    ///
    /// 注意：部分失败**不改道** —— 仍要走完 OpeningFiles / LoadingAi 才进 Done，
    /// 只是最后带上失败计数。所以 `Arranging → Done` 属于**跳步**，必须被拒。
    #[test]
    fn partial_failure_lands_on_done_with_count() {
        let path = [
            ApplyState::Arranging { done: 3, total: 4 },
            ApplyState::OpeningFiles { done: 0, total: 1 },
            ApplyState::LoadingAi,
            ApplyState::Done { failed: 1 },
        ];
        for w in path.windows(2) {
            assert!(w[0].can_transition(&w[1]), "{:?} → {:?} 应合法", w[0], w[1]);
        }
        assert!(ApplyState::Done { failed: 1 }.is_terminal());

        assert!(
            !ApplyState::Arranging { done: 3, total: 4 }
                .can_transition(&ApplyState::Done { failed: 1 }),
            "部分失败也必须走完剩余阶段，不得从 Arranging 直接跳 Done"
        );
    }

    #[test]
    fn progress_text_matches_step() {
        let s = ApplyState::Launching { done: 2, total: 4 };
        assert_eq!(s.progress(), ("正在启动软件", 2, 4));
        assert_eq!(s.step_name(), "launching");
        assert_eq!(ApplyState::Done { failed: 0 }.step_name(), "done");
    }
}
