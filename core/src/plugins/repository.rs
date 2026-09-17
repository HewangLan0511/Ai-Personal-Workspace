//! `plugins` / `plugin_permissions` / `plugin_audit` 三表读写（迁移 0001 预设 + 0008）。
//!
//! 权限的**权威数据**在这里：`plugin_permissions` 由安装（用户确认 manifest 权限清单）写入，
//! 由网关（`plugins::api_call`）与撤销操作读写。卸载插件时 `plugins` / `plugin_permissions`
//! 行**物理删除**（12 §验收5"数据库无残留"），`plugin_audit` 行保留（审计是历史事实，
//! 随插件删除会掩盖越权记录）。

use serde_json::Value;

use crate::db::Db;

pub struct PluginRepo {
    db: Db,
}

/// `plugins` 表行。
#[derive(Debug, Clone, serde::Serialize)]
pub struct PluginRow {
    #[serde(rename = "pluginId")]
    pub plugin_id: String,
    pub name: String,
    pub version: String,
    pub author: Option<String>,
    pub entry: String,
    pub enabled: bool,
    #[serde(rename = "installedAt")]
    pub installed_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

/// 已授予权限行（permission + scope，scope 空串 = 无范围）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct PermRow {
    pub permission: String,
    pub scope: String,
}

fn iso_now() -> String {
    crate::event_bus::iso_now()
}

impl PluginRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    // ---- plugins 表 ------------------------------------------------------

    pub fn list(&self) -> anyhow::Result<Vec<PluginRow>> {
        let rows = self.db.query_json(
            "SELECT plugin_id, name, version, author, entry, enabled, installed_at, updated_at
             FROM plugins ORDER BY installed_at ASC",
            &[],
        )?;
        Ok(rows.into_iter().filter_map(|r| row_to_plugin(r)).collect())
    }

    pub fn get(&self, plugin_id: &str) -> anyhow::Result<Option<PluginRow>> {
        let rows = self.db.query_json(
            "SELECT plugin_id, name, version, author, entry, enabled, installed_at, updated_at
             FROM plugins WHERE plugin_id = ?1",
            &[Value::from(plugin_id)],
        )?;
        Ok(rows.into_iter().next().and_then(row_to_plugin))
    }

    /// 安装登记（enabled=0；授权在 `grant_all`，由用户确认 manifest 权限清单后触发）。
    pub fn insert(
        &self,
        plugin_id: &str,
        name: &str,
        version: &str,
        author: &str,
        entry: &str,
    ) -> anyhow::Result<()> {
        let now = iso_now();
        self.db.exec(
            "INSERT INTO plugins(plugin_id, name, version, author, entry, enabled, installed_at, updated_at)
             VALUES(?1, ?2, ?3, ?4, ?5, 0, ?6, ?6)",
            &[
                Value::from(plugin_id),
                Value::from(name),
                Value::from(version),
                Value::from(author),
                Value::from(entry),
                Value::from(now.as_str()),
            ],
        )?;
        Ok(())
    }

    pub fn set_enabled(&self, plugin_id: &str, enabled: bool) -> anyhow::Result<()> {
        self.db.exec(
            "UPDATE plugins SET enabled = ?2, updated_at = ?3 WHERE plugin_id = ?1",
            &[
                Value::from(plugin_id),
                Value::from(enabled),
                Value::from(iso_now().as_str()),
            ],
        )?;
        Ok(())
    }

    /// 物理删除（12 §验收5）：`plugins` 行 + `plugin_permissions` 行一并删除
    /// （授权随插件消失；审计行**保留**，见 `audit_list`）。返回删除的行数（0 = 不存在）。
    pub fn delete(&self, plugin_id: &str) -> anyhow::Result<usize> {
        let before = self
            .db
            .query_json("SELECT COUNT(*) AS n FROM plugins WHERE plugin_id = ?1", &[Value::from(plugin_id)])?;
        let n = before.first().and_then(|r| r.get("n")).and_then(|v| v.as_i64()).unwrap_or(0);
        if n == 0 {
            return Ok(0);
        }
        self.db
            .exec("DELETE FROM plugins WHERE plugin_id = ?1", &[Value::from(plugin_id)])?;
        self.delete_permissions(plugin_id)?;
        Ok(n as usize)
    }

    // ---- plugin_permissions 表 -------------------------------------------

    pub fn permissions(&self, plugin_id: &str) -> anyhow::Result<Vec<PermRow>> {
        let rows = self.db.query_json(
            "SELECT permission, COALESCE(scope, '') AS scope
             FROM plugin_permissions WHERE plugin_id = ?1 ORDER BY permission ASC, scope ASC",
            &[Value::from(plugin_id)],
        )?;
        Ok(rows
            .into_iter()
            .filter_map(|r| {
                Some(PermRow {
                    permission: r.get("permission")?.as_str()?.to_string(),
                    scope: r.get("scope")?.as_str().unwrap_or("").to_string(),
                })
            })
            .collect())
    }

    /// 安装确认时按 manifest 声明批量授权（先清后写，重复安装同 id 幂等）。
    pub fn grant_all(&self, plugin_id: &str, perms: &[PermRow]) -> anyhow::Result<()> {
        self.db.exec(
            "DELETE FROM plugin_permissions WHERE plugin_id = ?1",
            &[Value::from(plugin_id)],
        )?;
        let now = iso_now();
        for p in perms {
            let scope = if p.scope.is_empty() { None } else { Some(p.scope.as_str()) };
            self.db.exec(
                "INSERT OR IGNORE INTO plugin_permissions(plugin_id, permission, scope, granted_at)
                 VALUES(?1, ?2, ?3, ?4)",
                &[
                    Value::from(plugin_id),
                    Value::from(p.permission.as_str()),
                    scope.map(Value::from).unwrap_or(Value::Null),
                    Value::from(now.as_str()),
                ],
            )?;
        }
        Ok(())
    }

    /// 撤销单项权限。撤销后调用方负责禁用插件（12 §A3：撤销即禁用）。
    /// 当前管理页未暴露撤销入口（权限=manifest 声明，重装即改）；保留给后续权限管理。
    #[allow(dead_code)]
    pub fn revoke(&self, plugin_id: &str, permission: &str) -> anyhow::Result<usize> {
        self.db.exec(
            "DELETE FROM plugin_permissions WHERE plugin_id = ?1 AND permission = ?2",
            &[Value::from(plugin_id), Value::from(permission)],
        )?;
        Ok(1)
    }

    /// 卸载时的权限清理。
    pub fn delete_permissions(&self, plugin_id: &str) -> anyhow::Result<()> {
        self.db.exec(
            "DELETE FROM plugin_permissions WHERE plugin_id = ?1",
            &[Value::from(plugin_id)],
        )?;
        Ok(())
    }

    // ---- plugin_audit 表（迁移 0008） -------------------------------------

    /// 写一条审计。`plugin_id` 也可填 `agent:<name>`（外部 Agent 网关共用本表）。
    pub fn audit(&self, plugin_id: &str, action: &str, outcome: &str, detail: &Value) -> anyhow::Result<()> {
        self.db.exec(
            "INSERT INTO plugin_audit(plugin_id, action, outcome, detail, created_at)
             VALUES(?1, ?2, ?3, ?4, ?5)",
            &[
                Value::from(plugin_id),
                Value::from(action),
                Value::from(outcome),
                Value::from(detail.to_string()),
                Value::from(iso_now().as_str()),
            ],
        )?;
        Ok(())
    }

    pub fn audit_list(&self, plugin_id: &str, limit: i64) -> anyhow::Result<Vec<Value>> {
        let limit = limit.clamp(1, 500);
        self.db.query_json(
            "SELECT action, outcome, detail, created_at FROM plugin_audit
             WHERE plugin_id = ?1 ORDER BY id DESC LIMIT ?2",
            &[Value::from(plugin_id), Value::from(limit)],
        )
    }
}

