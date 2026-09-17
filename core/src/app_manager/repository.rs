//! `apps` 表的唯一读写入口。
//!
//! 红线（02 §2.4）：**数据库的唯一写入者是 Rust core** —— UI / modules / plugins /
//! Python sidecar 一律不直接写库，只能经 core 的接口。本模块即 core 侧的写入口。
//!
//! 契约依据：`03-数据契约与接口规范.md` §3.2.3（软件条目字段）。
//! 迁移依据：`core/migrations/0002_apps_pinned.sql`（pinned 字段）。

use anyhow::Context;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::db::Db;

/// 预置分类（05 §1「分类」）。用户可新增自定义分类，此处只是默认建议。
pub const PRESET_CATEGORIES: &[&str] = &["开发", "浏览器", "办公", "媒体", "游戏", "其他"];

/// 入库/出参形态（apps 表全字段）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppRow {
    pub id: i64,
    pub name: String,
    pub path: String,
    pub args: String,
    pub icon: Option<String>,
    #[serde(rename = "type")]
    pub kind: Option<String>,
    pub category: Option<String>,
    pub launch_count: i64,
    pub last_used_at: Option<String>,
    pub pinned: bool,
    pub created_at: String,
    pub updated_at: String,
}

/// 新增入参（契约 3.2.3）。
#[derive(Debug, Clone, Deserialize)]
pub struct AppInput {
    pub name: String,
    pub path: String,
    #[serde(default)]
    pub args: String,
    #[serde(default)]
    pub icon: Option<String>,
    #[serde(rename = "type", default)]
    pub kind: Option<String>,
    #[serde(default)]
    pub category: Option<String>,
}

/// 编辑入参：只覆盖显式给出的字段（未给 = 不改）。
#[derive(Debug, Clone, Default, Deserialize)]
pub struct AppPatch {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub args: Option<String>,
    #[serde(default)]
    pub icon: Option<String>,
    #[serde(rename = "type", default)]
    pub kind: Option<String>,
    #[serde(default)]
    pub category: Option<String>,
    #[serde(default)]
    pub pinned: Option<bool>,
}

const COLS: &str = "id, name, path, args, icon, \"type\", category, launch_count, \
                    last_used_at, pinned, created_at, updated_at";

#[derive(Clone)]
pub struct AppsRepo {
    db: Db,
}

