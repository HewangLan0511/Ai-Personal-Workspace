//! 个人数字档案模块（阶段7 · `10-阶段指令-个人档案.md`）。
//!
//! **定位一句话**：记录"我是谁，我正在成为谁。"
//!
//! ## 核心流程的代码结构（10 §核心流程，不可绕过）
//!
//! ```text
//! 系统发现变化（采集器 collect_*）
//!     ↓
//! AI/规则生成建议（写 pending_suggestions，status='pending'）   ← 唯一的自动写路径
//!     ↓
//! ★ 用户确认 ★（suggestion_confirm，只能由用户动作触发）
//!     ↓
//! 写入档案四表 + 发布 PROFILE_UPDATED
//! ```
//!
//! ## 红线边界
//!
//! - **V3**：采集器永远不写档案四表（表级 + 函数级双重边界，见 `repository` 模块注释）；
//! - **V2**：档案数据进 AI 上下文的唯一通道是 `ai_context.rs` 的 `profile` scope，
//!   而 `is_data_allowed()` 只放行 workspace 模式 —— 咨询模式问"我的技能"拿不到答案；
//! - 导出只含 confirmed=1 的内容（`export.rs`）。

mod export;
mod repository;

pub use export::build_markdown;
pub use repository::{
    BasicInput, PendingSuggestion, ProfileBasic, ProfileProjectEntry, ProfileRepo, ProfileSkill,
    ProjectEntryInput, SkillInput, SkillPatch, SuggestionInput, TimelineEvent, TimelineInput,
};

use serde_json::{json, Value};

use crate::event_bus::PROFILE_UPDATED;
use crate::state::AppState;

/// 永久拒绝的建议类型清单（config 键，string 存 JSON 数组 —— 与 `ui.ai.*` 同构）。
pub const REJECTED_KINDS_KEY: &str = "profile.rejected_kinds";

/// 高频软件判定阈值（10 §5 触发点：某软件使用频率长期极高）。
/// 用启动次数近似"长期极高"：>= 20 次才建议，避免正常使用的软件刷屏。
pub const HOT_APP_THRESHOLD: i64 = 20;

// ================================================================ 事件辅助

fn publish_update(state: &AppState, changed: &str) {
    let _ = state.bus.publish(PROFILE_UPDATED, json!({ "changed": changed }));
}

// ================================================================ 拒绝清单

/// 当前被永久拒绝的建议类型。
pub fn rejected_kinds(state: &AppState) -> Vec<String> {
    match state.config.get(REJECTED_KINDS_KEY) {
        Value::String(raw) => serde_json::from_str(&raw).unwrap_or_default(),
        Value::Array(a) => a
            .iter()
            .filter_map(|v| v.as_str().map(str::to_string))
            .collect(),
        _ => Vec::new(),
    }
}

fn is_kind_rejected(state: &AppState, kind: &str) -> bool {
    rejected_kinds(state).iter().any(|k| k == kind)
}

/// 永久拒绝某类建议：记入拒绝清单 + 清掉该类 pending（10 §5 用户权利之四）。
/// 顺序有讲究：**先写拒绝清单，再清 pending** —— 若第二步失败，代价只是
/// "旧的 pending 还挂着"（用户手动忽略即可）；反过来（先清后写）失败时
/// 该类建议会"看起来被拒绝了但清单里没有"，下次又会静默入队。
pub fn apply_reject_kind(state: &AppState, kind: &str) -> anyhow::Result<u64> {
    let mut kinds = rejected_kinds(state);
    if !kinds.iter().any(|k| k == kind) {
        kinds.push(kind.to_string());
    }
    state.config.set(
        REJECTED_KINDS_KEY,
        Value::String(serde_json::to_string(&kinds)?),
    )?;
    let repo = ProfileRepo::new(state.db.clone());
    let n = repo.suggestions_ignore_kind(kind)?;
    Ok(n)
}

/// 采集器的统一闸门：被永久拒绝的类型不入队。
fn enqueue(state: &AppState, input: &SuggestionInput) -> anyhow::Result<Option<PendingSuggestion>> {
    if is_kind_rejected(state, &input.kind) {
        return Ok(None);
    }
    ProfileRepo::new(state.db.clone()).suggestion_add(input)
}

// ================================================================ 采集器（系统"发现变化"）

/// 触发点 1：学习目标完成 → 建议加入时间线（10 §5 表）。
/// 由 `learning::apply_goal_update` 在状态变为 done 时调用。
pub fn collect_goal_done(state: &AppState, goal_id: i64, title: &str, description: Option<&str>) {
    let input = SuggestionInput {
        kind: "timeline".into(),
        ref_key: format!("goal_done:{goal_id}"),
        title: format!("学习目标「{title}」已完成，记录到成长时间线？"),
        payload: json!({
            "eventDate": today(),
            "title": format!("完成学习目标：{title}"),
            "description": description,
            "type": "learning",
        }),
    };
    if let Err(e) = enqueue(state, &input) {
        tracing::warn!(goal_id, error = %e, "学习目标完成的档案建议入队失败");
    }
}

