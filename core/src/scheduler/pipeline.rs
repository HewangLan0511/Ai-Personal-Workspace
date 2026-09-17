//! 模式应用流水线（06 §2 七步）—— **本项目的灵魂**。
//!
//! ```text
//! ① 校验 → ② 并发启动 → ③ 等待就绪 → ④ 排列窗口 → ⑤ 打开文件 → ⑥ 载入 AI → ⑦ 更新状态
//! ```
//!
//! ## 落地了哪些硬约束（06 §2 工程要求）
//! | 要求 | 实现 |
//! |------|------|
//! | 并发启动 | 每个软件一个线程 + `mpsc` 收集；**不是串行 for 循环** |
//! | 单软件 15s 超时 | `recv_timeout(PER_APP_TIMEOUT)` |
//! | 进度可视 | 每步/每项发 `MODE_APPLY_PROGRESS` |
//! | 失败不中断 | 单项失败只记录，继续处理其余 |
//! | 幂等 | 已在运行的软件**跳过启动**，直接用已有 pid |
//! | 可取消 | 各步之间检查 `CancelToken` |
//! | 45s 兜底 | 主循环每轮检查 `TOTAL_TIMEOUT` |
//! | 显式状态机 | 全部经 `ModeSession::transition`（非法流转被拒） |
//!
//! ## 禁止事项自查（06 §禁止事项）
//! - **不串行启动**：见 ②
//! - **不用固定 sleep 代替就绪检测**：见 ③，是"轮询 + 超时 + 部分就绪"
//! - **单软件失败不中断**：见 ②④ 的错误处理
//! - **不用一堆 bool**：状态只在 `ApplyState` 里
//! - **不硬编码路径**：路径一律来自 `apps` 注册表（见 `launch_one`）

use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

use crate::event_bus::{MODE_APPLY_FAILED, MODE_APPLY_PROGRESS, MODE_CHANGED};
use crate::state::AppState;

use super::repository::{LayoutRepo, ModeRepo, OpenTarget, WorkMode};
use super::runner::{CancelToken, ModeSession, SlotResult};
use super::state::ApplyState;

/// 整体硬超时（06 §2：「45s 硬超时，避免卡死」）
const TOTAL_TIMEOUT: Duration = Duration::from_secs(45);
/// 单个软件启动超时（06 §2 表格）
const PER_APP_TIMEOUT: Duration = Duration::from_secs(15);
/// 等待窗口就绪的总超时（06 §技术要点：轮询 + 部分就绪）
const READY_TIMEOUT: Duration = Duration::from_secs(20);
/// 就绪轮询间隔（**不是**用它当就绪判据，只是轮询节奏）
const READY_POLL: Duration = Duration::from_millis(300);