impl AppsRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// 列表查询：软删除过滤 + 分类过滤 + 名称模糊搜索。
    ///
    /// 排序（05 §4）：`pinned DESC` → `launch_count DESC` → `last_used_at DESC` → `name ASC`。
    /// Dashboard「常用软件」Widget 直接消费这个顺序。
    pub fn list(&self, category: Option<&str>, search: Option<&str>) -> anyhow::Result<Vec<AppRow>> {
        let mut sql = format!("SELECT {COLS} FROM apps WHERE deleted_at IS NULL");
        let mut params: Vec<Value> = Vec::new();

        if let Some(c) = category.filter(|c| !c.is_empty()) {
            sql.push_str(" AND category = ?");
            params.push(Value::from(c));
        }
        if let Some(s) = search.filter(|s| !s.trim().is_empty()) {
            // LIKE 通配转义：避免用户输入的 % _ 被当通配符
            let escaped = s.trim().replace('\\', "\\\\").replace('%', "\\%").replace('_', "\\_");
            sql.push_str(" AND (name LIKE ? ESCAPE '\\' OR path LIKE ? ESCAPE '\\')");
            params.push(Value::from(format!("%{escaped}%")));
            params.push(Value::from(format!("%{escaped}%")));
        }
        sql.push_str(" ORDER BY pinned DESC, launch_count DESC, last_used_at DESC, name ASC");

        let rows = self.db.query_json(&sql, &params)?;
        Ok(rows.iter().map(to_row).collect())
    }

    pub fn get(&self, id: i64) -> anyhow::Result<Option<AppRow>> {
        let rows = self.db.query_json(
            &format!("SELECT {COLS} FROM apps WHERE id = ? AND deleted_at IS NULL"),
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_row))
    }

    /// 新增。
    ///
    /// `path` 有 UNIQUE 约束。若同路径的记录曾被**软删除**，这里做"复活"而非报错
    /// —— 否则用户删掉再加会撞 UNIQUE，体验上无解。
    pub fn add(&self, input: &AppInput) -> anyhow::Result<AppRow> {
        if let Some(existing) = self.find_by_path_including_deleted(&input.path)? {
            let id = existing.get("id").and_then(Value::as_i64).unwrap_or(0);
            let deleted = existing.get("deleted_at").map(|v| !v.is_null()).unwrap_or(false);
            if !deleted {
                anyhow::bail!("该路径已在软件库中：{}", input.name);
            }
            self.db.exec(
                "UPDATE apps SET name=?1, args=?2, icon=?3, \"type\"=?4, category=?5, \
                 deleted_at=NULL, updated_at=datetime('now','localtime') WHERE id=?6",
                &[
                    Value::from(input.name.as_str()),
                    Value::from(input.args.as_str()),
                    opt(&input.icon),
                    opt(&input.kind),
                    opt(&input.category),
                    Value::from(id),
                ],
            )?;
            return self
                .get(id)?
                .context("复活后应能查到该软件");
        }

        let id = self.db.insert(
            "INSERT INTO apps (name, path, args, icon, \"type\", category, created_at, updated_at) \
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, datetime('now','localtime'), datetime('now','localtime'))",
            &[
                Value::from(input.name.as_str()),
                Value::from(input.path.as_str()),
                Value::from(input.args.as_str()),
                opt(&input.icon),
                opt(&input.kind),
                opt(&input.category),
            ],
        )?;
        self.get(id)?.context("新增后应能查到该软件")
    }

    /// 编辑：只覆盖显式给出的字段。
    pub fn update(&self, id: i64, patch: &AppPatch) -> anyhow::Result<AppRow> {
        let current = self.get(id)?.with_context(|| format!("软件不存在：id={id}"))?;

        let name = patch.name.clone().unwrap_or(current.name);
        let args = patch.args.clone().unwrap_or(current.args);
        let icon = patch.icon.clone().or(current.icon);
        let kind = patch.kind.clone().or(current.kind);
        let category = patch.category.clone().or(current.category);
        let pinned = patch.pinned.unwrap_or(current.pinned);

        self.db.exec(
            "UPDATE apps SET name=?1, args=?2, icon=?3, \"type\"=?4, category=?5, pinned=?6, \
             updated_at=datetime('now','localtime') WHERE id=?7 AND deleted_at IS NULL",
            &[
                Value::from(name.as_str()),
                Value::from(args.as_str()),
                opt(&icon),
                opt(&kind),
                opt(&category),
                Value::from(if pinned { 1 } else { 0 }),
                Value::from(id),
            ],
        )?;
        self.get(id)?.context("编辑后应能查到该软件")
    }

    /// 软删除（写 `deleted_at`，不物理删行 —— 便于追溯与"复活"）。
    pub fn soft_delete(&self, id: i64) -> anyhow::Result<()> {
        let n = self.db.exec(
            "UPDATE apps SET deleted_at=datetime('now','localtime'), \
             updated_at=datetime('now','localtime') WHERE id=?1 AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        if n == 0 {
            anyhow::bail!("软件不存在或已删除：id={id}");
        }
        Ok(())
    }

    /// 记录一次启动（05 §2：更新 launch_count / last_used_at）。
    pub fn touch_launch(&self, id: i64) -> anyhow::Result<()> {
        self.db.exec(
            "UPDATE apps SET launch_count = launch_count + 1, \
             last_used_at = datetime('now','localtime'), \
             updated_at = datetime('now','localtime') WHERE id=?1 AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        Ok(())
    }

    /// 分类清单：预置 + 用户已用过的自定义分类（去重，保序）。
    pub fn categories(&self) -> anyhow::Result<Vec<String>> {
        let rows = self.db.query_json(
            "SELECT DISTINCT category FROM apps \
             WHERE deleted_at IS NULL AND category IS NOT NULL AND category <> '' \
             ORDER BY category ASC",
            &[],
        )?;
        let mut out: Vec<String> = PRESET_CATEGORIES.iter().map(|s| s.to_string()).collect();
        for r in rows {
            if let Some(c) = r.get("category").and_then(Value::as_str) {
                if !out.iter().any(|x| x == c) {
                    out.push(c.to_string());
                }
            }
        }
        Ok(out)
    }

    fn find_by_path_including_deleted(&self, path: &str) -> anyhow::Result<Option<Value>> {
        let rows = self
            .db
            .query_json("SELECT id, deleted_at FROM apps WHERE path = ?", &[Value::from(path)])?;
        Ok(rows.into_iter().next())
    }
}

