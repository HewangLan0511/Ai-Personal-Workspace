//! 项目管理的数据层（阶段6 §6「项目管理（同章节交付）」）。
//!
//! 与 `profile_projects`（阶段7 个人档案的"项目经历"）**是两个实体**：
//! - 本表 = **正在做/要做的事**（有目录、可绑定工作模式、可挂学习目标）；
//! - `profile_projects` = 档案里的经历条目（阶段7 从本表**同步**，且必须用户确认）。
//!
//! 联动点（09 §6 要求"优先做"）：
//! - `mode_name` —— 绑定的工作模式；进入该模式时 UI 侧栏/看板显示当前项目；
//! - `goal_id`   —— 关联的学习目标。
//!
//! ⚠️ 项目状态变为 `done` 时**不会**自动把关联目标标记完成 —— 那是"系统改学习进度"，
//! 属红线 V3。返回值里的 `linkedGoalDone` 只是给 UI 一个**提议**，采纳仍由用户点击。

use anyhow::Context;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::db::Db;

/// 项目状态（09 §6：起止时间 + 状态）。
pub const PROJECT_STATUSES: &[&str] = &["ongoing", "paused", "done"];

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: i64,
    pub name: String,
    pub role: Option<String>,
    pub summary: Option<String>,
    #[serde(rename = "techStack")]
    pub tech_stack: Vec<String>,
    #[serde(rename = "startDate")]
    pub start_date: Option<String>,
    #[serde(rename = "endDate")]
    pub end_date: Option<String>,
    /// `ongoing|paused|done`
    pub status: String,
    /// 关联目录（项目根）
    pub directory: Option<String>,
    /// 绑定的工作模式名（可空）
    #[serde(rename = "modeName")]
    pub mode_name: Option<String>,
    /// 关联的学习目标 id（可空）
    #[serde(rename = "goalId")]
    pub goal_id: Option<i64>,
    /// 关联目标的标题（读时联表带出，便于 UI 直接展示而不必再请求一次）
    #[serde(rename = "goalTitle")]
    pub goal_title: Option<String>,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ProjectInput {
    pub name: String,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default, rename = "techStack")]
    pub tech_stack: Vec<String>,
    #[serde(default, rename = "startDate")]
    pub start_date: Option<String>,
    #[serde(default, rename = "endDate")]
    pub end_date: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub directory: Option<String>,
    #[serde(default, rename = "modeName")]
    pub mode_name: Option<String>,
    #[serde(default, rename = "goalId")]
    pub goal_id: Option<i64>,
}

/// 编辑入参：只覆盖显式给出的字段。
///
/// 关联字段（`modeName` / `goalId`）用 `Option<Option<_>>` —— 需要区分
/// "没传"（保持原样）与"传了 null"（解除绑定），否则用户没法解绑。
#[derive(Debug, Clone, Default, Deserialize)]
pub struct ProjectPatch {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub summary: Option<String>,
    #[serde(default, rename = "techStack")]
    pub tech_stack: Option<Vec<String>>,
    #[serde(default, rename = "startDate")]
    pub start_date: Option<String>,
    #[serde(default, rename = "endDate")]
    pub end_date: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub directory: Option<String>,
    #[serde(default, rename = "modeName")]
    pub mode_name: Option<Option<String>>,
    #[serde(default, rename = "goalId")]
    pub goal_id: Option<Option<i64>>,
}

/// 写入结果：项目本体 + "目标也可以标记完成"的提议（**不自动执行**）。
#[derive(Debug, Clone, Serialize)]
pub struct ProjectWrite {
    #[serde(flatten)]
    pub project: Project,
    /// 项目刚进入 `done` 且挂着未完成的学习目标时为 true —— 由 UI 询问用户是否一并完成
    #[serde(rename = "linkedGoalDone")]
    pub linked_goal_done: bool,
}

#[derive(Clone)]
pub struct ProjectRepo {
    db: Db,
}