/// 触发点 2：项目状态变为 done → 建议加入项目经历 + 时间线（10 §5 表；验收项 6）。
/// 由 `project::apply_update` 在状态变为 done 时调用。
pub fn collect_project_done(state: &AppState, project_id: i64, name: &str, end_date: Option<&str>) {
    let repo = ProfileRepo::new(state.db.clone());
    // 已经在档案里的项目不再建议（用户同步过一次就够了）
    let exists = match repo.project_entry_exists(name) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!(project_id, error = %e, "档案项目经历查重失败");
            false
        }
    };
    if !exists {
        let input = SuggestionInput {
            kind: "project".into(),
            ref_key: format!("project_done:{project_id}"),
            title: format!("项目「{name}」已完成，加入档案的项目经历？"),
            payload: json!({
                "name": name,
                "status": "done",
                "endDate": end_date,
            }),
        };
        if let Err(e) = enqueue(state, &input) {
            tracing::warn!(project_id, error = %e, "项目完成的档案建议入队失败");
        }
    }

    let tl = SuggestionInput {
        kind: "timeline".into(),
        ref_key: format!("project_done_tl:{project_id}"),
        title: format!("项目「{name}」已完成，记录到成长时间线？"),
        payload: json!({
            "eventDate": end_date.filter(|s| !s.trim().is_empty()).map(str::to_string).unwrap_or_else(today),
            "title": format!("完成项目：{name}"),
            "description": Value::Null,
            "type": "project",
        }),
    };
    if let Err(e) = enqueue(state, &tl) {
        tracing::warn!(project_id, error = %e, "项目完成的时间线建议入队失败");
    }
}

/// 触发点 3：新增项目（含目录）→ 建议添加为档案项目经历（10 §5 表）。
/// 由 `project::apply_add` 调用。进行中的项目也建议 —— 档案的"项目经历"
/// 本就允许记录 ongoing 条目（profile_projects.status 有 ongoing|paused|done）。
pub fn collect_project_created(state: &AppState, project_id: i64, name: &str, start_date: Option<&str>) {
    let repo = ProfileRepo::new(state.db.clone());
    let exists = match repo.project_entry_exists(name) {
        Ok(v) => v,
        Err(e) => {
            tracing::warn!(project_id, error = %e, "档案项目经历查重失败");
            false
        }
    };
    if exists {
        return;
    }
    let input = SuggestionInput {
        kind: "project".into(),
        ref_key: format!("project_new:{project_id}"),
        title: format!("把项目「{name}」加入档案的项目经历？"),
        payload: json!({
            "name": name,
            "status": "ongoing",
            "startDate": start_date,
        }),
    };
    if let Err(e) = enqueue(state, &input) {
        tracing::warn!(project_id, error = %e, "新增项目的档案建议入队失败");
    }
}

/// 触发点 4：高频软件 → 建议加入技能（10 §5 表）。
/// **扫描式**采集：由 `profile_suggestions_scan` 显式触发（验收可复现），
/// 不做后台轮询 —— 软件启动计数本来就不是实时数据，没必要空转。
pub fn scan_app_usage(state: &AppState) -> anyhow::Result<usize> {
    let repo = ProfileRepo::new(state.db.clone());
    let rows = state.db.query_json(
        "SELECT name, launch_count FROM apps \
         WHERE deleted_at IS NULL AND launch_count >= ? \
         ORDER BY launch_count DESC",
        &[Value::from(HOT_APP_THRESHOLD)],
    )?;
    let mut added = 0;
    for row in rows {
        let Some(name) = row.get("name").and_then(Value::as_str) else {
            continue;
        };
        let count = row.get("launch_count").and_then(Value::as_i64).unwrap_or(0);
        // 已是技能（不管 confirmed 与否）就不再建议 —— 同名建议没有第二次意义
        if repo.skill_exists(name)? {
            continue;
        }
        // 等级与启动次数挂钩但有上限：确定性规则，验收可复现
        let level = (count * 2).min(90);
        let sug = SuggestionInput {
            kind: "skill".into(),
            ref_key: format!("app_hot:{name}"),
            title: format!("「{name}」已被高频使用（启动 {count} 次），加入技能（等级 {level}）？"),
            payload: json!({ "name": name, "level": level, "category": "tool" }),
        };
        if enqueue(state, &sug)?.is_some() {
            added += 1;
        }
    }
    Ok(added)
}

/// 今天的本地日期（YYYY-MM-DD）。采集器的时间戳来源，收敛在一处便于测。
fn today() -> String {
    chrono::Local::now().format("%Y-%m-%d").to_string()
}

// ================================================================ 写入口（用户动作，发事件）

/// 双通道同源约定（02 §2.2）：以下 apply_* 是 HTTP 与 Tauri command 的**共同落点**，
/// 写库 + 发事件都在这里，避免"有一边忘了发"。

pub fn apply_basic_save(state: &AppState, input: &BasicInput) -> anyhow::Result<ProfileBasic> {
    let basic = ProfileRepo::new(state.db.clone()).basic_save(input)?;
    publish_update(state, "basic");
    Ok(basic)
}

