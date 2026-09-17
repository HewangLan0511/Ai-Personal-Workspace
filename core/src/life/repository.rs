//! `usage_stats` 表读写（11 §A4 / 迁移 0007）。
//!
//! 聚合口径：主键 (day, app_name)，`add_seconds` 累加 —— 只存聚合结果，
//! 不存前台切换的时间点明细（数据轻量化，11 §A4）。

use serde_json::Value;

use crate::db::Db;

pub struct UsageRepo {
    db: Db,
}

/// 单应用使用统计行。
#[derive(Debug, Clone, serde::Serialize)]
pub struct UsageRow {
    pub app_name: String,
    pub seconds: i64,
}

impl UsageRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// 累加某天某应用的前台秒数（UPSERT）。
    pub fn add_seconds(&self, day: &str, app_name: &str, seconds: i64) -> anyhow::Result<()> {
        let name = app_name.to_lowercase();
        self.db.exec(
            "INSERT INTO usage_stats(day, app_name, seconds) VALUES(?1, ?2, ?3)
             ON CONFLICT(day, app_name) DO UPDATE SET seconds = seconds + ?3",
            &[Value::from(day), Value::from(name.as_str()), Value::from(seconds)],
        )?;
        Ok(())
    }

    /// 某天的总前台秒数。
    pub fn total_seconds(&self, day: &str) -> anyhow::Result<i64> {
        let rows = self.db.query_json(
            "SELECT COALESCE(SUM(seconds), 0) AS total FROM usage_stats WHERE day = ?1",
            &[Value::from(day)],
        )?;
        Ok(rows.first().and_then(|r| r.get("total")).and_then(|v| v.as_i64()).unwrap_or(0))
    }

    /// 某天按秒数倒序的排行（"今日使用时长排行"）。
    pub fn ranking(&self, day: &str, limit: i64) -> anyhow::Result<Vec<UsageRow>> {
        let rows = self.db.query_json(
            "SELECT app_name, seconds FROM usage_stats WHERE day = ?1
             ORDER BY seconds DESC LIMIT ?2",
            &[Value::from(day), Value::from(limit)],
        )?;
        Ok(rows
            .into_iter()
            .filter_map(|r| {
                Some(UsageRow {
                    app_name: r.get("app_name")?.as_str()?.to_string(),
                    seconds: r.get("seconds")?.as_i64()?,
                })
            })
            .collect())
    }

    /// 最近 N 天的每日总量（周趋势图数据源；不含未来/空天）。
    pub fn daily_totals(&self, days: i64) -> anyhow::Result<Vec<Value>> {
        let rows = self.db.query_json(
            "SELECT day, SUM(seconds) AS total FROM usage_stats
             WHERE day >= date('now', 'localtime', ?1) GROUP BY day ORDER BY day ASC",
            &[Value::from(format!("-{days} days"))],
        )?;
        Ok(rows)
    }

    /// 某应用近 N 天的每日秒数（周趋势 per-app，B4/健康页可选用）。
    #[allow(dead_code)]
    pub fn daily_for_app(&self, app_name: &str, days: i64) -> anyhow::Result<Vec<Value>> {
        let name = app_name.to_lowercase();
        self.db.query_json(
            "SELECT day, seconds FROM usage_stats WHERE app_name = ?1
             AND day >= date('now', 'localtime', ?2) ORDER BY day ASC",
            &[Value::from(name.as_str()), Value::from(format!("-{days} days"))],
        )
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mem_db() -> UsageRepo {
        // 与 profile::repository 测试同模式：临时目录真实文件（Db 无内存构造器）
        let dir = std::env::temp_dir().join(format!("pw-life-test-{}-{}", std::process::id(), std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().subsec_nanos()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        UsageRepo::new(db)
    }

    #[test]
    fn add_seconds_accumulates_and_ranks() {
        let r = mem_db();
        r.add_seconds("2026-09-13", "Code.exe", 30).unwrap();
        r.add_seconds("2026-09-13", "code.exe", 60).unwrap(); // 大小写归一
        r.add_seconds("2026-09-13", "chrome.exe", 10).unwrap();

        let rows = r.ranking("2026-09-13", 10).unwrap();
        assert_eq!(rows.len(), 2);
        assert_eq!(rows[0].app_name, "code.exe");
        assert_eq!(rows[0].seconds, 90);
        assert_eq!(rows[1].seconds, 10);
        assert_eq!(r.total_seconds("2026-09-13").unwrap(), 100);
    }

    #[test]
    fn days_are_isolated() {
        let r = mem_db();
        r.add_seconds("2026-09-12", "a.exe", 30).unwrap();
        r.add_seconds("2026-09-13", "a.exe", 45).unwrap();
        assert_eq!(r.total_seconds("2026-09-13").unwrap(), 45);
        let totals = r.daily_totals(7).unwrap();
        assert_eq!(totals.len(), 2);
    }
}
