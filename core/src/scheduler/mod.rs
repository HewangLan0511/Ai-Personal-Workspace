//! 工作模式调度引擎（阶段4 · **全项目核心 ★**）。
//!
//! 06-阶段指令-工作模式引擎：把"软件 + 文件 + 布局 + AI"打包成**可一键进入的环境**。
//!
//! 子模块：
//! - `state`      —— 应用流程的**显式状态机**（06 §2；禁止用一堆布尔变量表达流程状态）
//! - `repository` —— `work_modes` / `layouts` 持久化（**数据库是唯一真相**，JSON 是派生品）
//! - `pipeline`   —— 七步应用流水线（校验→并发启动→等待就绪→排列→开文件→载 AI→更新状态）
//! - `runner`     —— 运行时会话：当前模式、模式拉起的软件、取消令牌
//!
//! 硬约束（06 §2 工程要求）：并发启动 / 失败不中断 / 幂等 / 可取消 / 可重试 / 45s 兜底 / 进度可视。

mod ai_context;
mod pipeline;
mod repository;
mod runner;
mod state;

// 只 re-export 外部（api / state / main）真正用到的符号，避免 unused_imports 噪音。
// `ApplyState` / `ApplyOutcome` 等仅供本模块内部与 JSON 序列化使用，无需 re-export。
// MODE_WORKSPACE 由 ai_context 自身使用（is_data_allowed 的实现），
// 外部调用方一律走 is_data_allowed() —— 不再 re-export，避免"两条判据"的错觉。
pub use ai_context::{build as build_ai_context, is_data_allowed};
pub use pipeline::{apply_mode, exit_mode};
pub use repository::{LayoutRepo, ModeRepo, SWITCH_POLICIES, WorkModeInput, WorkModePatch};
pub use runner::{ModeSession, RunRecord};
