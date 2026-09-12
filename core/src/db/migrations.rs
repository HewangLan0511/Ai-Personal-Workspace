//! 迁移执行器：按版本号顺序执行 `core/migrations/` 内嵌脚本，只增不改。
//!
//! **两套版本号必须分开（REVIEW-002 R-01 修复要点）**：
//! - `db.migration_version` —— 迁移台账，记录**已执行的 DDL 脚本序号**，只有本模块写；
//! - `config.schema_version` —— **数据契约版本**（03 §3.5），只有 `db::initialize` 按常量写。
//!
//! 原实现把两者混用同一个键：`migrations::run()` 写入 1，种子再写 2（被 `INSERT OR IGNORE`
//! 忽略），结果是「契约版本」永远停在 1，同时"某迁移是否已执行"的判据也失真。

use super::Db;

/// 数据契约版本，与 `03-数据契约与接口规范.md` 底部「变更记录」的最后一版一致。
/// 契约改一次，这里 +1。
pub const CONTRACT_SCHEMA_VERSION: i64 = 3;

/// 迁移台账键（内部使用，不对用户开放，故**不**登记进 `config.rs` 的 KEYS）。
const MIGRATION_VERSION_KEY: &str = "db.migration_version";

/// 迁移清单：(目标版本, 脚本)。新迁移只允许追加。
const MIGRATIONS: &[(i64, &str)] = &[(1, include_str!("../../migrations/0001_init.sql"))];

/// 种子数据：首次建库时写入默认配置项（database/seeds/）。
pub const SEED_DEFAULT_CONFIG: &str = include_str!("../../../database/seeds/0001_default_config.sql");

pub fn run(db: &Db) -> anyhow::Result<()> {
    let current = read_migration_version(db)?;
    for (version, script) in MIGRATIONS {
        if *version > current {
            db.exec_script(script)?;
            db.kv_set(MIGRATION_VERSION_KEY, &version.to_string())?;
            tracing::info!(version, "已应用迁移");
        }
    }
    Ok(())
}

fn read_migration_version(db: &Db) -> anyhow::Result<i64> {
    // 首次运行时 config 表可能还不存在（0001 之前的空库）。
    let exists: bool = db
        .query_json(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'config'",
            &[],
        )?
        .iter()
        .any(|row| row.get("name").and_then(|v| v.as_str()) == Some("config"));
    if !exists {
        return Ok(0);
    }
    match db.kv_get(MIGRATION_VERSION_KEY)? {
        Some(raw) => Ok(raw.parse().unwrap_or(0)),
        None => Ok(0),
    }
}
