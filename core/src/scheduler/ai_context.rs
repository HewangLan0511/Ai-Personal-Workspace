//! AI 上下文装配（阶段5 §6）—— **红线 V2 在 core 侧的关口**。
//!
//! 与 `ai/context.py` 的 `assemble()` 形成双重保险：两边都在 mode != workspace 时
//! 提前返回 `None`。任一侧写错，另一侧仍能挡住 —— 这是"隐私红线不能只靠一处判断"的落实。
//!
//! ## 为什么上下文必须由 core 装配，而不是让 sidecar 自己取
//!
//! 数据（当前模式、项目目录、学习目标、档案）全在 core 的 SQLite 里。
//! 若让 sidecar 自己调 `/internal/db/*` 取，则"哪些数据可以给 AI"的判断
//! 会散落在 Python 侧，且咨询模式是否真的没读数据变得难以审计。
//! 集中在这里 ⇒ **只有一个函数需要被审查**。
//!
//! ## 返回 None 的含义
//!
//! `None` = "本次请求不应携带任何用户数据"。consult 模式恒为 None。
//! **不要**把它当成错误 —— 它是正常且预期的返回值。

use std::collections::HashMap;

use serde_json::{json, Value};

use crate::state::AppState;

/// 上下文来源开关（08 §6：提供开关让用户控制哪些上下文参与）。
pub const SCOPE_MODE: &str = "mode";
pub const SCOPE_APPS: &str = "apps";
pub const SCOPE_PROJECT: &str = "project";
pub const SCOPE_LEARNING: &str = "learning";
pub const SCOPE_PROFILE: &str = "profile";

pub const MODE_WORKSPACE: &str = "workspace";

/// **红线 V2 的判据本体**（抽成纯函数，便于机器断言）。
///
/// 只有它返回 true，`build()` 才会去读任何数据。
/// 测试直接打这个函数 —— 而不是"跑一遍 build 看看"，因为后者需要一个完整
/// 的 AppState（含数据库），会让这个最关键的断言变成"重到没人愿意跑"。
#[inline]
pub fn is_data_allowed(mode: &str) -> bool {
    mode == MODE_WORKSPACE
}

/// 装配 AI 上下文。
///
/// **第一行就是红线 V2**：非 workspace 模式直接返回 `None`，不触碰任何数据源。
pub fn build(
    state: &AppState,
    mode: &str,
    enabled: &HashMap<String, bool>,
) -> Option<Value> {
    // ← 红线 V2：consult（及任何非 workspace 的取值）一律不给数据。
    //    此处**故意不读取** state 的任何字段，从结构上保证"够不着"。
    if !is_data_allowed(mode) {
        return None;
    }

    let on = |key: &str| enabled.get(key).copied().unwrap_or(true);

    let mut ctx = serde_json::Map::new();

    // ---- 当前模式 + 该模式包含的软件 ----
    if on(SCOPE_MODE) {
        if let Some(name) = current_mode_name(state) {
            ctx.insert("modeName".into(), json!(name));
            if on(SCOPE_APPS) {
                if let Some(apps) = mode_apps(state, &name) {
                    ctx.insert("modeApps".into(), json!(apps));
                }
            }
        }
    }

    // ---- 项目目录（当前模式 openTargets 里的第一个目录）----
    if on(SCOPE_PROJECT) {
        if let Some(dir) = current_project_dir(state) {
            ctx.insert("projectDir".into(), json!(dir));
        }
    }

    // ---- 学习目标（阶段6 起读**真实表**）----
    //
    // 阶段5 这里读的是 `config` 的 `ai.context.learning_goal` —— 而那个键
    // **从未登记进 `KEYS`**，`set` 一律被拒、`get` 恒回 Null：
    // 也就是说"学习状态"这一路上下文实际**从未注入过**（典型的"文件里有代码 ≠ 功能存在"）。
    // 阶段6 有了 `learning_goals` 表，改为直接读表 —— 这条 scope 才算真正接线。
    if on(SCOPE_LEARNING) {
        if let Some(goal) = current_learning_goal(state) {
            ctx.insert("learningGoal".into(), json!(goal));
        }
    }

    // ---- 技能背景（读 `profile_skills` 表；阶段7 才有 UI 写入）----
    if on(SCOPE_PROFILE) {
        let skills = confirmed_skills(state);
        if !skills.is_empty() {
            ctx.insert("profileSkills".into(), json!(skills));
        }
    }

    if ctx.is_empty() {
        None
    } else {
        Some(Value::Object(ctx))
    }
}

/// 当前模式名（来自 config `mode.current`，由阶段4 的 runner 维护）。
fn current_mode_name(state: &AppState) -> Option<String> {
    let v = state.config.get("mode.current");
    let s = v.as_str()?.trim();
    if s.is_empty() {
        None
    } else {
        Some(s.to_string())
    }
}

