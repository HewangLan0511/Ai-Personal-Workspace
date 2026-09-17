//! 学习成长的数据层：`learning_goals` / `learning_roadmap` / `learning_updates`。
//!
//! 边界（02 §2.4 / 09-阶段指令-学习成长）：
//! - **数据库的唯一写入者是 Rust core** —— 本模块是这三张表的唯一写入口；
//! - **本模块不做任何"自动改状态"**：所有写入都由**用户动作**触发
//!   （`node_update` / `goal_update` / `roadmap_confirm`）。
//!   AI 建议走 `learning::ai_suggest`，它**只读不写**（红线 V3）—— 这是产品的信任基础。
//!
//! 关于 `learning_goals.roadmap` 列：它存的**不是**结构化节点（节点在 `learning_roadmap` 表），
//! 而是"最后一次 AI 原始输出"的快照。用途有二：
//! ① 模型返回非法 JSON 时，降级展示的那段文本重启后仍在（09 §2「不要让用户看到 JSON 解析错误」）；
//! ② 重新生成时可供对比。结构化数据只有一处真相，避免"两个副本对不上"。

use std::collections::HashMap;

use anyhow::Context;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::db::Db;

/// 路线节点状态（09 §3）。
pub const NODE_STATUSES: &[&str] = &["not_started", "learning", "done", "paused"];
/// 学习目标状态：节点状态 + `archived`（09 §5 提醒动作「归档」）。
pub const GOAL_STATUSES: &[&str] =
    &["not_started", "learning", "paused", "done", "archived"];
/// 优先级（09 §1）。
pub const PRIORITIES: &[&str] = &["low", "medium", "high"];

/// 目标进度（**派生值**，由 core 统一计算 —— 前端不得各算一套）。
///
/// `total == 0` 时 `percent = 0`（不除零，也不显示 100%）。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Progress {
    pub done: i64,
    pub total: i64,
    pub percent: i64,
}

impl Progress {
    fn new(done: i64, total: i64) -> Self {
        let percent = if total <= 0 { 0 } else { done * 100 / total };
        Self { done, total, percent }
    }
}

/// 学习目标（出参形态）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LearningGoal {
    pub id: i64,
    pub title: String,
    pub description: Option<String>,
    /// `not_started|learning|paused|done|archived`
    pub status: String,
    #[serde(rename = "expectedAt")]
    pub expected_at: Option<String>,
    pub priority: String,
    /// AI 原始输出快照（降级展示依据；结构化节点在 `learning_roadmap`）
    #[serde(rename = "roadmapRaw")]
    pub roadmap_raw: Option<String>,
    #[serde(rename = "lastRemindedAt")]
    pub last_reminded_at: Option<String>,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
    pub progress: Progress,
}

/// 创建目标入参（09 §1：标题必填，其余可选）。
#[derive(Debug, Clone, Deserialize)]
pub struct GoalInput {
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default, rename = "expectedAt")]
    pub expected_at: Option<String>,
    #[serde(default)]
    pub priority: Option<String>,
}

/// 编辑目标入参：只覆盖显式给出的字段。
#[derive(Debug, Clone, Default, Deserialize)]
pub struct GoalPatch {
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default, rename = "expectedAt")]
    pub expected_at: Option<String>,
    #[serde(default)]
    pub priority: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
}

/// 路线节点（出参形态）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RoadmapNode {
    pub id: i64,
    #[serde(rename = "goalId")]
    pub goal_id: i64,
    pub title: String,
    pub status: String,
    pub note: Option<String>,
    /// 预估时长，如 `"2周"`（AI 产出，用户可改）
    pub estimated: Option<String>,
    /// 资料方向（AI 产出；**不是**结构化榜单，只是提示方向）
    pub resources: Vec<String>,
    #[serde(rename = "sortOrder")]
    pub sort_order: i64,
    #[serde(rename = "completedAt")]
    pub completed_at: Option<String>,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

