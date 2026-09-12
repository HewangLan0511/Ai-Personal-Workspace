//! 工作模式调度引擎（阶段4 交付范围，全项目核心 ★）。
//!
//! 阶段1 只保留状态机骨架与指令引用（指令 06）：
//! Idle → Validating → Launching → WaitingReady → Arranging → OpeningFiles → LoadingAI → Done
//! 硬约束：并发启动、失败不中断、幂等、可取消、20s 内完成。

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModeState {
    Idle,
    Validating,
    Launching,
    WaitingReady,
    Arranging,
    OpeningFiles,
    LoadingAi,
    Done,
}

impl ModeState {
    /// 状态机的合法流转（阶段4 实现调度循环时使用）。
    pub fn next(self) -> Option<ModeState> {
        match self {
            ModeState::Idle => Some(ModeState::Validating),
            ModeState::Validating => Some(ModeState::Launching),
            ModeState::Launching => Some(ModeState::WaitingReady),
            ModeState::WaitingReady => Some(ModeState::Arranging),
            ModeState::Arranging => Some(ModeState::OpeningFiles),
            ModeState::OpeningFiles => Some(ModeState::LoadingAi),
            ModeState::LoadingAi => Some(ModeState::Done),
            ModeState::Done => None,
        }
    }
}

/// 应用模式（阶段4 实现完整流水线）。
pub fn apply_mode(_mode_id: i64) -> anyhow::Result<()> {
    anyhow::bail!("阶段4 实现：模式应用状态机（指令 06）")
}
