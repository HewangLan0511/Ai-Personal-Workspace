//! 档案数据层（阶段7 · `10-阶段指令-个人档案.md`）。
//!
//! ## 红线 V3 在表结构上的落实
//!
//! AI / 采集器**只有一条写路径**：往 [`Self::suggestion_add`]（`pending_suggestions` 表）塞
//! `pending` 建议。档案四表（basic/skills/projects/timeline）的写入只发生在：
//! 1. 用户手动编辑（`source = 'user'`）；
//! 2. 用户对建议点「确认」（[`Self::suggestion_confirm`]，`source = 'ai_suggested'`）。
//!
//! 不存在"从 AI 直达档案表"的调用链 —— 该不变量由 `tools/verify_stage7.py`
//! 的快照比对端到端断言（触发采集前后，档案四表必须逐行一致）。

use anyhow::Context;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::db::Db;

/// 技能分类（10 §2）。`other` 是迁移 0006 之前的存量数据的默认值。
pub const SKILL_CATEGORIES: &[&str] = &["other", "lang", "framework", "tool", "domain"];

/// 建议类型（10 §5 触发点表的三种落点）。
pub const SUGGESTION_KINDS: &[&str] = &["timeline", "skill", "project"];

/// 时间线条目类型（10 §4：技能突破 / 项目完成 / 学习里程碑 / 证书）。
pub const TIMELINE_TYPES: &[&str] = &["learning", "project", "skill", "cert"];

// ================================================================ 基础信息

#[derive(Debug, Clone, Serialize)]
pub struct ProfileBasic {
    pub name: String,
    pub direction: String,
    /// 兴趣标签
    pub interests: Vec<String>,
    /// 一句话签名
    pub motto: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct BasicInput {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub direction: Option<String>,
    /// `None` = 没传（保持原值）；`Some(vec)` = 覆盖（可为空数组 = 清空标签）。
    /// 与 ProjectPatch 同一个三态约定：区分不了就没法只改签名而不动标签。
    #[serde(default)]
    pub interests: Option<Vec<String>>,
    #[serde(default)]
    pub motto: Option<String>,
}

// ================================================================ 技能

#[derive(Debug, Clone, Serialize)]
pub struct ProfileSkill {
    pub id: i64,
    pub name: String,
    pub level: i64,
    /// `other|lang|framework|tool|domain`
    pub category: String,
    /// `user|ai_suggested`
    pub source: String,
    pub confirmed: bool,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SkillInput {
    pub name: String,
    #[serde(default)]
    pub level: Option<i64>,
    #[serde(default)]
    pub category: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
pub struct SkillPatch {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub level: Option<i64>,
    #[serde(default)]
    pub category: Option<String>,
}

// ================================================================ 项目经历

#[derive(Debug, Clone, Serialize)]
pub struct ProfileProjectEntry {
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
    /// `user|ai_suggested|project_sync`
    pub source: String,
    pub confirmed: bool,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ProjectEntryInput {
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
}

// ================================================================ 时间线

#[derive(Debug, Clone, Serialize)]
pub struct TimelineEvent {
    pub id: i64,
    #[serde(rename = "eventDate")]
    pub event_date: String,
    pub title: String,
    pub description: Option<String>,
    /// `learning|project|skill|cert`
    #[serde(rename = "type")]
    pub kind: String,
    /// `user|ai_suggested`
    pub source: String,
    pub confirmed: bool,
    #[serde(rename = "createdAt")]
    pub created_at: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct TimelineInput {
    #[serde(rename = "eventDate")]
    pub event_date: String,
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default, rename = "type")]
    pub kind: Option<String>,
}

// ================================================================ 待确认建议

#[derive(Debug, Clone, Serialize)]
pub struct PendingSuggestion {
    pub id: i64,
    /// `timeline|skill|project`
    pub kind: String,
    /// 去重键（同源只挂一条 pending）
    #[serde(rename = "refKey")]
    pub ref_key: String,
    /// 给用户看的一句话
    pub title: String,
    /// 确认时要写入正式表的数据（原样返回给前端预览）
    pub payload: Value,
    /// `pending|confirmed|ignored`
    pub status: String,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "decidedAt")]
    pub decided_at: Option<String>,
}

/// 建议入队（采集器唯一入口）。同一 `kind + ref_key` 已有 pending 时返回 `Ok(None)`
/// （去重不报错 —— 采集器是幂等触发的，重复触发不该变成用户眼前的刷屏）。
pub struct SuggestionInput {
    pub kind: String,
    pub ref_key: String,
    pub title: String,
    pub payload: Value,
}

#[derive(Clone)]
pub struct ProfileRepo {
    db: Db,
}

impl ProfileRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    // ------------------------------------------------------------ 基础信息