/// 新增节点入参（含"确认采纳 AI 建议"时的批量形态 —— 见 `roadmap_confirm`）。
///
/// 同时是**建议态节点**的载体：AI 解析结果（`roadmap::ParsedRoadmap`）与前端草稿
/// 都用它，故需要 `Serialize`（回给 UI）与 `PartialEq`（便于断言）。
#[derive(Debug, Clone, Default, Deserialize, Serialize, PartialEq)]
pub struct NodeInput {
    pub title: String,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub note: Option<String>,
    #[serde(default)]
    pub estimated: Option<String>,
    #[serde(default)]
    pub resources: Vec<String>,
}

/// 编辑节点入参。
#[derive(Debug, Clone, Default, Deserialize)]
pub struct NodePatch {
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub note: Option<String>,
    #[serde(default)]
    pub estimated: Option<String>,
    #[serde(default)]
    pub resources: Option<Vec<String>>,
    #[serde(default, rename = "sortOrder")]
    pub sort_order: Option<i64>,
}

/// 用户状态更新记录（`learning_updates`）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LearningUpdate {
    pub id: i64,
    #[serde(rename = "goalId")]
    pub goal_id: i64,
    #[serde(rename = "nodeId")]
    pub node_id: Option<i64>,
    pub content: String,
    #[serde(rename = "createdAt")]
    pub created_at: String,
}

#[derive(Clone)]
pub struct LearningRepo {
    db: Db,
}