fn row_to_plugin(r: Value) -> Option<PluginRow> {
    Some(PluginRow {
        plugin_id: r.get("plugin_id")?.as_str()?.to_string(),
        name: r.get("name")?.as_str()?.to_string(),
        version: r.get("version")?.as_str()?.to_string(),
        author: r.get("author").and_then(|v| v.as_str()).map(String::from),
        entry: r.get("entry")?.as_str()?.to_string(),
        enabled: r.get("enabled").and_then(|v| v.as_i64()).unwrap_or(0) != 0,
        installed_at: r.get("installed_at")?.as_str()?.to_string(),
        updated_at: r.get("updated_at")?.as_str()?.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo() -> PluginRepo {
        let dir = std::env::temp_dir().join(format!(
            "pw-plugins-test-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .subsec_nanos()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        PluginRepo::new(db)
    }

    #[test]
    fn insert_grant_revoke_roundtrip() {
        let r = repo();
        r.insert("com.t.p", "测试", "1.0.0", "t", "main/index.js").unwrap();
        assert!(r.get("com.t.p").unwrap().is_some());
        assert!(!r.get("com.t.p").unwrap().unwrap().enabled);

        r.grant_all(
            "com.t.p",
            &[
                PermRow { permission: "ui:widget".into(), scope: String::new() },
                PermRow { permission: "net:http".into(), scope: "api.example.com".into() },
            ],
        )
        .unwrap();
        let perms = r.permissions("com.t.p").unwrap();
        assert_eq!(perms.len(), 2);

        // 重复授权幂等（先清后写）
        r.grant_all("com.t.p", &[PermRow { permission: "data:own".into(), scope: String::new() }])
            .unwrap();
        assert_eq!(r.permissions("com.t.p").unwrap().len(), 1);

        r.revoke("com.t.p", "data:own").unwrap();
        assert!(r.permissions("com.t.p").unwrap().is_empty());
    }

    #[test]
    fn uninstall_keeps_audit_and_clears_rows() {
        let r = repo();
        r.insert("com.t.q", "Q", "1.0.0", "t", "main/index.js").unwrap();
        r.grant_all("com.t.q", &[PermRow { permission: "data:own".into(), scope: String::new() }])
            .unwrap();
        r.audit("com.t.q", "data.set", "ok", &serde_json::json!({"k": "v"})).unwrap();
        r.audit("com.t.q", "file.read", "denied", &serde_json::json!({})).unwrap();

        assert_eq!(r.delete("com.t.q").unwrap(), 1);
        assert_eq!(r.delete("com.t.q").unwrap(), 0, "重复删除应得 0");
        assert!(r.get("com.t.q").unwrap().is_none());
        assert!(r.permissions("com.t.q").unwrap().is_empty());
        // 审计保留（卸载不清历史）
        let audit = r.audit_list("com.t.q", 10).unwrap();
        assert_eq!(audit.len(), 2);
        assert_eq!(audit[0]["outcome"], "denied");
    }

    #[test]
    fn set_enabled_roundtrip() {
        let r = repo();
        r.insert("com.t.e", "E", "1.0.0", "t", "main/index.js").unwrap();
        r.set_enabled("com.t.e", true).unwrap();
        assert!(r.get("com.t.e").unwrap().unwrap().enabled);
        r.set_enabled("com.t.e", false).unwrap();
        assert!(!r.get("com.t.e").unwrap().unwrap().enabled);
    }
}