    /// 单行表（id=1）。没有行时返回全空默认值 —— 首次使用引导就是往这份默认值上填三个字段。
    pub fn basic_get(&self) -> anyhow::Result<ProfileBasic> {
        let rows = self.db.query_json(
            "SELECT name, direction, interests, motto, updated_at FROM profile_basic WHERE id = 1",
            &[],
        )?;
        let Some(v) = rows.first() else {
            return Ok(ProfileBasic {
                name: String::new(),
                direction: String::new(),
                interests: Vec::new(),
                motto: String::new(),
                updated_at: String::new(),
            });
        };
        let s = |k: &str| {
            v.get(k)
                .and_then(Value::as_str)
                .filter(|x| !x.trim().is_empty())
                .map(str::to_string)
                .unwrap_or_default()
        };
        let interests = match v.get("interests") {
            Some(Value::String(raw)) if !raw.trim().is_empty() => serde_json::from_str(raw)
                .unwrap_or(Vec::<String>::new()),
            Some(Value::Array(a)) => a
                .iter()
                .filter_map(|x| x.as_str().map(str::to_string))
                .collect(),
            _ => Vec::new(),
        };
        Ok(ProfileBasic {
            name: s("name"),
            direction: s("direction"),
            interests,
            motto: s("motto"),
            updated_at: s("updated_at"),
        })
    }

    pub fn basic_save(&self, input: &BasicInput) -> anyhow::Result<ProfileBasic> {
        let cur = self.basic_get()?;
        let name = input
            .name
            .clone()
            .unwrap_or(cur.name)
            .trim()
            .to_string();
        let direction = input.direction.clone().unwrap_or(cur.direction).trim().to_string();
        let motto = input.motto.clone().unwrap_or(cur.motto).trim().to_string();
        let interests = match &input.interests {
            None => cur.interests,
            Some(list) => list
                .iter()
                .map(|s| s.trim().to_string())
                .filter(|s| !s.is_empty())
                .collect(),
        };
        // 只有一行（id=1）：UPSERT，别让用户编辑两次就长出两行
        self.db.exec(
            "INSERT INTO profile_basic (id, name, direction, interests, motto, updated_at) \
             VALUES (1, ?1, ?2, ?3, ?4, datetime('now','localtime')) \
             ON CONFLICT(id) DO UPDATE SET name=?1, direction=?2, interests=?3, motto=?4, \
             updated_at=datetime('now','localtime')",
            &[
                Value::from(name),
                Value::from(direction),
                serde_json::to_value(&interests)?,
                Value::from(motto),
            ],
        )?;
        self.basic_get()
    }

    // ------------------------------------------------------------ 技能

    pub fn skills_list(&self, confirmed_only: bool) -> anyhow::Result<Vec<ProfileSkill>> {
        let sql = format!(
            "SELECT id, name, level, category, source, confirmed, updated_at FROM profile_skills {} \
             ORDER BY level DESC, name ASC",
            if confirmed_only { "WHERE confirmed = 1" } else { "" }
        );
        let rows = self.db.query_json(&sql, &[])?;
        Ok(rows.iter().map(to_skill).collect())
    }

    /// 用户手动添加（10 §2：等级来源之一）。同名校验交给 UNIQUE 约束 ——
    /// 报错文案转成用户可读的形式。
    pub fn skill_add(&self, input: &SkillInput) -> anyhow::Result<ProfileSkill> {
        let name = require_name(&input.name)?;
        let level = clamp_level(input.level.unwrap_or(0))?;
        let category = check_category(input.category.as_deref())?;
        let exists = self
            .db
            .query_json("SELECT id FROM profile_skills WHERE name = ?", &[Value::from(name.as_str())])?;
        if !exists.is_empty() {
            anyhow::bail!("技能「{name}」已存在，可直接调整它的等级");
        }
        self.db.exec(
            "INSERT INTO profile_skills (name, level, category, source, confirmed, updated_at) \
             VALUES (?1, ?2, ?3, 'user', 1, datetime('now','localtime'))",
            &[Value::from(name.as_str()), Value::from(level), Value::from(category)],
        )?;
        self.skill_get_by_name(&name)?
            .context("技能写入后应能读到")
    }