/// 一个待启动项（校验结果）。
#[derive(Debug, Clone)]
struct AppPlan {
    name: String,
    app_id: Option<i64>,
    /// 校验阶段就发现的问题（如"未注册"/"文件不存在"）—— 启动阶段直接记为失败，不浪费一次启动
    precheck_error: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct ApplyOutcome {
    #[serde(rename = "modeId")]
    pub mode_id: i64,
    #[serde(rename = "modeName")]
    pub mode_name: String,
    pub state: ApplyState,
    pub launched: usize,
    #[serde(rename = "alreadyRunning")]
    pub already_running: usize,
    pub failed: usize,
    pub arranged: usize,
    #[serde(rename = "filesOpened")]
    pub files_opened: usize,
    pub slots: Vec<SlotResult>,
    #[serde(rename = "tookMs")]
    pub took_ms: u128,
    pub cancelled: bool,
    /// ④ 排列阶段的可读说明（例如"A 未运行，槽位跳过"）
    #[serde(rename = "arrangeNote")]
    pub arrange_note: Option<String>,
    /// `exclusive` 策略下被关闭的软件名（06 §3；只含**上一个模式拉起的**）
    pub closed: Vec<String>,
    /// 本次实际采用的切换策略
    pub policy: String,
    /// 06 §3 `ask`：需要在 UI 上询问用户（本次已按 additive 执行，用户选完可带 override 重跑）
    #[serde(rename = "askPending")]
    pub ask_pending: bool,
}

/// 应用一个模式。**同步阻塞**（含必要的等待），调用方应放在阻塞线程里。
pub fn apply_mode(
    state: &Arc<AppState>,
    mode_id: i64,
    policy_override: Option<String>,
) -> anyhow::Result<ApplyOutcome> {
    let started = Instant::now();
    let repo = ModeRepo::new(state.db.clone());

    // 软删除的模式不得被 apply（R-02）
    let mode = repo
        .get(mode_id)?
        .ok_or_else(|| anyhow::anyhow!("模式不存在或已删除：id={mode_id}"))?;

    let session = Arc::new(ModeSession::new(mode.id, mode.name.clone()));
    *state.mode_session.lock().unwrap_or_else(|e| e.into_inner()) = Some(session.clone());
    let cancel = session.cancel_token();

    // ---- ① 校验：提前暴露问题（06 §2）----
    if !session.transition(ApplyState::Validating) {
        anyhow::bail!("状态机拒绝进入校验阶段");
    }
    let plans = match validate(state, &mode) {
        Ok(p) => p,
        Err(e) => {
            // 校验失败 ⇒ 状态机进 `Failed`（流程未开始），再向上报错。
            // 06 §2 状态图把 Failed 画在 Validating 之下，这一步不能省 ——
            // 否则 UI 会永远看到 state=validating 的"僵尸进度"。
            session.transition(ApplyState::Failed { reason: e.to_string() });
            emit_progress(state, &session, &format!("校验失败：{e}"));
            return Err(e);
        }
    };
    emit_progress(state, &session, "校验完成");

    // 06 §3：**切换前必须保存当前模式的运行快照**（用于"回到上一个模式"）。
    // 放在启动之前 —— 一旦开始启动 B 的软件，A 的现场就不再完整了。
    let prev_name = state.modes_run.current().filter(|p| *p != mode.name);
    if let Some(prev) = &prev_name {
        state.modes_run.snapshot_before_switch(prev);
        tracing::info!(from = %prev, to = %mode.name, "已保存切换前快照");
    }

    // ---- 06 §3 模式切换语义：additive / exclusive / ask ----
    let remembered = prev_name
        .as_deref()
        .and_then(|p| remembered_policy(state, p, &mode.name));
    let policy = match &policy_override {
        Some(p) => p.clone(),
        // `ask`：查有没有"上次的选择"；没有就先按 additive 跑，并让 UI 去询问
        None if mode.switch_policy == "ask" => {
            remembered.clone().unwrap_or_else(|| "additive".to_string())
        }
        None => mode.switch_policy.clone(),
    };
    let ask_pending = mode.switch_policy == "ask"
        && prev_name.is_some()
        && policy_override.is_none()
        && remembered.is_none();

    // `exclusive`：关闭"上一个模式拉起、但本模式不需要"的软件。
    // **只关上一个模式自己拉起的**（R-01）—— 用户手动开的程序一律不碰。
    let mut closed: Vec<String> = Vec::new();
    if policy == "exclusive" {
        if let Some(prev) = &prev_name {
            let keep: Vec<i64> = plans.iter().filter_map(|p| p.app_id).collect();
            for id in state.modes_run.launched_by(prev) {
                if keep.contains(&id) {
                    continue;
                }
                match crate::app_manager::kill_registered(state, id) {
                    Ok(()) => {
                        let nm = state
                            .apps
                            .get(id)
                            .ok()
                            .flatten()
                            .map(|a| a.name)
                            .unwrap_or_else(|| format!("app#{id}"));
                        closed.push(nm);
                    }
                    Err(e) => tracing::warn!(app_id = id, error = %e, "exclusive 关闭失败（继续处理其余）"),
                }
            }
        }
    }

    // ---- ② 并发启动 ----
    session.transition(ApplyState::Launching { done: 0, total: plans.len() });
    let done_counter = Arc::new(AtomicUsize::new(0));
    let total = plans.len();
    let mut receivers = Vec::with_capacity(total);

    for p in &plans {
        if let Some(err) = p.precheck_error.clone() {
            // 校验期已发现的问题 —— 不浪费一次启动尝试
            session.record(SlotResult {
                app: p.name.clone(),
                app_id: p.app_id,
                status: "failed".into(),
                pid: None,
                reason: Some(err.clone()),
                retriable: true,
            });
            let _ = state.bus.publish(
                MODE_APPLY_FAILED,
                json!({ "modeId": mode.id, "app": p.name, "stage": "validate", "reason": err, "recoverable": true }),
            );
            continue;
        }
        let st = state.clone();
        let plan = p.clone();
        let (tx, rx) = std::sync::mpsc::channel();
        // 每个软件一个独立线程 —— 这就是"并发启动"（06 §2 表格第一条）
        std::thread::spawn(move || {
            let _ = tx.send(launch_one(&st, &plan));
        });
        receivers.push((p.name.clone(), rx));
    }

    for (name, rx) in receivers {
        if cancel.is_cancelled() {
            session.record(SlotResult {
                app: name.clone(),
                app_id: None,
                status: "skipped_cancelled".into(),
                pid: None,
                reason: Some("用户取消".into()),
                retriable: true,
            });
            continue;
        }
        let r = match rx.recv_timeout(PER_APP_TIMEOUT) {
            Ok(r) => r,
            Err(_) => SlotResult {
                app: name.clone(),
                app_id: None,
                status: "failed".into(),
                pid: None,
                reason: Some(format!("启动超时（{}s）", PER_APP_TIMEOUT.as_secs())),
                retriable: true,
            },
        };
        if r.status == "failed" {
            let _ = state.bus.publish(
                MODE_APPLY_FAILED,
                json!({ "modeId": mode.id, "app": r.app, "stage": "launch", "reason": r.reason, "recoverable": true }),
            );
        }
        session.record(r);

        let n = done_counter.fetch_add(1, Ordering::SeqCst) + 1;
        session.transition(ApplyState::Launching { done: n, total });
        emit_progress(state, &session, &format!("正在启动 {name} ({n}/{total})"));
        if started.elapsed() > TOTAL_TIMEOUT {
            tracing::warn!("整体超时，中止后续启动");
            break;
        }
    }

    // 结果统一从会话取（**单一来源**）：`mode_progress` 读的也是这里
    let snapshot: Vec<SlotResult> = session.slots();

    // ---- ③ 等待就绪（轮询，不固定 sleep）----
    let live: Vec<(String, u32)> = snapshot
        .iter()
        .filter_map(|r| r.pid.map(|p| (r.app.clone(), p)))
        .collect();
    session.transition(ApplyState::WaitingReady { ready: 0, total: live.len() });
    let ready_map = wait_ready(state, &session, &live, &cancel);

    // ---- ④ 排列窗口（复用阶段3 的编排：含重试 + 单窗口失败不阻塞）----
    session.transition(ApplyState::Arranging { done: 0, total: ready_map.len() });
    let (arranged, arrange_note) = arrange(state, &mode, &session)?;
    emit_progress(state, &session, "窗口排列完成");

    // ---- ⑤ 打开文件入口 ----
    session.transition(ApplyState::OpeningFiles { done: 0, total: mode.open_targets.len() });
    let files_opened = open_targets(state, &session, &mode.open_targets, &cancel);

    // ---- ⑥ 载入 AI 配置（阶段5 消费；此处先落到 config）----
    session.transition(ApplyState::LoadingAi);
    if let Some(profile) = &mode.ai_profile {
        if let Err(e) = state.config.set("ai.active_profile", json!(profile)) {
            tracing::warn!(error = %e, "写入 ai.active_profile 失败（本阶段 AI 尚未启用，不阻塞）");
        }
    }
    emit_progress(state, &session, "AI 配置已就绪");

    // ---- ⑦ 更新状态 ----
    let cancelled = cancel.is_cancelled();
    let failed = snapshot.iter().filter(|r| r.status == "failed").count();
    if cancelled {
        session.transition(ApplyState::Cancelled);
    } else {
        session.transition(ApplyState::Done { failed });
    }

    if !cancelled {
        // R-07：`use_count` / `last_used_at` 只在**成功完成**时更新（取消不算用过）
        if let Err(e) = repo.touch_used(mode.id) {
            tracing::warn!(error = %e, "更新 use_count 失败");
        }
        let _ = state.config.set("mode.current", json!(mode.name));
        state
            .modes_run
            .set_current(Some(mode.name.as_str()));
        let launched_ids: Vec<i64> = snapshot
            .iter()
            .filter(|r| r.status == "launched" || r.status == "already_running")
            .filter_map(|r| r.app_id)
            .collect();
        state.modes_run.mark_launched(&mode.name, &launched_ids);

        // 契约 3.3：MODE_CHANGED { modeId, name, apps }
        let _ = state.bus.publish(
            MODE_CHANGED,
            json!({
                "modeId": mode.id, "name": mode.name, "apps": mode.apps,
                "policy": policy_override.unwrap_or_else(|| mode.switch_policy.clone()),
            }),
        );
    }

    let launched = snapshot.iter().filter(|r| r.status == "launched").count();
    let already = snapshot.iter().filter(|r| r.status == "already_running").count();

    Ok(ApplyOutcome {
        mode_id: mode.id,
        mode_name: mode.name,
        state: session.state(),
        launched,
        already_running: already,
        failed,
        arranged,
        files_opened,
        slots: snapshot,
        took_ms: started.elapsed().as_millis(),
        cancelled,
        arrange_note,
        closed,
        policy,
        ask_pending,
    })
}

/// 读 06 §3 `ask` 策略的"上次选择"记忆：`mode.switch_memory` = `{"A>B": "exclusive"}`。
fn remembered_policy(state: &AppState, from: &str, to: &str) -> Option<String> {
    let mem = state.config.get("mode.switch_memory");
    let key = format!("{from}>{to}");
    mem.get(&key)
        .and_then(Value::as_str)
        .map(str::to_string)
        .filter(|p| super::repository::SWITCH_POLICIES.contains(&p.as_str()))
}

/// 退出当前模式：关闭**该模式自己拉起的**软件。
///
/// 06 §4「模式只管理自己拉起的」的直接落地 —— 也是 REVIEW-010 **R-01** 的验证点：
/// 用户手动打开的程序（不在 `RunRecord` 登记里）**一个都不能碰**。
///
/// 返回被关闭的软件名。
pub fn exit_mode(state: &Arc<AppState>) -> anyhow::Result<Vec<String>> {
    let Some(cur) = state.modes_run.current() else {
        return Ok(Vec::new());
    };
    let mut closed = Vec::new();
    for id in state.modes_run.launched_by(&cur) {
        let name = state
            .apps
            .get(id)
            .ok()
            .flatten()
            .map(|a| a.name)
            .unwrap_or_else(|| format!("app#{id}"));
        match crate::app_manager::kill_registered(state, id) {
            Ok(()) => closed.push(name),
            Err(e) => tracing::warn!(app_id = id, error = %e, "退出模式时关闭失败（继续）"),
        }
    }
    state.modes_run.clear(&cur);
    // ⚠️ **不清 `mode.current`**：它承载的是"**上次使用过**的模式"，用于 06 §4 的一键恢复。
    // 「退出模式」≠「没用过这个模式」—— 清掉它会让验收 V-10
    // 「重启后显示上次使用：X」永远拿不到值（这是本模块第一版的真实 bug）。
    // 契约 3.3：MODE_CHANGED（退出）
    let _ = state.bus.publish(
        MODE_CHANGED,
        json!({ "modeId": Value::Null, "name": Value::Null, "exited": cur, "closed": closed }),
    );
    Ok(closed)
}

/// ① 校验：把所有"先决条件问题"提前查出来（06 §2「提前暴露问题，而不是执行到一半才报错」）。
///
/// **注意分级**：单个软件的问题**不致命**（记为该项的 `precheck_error`，容错实测 V-04 要求
/// 其余软件仍能正常启动）；只有"整个模式无法进行"才返回 `Err`。
fn validate(state: &AppState, mode: &WorkMode) -> anyhow::Result<Vec<AppPlan>> {
    if mode.apps.is_empty() && mode.layout.is_none() {
        anyhow::bail!("该模式既没有软件也没有布局，无法应用");
    }

    let registered = state.apps.list(None, None)?;
    let mut plans = Vec::with_capacity(mode.apps.len());

    for name in &mode.apps {
        let hit = registered
            .iter()
            .find(|a| a.name.eq_ignore_ascii_case(name.trim()));
        match hit {
            None => plans.push(AppPlan {
                name: name.clone(),
                app_id: None,
                // 06 §禁止事项：路径必须来自软件注册表 —— 未注册就是硬错误，且**不回退猜路径**
                precheck_error: Some(format!("软件未注册：{name}（请先在软件库添加）")),
            }),
            Some(app) => {
                let bad = if !crate::app_manager::validate_path(&app.path) {
                    Some(format!("文件不存在或不可启动：{}", app.path))
                } else {
                    None
                };
                plans.push(AppPlan {
                    name: name.clone(),
                    app_id: Some(app.id),
                    precheck_error: bad,
                });
            }
        }
    }

    // 布局可读性也提前查（不可读不致命，但要在开始前就知道）
    if let Some(layout) = &mode.layout {
        if LayoutRepo::new(state.db.clone()).get(layout)?.is_none()
            && crate::window_manager::load_layout(layout).is_err()
        {
            tracing::warn!(layout, "布局既不在数据库也不在 config/layouts，排列阶段将跳过");
        }
    }
    Ok(plans)
}

/// 启动单个软件。**复用阶段2 的 `launch_registered`**（校验/记录/事件全在里面，不另写一套）。
fn launch_one(state: &AppState, plan: &AppPlan) -> SlotResult {
    let Some(app_id) = plan.app_id else {
        return SlotResult {
            app: plan.name.clone(),
            app_id: None,
            status: "failed".into(),
            pid: None,
            reason: plan.precheck_error.clone(),
            retriable: true,
        };
    };

    // 幂等（06 §2）：已在运行 → 跳过启动，直接复用 pid
    if let Some(pid) = state.running.get(app_id) {
        if crate::app_manager::is_alive(pid) {
            return SlotResult {
                app: plan.name.clone(),
                app_id: Some(app_id),
                status: "already_running".into(),
                pid: Some(pid),
                reason: None,
                retriable: false,
            };
        }
        state.running.forget(app_id); // 进程已死，清掉陈旧登记
    }

    match crate::app_manager::launch_registered(state, app_id) {
        Ok(v) => {
            let already = v.get("alreadyRunning").and_then(Value::as_bool).unwrap_or(false);
            SlotResult {
                app: plan.name.clone(),
                app_id: Some(app_id),
                status: if already { "already_running".into() } else { "launched".into() },
                pid: v.get("pid").and_then(Value::as_u64).map(|p| p as u32),
                reason: None,
                retriable: false,
            }
        }
        Err(e) => SlotResult {
            app: plan.name.clone(),
            app_id: Some(app_id),
            status: "failed".into(),
            pid: None,
            reason: Some(e.to_string()),
            retriable: true,
        },
    }
}

/// ③ 等待窗口就绪：轮询直到拿到所有 pid 的 hwnd，或超时（返回已就绪的部分）。
///
/// 06 §技术要点明确：「不要用固定 `sleep(5)` 糊过去」——
/// 慢机器会失败、快机器浪费时间。这里返回 `(appName → hwnd)`，未就绪的不在其中。
///
/// splash 过滤：`find_main_window` 内部按"可见 + 非工具窗口 + 面积最大"取主窗口，
/// 天然跳过小的启动画面。
fn wait_ready(
    state: &AppState,
    session: &ModeSession,
    live: &[(String, u32)],
    cancel: &CancelToken,
) -> Vec<(String, u32, isize)> {
    let deadline = Instant::now() + READY_TIMEOUT;
    let mut ready: Vec<(String, u32, isize)> = Vec::new();

    loop {
        ready.clear();
        for (name, pid) in live {
            if let Some(w) = crate::window_manager::find_main_window(*pid) {
                ready.push((name.clone(), *pid, w.hwnd));
            }
        }
        session.transition(ApplyState::WaitingReady { ready: ready.len(), total: live.len() });
        emit_progress(
            state,
            session,
            &format!("等待窗口就绪（{}/{}）", ready.len(), live.len()),
        );
        if ready.len() >= live.len() || cancel.is_cancelled() || Instant::now() >= deadline {
            break;
        }
        std::thread::sleep(READY_POLL);
    }
    ready
}

/// ④ 排列窗口：布局取自**数据库**（真相），回退 JSON（并回填数据库）。
fn arrange(
    state: &AppState,
    mode: &WorkMode,
    _session: &ModeSession,
) -> anyhow::Result<(usize, Option<String>)> {
    let Some(layout_name) = &mode.layout else {
        return Ok((0, Some("该模式未设置布局".into())));
    };
    let repo = LayoutRepo::new(state.db.clone());

    let layout_json: Value = match repo.get(layout_name)? {
        Some(rec) => json!({
            "name": rec.name,
            "description": rec.description,
            "monitor": rec.monitor,
            "slots": rec.slots,
            // 侧栏配置必须带上 —— 否则"从库路径读布局"会丢掉 AI 侧栏留位
            // （阶段3 验收过的功能在阶段4 路径上的回归，见迁移 0004）
            "aiSidebar": rec.ai_sidebar,
        }),
        None => {
            // JSON 里有、数据库没有 → 回填数据库（此后数据库才是真相）
            let json_path = crate::window_manager::layouts_dir().join(format!("{layout_name}.json"));
            let text = std::fs::read_to_string(&json_path)
                .map_err(|e| anyhow::anyhow!("布局不可读（{}）：{e}", json_path.display()))?;
            let v: Value = serde_json::from_str(&text)?;
            if let Some(slots) = v.get("slots") {
                if let Err(e) = repo.upsert(
                    layout_name,
                    v.get("description").and_then(Value::as_str),
                    slots,
                    v.get("monitor").and_then(Value::as_i64).unwrap_or(0),
                    // 回填时把 JSON 里的 aiSidebar 一并存库，避免二次读时丢失
                    v.get("aiSidebar"),
                    true,
                ) {
                    tracing::warn!(error = %e, "布局回填数据库失败（排列仍继续）");
                }
            }
            v
        }
    };

    let layout: crate::window_manager::Layout = serde_json::from_value(layout_json)
        .map_err(|e| anyhow::anyhow!("布局格式不合法：{e}"))?;
    let outcome = crate::window_manager::apply_layout(state, &layout)?;
    let note = if outcome.skipped > 0 {
        Some(format!(
            "{} 个槽位跳过（软件未运行或无可见窗口）",
            outcome.skipped
        ))
    } else {
        None
    };
    Ok((outcome.placed, note))
}

/// ⑤ 打开文件/目录入口。
fn open_targets(
    state: &AppState,
    session: &ModeSession,
    targets: &[OpenTarget],
    cancel: &CancelToken,
) -> usize {
    let mut opened = 0;
    for (i, t) in targets.iter().enumerate() {
        if cancel.is_cancelled() {
            break;
        }
        match crate::window_manager::open_path(&t.path) {
            Ok(()) => opened += 1,
            Err(e) => {
                let _ = state.bus.publish(
                    MODE_APPLY_FAILED,
                    json!({ "app": t.label, "stage": "open_file", "path": t.path, "reason": e.to_string(), "recoverable": true }),
                );
            }
        }
        session.transition(ApplyState::OpeningFiles { done: i + 1, total: targets.len() });
        emit_progress(
            state,
            session,
            &format!("打开入口 {}/{}", i + 1, targets.len()),
        );
    }
    opened
}

/// 发 `MODE_APPLY_PROGRESS`（06 §2「进度可视」）。
fn emit_progress(state: &AppState, session: &ModeSession, detail: &str) {
    let st = session.state();
    let (step, done, total) = st.progress();
    let _ = state.bus.publish(
        MODE_APPLY_PROGRESS,
        json!({
            "modeId": session.mode_id,
            "modeName": session.mode_name,
            "phase": st.step_name(),
            "step": step,
            "done": done,
            "total": total,
            "detail": detail,
        }),
    );
}