impl ProjectRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// 项目列表（可按状态 / 绑定模式过滤）。
    pub fn list(&self, status: Option<&str>, mode_name: Option<&str>) -> anyhow::Result<Vec<Project>> {
        let mut sql = String::from(
            "SELECT p.id, p.name, p.role, p.summary, p.tech_stack, p.start_date, p.end_date, \
                    p.status, p.directory, p.mode_name, p.goal_id, p.created_at, p.updated_at, \
                    g.title AS goal_title \
             FROM projects p LEFT JOIN learning_goals g \
               ON g.id = p.goal_id AND g.deleted_at IS NULL \
             WHERE p.deleted_at IS NULL",
        );
        let mut params: Vec<Value> = Vec::new();
        if let Some(s) = status.filter(|s| !s.trim().is_empty()) {
            params.push(Value::from(s.trim()));
            sql.push_str(&format!(" AND p.status = ?{}", params.len()));
        }
        if let Some(m) = mode_name.filter(|m| !m.trim().is_empty()) {
            params.push(Value::from(m.trim()));
            sql.push_str(&format!(" AND p.mode_name = ?{}", params.len()));
        }
        // 进行中优先，再按更新时间倒序：用户最关心"手头这个"
        sql.push_str(
            " ORDER BY CASE p.status WHEN 'ongoing' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, \
              p.updated_at DESC, p.id DESC",
        );
        let rows = self.db.query_json(&sql, &params)?;
        Ok(rows.iter().map(to_project).collect())
    }

    pub fn get(&self, id: i64) -> anyhow::Result<Option<Project>> {
        let rows = self.db.query_json(
            "SELECT p.id, p.name, p.role, p.summary, p.tech_stack, p.start_date, p.end_date, \
                    p.status, p.directory, p.mode_name, p.goal_id, p.created_at, p.updated_at, \
                    g.title AS goal_title \
             FROM projects p LEFT JOIN learning_goals g \
               ON g.id = p.goal_id AND g.deleted_at IS NULL \
             WHERE p.id = ? AND p.deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_project))
    }

    /// 某工作模式绑定的项目（09 §6 联动的查询入口；优先"未完成"，否则回退到最新一个）。
    pub fn by_mode(&self, mode_name: &str) -> anyhow::Result<Option<Project>> {
        let all = self.list(None, Some(mode_name))?;
        if let Some(p) = all.iter().find(|p| p.status != "done") {
            return Ok(Some(p.clone()));
        }
        Ok(all.into_iter().next())
    }

    pub fn add(&self, input: &ProjectInput) -> anyhow::Result<ProjectWrite> {
        let name = input.name.trim();
        if name.is_empty() {
            anyhow::bail!("项目名称不能为空");
        }
        let status = normalize(input.status.as_deref())?;
        let mode = self.check_mode(input.mode_name.as_deref())?;
        self.check_goal(input.goal_id)?;
        let id = self.db.insert(
            "INSERT INTO projects \
             (name, role, summary, tech_stack, start_date, end_date, status, directory, mode_name, goal_id, \
              created_at, updated_at) \
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10, datetime('now','localtime'), datetime('now','localtime'))",
            &[
                Value::from(name),
                opt(&input.role),
                opt(&input.summary),
                serde_json::to_value(&input.tech_stack)?,
                opt(&input.start_date),
                opt(&input.end_date),
                Value::from(status),
                opt(&input.directory),
                opt(&mode),
                input.goal_id.map(Value::from).unwrap_or(Value::Null),
            ],
        )?;
        let p = self.get(id)?.context("创建后应能读到项目")?;
        Ok(ProjectWrite { linked_goal_done: false, project: p })
    }

    pub fn update(&self, id: i64, patch: &ProjectPatch) -> anyhow::Result<ProjectWrite> {
        let cur = self
            .get(id)?
            .with_context(|| format!("项目不存在：id={id}"))?;
        let status = match patch.status.as_deref() {
            Some(s) => normalize(Some(s))?,
            None => cur.status.clone(),
        };
        // 关联字段：None = 没传（保持），Some(None) = 显式解绑
        let mode = match &patch.mode_name {
            None => cur.mode_name.clone(),
            Some(m) => self.check_mode(m.as_deref())?,
        };
        let goal_id = match &patch.goal_id {
            None => cur.goal_id,
            Some(g) => {
                self.check_goal(*g)?;
                *g
            }
        };
        let tech = match &patch.tech_stack {
            Some(t) => serde_json::to_value(t)?,
            None => serde_json::to_value(&cur.tech_stack)?,
        };
        self.db.exec(
            "UPDATE projects SET name=?1, role=?2, summary=?3, tech_stack=?4, start_date=?5, \
             end_date=?6, status=?7, directory=?8, mode_name=?9, goal_id=?10, \
             updated_at=datetime('now','localtime') WHERE id=?11 AND deleted_at IS NULL",
            &[
                Value::from(patch.name.clone().unwrap_or(cur.name).trim().to_string()),
                opt(&patch.role.clone().or(cur.role)),
                opt(&patch.summary.clone().or(cur.summary)),
                tech,
                opt(&patch.start_date.clone().or(cur.start_date)),
                opt(&patch.end_date.clone().or(cur.end_date)),
                Value::from(status.clone()),
                opt(&patch.directory.clone().or(cur.directory)),
                opt(&mode),
                goal_id.map(Value::from).unwrap_or(Value::Null),
                Value::from(id),
            ],
        )?;
        let p = self.get(id)?.context("更新后应能读到项目")?;
        // 项目刚完成且挂着目标 ⇒ 提议（不是执行）—— 红线 V3 的边界在这里
        let linked_goal_done = status == "done"
            && cur.status != "done"
            && p.goal_id.is_some()
            && p.goal_title.is_some();
        Ok(ProjectWrite { project: p, linked_goal_done })
    }

    pub fn soft_delete(&self, id: i64) -> anyhow::Result<()> {
        let n = self.db.exec(
            "UPDATE projects SET deleted_at=datetime('now','localtime'), \
             updated_at=datetime('now','localtime') WHERE id=?1 AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        if n == 0 {
            anyhow::bail!("项目不存在或已删除：id={id}");
        }
        Ok(())
    }

    // ------------------------------------------------------------ 内部

    /// 校验绑定的工作模式存在（避免悬空绑定：进入该模式时永远找不到项目）。
    fn check_mode(&self, mode: Option<&str>) -> anyhow::Result<Option<String>> {
        let Some(m) = mode.map(str::trim).filter(|s| !s.is_empty()) else {
            return Ok(None);
        };
        let exists = self
            .db
            .query_json(
                "SELECT id FROM work_modes WHERE name = ? AND deleted_at IS NULL",
                &[Value::from(m)],
            )?
            .into_iter()
            .next()
            .is_some();
        if !exists {
            anyhow::bail!("绑定的工作模式不存在：{m}（请先在「工作模式」里创建）");
        }
        Ok(Some(m.to_string()))
    }

    fn check_goal(&self, goal_id: Option<i64>) -> anyhow::Result<()> {
        let Some(id) = goal_id else { return Ok(()) };
        let exists = self
            .db
            .query_json(
                "SELECT id FROM learning_goals WHERE id = ? AND deleted_at IS NULL",
                &[Value::from(id)],
            )?
            .into_iter()
            .next()
            .is_some();
        if !exists {
            anyhow::bail!("关联的学习目标不存在：id={id}");
        }
        Ok(())
    }
}