/// 该模式包含的软件名列表。
fn mode_apps(state: &AppState, mode_name: &str) -> Option<Vec<String>> {
    let repo = crate::scheduler::ModeRepo::new(state.db.clone());
    let mode = repo.get_by_name(mode_name).ok()??;
    let apps = mode.apps;
    if apps.is_empty() {
        None
    } else {
        Some(apps)
    }
}

/// 当前进行中的学习目标（阶段6）。
///
/// 取"学习中"优先，其次"未开始"；带上进度，让 AI 的建议能对上用户实际处境。
/// `paused` / `done` / `archived` 不参与 —— 用户已经表明不需要推进它。
fn current_learning_goal(state: &AppState) -> Option<String> {
    let repo = crate::learning::LearningRepo::new(state.db.clone());
    let goals = repo.goals_list().ok()?;
    let g = goals
        .iter()
        .find(|g| g.status == "learning")
        .or_else(|| goals.iter().find(|g| g.status == "not_started"))?;
    Some(if g.progress.total > 0 {
        format!("{}（已完成 {}/{} 个阶段）", g.title, g.progress.done, g.progress.total)
    } else {
        g.title.clone()
    })
}

/// 已确认的技能（`profile_skills`，阶段7 起有 UI 写入）。
///
/// 只取 `confirmed = 1`：未确认的是 AI 建议，不得当作"用户的技能"喂给模型
/// （10 §2：`confirmed = 0` 需用户点确认才生效）。
fn confirmed_skills(state: &AppState) -> Vec<String> {
    let rows = match state.db.query_json(
        // 注意：`profile_skills` 没有 `deleted_at` 列（0001 建表，档案阶段不做软删）——
        // 这里若照抄其它表加 `deleted_at IS NULL`，SQL 会因"无此列"直接报错，
        // 而错误被下面的 `Err` 分支吞掉 ⇒ **功能静默失效**。别顺手加。
        "SELECT name FROM profile_skills WHERE confirmed = 1 ORDER BY level DESC, name ASC LIMIT 8",
        &[],
    ) {
        Ok(rows) => rows,
        // 档案表尚不存在（旧库）也不该让上下文装配失败 —— 少一项而已
        Err(_) => return Vec::new(),
    };
    rows.iter()
        .filter_map(|v| v.get("name").and_then(Value::as_str).map(str::to_string))
        .collect()
}

/// 当前项目目录：优先取**当前模式绑定的项目**目录（阶段6 §6 联动），
/// 其次回退到模式 `openTargets` 里第一个 `folder`。
fn current_project_dir(state: &AppState) -> Option<String> {
    if let Some(name) = current_mode_name(state) {
        let repo = crate::project::ProjectRepo::new(state.db.clone());
        if let Ok(Some(p)) = repo.by_mode(&name) {
            if let Some(dir) = p.directory.filter(|d| !d.trim().is_empty()) {
                return Some(dir);
            }
        }
    }

    let name = current_mode_name(state)?;
    let repo = crate::scheduler::ModeRepo::new(state.db.clone());
    let mode = repo.get_by_name(&name).ok()??;

    for target in &mode.open_targets {
        let is_folder = match target.kind.as_deref() {
            Some("folder") => true,
            // `type` 缺省时视为目录（契约 3.2.1 的 folder/file；缺省按目录更符合"项目入口"语义）
            None | Some("") => true,
            Some(_) => false,
        };
        if is_folder && !target.path.is_empty() {
            return Some(target.path.clone());
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    /// **红线 V2 的机器断言**：只有 workspace 才允许读取用户数据。
    ///
    /// 这里覆盖了"任何非 workspace 取值"而不只是 "consult" ——
    /// 因为未来可能有第三个模式，若判据写成 `mode != "consult"` 就会漏。
    #[test]
    fn only_workspace_mode_is_data_allowed() {
        assert!(is_data_allowed(MODE_WORKSPACE));
        assert!(!is_data_allowed("consult"));
        assert!(!is_data_allowed(""));
        assert!(!is_data_allowed("CONSULT"));    // 大小写不同即不等（不模糊匹配）
        assert!(!is_data_allowed("workspace ")); // 带空格也不等（不做 trim 宽容）
        assert!(!is_data_allowed("admin"));      // 未知模式一律拒绝（默认安全）
    }

    #[test]
    fn scope_constants_match_python_side() {
        // 与 ai/context.py 的 SCOPES 必须一致 —— 两侧不一致会导致
        // "UI 说开了但实际没开"（08 §5 权限提示失真）
        let expected = ["mode", "apps", "project", "learning", "profile"];
        let actual = [
            SCOPE_MODE,
            SCOPE_APPS,
            SCOPE_PROJECT,
            SCOPE_LEARNING,
            SCOPE_PROFILE,
        ];
        assert_eq!(expected, actual);
    }
}
