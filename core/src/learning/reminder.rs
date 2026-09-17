//! 提醒机制（09 §5）：检测"长期未更新"，发应用内提醒。
//!
//! 规则（全部来自 09 §5，逐条可机器断言）：
//! 1. 阈值可配置：`config.learning.remind_after_days`（默认 **30** 天）；
//! 2. 只有 `not_started` / `learning` 的目标会被提醒 —— `paused`（用户点了暂停）、
//!    `done`、`archived` 一律不打扰；
//! 3. **同目标最多 7 天提醒一次**（`last_reminded_at` 节流，避免骚扰）；
//! 4. 提醒提供三个动作：继续 / 暂停 / 归档 —— 由 UI 调 `learning_goal_update` 完成，
//!    本模块只负责"发现"和"通知"，**不替用户做选择**。
//!
//! 判定逻辑（[`should_remind`]）刻意做成**纯函数**：时间是入参而不是 `Local::now()`，
//! 于是"30 天前更新该提醒 / 昨天刚提醒过不该再提醒"这类边界可以直接单测，
//! 不必靠改系统时钟或等 30 天。

use std::sync::Arc;
use std::time::Duration;

use chrono::{Local, NaiveDateTime};
use serde::Serialize;
use serde_json::json;

use crate::event_bus::LEARNING_REMINDER;
use crate::state::AppState;

/// 同一目标的提醒冷却期（09 §5）。
pub const REMIND_COOLDOWN_DAYS: i64 = 7;
/// `learning.remind_after_days` 的默认值（09 §5）。
pub const DEFAULT_REMIND_AFTER_DAYS: i64 = 30;
/// 后台轮询间隔：提醒是"天"级事件，10 分钟一次足够，且每次只查一张小表。
const CHECK_INTERVAL_SECS: u64 = 600;
/// 启动后首次检查的延时：让数据库初始化与 UI 先就绪。
const FIRST_CHECK_DELAY_SECS: u64 = 3;

/// 时间格式与 SQLite 侧 `datetime('now','localtime')` 一致。
const FMT: &str = "%Y-%m-%d %H:%M:%S";

pub fn parse_dt(s: &str) -> Option<NaiveDateTime> {
    NaiveDateTime::parse_from_str(s.trim(), FMT)
        .ok()
        // 容忍 ISO8601 带 T（契约 3.1 写的是 ISO8601，实现用的是空格分隔）
        .or_else(|| NaiveDateTime::parse_from_str(s.trim(), "%Y-%m-%dT%H:%M:%S").ok())
}

/// 一次提醒命中。
#[derive(Debug, Clone, Serialize)]
pub struct ReminderHit {
    #[serde(rename = "goalId")]
    pub goal_id: i64,
    pub title: String,
    /// 距上次更新多少天（未开始时算"创建至今"）
    #[serde(rename = "idleDays")]
    pub idle_days: i64,
}

/// **提醒判据本体**（纯函数，时间入参 —— 便于机器断言）。
///
/// 返回 `Some(idle_days)` 表示该提醒，`None` 表示不提醒。
pub fn should_remind(
    status: &str,
    updated_at: &str,
    last_reminded_at: Option<&str>,
    remind_after_days: i64,
    now: NaiveDateTime,
) -> Option<i64> {
    // ① 用户明确表示过"别打扰"的状态，不提醒
    if !matches!(status, "not_started" | "learning") {
        return None;
    }
    // ② 阈值非法（负数）视为关闭 —— 不做"负数即全部提醒"这种反直觉解释
    if remind_after_days < 0 {
        return None;
    }
    let updated = parse_dt(updated_at)?;
    let idle_days = (now - updated).num_days();
    if idle_days < remind_after_days {
        return None;
    }
    // ③ 冷却期：7 天内提醒过就不再提醒
    if let Some(last) = last_reminded_at.and_then(parse_dt) {
        if (now - last).num_days() < REMIND_COOLDOWN_DAYS {
            return None;
        }
    }
    Some(idle_days)
}