    pub fn skill_update(&self, id: i64, patch: &SkillPatch) -> anyhow::Result<ProfileSkill> {
        let cur = self
            .skill_get(id)?
            .with_context(|| format!("技能不存在：id={id}"))?;
        let name = match &patch.name {
            Some(n) => require_name(n)?,
            None => cur.name.clone(),
        };
        let level = clamp_level(patch.level.unwrap_or(cur.level))?;
        let category = check_category(patch.category.as_deref().or(Some(&cur.category)))?;
        if name != cur.name {
            let clash = self.db.query_json(
                "SELECT id FROM profile_skills WHERE name = ? AND id != ?",
                &[Value::from(name.as_str()), Value::from(id)],
            )?;
            if !clash.is_empty() {
                anyhow::bail!("技能「{name}」已存在");
            }
        }
        self.db.exec(
            "UPDATE profile_skills SET name=?1, level=?2, category=?3, \
             updated_at=datetime('now','localtime') WHERE id=?4",
            &[Value::from(name), Value::from(level), Value::from(category), Value::from(id)],
        )?;
        self.skill_get(id)?.context("技能更新后应能读到")
    }

    pub fn skill_remove(&self, id: i64) -> anyhow::Result<()> {
        let n = self.db.exec("DELETE FROM profile_skills WHERE id = ?1", &[Value::from(id)])?;
        if n == 0 {
            anyhow::bail!("技能不存在：id={id}");
        }
        Ok(())
    }

    /// 确认一条技能（`confirmed=0 → 1`）。用户手动添加的技能本来就是 confirmed=1，
    /// 此方法主要服务于"建议确认后补确认"之外的历史数据场景。
    pub fn skill_confirm(&self, id: i64) -> anyhow::Result<ProfileSkill> {
        self.db.exec(
            "UPDATE profile_skills SET confirmed = 1, updated_at=datetime('now','localtime') \
             WHERE id = ?1",
            &[Value::from(id)],
        )?;
        self.skill_get(id)?.with_context(|| format!("技能不存在：id={id}"))
    }