// ================================================================ 写入口（阶段7 联动）

// 双通道同源约定（02 §2.2）：HTTP 与 Tauri command 的项目写入都走这里的 apply_*，
// 写库 + 档案采集触发集中在同一处，避免"有一边忘了触发"。

/// 创建项目 + 档案采集（阶段7 §5 触发点 3：新增项目 → 建议加入项目经历）。
/// 已完成状态直接建的项目走"完成"触发点而非"新增"。
pub fn apply_add(
    state: &crate::state::AppState,
    input: &ProjectInput,
) -> anyhow::Result<ProjectWrite> {
    let w = ProjectRepo::new(state.db.clone()).add(input)?;
    if w.project.status == "done" {
        crate::profile::collect_project_done(
            state,
            w.project.id,
            &w.project.name,
            w.project.end_date.as_deref(),
        );
    } else {
        crate::profile::collect_project_created(
            state,
            w.project.id,
            &w.project.name,
            w.project.start_date.as_deref(),
        );
    }
    Ok(w)
}

/// 更新项目 + 档案采集（阶段7 §5 触发点 2：状态变为 done → 建议加入项目经历 + 时间线）。
/// 只在 ongoing/paused → done 的**转变沿**触发；反复改 done 项目不重复建议（去重键兜底）。
pub fn apply_update(
    state: &crate::state::AppState,
    id: i64,
    patch: &ProjectPatch,
) -> anyhow::Result<ProjectWrite> {
    let repo = ProjectRepo::new(state.db.clone());
    let before = repo.get(id)?;
    let w = repo.update(id, patch)?;
    if w.project.status == "done" && before.as_ref().map(|p| p.status.as_str()) != Some("done") {
        crate::profile::collect_project_done(
            state,
            w.project.id,
            &w.project.name,
            w.project.end_date.as_deref(),
        );
    }
    Ok(w)
}

