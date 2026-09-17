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
///
/// 版本对照：v5 = 阶段4 `mode.*` / `ai.active_profile` 三个 config 键；
/// v6 = 阶段4 迁移 0004（`layouts.ai_sidebar` 列）；
/// v7 = **阶段5** `ui.ai.*` 五个侧栏持久化键 + `/ai/*` 端点登记（**无表结构变更，故无迁移**）；
/// v8 = **阶段6** `projects` 表 + `learning_goals` / `learning_roadmap` 补列（迁移 0005）
///      + `learning.remind_*` 两个 config 键；
/// v9 = **阶段7** `pending_suggestions` 表 + `profile_skills.category` 列（迁移 0006）
///      + `profile.rejected_kinds` config 键；
/// v10 = **阶段8** `usage_stats` 表（迁移 0007）+ `life.*` / `device.*` config 键；
/// v11 = **阶段9** `plugin_audit` 表（迁移 0008）+ `agents.external` / `widget.desktop.*` config 键。
/// v12 = **TECH-04 §一** 登记 canonical 正式落点 `ai.provider.current` / `ai.model.current`
///      （**无表结构变更，故无迁移**）。这两个键是 PW-INTEGRATION-003 冻结契约指定的 L1 键，
///      TECH-03-A/B 期间未登记 ⇒ canonical 只能落过渡镜像键 `ui.ai.*`；本轮正式登记后
///      L1 成为唯一落点，旧镜像键保留兼容（迁移路径见 `ui/src/ai/model/bridge.ts`）。
/// v13 = **TECH-06-B Part 1** 登记模型清单唯一持久化键 `ai.models.registry`
///      （string 存 JSON，形态见 `ui/src/ai/model/archive.ts`；**无表结构变更，故无迁移**）。
///      读写只经 `ModelRegistry` 的 archive 端口；恢复出的模型一律回到「未测试」
///      （探测状态不持久化 —— 反假绿，见 archive.ts 文件头）。
pub const CONTRACT_SCHEMA_VERSION: i64 = 13;

/// 迁移台账键（内部使用，不对用户开放，故**不**登记进 `config.rs` 的 KEYS）。
const MIGRATION_VERSION_KEY: &str = "db.migration_version";

/// 迁移清单：(目标版本, 脚本)。新迁移只允许追加。
const MIGRATIONS: &[(i64, &str)] = &[
    (1, include_str!("../../migrations/0001_init.sql")),
    (2, include_str!("../../migrations/0002_apps_pinned.sql")),
    (3, include_str!("../../migrations/0003_work_modes_switch_policy.sql")),
    (4, include_str!("../../migrations/0004_layouts_ai_sidebar.sql")),
    (5, include_str!("../../migrations/0005_learning_projects.sql")),
    (6, include_str!("../../migrations/0006_profile.sql")),
    (7, include_str!("../../migrations/0007_life_device.sql")),
    (8, include_str!("../../migrations/0008_plugin_audit.sql")),
];

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