    pub fn skill_get(&self, id: i64) -> anyhow::Result<Option<ProfileSkill>> {
        let rows = self.db.query_json(
            "SELECT id, name, level, category, source, confirmed, updated_at \
             FROM profile_skills WHERE id = ?",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_skill))
    }

    fn skill_get_by_name(&self, name: &str) -> anyhow::Result<Option<ProfileSkill>> {
        let rows = self.db.query_json(
            "SELECT id, name, level, category, source, confirmed, updated_at \
             FROM profile_skills WHERE name = ?",
            &[Value::from(name)],
        )?;
        Ok(rows.first().map(to_skill))
    }

    /// 同名技能是否已存在（采集器用来跳过"已是技能"的高频软件）。
    pub fn skill_exists(&self, name: &str) -> anyhow::Result<bool> {
        Ok(!self
            .db
            .query_json("SELECT id FROM profile_skills WHERE name = ?", &[Value::from(name)])?
            .is_empty())
    }

    // ------------------------------------------------------------ 项目经历

    pub fn projects_list(&self, confirmed_only: bool) -> anyhow::Result<Vec<ProfileProjectEntry>> {
        let sql = format!(
            "SELECT id, name, role, summary, tech_stack, start_date, end_date, status, source, \
             confirmed, created_at, updated_at FROM profile_projects {} \
             ORDER BY COALESCE(end_date, start_date, created_at) DESC, id DESC",
            if confirmed_only { "WHERE confirmed = 1" } else { "" }
        );
        let rows = self.db.query_json(&sql, &[])?;
        Ok(rows.iter().map(to_project_entry).collect())
    }

    pub fn project_entry_add(&self, input: &ProjectEntryInput) -> anyhow::Result<ProfileProjectEntry> {
        let name = require_name(&input.name)?;
        let status = match input.status.as_deref().map(str::trim) {
            None | Some("") => "done",
            Some(s) => s,
        };
        let id = self.db.insert(
            "INSERT INTO profile_projects \
             (name, role, summary, tech_stack, start_date, end_date, status, source, confirmed, \
              created_at, updated_at) \
             VALUES (?1,?2,?3,?4,?5,?6,?7,'user',1, datetime('now','localtime'), datetime('now','localtime'))",
            &[
                Value::from(name),
                opt(&input.role),
                opt(&input.summary),
                serde_json::to_value(&input.tech_stack)?,
                opt(&input.start_date),
                opt(&input.end_date),
                Value::from(status),
            ],
        )?;
        self.project_entry_get(id)?.context("项目经历写入后应能读到")
    }

    pub fn project_entry_get(&self, id: i64) -> anyhow::Result<Option<ProfileProjectEntry>> {
        let rows = self.db.query_json(
            "SELECT id, name, role, summary, tech_stack, start_date, end_date, status, source, \
             confirmed, created_at, updated_at FROM profile_projects WHERE id = ?",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_project_entry))
    }

    /// 同名项目经历是否已存在（"项目管理 → 档案"同步的防重闸）。
    pub fn project_entry_exists(&self, name: &str) -> anyhow::Result<bool> {
        Ok(!self
            .db
            .query_json("SELECT id FROM profile_projects WHERE name = ?", &[Value::from(name)])?
            .is_empty())
    }

    pub fn project_entry_confirm(&self, id: i64) -> anyhow::Result<ProfileProjectEntry> {
        self.db.exec(
            "UPDATE profile_projects SET confirmed = 1, updated_at=datetime('now','localtime') \
             WHERE id = ?1",
            &[Value::from(id)],
        )?;
        self.project_entry_get(id)?.with_context(|| format!("项目经历不存在：id={id}"))
    }

    pub fn project_entry_remove(&self, id: i64) -> anyhow::Result<()> {
        let n = self
            .db
            .exec("DELETE FROM profile_projects WHERE id = ?1", &[Value::from(id)])?;
        if n == 0 {
            anyhow::bail!("项目经历不存在：id={id}");
        }
        Ok(())
    }

    // ------------------------------------------------------------ 时间线

    pub fn timeline_list(&self, confirmed_only: bool) -> anyhow::Result<Vec<TimelineEvent>> {
        let sql = format!(
            "SELECT id, event_date, title, description, type, source, confirmed, created_at \
             FROM profile_timeline {} ORDER BY event_date DESC, id DESC",
            if confirmed_only { "WHERE confirmed = 1" } else { "" }
        );
        let rows = self.db.query_json(&sql, &[])?;
        Ok(rows.iter().map(to_timeline).collect())
    }

    pub fn timeline_add(&self, input: &TimelineInput) -> anyhow::Result<TimelineEvent> {
        let title = require_name(&input.title)?;
        let date = input.event_date.trim();
        if date.is_empty() {
            anyhow::bail!("时间线日期不能为空");
        }
        let kind = match input.kind.as_deref().map(str::trim) {
            None | Some("") => "learning",
            Some(s) if TIMELINE_TYPES.contains(&s) => s,
            Some(s) => anyhow::bail!("非法的时间线类型：{s}（可选 {TIMELINE_TYPES:?}）"),
        };
        let id = self.db.insert(
            "INSERT INTO profile_timeline (event_date, title, description, type, source, confirmed, created_at) \
             VALUES (?1, ?2, ?3, ?4, 'user', 1, datetime('now','localtime'))",
            &[
                Value::from(date),
                Value::from(title),
                opt(&input.description),
                Value::from(kind),
            ],
        )?;
        self.timeline_get(id)?.context("时间线条目写入后应能读到")
    }

    pub fn timeline_get(&self, id: i64) -> anyhow::Result<Option<TimelineEvent>> {
        let rows = self.db.query_json(
            "SELECT id, event_date, title, description, type, source, confirmed, created_at \
             FROM profile_timeline WHERE id = ?",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_timeline))
    }

    pub fn timeline_remove(&self, id: i64) -> anyhow::Result<()> {
        let n = self
            .db
            .exec("DELETE FROM profile_timeline WHERE id = ?1", &[Value::from(id)])?;
        if n == 0 {
            anyhow::bail!("时间线条目不存在：id={id}");
        }
        Ok(())
    }

    pub fn timeline_confirm(&self, id: i64) -> anyhow::Result<TimelineEvent> {
        self.db.exec(
            "UPDATE profile_timeline SET confirmed = 1 WHERE id = ?1",
            &[Value::from(id)],
        )?;
        self.timeline_get(id)?.with_context(|| format!("时间线条目不存在：id={id}"))
    }

    // ------------------------------------------------------------ 待确认建议

    pub fn suggestions_list(&self, status: Option<&str>) -> anyhow::Result<Vec<PendingSuggestion>> {
        let mut sql = String::from(
            "SELECT id, kind, ref_key, title, payload, status, created_at, decided_at \
             FROM pending_suggestions",
        );
        let mut params: Vec<Value> = Vec::new();
        if let Some(s) = status.filter(|s| !s.trim().is_empty()) {
            params.push(Value::from(s.trim()));
            sql.push_str(&format!(" WHERE status = ?{}", params.len()));
        }
        sql.push_str(" ORDER BY created_at ASC, id ASC");
        let rows = self.db.query_json(&sql, &params)?;
        Ok(rows.iter().map(to_suggestion).collect())
    }

    pub fn suggestion_get(&self, id: i64) -> anyhow::Result<Option<PendingSuggestion>> {
        let rows = self.db.query_json(
            "SELECT id, kind, ref_key, title, payload, status, created_at, decided_at \
             FROM pending_suggestions WHERE id = ?",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_suggestion))
    }

    /// 建议入队。已存在同 `kind+ref_key` 的 pending 时静默返回 None（去重）。
    pub fn suggestion_add(&self, input: &SuggestionInput) -> anyhow::Result<Option<PendingSuggestion>> {
        if !SUGGESTION_KINDS.contains(&input.kind.as_str()) {
            anyhow::bail!("非法的建议类型：{}（可选 {SUGGESTION_KINDS:?}）", input.kind);
        }
        if input.ref_key.trim().is_empty() {
            anyhow::bail!("建议去重键不能为空");
        }
        if input.title.trim().is_empty() {
            anyhow::bail!("建议标题不能为空");
        }
        let dup = self.db.query_json(
            "SELECT id FROM pending_suggestions WHERE kind = ?1 AND ref_key = ?2 AND status = 'pending'",
            &[Value::from(input.kind.as_str()), Value::from(input.ref_key.trim())],
        )?;
        if !dup.is_empty() {
            return Ok(None);
        }
        self.db.exec(
            "INSERT INTO pending_suggestions (kind, ref_key, title, payload, status, created_at) \
             VALUES (?1, ?2, ?3, ?4, 'pending', datetime('now','localtime'))",
            &[
                Value::from(input.kind.trim()),
                Value::from(input.ref_key.trim()),
                Value::from(input.title.trim()),
                Value::from(input.payload.to_string()),
            ],
        )?;
        let rows = self.db.query_json(
            "SELECT id FROM pending_suggestions WHERE kind = ?1 AND ref_key = ?2 AND status = 'pending'",
            &[Value::from(input.kind.trim()), Value::from(input.ref_key.trim())],
        )?;
        let id = rows
            .first()
            .and_then(|v| v.get("id").and_then(Value::as_i64))
            .context("建议写入后应能读到")?;
        Ok(self.suggestion_get(id)?)
    }

    /// **确认一条建议并落正式表** —— 全系统唯一一条"建议 → 档案"的通路，
    /// 只能由用户动作（command / HTTP）触发。返回被确认的建议（供上层发事件）。
    pub fn suggestion_confirm(&self, id: i64) -> anyhow::Result<PendingSuggestion> {
        let sug = self
            .suggestion_get(id)?
            .with_context(|| format!("建议不存在：id={id}"))?;
        if sug.status != "pending" {
            anyhow::bail!("该建议已处理过（{}），无需重复确认", sug.status);
        }
        match sug.kind.as_str() {
            "timeline" => {
                let ev: TimelineInput = serde_json::from_value(sug.payload.clone())
                    .map_err(|e| anyhow::anyhow!("建议数据不合法（timeline）：{e}"))?;
                self.db.insert(
                    "INSERT INTO profile_timeline (event_date, title, description, type, source, confirmed, created_at) \
                     VALUES (?1, ?2, ?3, ?4, 'ai_suggested', 1, datetime('now','localtime'))",
                    &[
                        Value::from(ev.event_date.trim()),
                        Value::from(require_name(&ev.title)?),
                        opt(&ev.description),
                        Value::from(ev.kind.as_deref().map(str::trim).filter(|s| !s.is_empty()).unwrap_or("learning")),
                    ],
                )?;
            }
            "skill" => {
                let sk: SkillInput = serde_json::from_value(sug.payload.clone())
                    .map_err(|e| anyhow::anyhow!("建议数据不合法（skill）：{e}"))?;
                let name = require_name(&sk.name)?;
                let level = clamp_level(sk.level.unwrap_or(0))?;
                let category = check_category(sk.category.as_deref())?;
                // UPSERT：若用户手动建过同名技能，确认建议视为"用户拍板更新等级"
                self.db.exec(
                    "INSERT INTO profile_skills (name, level, category, source, confirmed, updated_at) \
                     VALUES (?1, ?2, ?3, 'ai_suggested', 1, datetime('now','localtime')) \
                     ON CONFLICT(name) DO UPDATE SET level=?2, category=?3, source='ai_suggested', \
                     confirmed=1, updated_at=datetime('now','localtime')",
                    &[Value::from(name), Value::from(level), Value::from(category)],
                )?;
            }
            "project" => {
                let pr: ProjectEntryInput = serde_json::from_value(sug.payload.clone())
                    .map_err(|e| anyhow::anyhow!("建议数据不合法（project）：{e}"))?;
                self.db.insert(
                    "INSERT INTO profile_projects \
                     (name, role, summary, tech_stack, start_date, end_date, status, source, confirmed, \
                      created_at, updated_at) \
                     VALUES (?1,?2,?3,?4,?5,?6,?7,'ai_suggested',1, datetime('now','localtime'), datetime('now','localtime'))",
                    &[
                        Value::from(require_name(&pr.name)?),
                        opt(&pr.role),
                        opt(&pr.summary),
                        serde_json::to_value(&pr.tech_stack)?,
                        opt(&pr.start_date),
                        opt(&pr.end_date),
                        Value::from(pr.status.as_deref().map(str::trim).filter(|s| !s.is_empty()).unwrap_or("done")),
                    ],
                )?;
            }
            other => anyhow::bail!("未知的建议类型：{other}"),
        }
        self.db.exec(
            "UPDATE pending_suggestions SET status='confirmed', decided_at=datetime('now','localtime') \
             WHERE id = ?1",
            &[Value::from(id)],
        )?;
        self.suggestion_get(id)?.context("确认后应能读到建议")
    }

    /// 忽略（不写入，也不算拒绝 —— 同源日后有新变化可再次建议）。
    pub fn suggestion_ignore(&self, id: i64) -> anyhow::Result<()> {
        let n = self.db.exec(
            "UPDATE pending_suggestions SET status='ignored', decided_at=datetime('now','localtime') \
             WHERE id = ?1 AND status = 'pending'",
            &[Value::from(id)],
        )?;
        if n == 0 {
            anyhow::bail!("建议不存在或已处理：id={id}");
        }
        Ok(())
    }

    /// 永久拒绝某类：把该类所有 pending 置为 ignored（采集器侧再按 config 的拒绝清单拦截）。
    pub fn suggestions_ignore_kind(&self, kind: &str) -> anyhow::Result<u64> {
        let n = self.db.exec(
            "UPDATE pending_suggestions SET status='ignored', decided_at=datetime('now','localtime') \
             WHERE kind = ?1 AND status = 'pending'",
            &[Value::from(kind)],
        )?;
        Ok(n)
    }

    /// 待确认数量（档案页顶部的"N 条待确认"）。
    pub fn pending_count(&self) -> anyhow::Result<i64> {
        let rows = self
            .db
            .query_json("SELECT COUNT(*) AS n FROM pending_suggestions WHERE status = 'pending'", &[])?;
        Ok(rows
            .first()
            .and_then(|v| v.get("n").and_then(Value::as_i64))
            .unwrap_or(0))
    }
}

