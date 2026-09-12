//! 配置服务：config 表的统一读写口 + 类型默认值 + 类型校验 + CONFIG_CHANGED 广播。
//!
//! 前端经 Tauri command（首选，见 api/commands.rs）或 `/api/v1/config/{key}` 访问；
//! Python 经 `/internal/config/{key}`。

use std::sync::Arc;

use serde_json::Value;

use crate::db::Db;
use crate::event_bus::{EventBus, CONFIG_CHANGED};

#[derive(Clone)]
pub struct ConfigService {
    db: Arc<Db>,
    bus: EventBus,
}

impl ConfigService {
    pub fn new(db: Db, bus: EventBus) -> Self {
        Self {
            db: Arc::new(db),
            bus: Arc::new(bus),
        }
    }

    /// 读取配置项；不存在时返回登记过的默认值。
    pub fn get(&self, key: &str) -> Value {
        match self.db.kv_get(key) {
            Ok(Some(raw)) => serde_json::from_str(&raw).unwrap_or_else(|_| default_for(key)),
            _ => default_for(key),
        }
    }

    /// 写入配置项并广播 `CONFIG_CHANGED`（含 oldValue / newValue，契约 3.3）。
    ///
    /// 修复（REVIEW-003 C-02）：原实现既未校验键是否登记，也无类型校验，
    /// 经 `PUT /api/v1/config/{任意key}` 可写入任意键、任意类型。
    /// 现按 04 §4「必须支持：默认值、类型校验、变更广播」补齐前两项。
    pub fn set(&self, key: &str, value: Value) -> anyhow::Result<Value> {
        if !KEYS.contains(&key) {
            anyhow::bail!("未登记的配置键：{key}（新增键必须先登记到 config.rs 的 KEYS）");
        }
        let expected = expected_type(key);
        if !type_ok(&value, expected) {
            anyhow::bail!("配置项类型不匹配：{key} 期望 {expected}");
        }
        let old = self.get(key);
        let raw = serde_json::to_string(&value)?;
        self.db.kv_set(key, &raw)?;
        let _ = self.bus.publish(
            CONFIG_CHANGED,
            serde_json::json!({ "key": key, "oldValue": old, "newValue": value }),
        );
        Ok(old)
    }
}

/// 已登记的配置键。**新增键必须在此登记**（禁止散落魔法字符串，02 §2.5），
/// 且 `ConfigService::set` 会据此拒绝未登记键。
pub const KEYS: &[&str] = &[
    SCHEMA_VERSION_KEY,
    "ui.theme",
    "ui.nav.collapsed",
    "ui.dashboard.widgets",
    "ui.dashboard.usage",
    "ui.dashboard.layout_locked",
    "app.autostart",
    "app.data_dir",
    "ai.default_provider",
    "privacy.telemetry",
    "runtime.sidecar_port",
    "runtime.http_port",
];

/// 配置项期望类型（04 §4 类型校验）。`number|null` 表示可空数值。
pub fn expected_type(key: &str) -> &'static str {
    match key {
        "schema_version" | "runtime.http_port" => "number",
        "ui.theme" | "app.data_dir" | "ai.default_provider" => "string",
        "ui.nav.collapsed" | "app.autostart" | "privacy.telemetry" => "boolean",
        "ui.dashboard.widgets" => "array",
        "ui.dashboard.usage" => "object",
        "runtime.sidecar_port" => "number|null",
        _ => "any",
    }
}

fn type_ok(value: &Value, expected: &str) -> bool {
    match expected {
        "number" => value.is_number(),
        "string" => value.is_string(),
        "boolean" => value.is_boolean(),
        "array" => value.is_array(),
        "object" => value.is_object(),
        "number|null" => value.is_number() || value.is_null(),
        _ => true,
    }
}

/// 已登记的配置键默认值（新增键必须在此登记，禁止散落）。
fn default_for(key: &str) -> Value {
    match key {
        "schema_version" => serde_json::json!(0),
        "ui.theme" => serde_json::json!("light"),
        "ui.nav.collapsed" => serde_json::json!(false),
        "ui.dashboard.widgets" => serde_json::json!([]),
        "ui.dashboard.usage" => serde_json::json!({}),
        "ui.dashboard.layout_locked" => serde_json::json!(false),
        "app.autostart" => serde_json::json!(false),
        "app.data_dir" => serde_json::json!(""),
        "ai.default_provider" => serde_json::json!(""),
        "privacy.telemetry" => serde_json::json!(false),
        "runtime.sidecar_port" => Value::Null,
        "runtime.http_port" => Value::Null,
        _ => Value::Null,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn unregistered_key_is_not_in_whitelist() {
        assert!(KEYS.contains(&"ui.theme"));
        assert!(!KEYS.contains(&"evil.key"));
    }

    #[test]
    fn type_rules_hold() {
        assert!(type_ok(&serde_json::json!(7), expected_type("runtime.http_port")));
        assert!(!type_ok(&serde_json::json!("7"), expected_type("runtime.http_port")));
        assert!(type_ok(&serde_json::json!(true), expected_type("ui.nav.collapsed")));
        assert!(!type_ok(&serde_json::json!("true"), expected_type("ui.nav.collapsed")));
        assert!(type_ok(&serde_json::json!([]), expected_type("ui.dashboard.widgets")));
        assert!(type_ok(&serde_json::json!({}), expected_type("ui.dashboard.usage")));
        assert!(type_ok(&Value::Null, expected_type("runtime.sidecar_port")));
    }

    /// 契约约束：每个登记键都必须有默认值（否则 get() 会落进 `_ => Null` 的未登记分支）。
    #[test]
    fn every_registered_key_has_an_explicit_default() {
        for key in KEYS {
            let v = default_for(key);
            assert!(
                !v.is_null() || matches!(*key, "runtime.sidecar_port" | "runtime.http_port"),
                "登记键 {key} 缺少显式默认值"
            );
        }
    }
}
