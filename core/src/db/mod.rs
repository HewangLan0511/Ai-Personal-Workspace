//! 数据库访问层：SQLite 的唯一写入者（02 §2.4 红线）。
//!
//! - migration 只增不改（契约 3.1），脚本在 `core/migrations/`
//! - 种子数据在 `database/seeds/`（首次建库后执行）
//! - UI / modules / plugins / Python sidecar 一律不直接写库

mod config;
mod migrations;

pub use config::ConfigService;

use std::path::Path;
use std::sync::Mutex;

use anyhow::Context;
use rusqlite::Connection;

/// 写入白名单表（契约 3.4 `/internal/db/exec` 仅限白名单）。
/// 阶段1 只开放 config；后续阶段按需扩表并同步契约。
pub const WRITABLE_TABLES: &[&str] = &["config"];

#[derive(Clone)]
pub struct Db {
    conn: std::sync::Arc<Mutex<Connection>>,
}

impl Db {
    pub fn open(path: &Path) -> anyhow::Result<Self> {
        let conn = Connection::open(path)
            .with_context(|| format!("打开数据库失败: {}", path.display()))?;
        conn.execute_batch("PRAGMA journal_mode = WAL; PRAGMA foreign_keys = ON;")?;
        Ok(Self {
            conn: std::sync::Arc::new(Mutex::new(conn)),
        })
    }

    /// 首次建库：跑 migration + 种子数据 + 落契约版本。
    ///
    /// 修复（REVIEW-002 R-01）：原实现用 `is_fresh()`（`COUNT(*) FROM config == 0`）决定是否播种，
    /// 但 `migrations::run()` 已先行写入 `schema_version` 行 → 该判定恒为 false → 种子永不执行。
    /// 种子脚本全部是 `INSERT OR IGNORE`，重复执行无副作用，故直接执行、不再判空。
    ///
    /// 另修（L-006）：`schema_version`（契约版本）改由代码按常量写入 ——
    /// 单一所有者，避免与迁移台账（`db.migration_version`）混用一个键。
    pub fn initialize(&self) -> anyhow::Result<()> {
        migrations::run(self)?;
        self.exec_script(migrations::SEED_DEFAULT_CONFIG)?;
        self.kv_set(
            config::SCHEMA_VERSION_KEY,
            &migrations::CONTRACT_SCHEMA_VERSION.to_string(),
        )?;
        Ok(())
    }

    fn lock(&self) -> std::sync::MutexGuard<'_, Connection> {
        // 锁中毒意味着持锁线程崩溃，重启进程即可恢复；这里直接重建。
        match self.conn.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        }
    }

    /// 执行内嵌 SQL 脚本（migration / 种子，来源可信）。
    pub fn exec_script(&self, sql: &str) -> anyhow::Result<()> {
        let conn = self.lock();
        conn.execute_batch(sql)?;
        Ok(())
    }

    /// 参数化只读查询（契约 3.4 `/internal/db/query` 底层）。
    pub fn query_json(
        &self,
        sql: &str,
        params: &[serde_json::Value],
    ) -> anyhow::Result<Vec<serde_json::Value>> {
        let conn = self.lock();
        let mut stmt = conn.prepare(sql)?;
        let cols: Vec<String> = stmt.column_names().into_iter().map(String::from).collect();
        let mut rows = stmt.query(rusqlite::params_from_iter(params.iter().map(to_rusqlite)))?;
        let mut out = Vec::new();
        while let Some(row) = rows.next()? {
            let mut obj = serde_json::Map::new();
            for (i, col) in cols.iter().enumerate() {
                let v: serde_json::Value = match row.get_ref(i)? {
                    rusqlite::types::ValueRef::Null => serde_json::Value::Null,
                    rusqlite::types::ValueRef::Integer(n) => serde_json::Value::from(n),
                    rusqlite::types::ValueRef::Real(f) => serde_json::Value::from(f),
                    rusqlite::types::ValueRef::Text(t) => {
                        serde_json::Value::from(String::from_utf8_lossy(t).into_owned())
                    }
                    rusqlite::types::ValueRef::Blob(b) => {
                        serde_json::Value::from(String::from_utf8_lossy(b).into_owned())
                    }
                };
                obj.insert(col.clone(), v);
            }
            out.push(serde_json::Value::Object(obj));
        }
        Ok(out)
    }

    /// 参数化写入（契约 3.4 `/internal/db/exec` 底层；表白名单在 api 层校验）。
    pub fn exec(&self, sql: &str, params: &[serde_json::Value]) -> anyhow::Result<u64> {
        let conn = self.lock();
        let affected = conn.execute(sql, rusqlite::params_from_iter(params.iter().map(to_rusqlite)))?;
        Ok(affected as u64)
    }

    /// KV 直读（config 表专用）。
    pub fn kv_get(&self, key: &str) -> anyhow::Result<Option<String>> {
        let conn = self.lock();
        let value: Option<String> = conn
            .query_row("SELECT value FROM config WHERE key = ?1", [key], |row| {
                row.get(0)
            })
            .map(Some)
            .or_else(|err| match err {
                rusqlite::Error::QueryReturnedNoRows => Ok(None),
                other => Err(other),
            })?;
        Ok(value)
    }

    /// KV 直写（config 表专用，UPSERT）。
    pub fn kv_set(&self, key: &str, value: &str) -> anyhow::Result<()> {
        let conn = self.lock();
        conn.execute(
            "INSERT INTO config (key, value, updated_at) VALUES (?1, ?2, datetime('now', 'localtime'))
             ON CONFLICT(key) DO UPDATE SET value = ?2, updated_at = datetime('now', 'localtime')",
            [key, value],
        )?;
        Ok(())
    }
}

/// JSON 值 → rusqlite 参数。
fn to_rusqlite(v: &serde_json::Value) -> rusqlite::types::Value {
    use rusqlite::types::Value as RV;
    match v {
        serde_json::Value::Null => RV::Null,
        serde_json::Value::Bool(b) => RV::Integer(if *b { 1 } else { 0 }),
        serde_json::Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                RV::Integer(i)
            } else {
                RV::Real(n.as_f64().unwrap_or_default())
            }
        }
        serde_json::Value::String(s) => RV::Text(s.clone()),
        other => RV::Text(other.to_string()),
    }
}