pub fn apply_skill_add(state: &AppState, input: &SkillInput) -> anyhow::Result<ProfileSkill> {
    let skill = ProfileRepo::new(state.db.clone()).skill_add(input)?;
    publish_update(state, "skill");
    Ok(skill)
}

pub fn apply_skill_update(state: &AppState, id: i64, patch: &SkillPatch) -> anyhow::Result<ProfileSkill> {
    let skill = ProfileRepo::new(state.db.clone()).skill_update(id, patch)?;
    publish_update(state, "skill");
    Ok(skill)
}

pub fn apply_skill_remove(state: &AppState, id: i64) -> anyhow::Result<()> {
    ProfileRepo::new(state.db.clone()).skill_remove(id)?;
    publish_update(state, "skill");
    Ok(())
}

pub fn apply_skill_confirm(state: &AppState, id: i64) -> anyhow::Result<ProfileSkill> {
    let skill = ProfileRepo::new(state.db.clone()).skill_confirm(id)?;
    publish_update(state, "skill");
    Ok(skill)
}

pub fn apply_project_entry_add(
    state: &AppState,
    input: &ProjectEntryInput,
) -> anyhow::Result<ProfileProjectEntry> {
    let entry = ProfileRepo::new(state.db.clone()).project_entry_add(input)?;
    publish_update(state, "project");
    Ok(entry)
}

pub fn apply_project_entry_remove(state: &AppState, id: i64) -> anyhow::Result<()> {
    ProfileRepo::new(state.db.clone()).project_entry_remove(id)?;
    publish_update(state, "project");
    Ok(())
}

pub fn apply_project_entry_confirm(state: &AppState, id: i64) -> anyhow::Result<ProfileProjectEntry> {
    let entry = ProfileRepo::new(state.db.clone()).project_entry_confirm(id)?;
    publish_update(state, "project");
    Ok(entry)
}

pub fn apply_timeline_add(state: &AppState, input: &TimelineInput) -> anyhow::Result<TimelineEvent> {
    let event = ProfileRepo::new(state.db.clone()).timeline_add(input)?;
    publish_update(state, "timeline");
    Ok(event)
}

pub fn apply_timeline_remove(state: &AppState, id: i64) -> anyhow::Result<()> {
    ProfileRepo::new(state.db.clone()).timeline_remove(id)?;
    publish_update(state, "timeline");
    Ok(())
}

pub fn apply_timeline_confirm(state: &AppState, id: i64) -> anyhow::Result<TimelineEvent> {
    let event = ProfileRepo::new(state.db.clone()).timeline_confirm(id)?;
    publish_update(state, "timeline");
    Ok(event)
}

/// 确认单条建议（**建议 → 档案的唯一通路**，必须由用户动作触发）。
pub fn apply_suggestion_confirm(state: &AppState, id: i64) -> anyhow::Result<PendingSuggestion> {
    let sug = ProfileRepo::new(state.db.clone()).suggestion_confirm(id)?;
    publish_update(state, &sug.kind);
    Ok(sug)
}

/// 批量确认。逐条走同一通路；一条失败即停（已确认的不回滚 —— 档案写入是幂等安全的插入，
/// 重复执行同一批不会产生重复行：建议状态机保证 second confirm 会报"已处理"）。
pub fn apply_suggestion_batch_confirm(state: &AppState, ids: &[i64]) -> anyhow::Result<usize> {
    let repo = ProfileRepo::new(state.db.clone());
    let mut n = 0;
    for id in ids {
        repo.suggestion_confirm(*id)?;
        n += 1;
    }
    publish_update(state, "batch");
    Ok(n)
}

pub fn apply_suggestion_ignore(state: &AppState, id: i64) -> anyhow::Result<()> {
    ProfileRepo::new(state.db.clone()).suggestion_ignore(id)?;
    publish_update(state, "suggestion");
    Ok(())
}

/// 导出 Markdown（只含 confirmed 内容 —— 见 export.rs 模块注释）。
pub fn export_markdown(state: &AppState) -> anyhow::Result<String> {
    let repo = ProfileRepo::new(state.db.clone());
    let basic = repo.basic_get()?;
    let skills = repo.skills_list(true)?;
    let projects = repo.projects_list(true)?;
    let timeline = repo.timeline_list(true)?;
    if basic.name.is_empty()
        && basic.motto.is_empty()
        && skills.is_empty()
        && projects.is_empty()
        && timeline.is_empty()
    {
        anyhow::bail!("档案还是空的，先填写基础信息或添加技能再导出");
    }
    Ok(build_markdown(&basic, &skills, &projects, &timeline))
}

/// 档案页一次拉全（减少前端 5 连发的往返；字段与各 list 接口同构）。
pub fn overview(state: &AppState) -> anyhow::Result<Value> {
    let repo = ProfileRepo::new(state.db.clone());
    Ok(json!({
        "basic": repo.basic_get()?,
        "skills": repo.skills_list(false)?,
        "projects": repo.projects_list(false)?,
        "timeline": repo.timeline_list(false)?,
        "suggestions": repo.suggestions_list(Some("pending"))?,
        "pendingCount": repo.pending_count()?,
        "rejectedKinds": rejected_kinds(state),
    }))
}