// ---------------------------------------------------------------- helpers

fn normalize(v: Option<&str>) -> anyhow::Result<String> {
    match v.map(str::trim) {
        None | Some("") => Ok("ongoing".into()),
        Some(s) if PROJECT_STATUSES.contains(&s) => Ok(s.to_string()),
        Some(s) => anyhow::bail!("非法的项目状态：{s}（可选 {PROJECT_STATUSES:?}）"),
    }
}

fn opt(v: &Option<String>) -> Value {
    match v {
        Some(s) if !s.trim().is_empty() => Value::from(s.trim()),
        _ => Value::Null,
    }
}

fn json_field(v: Option<&Value>) -> Value {
    match v {
        Some(Value::String(s)) => serde_json::from_str(s).unwrap_or(Value::Null),
        Some(other) => other.clone(),
        None => Value::Null,
    }
}

fn to_project(v: &Value) -> Project {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let tech = json_field(v.get("tech_stack"));
    Project {
        id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
        name: s("name").unwrap_or_default(),
        role: s("role"),
        summary: s("summary"),
        tech_stack: tech
            .as_array()
            .map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
            .unwrap_or_default(),
        start_date: s("start_date"),
        end_date: s("end_date"),
        status: s("status").unwrap_or_else(|| "ongoing".into()),
        directory: s("directory"),
        mode_name: s("mode_name"),
        goal_id: v.get("goal_id").and_then(Value::as_i64),
        goal_title: s("goal_title"),
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::learning::{GoalInput, LearningRepo};

    fn repo() -> (ProjectRepo, LearningRepo, std::path::PathBuf) {
        let dir = std::env::temp_dir().join(format!(
            "pw-project-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        (ProjectRepo::new(db.clone()), LearningRepo::new(db), dir)
    }

    fn input(name: &str) -> ProjectInput {
        ProjectInput {
            name: name.into(),
            role: Some("负责人".into()),
            summary: Some("一个测试项目".into()),
            tech_stack: vec!["Rust".into(), "Vue".into()],
            start_date: Some("2026-01-01".into()),
            end_date: None,
            status: None,
            directory: Some("D:/projects/demo".into()),
            mode_name: None,
            goal_id: None,
        }
    }

    #[test]
    fn crud_roundtrip_keeps_json_array() {
        let (p, _, dir) = repo();
        let w = p.add(&input("demo")).unwrap();
        assert_eq!(w.project.tech_stack, vec!["Rust", "Vue"]);
        assert_eq!(w.project.status, "ongoing");
        let got = p.get(w.project.id).unwrap().unwrap();
        assert_eq!(got.directory.as_deref(), Some("D:/projects/demo"));

        p.update(
            w.project.id,
            &ProjectPatch {
                status: Some("done".into()),
                ..Default::default()
            },
        )
        .unwrap();
        assert_eq!(p.get(w.project.id).unwrap().unwrap().status, "done");
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 悬空绑定必须被拒 —— 否则"进入模式自动关联项目"永远找不到东西。
    #[test]
    fn rejects_unknown_mode_and_goal() {
        let (p, _, dir) = repo();
        let mut bad = input("悬空");
        bad.mode_name = Some("不存在的模式".into());
        assert!(p.add(&bad).unwrap_err().to_string().contains("工作模式不存在"));

        let mut bad2 = input("悬空目标");
        bad2.goal_id = Some(999);
        assert!(p.add(&bad2).unwrap_err().to_string().contains("学习目标不存在"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 关联字段的三态：不传=保持、传值=改、传 null=解绑。
    #[test]
    fn relation_patch_supports_unbind() {
        let (p, l, dir) = repo();
        let g = l
            .goal_add(&GoalInput {
                title: "CV".into(),
                description: None,
                expected_at: None,
                priority: None,
            })
            .unwrap();
        let mut i = input("关联");
        i.goal_id = Some(g.id);
        let w = p.add(&i).unwrap();
        assert_eq!(w.project.goal_id, Some(g.id));
        assert_eq!(w.project.goal_title.as_deref(), Some("CV"));

        // 不传 goalId ⇒ 保持
        let kept = p
            .update(
                w.project.id,
                &ProjectPatch {
                    summary: Some("改了简介".into()),
                    ..Default::default()
                },
            )
            .unwrap();
        assert_eq!(kept.project.goal_id, Some(g.id));

        // 显式 null ⇒ 解绑
        let unbound = p
            .update(
                w.project.id,
                &ProjectPatch {
                    goal_id: Some(None),
                    ..Default::default()
                },
            )
            .unwrap();
        assert_eq!(unbound.project.goal_id, None);
        assert!(unbound.project.goal_title.is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 完成项目**不**自动改学习目标 —— 只给提议（红线 V3）。
    #[test]
    fn done_project_only_proposes_goal_completion() {
        let (p, l, dir) = repo();
        let g = l
            .goal_add(&GoalInput {
                title: "目标".into(),
                description: None,
                expected_at: None,
                priority: None,
            })
            .unwrap();
        let mut i = input("关联项目");
        i.goal_id = Some(g.id);
        let w = p.add(&i).unwrap();

        let done = p
            .update(
                w.project.id,
                &ProjectPatch {
                    status: Some("done".into()),
                    ..Default::default()
                },
            )
            .unwrap();
        assert!(done.linked_goal_done, "应给出'可一并完成目标'的提议");
        // 但目标本身**没变**
        assert_eq!(l.goal_get(g.id).unwrap().unwrap().status, "not_started");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn by_mode_skips_done_projects() {
        let (p, _, dir) = repo();
        let db = p.db.clone();
        db.exec(
            "INSERT INTO work_modes (name, apps, created_at, updated_at) \
             VALUES ('开发模式', '[]', datetime('now','localtime'), datetime('now','localtime'))",
            &[],
        )
        .unwrap();
        let mut a = input("已完成");
        a.mode_name = Some("开发模式".into());
        a.status = Some("done".into());
        let wa = p.add(&a).unwrap();
        let mut b = input("进行中");
        b.mode_name = Some("开发模式".into());
        let wb = p.add(&b).unwrap();
        let _ = wa;
        let found = p.by_mode("开发模式").unwrap().unwrap();
        assert_eq!(found.id, wb.project.id, "应优先取未完成的项目");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_illegal_status_and_soft_delete_hides() {
        let (p, _, dir) = repo();
        let w = p.add(&input("x")).unwrap();
        assert!(p
            .update(
                w.project.id,
                &ProjectPatch {
                    status: Some("finished".into()),
                    ..Default::default()
                }
            )
            .is_err());
        p.soft_delete(w.project.id).unwrap();
        assert!(p.get(w.project.id).unwrap().is_none());
        assert!(p.list(None, None).unwrap().is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }
}