// ---------------------------------------------------------------- helpers

fn require_name(raw: &str) -> anyhow::Result<String> {
    let name = raw.trim();
    if name.is_empty() {
        anyhow::bail!("名称不能为空");
    }
    Ok(name.to_string())
}

fn clamp_level(v: i64) -> anyhow::Result<i64> {
    if !(0..=100).contains(&v) {
        anyhow::bail!("技能等级须在 0~100 之间（收到 {v}）");
    }
    Ok(v)
}

fn check_category(raw: Option<&str>) -> anyhow::Result<String> {
    match raw.map(str::trim) {
        None | Some("") => Ok("other".into()),
        Some(s) if SKILL_CATEGORIES.contains(&s) => Ok(s.to_string()),
        Some(s) => anyhow::bail!("非法的技能分类：{s}（可选 {SKILL_CATEGORIES:?}）"),
    }
}

fn opt(v: &Option<String>) -> Value {
    match v {
        Some(s) if !s.trim().is_empty() => Value::from(s.trim()),
        _ => Value::Null,
    }
}

fn json_arr_field(v: Option<&Value>) -> Vec<String> {
    match v {
        Some(Value::String(s)) => serde_json::from_str::<Vec<String>>(s).unwrap_or_default(),
        Some(Value::Array(a)) => a
            .iter()
            .filter_map(|x| x.as_str().map(str::to_string))
            .collect(),
        _ => Vec::new(),
    }
}