/// 扫描一次：发现应提醒的目标 → 发 `LEARNING_REMINDER` 事件 + 记冷却时间。
///
/// 返回值同时给调用方（command / 验收脚本），使"是否触发"可被直接断言 ——
/// 只靠事件的话，验收脚本得去监听事件流，成本高且容易漏。
pub fn scan(state: &AppState) -> anyhow::Result<Vec<ReminderHit>> {
    // 用户总开关（09 §禁止事项：不要做强制提醒）
    let enabled = state
        .config
        .get("learning.remind_enabled")
        .as_bool()
        .unwrap_or(true);
    if !enabled {
        return Ok(Vec::new());
    }
    let after_days = state
        .config
        .get("learning.remind_after_days")
        .as_i64()
        .unwrap_or(DEFAULT_REMIND_AFTER_DAYS);

    let repo = super::LearningRepo::new(state.db.clone());
    let now = Local::now().naive_local();
    let mut hits = Vec::new();

    for goal in repo.goals_watchable()? {
        let Some(idle_days) = should_remind(
            &goal.status,
            &goal.updated_at,
            goal.last_reminded_at.as_deref(),
            after_days,
            now,
        ) else {
            continue;
        };
        repo.mark_reminded(goal.id)?;
        // 契约 3.3：LEARNING_REMINDER { goalId, title, idleDays }
        let _ = state.bus.publish(
            LEARNING_REMINDER,
            json!({ "goalId": goal.id, "title": goal.title, "idleDays": idle_days }),
        );
        tracing::info!(goal = %goal.title, idle_days, "学习目标长期未更新，已发出提醒");
        hits.push(ReminderHit { goal_id: goal.id, title: goal.title, idle_days });
    }
    Ok(hits)
}

/// 启动后台提醒调度（在 `main.rs` 装配）。
pub fn spawn_watcher(state: Arc<AppState>) {
    std::thread::spawn(move || {
        std::thread::sleep(Duration::from_secs(FIRST_CHECK_DELAY_SECS));
        loop {
            match scan(&state) {
                Ok(hits) if !hits.is_empty() => {
                    tracing::info!(count = hits.len(), "本轮提醒已发出")
                }
                Ok(_) => {}
                Err(e) => tracing::warn!(error = %e, "提醒扫描失败（不中断后台线程）"),
            }
            std::thread::sleep(Duration::from_secs(CHECK_INTERVAL_SECS));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn now() -> NaiveDateTime {
        parse_dt("2026-09-13 12:00:00").unwrap()
    }

    #[test]
    fn triggers_after_threshold() {
        // 30 天前更新，阈值 30 → 提醒，且 idle 恰好 30
        assert_eq!(
            should_remind("learning", "2026-08-14 12:00:00", None, 30, now()),
            Some(30)
        );
        // 29 天 → 不提醒
        assert_eq!(should_remind("learning", "2026-08-15 12:00:00", None, 30, now()), None);
    }

    /// 验收项 4：阈值改成 0 天 → **立刻**触发（连"刚创建"的目标也不例外）。
    #[test]
    fn zero_threshold_triggers_immediately() {
        assert_eq!(
            should_remind("not_started", "2026-09-13 12:00:00", None, 0, now()),
            Some(0)
        );
    }

    /// 验收项 5：点"暂停"后状态变 paused 且不再提醒。
    #[test]
    fn paused_and_archived_are_never_reminded() {
        for st in ["paused", "done", "archived"] {
            assert_eq!(
                should_remind(st, "2020-01-01 00:00:00", None, 0, now()),
                None,
                "{st} 不应被提醒"
            );
        }
    }

    /// 冷却：7 天内提醒过就不重复打扰；超过 7 天可再提醒。
    #[test]
    fn cooldown_is_seven_days() {
        let old = "2026-01-01 00:00:00"; // 早已超阈值
        assert_eq!(should_remind("learning", old, Some("2026-09-10 12:00:00"), 30, now()), None);
        assert_eq!(should_remind("learning", old, Some("2026-09-05 12:00:00"), 30, now()), Some(255));
    }

    #[test]
    fn negative_threshold_disables_reminders() {
        assert_eq!(should_remind("learning", "2020-01-01 00:00:00", None, -1, now()), None);
    }

    #[test]
    fn bad_timestamp_does_not_panic() {
        assert_eq!(should_remind("learning", "不是时间", None, 0, now()), None);
        assert_eq!(should_remind("learning", "2026-09-13 12:00:00", Some("坏值"), 0, now()), Some(0));
    }

    #[test]
    fn accepts_iso8601_with_t_separator() {
        assert_eq!(should_remind("learning", "2026-08-01T12:00:00", None, 30, now()), Some(43));
    }
}