impl LearningRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    // ------------------------------------------------------------ 目标

    /// 全部未删除的目标（含派生进度），按手动排序 → 创建时间。
    pub fn goals_list(&self) -> anyhow::Result<Vec<LearningGoal>> {
        let rows = self.db.query_json(
            "SELECT id, title, description, status, roadmap, expected_at, priority, \
                    last_reminded_at, created_at, updated_at \
             FROM learning_goals WHERE deleted_at IS NULL \
             ORDER BY sort_order ASC, id ASC",
            &[],
        )?;
        let mut prog = self.progress_map()?;
        Ok(rows.iter().map(|v| to_goal(v, prog.remove(&id_of(v)).unwrap_or((0, 0)))).collect())
    }

    pub fn goal_get(&self, id: i64) -> anyhow::Result<Option<LearningGoal>> {
        let rows = self.db.query_json(
            "SELECT id, title, description, status, roadmap, expected_at, priority, \
                    last_reminded_at, created_at, updated_at \
             FROM learning_goals WHERE id = ? AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(|v| to_goal(v, self.progress_of(id).unwrap_or((0, 0)))))
    }

    pub fn goal_add(&self, input: &GoalInput) -> anyhow::Result<LearningGoal> {
        let title = input.title.trim();
        if title.is_empty() {
            anyhow::bail!("目标标题不能为空");
        }
        let priority = normalize(input.priority.as_deref(), PRIORITIES)?
            .unwrap_or_else(|| "medium".into());
        let next: i64 = self
            .db
            .query_json(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM learning_goals",
                &[],
            )?
            .first()
            .and_then(|v| v.get("n"))
            .and_then(Value::as_i64)
            .unwrap_or(1);
        let id = self.db.insert(
            "INSERT INTO learning_goals \
             (title, description, status, expected_at, priority, sort_order, created_at, updated_at) \
             VALUES (?1, ?2, 'not_started', ?3, ?4, ?5, datetime('now','localtime'), datetime('now','localtime'))",
            &[
                Value::from(title),
                opt(&input.description),
                opt(&input.expected_at),
                Value::from(priority),
                Value::from(next),
            ],
        )?;
        self.goal_get(id)?.context("创建后应能读到学习目标")
    }

    pub fn goal_update(&self, id: i64, patch: &GoalPatch) -> anyhow::Result<LearningGoal> {
        let cur = self
            .goal_get(id)?
            .with_context(|| format!("学习目标不存在：id={id}"))?;
        let status = match patch.status.as_deref() {
            Some(s) => normalize(Some(s), GOAL_STATUSES)?
                .context("状态不能为空")?,
            None => cur.status.clone(),
        };
        let priority = match patch.priority.as_deref() {
            Some(p) => normalize(Some(p), PRIORITIES)?.unwrap_or_else(|| "medium".into()),
            None => cur.priority.clone(),
        };
        self.db.exec(
            "UPDATE learning_goals SET title=?1, description=?2, status=?3, expected_at=?4, \
             priority=?5, updated_at=datetime('now','localtime') \
             WHERE id=?6 AND deleted_at IS NULL",
            &[
                Value::from(
                    patch
                        .title
                        .clone()
                        .unwrap_or(cur.title)
                        .trim()
                        .to_string(),
                ),
                opt(&patch.description.clone().or(cur.description)),
                Value::from(status),
                opt(&patch.expected_at.clone().or(cur.expected_at)),
                Value::from(priority),
                Value::from(id),
            ],
        )?;
        self.goal_get(id)?.context("编辑后应能读到学习目标")
    }

    /// 软删除（保留历史，与 apps / work_modes 一致的删除语义）。
    pub fn goal_delete(&self, id: i64) -> anyhow::Result<()> {
        let n = self.db.exec(
            "UPDATE learning_goals SET deleted_at=datetime('now','localtime'), \
             updated_at=datetime('now','localtime') WHERE id=?1 AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        if n == 0 {
            anyhow::bail!("学习目标不存在或已删除：id={id}");
        }
        Ok(())
    }

    /// 记录一次提醒（供 09 §5 的"最多 7 天一次"节流）。
    pub fn mark_reminded(&self, id: i64) -> anyhow::Result<()> {
        self.db.exec(
            "UPDATE learning_goals SET last_reminded_at=datetime('now','localtime') WHERE id=?1",
            &[Value::from(id)],
        )?;
        Ok(())
    }

    /// 保存 AI 原始输出快照（降级展示用）。**不触碰任何节点数据**。
    pub fn set_roadmap_raw(&self, id: i64, raw: Option<&str>) -> anyhow::Result<()> {
        self.db.exec(
            "UPDATE learning_goals SET roadmap=?1 WHERE id=?2 AND deleted_at IS NULL",
            &[opt(&raw.map(str::to_string)), Value::from(id)],
        )?;
        Ok(())
    }

    /// 供提醒调度器使用：需要"看是否久未更新"的目标（含未开始/学习中）。
    ///
    /// 只回 `not_started|learning` —— 暂停 / 完成 / 归档的用户**明确表示过不要打扰**
    /// （09 §5「点暂停后不再提醒」）。
    pub fn goals_watchable(&self) -> anyhow::Result<Vec<LearningGoal>> {
        Ok(self
            .goals_list()?
            .into_iter()
            .filter(|g| matches!(g.status.as_str(), "not_started" | "learning"))
            .collect())
    }

    // ------------------------------------------------------------ 路线节点

    pub fn nodes_list(&self, goal_id: i64) -> anyhow::Result<Vec<RoadmapNode>> {
        let rows = self.db.query_json(
            "SELECT id, goal_id, title, status, note, estimated, resources, sort_order, \
                    completed_at, created_at, updated_at \
             FROM learning_roadmap WHERE goal_id = ? ORDER BY sort_order ASC, id ASC",
            &[Value::from(goal_id)],
        )?;
        Ok(rows.iter().map(to_node).collect())
    }

    /// 确认采纳一条路线（09 §2 的最后一步：**确认后**才写入 `learning_roadmap`）。
    ///
    /// - `replace=false` 且该目标**已有节点** → 报错。这是刻意的：覆盖会丢掉用户
    ///   已标记的进度，属于**破坏性操作**（红线 V5），必须由 UI 显式二次确认后
    ///   才传 `replace=true`；不静默覆盖是这里唯一的正确默认值。
    /// - 全量替换在**一个事务**里完成（`Db::exec_many`），避免"删了一半"的半截路线。
    /// - `raw` = 被采纳的那版 AI 原始输出，存进 `learning_goals.roadmap` 作为快照。
    ///   它由**用户采纳动作**带来，不是 AI 自动写入（红线 V3）。
    pub fn roadmap_confirm(
        &self,
        goal_id: i64,
        nodes: &[NodeInput],
        replace: bool,
        raw: Option<&str>,
    ) -> anyhow::Result<Vec<RoadmapNode>> {
        self.goal_get(goal_id)?
            .with_context(|| format!("学习目标不存在：id={goal_id}"))?;
        if nodes.is_empty() {
            anyhow::bail!("路线至少要有一个节点");
        }
        let existing = self.nodes_list(goal_id)?;
        if !existing.is_empty() && !replace {
            anyhow::bail!(
                "该目标已有 {} 个节点。覆盖会重置已标记的进度，请显式确认覆盖",
                existing.len()
            );
        }

        let mut stmts: Vec<(String, Vec<Value>)> =
            vec![("DELETE FROM learning_roadmap WHERE goal_id = ?".into(), vec![Value::from(goal_id)])];
        for (i, n) in nodes.iter().enumerate() {
            let title = n.title.trim();
            if title.is_empty() {
                anyhow::bail!("第 {} 个节点缺少标题", i + 1);
            }
            let status = normalize(n.status.as_deref(), NODE_STATUSES)?
                .unwrap_or_else(|| "not_started".into());
            let completed = if status == "done" {
                Value::from("__now__")
            } else {
                Value::Null
            };
            stmts.push((
                "INSERT INTO learning_roadmap \
                 (goal_id, title, status, note, estimated, resources, sort_order, completed_at, created_at, updated_at) \
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, \
                         CASE WHEN ?8 = '__now__' THEN datetime('now','localtime') ELSE NULL END, \
                         datetime('now','localtime'), datetime('now','localtime'))"
                    .into(),
                vec![
                    Value::from(goal_id),
                    Value::from(title),
                    Value::from(status),
                    opt(&n.note),
                    opt(&n.estimated),
                    serde_json::to_value(&n.resources)?,
                    Value::from((i + 1) as i64),
                    completed,
                ],
            ));
        }
        self.db.exec_many(&stmts)?;
        // 记录"采纳的这版原文"（供重新生成时对比）—— 由用户采纳动作触发，非 AI 自动写
        self.set_roadmap_raw(goal_id, raw)?;
        self.touch_goal(goal_id)?;
        self.nodes_list(goal_id)
    }

    /// 追加单个节点（09 §2「用户可增删节点」）。
    pub fn node_add(&self, goal_id: i64, input: &NodeInput) -> anyhow::Result<RoadmapNode> {
        self.goal_get(goal_id)?
            .with_context(|| format!("学习目标不存在：id={goal_id}"))?;
        let title = input.title.trim();
        if title.is_empty() {
            anyhow::bail!("节点标题不能为空");
        }
        let next: i64 = self
            .db
            .query_json(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM learning_roadmap WHERE goal_id = ?",
                &[Value::from(goal_id)],
            )?
            .first()
            .and_then(|v| v.get("n"))
            .and_then(Value::as_i64)
            .unwrap_or(1);
        let status =
            normalize(input.status.as_deref(), NODE_STATUSES)?.unwrap_or_else(|| "not_started".into());
        let id = self.db.insert(
            "INSERT INTO learning_roadmap \
             (goal_id, title, status, note, estimated, resources, sort_order, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, datetime('now','localtime'), datetime('now','localtime'))",
            &[
                Value::from(goal_id),
                Value::from(title),
                Value::from(status),
                opt(&input.note),
                opt(&input.estimated),
                serde_json::to_value(&input.resources)?,
                Value::from(next),
            ],
        )?;
        self.node_get(id)?.context("创建后应能读到节点")
    }

    pub fn node_get(&self, id: i64) -> anyhow::Result<Option<RoadmapNode>> {
        let rows = self.db.query_json(
            "SELECT id, goal_id, title, status, note, estimated, resources, sort_order, \
                    completed_at, created_at, updated_at FROM learning_roadmap WHERE id = ?",
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_node))
    }

    /// 更新节点（**用户手动**改状态 / 改名 / 调序 / 附备注）。
    ///
    /// 返回 `(节点, 是否发生了状态变化)` —— 状态变化时调用方负责发
    /// `LEARNING_PROGRESS_UPDATED` 事件（契约 3.3）。
    pub fn node_update(&self, id: i64, patch: &NodePatch) -> anyhow::Result<(RoadmapNode, bool)> {
        let cur = self
            .node_get(id)?
            .with_context(|| format!("节点不存在：id={id}"))?;
        let status = match patch.status.as_deref() {
            Some(s) => normalize(Some(s), NODE_STATUSES)?
                .context("状态不能为空")?,
            None => cur.status.clone(),
        };
        let status_changed = status != cur.status;
        // 完成时间：进入 done 时补写；离开 done 时清空（否则"完成于"会留在错误的节点上）
        let completed_sql = if status == "done" && cur.completed_at.is_none() {
            "COALESCE(completed_at, datetime('now','localtime'))"
        } else if status == "done" {
            "completed_at"
        } else {
            "NULL"
        };
        let resources = match &patch.resources {
            Some(r) => serde_json::to_value(r)?,
            None => serde_json::to_value(&cur.resources)?,
        };
        self.db.exec(
            &format!(
                "UPDATE learning_roadmap SET title=?1, status=?2, note=?3, estimated=?4, \
                 resources=?5, sort_order=?6, completed_at={completed_sql}, \
                 updated_at=datetime('now','localtime') WHERE id=?7"
            ),
            &[
                Value::from(
                    patch.title.clone().unwrap_or(cur.title).trim().to_string(),
                ),
                Value::from(status),
                opt(&patch.note.clone().or(cur.note)),
                opt(&patch.estimated.clone().or(cur.estimated)),
                resources,
                Value::from(patch.sort_order.unwrap_or(cur.sort_order)),
                Value::from(id),
            ],
        )?;
        // 备注：写 learning_updates（09 §3「用户主动更新，可以附一条备注」）
        if let Some(note) = patch.note.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
            self.update_add(cur.goal_id, Some(id), note)?;
        }
        // 目标页有"最近更新"概念 → 节点变动也应刷新目标的 updated_at
        self.touch_goal(cur.goal_id)?;
        Ok((self.node_get(id)?.context("更新后应能读到节点")?, status_changed))
    }

    pub fn node_delete(&self, id: i64) -> anyhow::Result<()> {
        let cur = self
            .node_get(id)?
            .with_context(|| format!("节点不存在：id={id}"))?;
        self.db
            .exec("DELETE FROM learning_roadmap WHERE id = ?", &[Value::from(id)])?;
        // 重排剩余节点的 sort_order，避免出现空洞导致调序跳步
        let rest = self.nodes_list(cur.goal_id)?;
        let stmts: Vec<(String, Vec<Value>)> = rest
            .iter()
            .enumerate()
            .map(|(i, n)| {
                (
                    "UPDATE learning_roadmap SET sort_order = ?1 WHERE id = ?2".to_string(),
                    vec![Value::from((i + 1) as i64), Value::from(n.id)],
                )
            })
            .collect();
        if !stmts.is_empty() {
            self.db.exec_many(&stmts)?;
        }
        self.touch_goal(cur.goal_id)?;
        Ok(())
    }

    /// 上移 / 下移一个节点（09 §2「调顺序」）。
    pub fn node_move(&self, id: i64, delta: i64) -> anyhow::Result<Vec<RoadmapNode>> {
        let cur = self
            .node_get(id)?
            .with_context(|| format!("节点不存在：id={id}"))?;
        let mut list = self.nodes_list(cur.goal_id)?;
        let idx = list
            .iter()
            .position(|n| n.id == id)
            .context("节点不在路线中")?;
        let target = idx as i64 + delta;
        if target < 0 || target >= list.len() as i64 {
            return Ok(list); // 越界不动，不报错（按钮置灰由 UI 负责）
        }
        list.swap(idx, target as usize);
        let stmts: Vec<(String, Vec<Value>)> = list
            .iter()
            .enumerate()
            .map(|(i, n)| {
                (
                    "UPDATE learning_roadmap SET sort_order = ?1, updated_at=datetime('now','localtime') WHERE id = ?2"
                        .to_string(),
                    vec![Value::from((i + 1) as i64), Value::from(n.id)],
                )
            })
            .collect();
        self.db.exec_many(&stmts)?;
        self.nodes_list(cur.goal_id)
    }

    // ------------------------------------------------------------ 更新记录

    pub fn updates_list(&self, goal_id: i64, limit: i64) -> anyhow::Result<Vec<LearningUpdate>> {
        let rows = self.db.query_json(
            "SELECT id, goal_id, node_id, content, created_at FROM learning_updates \
             WHERE goal_id = ? ORDER BY id DESC LIMIT ?",
            &[Value::from(goal_id), Value::from(limit)],
        )?;
        Ok(rows
            .iter()
            .map(|v| LearningUpdate {
                id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
                goal_id: v.get("goal_id").and_then(Value::as_i64).unwrap_or(0),
                node_id: v.get("node_id").and_then(Value::as_i64),
                content: v
                    .get("content")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
                created_at: v
                    .get("created_at")
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_string(),
            })
            .collect())
    }

    pub fn update_add(
        &self,
        goal_id: i64,
        node_id: Option<i64>,
        content: &str,
    ) -> anyhow::Result<i64> {
        if content.trim().is_empty() {
            anyhow::bail!("更新内容不能为空");
        }
        self.db.insert(
            "INSERT INTO learning_updates (goal_id, node_id, content, created_at) \
             VALUES (?1, ?2, ?3, datetime('now','localtime'))",
            &[
                Value::from(goal_id),
                node_id.map(Value::from).unwrap_or(Value::Null),
                Value::from(content.trim()),
            ],
        )
    }

    // ------------------------------------------------------------ 内部

    fn touch_goal(&self, goal_id: i64) -> anyhow::Result<()> {
        self.db.exec(
            "UPDATE learning_goals SET updated_at=datetime('now','localtime') WHERE id=?1",
            &[Value::from(goal_id)],
        )?;
        Ok(())
    }

    /// 一次查询算出所有目标的 `(done, total)`，避免 list 时的 N+1。
    fn progress_map(&self) -> anyhow::Result<HashMap<i64, (i64, i64)>> {
        let rows = self.db.query_json(
            "SELECT goal_id, \
                    SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done, \
                    COUNT(*) AS total \
             FROM learning_roadmap GROUP BY goal_id",
            &[],
        )?;
        let mut map = HashMap::new();
        for v in rows {
            let gid = v.get("goal_id").and_then(Value::as_i64).unwrap_or(0);
            let done = v.get("done").and_then(Value::as_i64).unwrap_or(0);
            let total = v.get("total").and_then(Value::as_i64).unwrap_or(0);
            map.insert(gid, (done, total));
        }
        Ok(map)
    }

    fn progress_of(&self, goal_id: i64) -> anyhow::Result<(i64, i64)> {
        Ok(self.progress_map()?.get(&goal_id).copied().unwrap_or((0, 0)))
    }
}