fn to_skill(v: &Value) -> ProfileSkill {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    ProfileSkill {
        id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
        name: s("name").unwrap_or_default(),
        level: v.get("level").and_then(Value::as_i64).unwrap_or(0),
        category: s("category").unwrap_or_else(|| "other".into()),
        source: s("source").unwrap_or_else(|| "user".into()),
        confirmed: v.get("confirmed").and_then(Value::as_i64).unwrap_or(1) == 1,
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

fn to_project_entry(v: &Value) -> ProfileProjectEntry {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    ProfileProjectEntry {
        id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
        name: s("name").unwrap_or_default(),
        role: s("role"),
        summary: s("summary"),
        tech_stack: json_arr_field(v.get("tech_stack")),
        start_date: s("start_date"),
        end_date: s("end_date"),
        status: s("status").unwrap_or_else(|| "done".into()),
        source: s("source").unwrap_or_else(|| "user".into()),
        confirmed: v.get("confirmed").and_then(Value::as_i64).unwrap_or(1) == 1,
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

fn to_timeline(v: &Value) -> TimelineEvent {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    TimelineEvent {
        id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
        event_date: s("event_date").unwrap_or_default(),
        title: s("title").unwrap_or_default(),
        description: s("description"),
        kind: s("type").unwrap_or_else(|| "learning".into()),
        source: s("source").unwrap_or_else(|| "user".into()),
        confirmed: v.get("confirmed").and_then(Value::as_i64).unwrap_or(1) == 1,
        created_at: s("created_at").unwrap_or_default(),
    }
}

fn to_suggestion(v: &Value) -> PendingSuggestion {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let payload = v
        .get("payload")
        .and_then(Value::as_str)
        .and_then(|raw| serde_json::from_str(raw).ok())
        .unwrap_or(Value::Null);
    PendingSuggestion {
        id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
        kind: s("kind").unwrap_or_default(),
        ref_key: s("ref_key").unwrap_or_default(),
        title: s("title").unwrap_or_default(),
        payload,
        status: s("status").unwrap_or_else(|| "pending".into()),
        created_at: s("created_at").unwrap_or_default(),
        decided_at: s("decided_at"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo() -> (ProfileRepo, std::path::PathBuf) {
        let dir = std::env::temp_dir().join(format!(
            "pw-profile-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        (ProfileRepo::new(db), dir)
    }

    #[test]
    fn basic_roundtrip_and_empty_default() {
        let (r, dir) = repo();
        let empty = r.basic_get().unwrap();
        assert!(empty.name.is_empty(), "无行时应返回全空默认值");
        r.basic_save(&BasicInput {
            name: Some("白宇".into()),
            direction: Some("AI 工程".into()),
            interests: Some(vec!["Rust".into(), "本地优先".into()]),
            motto: Some("少废话".into()),
        })
        .unwrap();
        let got = r.basic_get().unwrap();
        assert_eq!(got.name, "白宇");
        assert_eq!(got.interests, vec!["Rust", "本地优先"]);
        // 只改签名（interests 不传）⇒ 标签保持
        r.basic_save(&BasicInput { motto: Some("改签名".into()), ..Default::default() })
            .unwrap();
        assert_eq!(r.basic_get().unwrap().motto, "改签名");
        assert_eq!(r.basic_get().unwrap().interests, vec!["Rust", "本地优先"]);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn skill_add_rejects_dup_and_bad_level() {
        let (r, dir) = repo();
        r.skill_add(&SkillInput { name: "Python".into(), level: Some(70), category: Some("lang".into()) })
            .unwrap();
        assert!(r
            .skill_add(&SkillInput { name: " Python ".into(), level: Some(10), category: None })
            .unwrap_err()
            .to_string()
            .contains("已存在"));
        assert!(r
            .skill_add(&SkillInput { name: "X".into(), level: Some(120), category: None })
            .unwrap_err()
            .to_string()
            .contains("0~100"));
        assert!(r
            .skill_add(&SkillInput { name: "X".into(), level: None, category: Some("bad".into()) })
            .unwrap_err()
            .to_string()
            .contains("分类"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 红线 V3 的库级护栏：同源重复建议被部分唯一索引挡住（不报错、不重复入队）。
    #[test]
    fn suggestion_dedup_and_confirm_writes_profile() {
        let (r, dir) = repo();
        let payload = serde_json::json!({
            "name": "演示项目", "role": "开发", "summary": "简介",
            "techStack": ["Rust"], "startDate": "2026-01-01", "endDate": "2026-09-01",
            "status": "done"
        });
        let input = SuggestionInput {
            kind: "project".into(),
            ref_key: "project_done:1".into(),
            title: "把「演示项目」加入档案？".into(),
            payload: payload.clone(),
        };
        let first = r.suggestion_add(&input).unwrap().expect("首次应入队");
        assert!(r.suggestion_add(&input).unwrap().is_none(), "重复入队应被去重");

        // 确认前：档案表没有这条
        assert!(r.projects_list(true).unwrap().is_empty());

        let done = r.suggestion_confirm(first.id).unwrap();
        assert_eq!(done.status, "confirmed");
        let entries = r.projects_list(true).unwrap();
        assert_eq!(entries.len(), 1);
        assert_eq!(entries[0].name, "演示项目");
        assert!(entries[0].confirmed);
        assert_eq!(entries[0].source, "ai_suggested");

        // 已确认的建议不能重复确认
        assert!(r.suggestion_confirm(first.id).is_err());
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn suggestion_confirm_skill_upserts_and_timeline_inserts() {
        let (r, dir) = repo();
        // 技能建议：确认后 confirmed=1（只有确认过的技能才进档案/AI 上下文）
        let sk = r
            .suggestion_add(&SuggestionInput {
                kind: "skill".into(),
                ref_key: "app_hot:Code".into(),
                title: "把「开发工具」加入技能？".into(),
                payload: serde_json::json!({ "name": "开发工具", "level": 40, "category": "tool" }),
            })
            .unwrap()
            .unwrap();
        r.suggestion_confirm(sk.id).unwrap();
        let skills = r.skills_list(true).unwrap();
        assert_eq!(skills.len(), 1);
        assert_eq!(skills[0].name, "开发工具");
        assert_eq!(skills[0].level, 40);
        assert!(skills[0].confirmed);

        // 时间线建议
        let tl = r
            .suggestion_add(&SuggestionInput {
                kind: "timeline".into(),
                ref_key: "goal_done:7".into(),
                title: "记录到时间线？".into(),
                payload: serde_json::json!({
                    "eventDate": "2026-09-13", "title": "完成学习目标：CV",
                    "description": null, "type": "learning"
                }),
            })
            .unwrap()
            .unwrap();
        r.suggestion_confirm(tl.id).unwrap();
        let events = r.timeline_list(true).unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].kind, "learning");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn ignore_and_reject_kind_only_touch_pending() {
        let (r, dir) = repo();
        let a = r
            .suggestion_add(&SuggestionInput {
                kind: "skill".into(),
                ref_key: "k1".into(),
                title: "t1".into(),
                payload: serde_json::json!({ "name": "A", "level": 10 }),
            })
            .unwrap()
            .unwrap();
        let b = r
            .suggestion_add(&SuggestionInput {
                kind: "skill".into(),
                ref_key: "k2".into(),
                title: "t2".into(),
                payload: serde_json::json!({ "name": "B", "level": 20 }),
            })
            .unwrap()
            .unwrap();
        r.suggestion_ignore(a.id).unwrap();
        assert_eq!(r.suggestions_list(Some("pending")).unwrap().len(), 1);
        // 拒绝整类：把剩下的 pending 全部 ignored
        r.suggestions_ignore_kind("skill").unwrap();
        assert!(r.suggestions_list(Some("pending")).unwrap().is_empty());
        // 已 decided 的不受影响（状态仍 ignored，不会变别的）
        assert_eq!(r.suggestion_get(a.id).unwrap().unwrap().status, "ignored");
        assert_eq!(r.suggestion_get(b.id).unwrap().unwrap().status, "ignored");
        assert!(r.skills_list(false).unwrap().is_empty(), "忽略/拒绝不得写档案表");
        let _ = std::fs::remove_dir_all(dir);
    }

    #[test]
    fn timeline_rejects_bad_type_and_project_list_order() {
        let (r, dir) = repo();
        assert!(r
            .timeline_add(&TimelineInput {
                event_date: "2026-09-13".into(),
                title: "x".into(),
                description: None,
                kind: Some("weird".into()),
            })
            .unwrap_err()
            .to_string()
            .contains("时间线类型"));
        r.timeline_add(&TimelineInput {
            event_date: "2026-01-01".into(),
            title: "旧的".into(),
            description: None,
            kind: None,
        })
        .unwrap();
        r.timeline_add(&TimelineInput {
            event_date: "2026-09-01".into(),
            title: "新的".into(),
            description: None,
            kind: Some("cert".into()),
        })
        .unwrap();
        let list = r.timeline_list(true).unwrap();
        assert_eq!(list[0].title, "新的", "应按日期倒序");
        let _ = std::fs::remove_dir_all(dir);
    }
}