/// `Option<String>` → JSON（None → Null）。
fn opt(v: &Option<String>) -> Value {
    match v {
        Some(s) => Value::from(s.as_str()),
        None => Value::Null,
    }
}

/// JSON 行 → `AppRow`。
fn to_row(v: &Value) -> AppRow {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let n = |k: &str| v.get(k).and_then(Value::as_i64);
    AppRow {
        id: n("id").unwrap_or(0),
        name: s("name").unwrap_or_default(),
        path: s("path").unwrap_or_default(),
        args: s("args").unwrap_or_default(),
        icon: s("icon"),
        kind: s("type"),
        category: s("category"),
        launch_count: n("launch_count").unwrap_or(0),
        last_used_at: s("last_used_at"),
        pinned: n("pinned").unwrap_or(0) != 0,
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 排序规则是 05 §4 的硬要求，且 Dashboard Widget 直接消费它 —— 用真实 SQLite 锁死。
    #[test]
    fn list_orders_by_pinned_then_launch_count() {
        let dir = std::env::temp_dir().join(format!("pw-apps-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        let repo = AppsRepo::new(db);

        let mk = |name: &str| AppInput {
            name: name.to_string(),
            path: format!("C:/fake/{name}.exe"),
            args: String::new(),
            icon: None,
            kind: Some("exe".into()),
            category: Some("开发".into()),
        };
        let a = repo.add(&mk("A")).unwrap();
        let b = repo.add(&mk("B")).unwrap();
        let c = repo.add(&mk("C")).unwrap();

        repo.touch_launch(b.id).unwrap();
        repo.touch_launch(b.id).unwrap();
        repo.touch_launch(c.id).unwrap();
        repo.update(a.id, &AppPatch { pinned: Some(true), ..Default::default() }).unwrap();

        let names: Vec<String> = repo.list(None, None).unwrap().into_iter().map(|r| r.name).collect();
        // A 置顶；B 用 2 次 > C 用 1 次
        assert_eq!(names, vec!["A", "B", "C"], "顺序应为 pinned → launch_count");

        // 搜索（转义）
        let hit = repo.list(None, Some("B")).unwrap();
        assert_eq!(hit.len(), 1);
        assert_eq!(hit[0].name, "B");

        // 软删除后不再出现，且同路径可"复活"
        repo.soft_delete(a.id).unwrap();
        assert_eq!(repo.list(None, None).unwrap().len(), 2);
        let revived = repo.add(&mk("A")).unwrap();
        assert_eq!(revived.id, a.id, "软删除后同路径应复活原记录，而非新建");
        assert_eq!(repo.list(None, None).unwrap().len(), 3);

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// 未登记的 path 重复添加（未删除）必须被拒绝，而不是撞出 SQL 层错误。
    #[test]
    fn duplicate_active_path_is_rejected_with_friendly_error() {
        let dir = std::env::temp_dir().join(format!("pw-apps-dup-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        let repo = AppsRepo::new(db);

        let input = AppInput {
            name: "Dup".into(),
            path: "C:/fake/dup.exe".into(),
            args: String::new(),
            icon: None,
            kind: None,
            category: None,
        };
        repo.add(&input).unwrap();
        let err = repo.add(&input).unwrap_err().to_string();
        assert!(err.contains("已在软件库"), "错误信息应可读，实际：{err}");

        let _ = std::fs::remove_dir_all(&dir);
    }
}