// ---------------------------------------------------------------- helpers

fn id_of(v: &Value) -> i64 {
    v.get("id").and_then(Value::as_i64).unwrap_or(0)
}

/// 校验枚举值；空串/None → `None`（由调用方决定默认值）。
fn normalize(v: Option<&str>, allowed: &[&str]) -> anyhow::Result<Option<String>> {
    match v.map(str::trim) {
        None | Some("") => Ok(None),
        Some(s) if allowed.contains(&s) => Ok(Some(s.to_string())),
        Some(s) => anyhow::bail!("非法取值：{s}（可选 {allowed:?}）"),
    }
}

fn opt(v: &Option<String>) -> Value {
    match v {
        Some(s) if !s.trim().is_empty() => Value::from(s.trim()),
        _ => Value::Null,
    }
}

/// 取"JSON 存在 TEXT 列里"的字段 —— **必须二次解析**。
///
/// `Db::query_json` 只做一层 SQL→JSON 转换，TEXT 列拿到的是 `Value::String("[\"a\"]")`，
/// 不是 `Value::Array`。少了这步，`resources` 会永远是空数组
/// （同 `scheduler::repository::json_field`，那边是这个坑的首次记录）。
fn json_field(v: Option<&Value>) -> Value {
    match v {
        Some(Value::String(s)) => serde_json::from_str(s).unwrap_or(Value::Null),
        Some(other) => other.clone(),
        None => Value::Null,
    }
}

fn to_goal(v: &Value, prog: (i64, i64)) -> LearningGoal {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    LearningGoal {
        id: id_of(v),
        title: s("title").unwrap_or_default(),
        description: s("description"),
        status: s("status").unwrap_or_else(|| "not_started".into()),
        expected_at: s("expected_at"),
        priority: s("priority").unwrap_or_else(|| "medium".into()),
        roadmap_raw: s("roadmap"),
        last_reminded_at: s("last_reminded_at"),
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
        progress: Progress::new(prog.0, prog.1),
    }
}

fn to_node(v: &Value) -> RoadmapNode {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let resources = json_field(v.get("resources"));
    RoadmapNode {
        id: id_of(v),
        goal_id: v.get("goal_id").and_then(Value::as_i64).unwrap_or(0),
        title: s("title").unwrap_or_default(),
        status: s("status").unwrap_or_else(|| "not_started".into()),
        note: s("note"),
        estimated: s("estimated"),
        resources: resources
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|x| x.as_str().map(str::to_string))
                    .collect()
            })
            .unwrap_or_default(),
        sort_order: v.get("sort_order").and_then(Value::as_i64).unwrap_or(0),
        completed_at: s("completed_at"),
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo() -> (LearningRepo, std::path::PathBuf) {
        let dir = std::env::temp_dir().join(format!(
            "pw-learning-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        (LearningRepo::new(db), dir)
    }

    fn goal(r: &LearningRepo, title: &str) -> LearningGoal {
        r.goal_add(&GoalInput {
            title: title.into(),
            description: Some("测试目标".into()),
            expected_at: None,
            priority: Some("high".into()),
        })
        .unwrap()
    }

    fn nodes(titles: &[&str]) -> Vec<NodeInput> {
        titles
            .iter()
            .map(|t| NodeInput {
                title: (*t).into(),
                estimated: Some("2周".into()),
                resources: vec!["https://example.com/a".into()],
                ..Default::default()
            })
            .collect()
    }

    #[test]
    fn goal_crud_and_progress() {
        let (r, dir) = repo();
        let g = goal(&r, "学习计算机视觉");
        assert_eq!(g.status, "not_started");
        assert_eq!(g.priority, "high");
        assert_eq!(g.progress, Progress { done: 0, total: 0, percent: 0 });

        r.roadmap_confirm(g.id, &nodes(&["Python", "OpenCV", "CNN"]), false, Some("{\"nodes\":[]}"))
            .unwrap();
        let after = r.goal_get(g.id).unwrap().unwrap();
        assert_eq!(after.progress.total, 3, "进度总数应等于节点数");

        // 手动标记一个节点完成 → 进度随之变化
        let list = r.nodes_list(g.id).unwrap();
        let (_, changed) = r
            .node_update(
                list[0].id,
                &NodePatch {
                    status: Some("done".into()),
                    note: Some("看完基础语法".into()),
                    ..Default::default()
                },
            )
            .unwrap();
        assert!(changed);
        let g2 = r.goal_get(g.id).unwrap().unwrap();
        assert_eq!(g2.progress, Progress { done: 1, total: 3, percent: 33 });
        assert!(r.node_get(list[0].id).unwrap().unwrap().completed_at.is_some());

        // 备注应进 learning_updates
        let ups = r.updates_list(g.id, 10).unwrap();
        assert_eq!(ups.len(), 1);
        assert_eq!(ups[0].content, "看完基础语法");

        // 目标状态**不**随节点自动变化（红线 V3：系统不得自动改学习进度）
        assert_eq!(g2.status, "not_started");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn roadmap_confirm_refuses_silent_overwrite() {
        let (r, dir) = repo();
        let g = goal(&r, "重复采纳");
        r.roadmap_confirm(g.id, &nodes(&["A", "B"]), false, None).unwrap();
        // 已有节点时不带 replace ⇒ 必须拒绝（覆盖会重置进度，属破坏性操作）
        assert!(r
            .roadmap_confirm(g.id, &nodes(&["C"]), false, None)
            .unwrap_err()
            .to_string()
            .contains("显式确认覆盖"));
        // 显式覆盖 ⇒ 通过，且是全量替换（旧节点不残留）
        let after = r.roadmap_confirm(g.id, &nodes(&["C", "D"]), true, None).unwrap();
        assert_eq!(after.len(), 2);
        assert_eq!(after[0].title, "C");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn node_move_and_delete_reindex() {
        let (r, dir) = repo();
        let g = goal(&r, "调序");
        let list = r.roadmap_confirm(g.id, &nodes(&["A", "B", "C"]), false, None).unwrap();
        let moved = r.node_move(list[2].id, -1).unwrap();
        assert_eq!(
            moved.iter().map(|n| n.title.clone()).collect::<Vec<_>>(),
            vec!["A", "C", "B"]
        );
        // 越界不报错、原地不动
        let same = r.node_move(list[0].id, -1).unwrap();
        assert_eq!(same[0].title, "A");

        r.node_delete(list[0].id).unwrap();
        let rest = r.nodes_list(g.id).unwrap();
        assert_eq!(rest.len(), 2);
        assert_eq!(
            rest.iter().map(|n| n.sort_order).collect::<Vec<_>>(),
            vec![1, 2],
            "删除后 sort_order 必须重排，不留空洞"
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_illegal_values() {
        let (r, dir) = repo();
        assert!(r
            .goal_add(&GoalInput {
                title: "   ".into(),
                description: None,
                expected_at: None,
                priority: None,
            })
            .is_err(), "空标题必须被拒");
        let g = goal(&r, "枚举校验");
        assert!(r
            .goal_update(
                g.id,
                &GoalPatch {
                    status: Some("whatever".into()),
                    ..Default::default()
                }
            )
            .is_err());
        let n = r.node_add(g.id, &NodeInput { title: "X".into(), ..Default::default() }).unwrap();
        assert!(r
            .node_update(
                n.id,
                &NodePatch {
                    status: Some("finished".into()),
                    ..Default::default()
                }
            )
            .is_err());
        // 归档是目标的合法状态（09 §5 提醒动作）
        let arch = r
            .goal_update(
                g.id,
                &GoalPatch {
                    status: Some("archived".into()),
                    ..Default::default()
                },
            )
            .unwrap();
        assert_eq!(arch.status, "archived");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn soft_deleted_goal_is_invisible() {
        let (r, dir) = repo();
        let g = goal(&r, "待删");
        r.goal_delete(g.id).unwrap();
        assert!(r.goals_list().unwrap().is_empty());
        assert!(r.goal_get(g.id).unwrap().is_none());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn watchable_excludes_paused_and_archived() {
        let (r, dir) = repo();
        let a = goal(&r, "A");
        let b = goal(&r, "B");
        goal(&r, "C");
        r.goal_update(
            b.id,
            &GoalPatch {
                status: Some("paused".into()),
                ..Default::default()
            },
        )
        .unwrap();
        let w = r.goals_watchable().unwrap();
        assert_eq!(w.len(), 2, "暂停的目标不应进入提醒候选");
        assert!(w.iter().any(|g| g.id == a.id));
        assert!(!w.iter().any(|g| g.id == b.id));
        let _ = std::fs::remove_dir_all(&dir);
    }
}
