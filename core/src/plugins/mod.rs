//! 插件宿主（阶段9，12 §A）。
//!
//! **架构口径（02 §「插件加载与权限校验 = Rust」，v11 契约 ② 如实登记）**：
//! core 是插件的**信任边界** —— 发现、manifest 校验、安装/卸载、权限判定、审计、
//! 数据隔离、文件服务全部在这里；插件 JS 本体运行在 **UI webview 的沙箱 iframe**
//! （无 `allow-same-origin`，opaque origin，崩溃不上抛），通过 postMessage 桥 +
//! 本模块的权限网关（`api_call`）访问能力。
//! 为什么运行时不在 core：纯 Rust JS 引擎（rquickjs/boa/deno_core）依赖 crates.io，
//! 本机代理不可达（阶段8 已实证）；webview 沙箱是零新依赖的隔离方案，且
//! 红线 V7（插件不碰数据库）由"一切能力必须过 core 网关"结构性保证。
//!
//! 红线：V4（默认零权限——manifest 未声明的能力一律拦截）、
//!       V7（插件无任何 SQL 通道——Data API 只写 `plugins/<id>/data/` 下的 JSON 文件）、
//!       禁止事项⑤（禁止针对特定插件 id 的业务特判——本模块对插件 id 无任何业务判断）。

mod repository;

pub use repository::{PermRow, PluginRepo};

use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use crate::state::AppState;

/// 权限枚举（契约 3.2.4，12 §A2 + v11 补充的 `system:media`）。
pub mod perms {
    pub const UI_WIDGET: &str = "ui:widget";
    pub const APP_LAUNCH: &str = "app:launch";
    pub const WINDOW_READ: &str = "window:read";
    pub const CLIPBOARD_READ: &str = "clipboard:read";
    pub const CLIPBOARD_WRITE: &str = "clipboard:write";
    pub const AI_INVOKE: &str = "ai:invoke";
    pub const DATA_OWN: &str = "data:own";
    pub const NET_HTTP: &str = "net:http";
    pub const FILE_READ: &str = "file:read";
    pub const FILE_WRITE: &str = "file:write";
    pub const SYSTEM_MEDIA: &str = "system:media";

    pub const ALL: &[&str] = &[
        UI_WIDGET,
        APP_LAUNCH,
        WINDOW_READ,
        CLIPBOARD_READ,
        CLIPBOARD_WRITE,
        AI_INVOKE,
        DATA_OWN,
        NET_HTTP,
        FILE_READ,
        FILE_WRITE,
        SYSTEM_MEDIA,
    ];
}

/// core 自身版本（manifest `minAppVersion` 兼容性判据）。
const CORE_VERSION: &str = "0.1.0";

// ---------------------------------------------------------------------------
// manifest

/// manifest.json 解析结果（契约 3.2.4）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct Manifest {
    #[serde(rename = "pluginId")]
    pub plugin_id: String,
    pub name: String,
    pub version: String,
    #[serde(default)]
    pub author: String,
    pub entry: String,
    #[serde(default)]
    pub description: String,
    #[serde(default)]
    pub permissions: Vec<PermSpec>,
    #[serde(default)]
    pub ui: Option<UiSpec>,
    #[serde(rename = "minAppVersion", default)]
    pub min_app_version: String,
}

/// 权限声明：字符串（无 scope）或 `{permission, scope}` 对象（v11）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct PermSpec {
    pub permission: String,
    #[serde(default)]
    pub scope: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct UiSpec {
    #[serde(rename = "type", default)]
    pub kind: String,
    #[serde(default)]
    pub size: String,
    #[serde(default)]
    pub route: String,
}

impl Manifest {
    pub fn from_json(v: &Value) -> Result<Self, String> {
        // serde_json::from_value 会吞掉"哪个字段错"的细节，手工映射以便给出可读错误。
        let get_str = |key: &str| -> Result<String, String> {
            v.get(key)
                .and_then(Value::as_str)
                .map(String::from)
                .ok_or_else(|| format!("manifest 缺少或类型错误的字段：{key}"))
        };
        let mut permissions = Vec::new();
        if let Some(arr) = v.get("permissions").and_then(Value::as_array) {
            for p in arr {
                if let Some(s) = p.as_str() {
                    permissions.push(PermSpec { permission: s.to_string(), scope: vec![] });
                } else if let Some(obj) = p.as_object() {
                    let permission = obj
                        .get("permission")
                        .and_then(Value::as_str)
                        .ok_or_else(|| "permissions 对象形态缺少 permission 字段".to_string())?;
                    let scope = obj
                        .get("scope")
                        .and_then(Value::as_array)
                        .map(|a| {
                            a.iter().filter_map(|x| x.as_str().map(String::from)).collect::<Vec<_>>()
                        })
                        .unwrap_or_default();
                    permissions.push(PermSpec { permission: permission.to_string(), scope });
                } else {
                    return Err("permissions 元素必须是字符串或 {permission, scope} 对象".into());
                }
            }
        }
        let ui = v.get("ui").and_then(|u| {
            Some(UiSpec {
                kind: u.get("type").and_then(Value::as_str).unwrap_or("").to_string(),
                size: u.get("size").and_then(Value::as_str).unwrap_or("").to_string(),
                route: u.get("route").and_then(Value::as_str).unwrap_or("").to_string(),
            })
        });
        Ok(Self {
            plugin_id: get_str("pluginId")?,
            name: get_str("name")?,
            version: get_str("version")?,
            author: v.get("author").and_then(Value::as_str).unwrap_or("").to_string(),
            entry: get_str("entry")?,
            description: v.get("description").and_then(Value::as_str).unwrap_or("").to_string(),
            permissions,
            ui,
            min_app_version: v
                .get("minAppVersion")
                .and_then(Value::as_str)
                .unwrap_or("0.1.0")
                .to_string(),
        })
    }

    /// 结构 + 语义校验（12 §A4"校验"）。`check_files=true` 时还要求 entry/ui.route 文件存在
    /// （发现阶段只读元信息，文件检查放安装阶段；两阶段共用本函数）。
    pub fn validate(&self, root: Option<&Path>) -> Result<(), String> {
        // pluginId：反向域名（02 §命名：com.example.music）
        let id = &self.plugin_id;
        let id_ok = {
            let parts: Vec<&str> = id.split('.').collect();
            parts.len() >= 2
                && parts.iter().all(|p| {
                    !p.is_empty()
                        && p.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
                        && p.chars().next().map(|c| c.is_ascii_lowercase() || c.is_ascii_digit()).unwrap_or(false)
                })
        };
        if !id_ok {
            return Err(format!("pluginId 必须是反向域名（小写字母/数字/下划线，≥2 段）：{id}"));
        }
        // version / minAppVersion：X.Y.Z
        for (label, v) in [("version", &self.version), ("minAppVersion", &self.min_app_version)] {
            let segs: Vec<&str> = v.split('.').collect();
            if segs.len() != 3 || segs.iter().any(|s| s.is_empty() || !s.chars().all(|c| c.is_ascii_digit())) {
                return Err(format!("{label} 必须是 X.Y.Z：{v}"));
            }
        }
        if self.name.trim().is_empty() {
            return Err("name 不能为空".into());
        }
        if self.entry.trim().is_empty() {
            return Err("entry 不能为空".into());
        }
        // 权限必须在枚举内（未知权限 → 拒绝安装，12 §A3"默认零权限"的入口守门）
        for p in &self.permissions {
            if !perms::ALL.contains(&p.permission.as_str()) {
                return Err(format!("未知权限：{}（允许清单见契约 3.2.4）", p.permission));
            }
        }
        // 版本兼容
        if semver_gt(&self.min_app_version, CORE_VERSION) {
            return Err(format!(
                "插件要求 minAppVersion >= {}，当前 core 版本 {CORE_VERSION}",
                self.min_app_version
            ));
        }
        // 文件存在性（安装阶段）
        if let Some(root) = root {
            let dir = root.join(&self.plugin_id);
            if !dir.join(&self.entry).is_file() {
                return Err(format!("入口文件不存在：{}", self.entry));
            }
            if let Some(ui) = &self.ui {
                if !ui.route.trim().is_empty() && !dir.join(&ui.route).is_file() {
                    return Err(format!("ui.route 文件不存在：{}", ui.route));
                }
            }
        }
        Ok(())
    }

    /// 序列化给 UI 的形态（权限清单 + ui 信息，安装确认页直接展示，验收 3）。
    pub fn to_public_json(&self) -> Value {
        json!({
            "pluginId": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "author": self.author,
            "description": self.description,
            "entry": self.entry,
            "permissions": self.permissions,
            "ui": self.ui,
            "minAppVersion": self.min_app_version,
        })
    }
}

/// 极简 semver 比较：a > b（各段为数字，逐段比较）。
fn semver_gt(a: &str, b: &str) -> bool {
    let parse = |s: &str| -> Vec<u64> {
        s.split('.').filter_map(|x| x.parse::<u64>().ok()).collect()
    };
    let (av, bv) = (parse(a), parse(b));
    for i in 0..3 {
        let x = av.get(i).copied().unwrap_or(0);
        let y = bv.get(i).copied().unwrap_or(0);
        if x != y {
            return x > y;
        }
    }
    false
}

// ---------------------------------------------------------------------------
// 插件根目录

/// 插件根：环境变量 `PW_PLUGINS_DIR` > `<data_dir>/plugins`。
/// 仓库 `plugins/` 是示例插件的开发参考副本，不自动加载 —— 安装（拷贝）即边界。
pub fn plugins_root(state: &AppState) -> PathBuf {
    if let Some(dir) = std::env::var_os("PW_PLUGINS_DIR") {
        return PathBuf::from(dir);
    }
    state.data_dir.join("plugins")
}

/// 插件 id → 目录，带 id 白名单校验（防 `../` 类路径注入；id 合法性由 manifest 校验保证，
/// 但路由参数可能来自外部，防御性再查一次）。
fn plugin_dir(root: &Path, plugin_id: &str) -> Result<PathBuf, String> {
    if plugin_id.is_empty()
        || !plugin_id
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '.')
        || plugin_id.contains("..")
    {
        return Err(format!("非法插件 id：{plugin_id}"));
    }
    Ok(root.join(plugin_id))
}

// ---------------------------------------------------------------------------
// 发现 / 安装 / 卸载 / 启停

/// 发现：扫描目录下每个含 manifest.json 的子目录，返回解析 + 校验结果（**不落库**）。
pub fn discover(dir: &Path) -> Vec<Value> {
    let mut out = Vec::new();
    let entries = match std::fs::read_dir(dir) {
        Ok(e) => e,
        Err(_) => return out,
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }
        let manifest_path = path.join("manifest.json");
        let manifest_raw = match std::fs::read_to_string(&manifest_path) {
            Ok(s) => s,
            Err(_) => continue, // 无 manifest 的子目录跳过（不是错误：目录里可能有杂物）
        };
        let parsed: Result<Value, String> =
            serde_json::from_str(&manifest_raw).map_err(|e| e.to_string());
        match parsed.and_then(|v| Manifest::from_json(&v).map(|m| (m, v))) {
            Ok((manifest, raw)) => match manifest.validate(None) {
                Ok(()) => out.push(json!({
                    "dir": path.to_string_lossy(),
                    "valid": true,
                    "manifest": manifest.to_public_json(),
                })),
                Err(e) => out.push(json!({
                    "dir": path.to_string_lossy(), "valid": false, "errors": [e],
                    "raw": raw,
                })),
            },
            Err(e) => out.push(json!({
                "dir": path.to_string_lossy(), "valid": false, "errors": [e],
            })),
        }
    }
    out
}

/// 安装（12 §A4：拷贝进插件根 + 校验 + 登记表 + 按声明授权，enabled=0）。
/// 安装确认页展示的权限清单 = manifest.permissions（验收 3），用户点确认即授权（A3）。
pub fn install(state: &AppState, source_dir: &Path) -> anyhow::Result<Value> {
    let manifest_raw = std::fs::read_to_string(source_dir.join("manifest.json"))
        .map_err(|e| anyhow::anyhow!("读取 manifest.json 失败：{e}"))?;
    let v: Value = serde_json::from_str(&manifest_raw)
        .map_err(|e| anyhow::anyhow!("manifest.json 不是合法 JSON：{e}"))?;
    let manifest =
        Manifest::from_json(&v).map_err(|e| anyhow::anyhow!("manifest 校验失败：{e}"))?;

    let root = plugins_root(state);
    let dest = plugin_dir(&root, &manifest.plugin_id)
        .map_err(|e| anyhow::anyhow!("{e}"))?;
    // 三种起点（12 §A4）：
    // 1. 已登记 → 拒绝（先卸载再重装）；
    // 2. 未登记但目录已在根里（"发现→安装"的正常流程：用户把插件文件夹放进来）→ 就地登记，不重复拷贝；
    // 3. 目录不在 → 从 source_dir 拷贝进根。
    let repo = PluginRepo::new(state.db.clone());
    if repo.get(&manifest.plugin_id)?.is_some() {
        anyhow::bail!("插件已安装：{}（先卸载再重装）", manifest.plugin_id);
    }
    let in_place = dest.exists();
    if !in_place {
        std::fs::create_dir_all(&dest)?;
        if let Err(e) = copy_dir_recursive(source_dir, &dest) {
            let _ = std::fs::remove_dir_all(&dest); // 半拷贝不留尸体
            anyhow::bail!("拷贝插件文件失败：{e}");
        }
    }
    if let Err(e) = manifest.validate(Some(&root)) {
        if !in_place {
            let _ = std::fs::remove_dir_all(&dest);
        }
        anyhow::bail!("manifest 校验失败：{e}");
    }

    repo.insert(
        &manifest.plugin_id,
        &manifest.name,
        &manifest.version,
        &manifest.author,
        &manifest.entry,
    )?;
    let perms: Vec<PermRow> = manifest
        .permissions
        .iter()
        .map(|p| PermRow {
            permission: p.permission.clone(),
            scope: p.scope.join(","),
        })
        .collect();
    repo.grant_all(&manifest.plugin_id, &perms)?;
    repo.audit(
        &manifest.plugin_id,
        "plugin.install",
        "ok",
        &json!({ "version": manifest.version, "permissions": perms.iter().map(|p| p.permission.clone()).collect::<Vec<_>>() }),
    )?;

    tracing::info!(plugin = %manifest.plugin_id, "插件已安装（默认禁用，待用户启用）");
    Ok(json!({ "installed": true, "plugin": manifest.to_public_json() }))
}

/// 卸载：删目录 + 物理删表行（审计保留）。目录不存在也照样清表（幂等）。
pub fn uninstall(state: &AppState, plugin_id: &str) -> anyhow::Result<Value> {
    let root = plugins_root(state);
    let repo = PluginRepo::new(state.db.clone());
    if repo.get(plugin_id)?.is_none() {
        anyhow::bail!("插件未安装：{plugin_id}");
    }
    let dir = plugin_dir(&root, plugin_id).map_err(|e| anyhow::anyhow!("{e}"))?;
    if dir.exists() {
        std::fs::remove_dir_all(&dir)
            .map_err(|e| anyhow::anyhow!("清理插件目录失败（{}）：{e}", dir.display()))?;
    }
    repo.delete_permissions(plugin_id)?;
    repo.delete(plugin_id)?;
    let _ = repo.audit(plugin_id, "plugin.uninstall", "ok", &json!({}));
    tracing::info!(plugin = %plugin_id, "插件已卸载（目录与登记已清理，审计保留）");
    Ok(json!({ "uninstalled": true, "pluginId": plugin_id }))
}

/// 启用/禁用。启用成功发布 `PLUGIN_LOADED`（契约 3.3，阶段9 起真正发出）。
pub fn set_enabled(state: &AppState, plugin_id: &str, enabled: bool) -> anyhow::Result<Value> {
    let root = plugins_root(state);
    let repo = PluginRepo::new(state.db.clone());
    let row = repo
        .get(plugin_id)?
        .ok_or_else(|| anyhow::anyhow!("插件未安装：{plugin_id}"))?;
    let dir = plugin_dir(&root, plugin_id).map_err(|e| anyhow::anyhow!("{e}"))?;
    if enabled && !dir.is_dir() {
        anyhow::bail!("插件目录缺失（{}）：无法启用，请卸载后重装", dir.display());
    }
    repo.set_enabled(plugin_id, enabled)?;
    if enabled {
        state.bus.publish(
            crate::event_bus::PLUGIN_LOADED,
            json!({ "pluginId": plugin_id, "version": row.version }),
        )?;
        let _ = repo.audit(plugin_id, "plugin.enable", "ok", &json!({}));
    } else {
        let _ = repo.audit(plugin_id, "plugin.disable", "ok", &json!({}));
    }
    Ok(json!({ "pluginId": plugin_id, "enabled": enabled }))
}

/// 全量列表（plugins 表 + manifest 补充字段 + 有效权限合并，管理页一次拉全）。
pub fn list(state: &AppState) -> anyhow::Result<Vec<Value>> {
    let repo = PluginRepo::new(state.db.clone());
    let mut out = Vec::new();
    for row in repo.list()? {
        let root = plugins_root(state);
        // manifest 是权威补充源：ui 信息 / description / entry 随安装拷贝的 manifest 为准
        let manifest = std::fs::read_to_string(
            plugin_dir(&root, &row.plugin_id).unwrap_or_default().join("manifest.json"),
        )
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .unwrap_or(Value::Null);
        let perms = repo.permissions(&row.plugin_id)?;
        out.push(json!({
            "pluginId": row.plugin_id,
            "name": row.name,
            "version": row.version,
            "author": row.author,
            "description": manifest.get("description").cloned().unwrap_or(Value::Null),
            "entry": manifest.get("entry").cloned().unwrap_or(Value::from(row.entry.clone())),
            "enabled": row.enabled,
            "installedAt": row.installed_at,
            "permissions": perms,
            "ui": manifest.get("ui").cloned().unwrap_or(Value::Null),
        }));
    }
    Ok(out)
}

/// 宿主崩溃上报（宿主桥捕获 iframe onerror / 超时后调用）：
/// 发布 `PLUGIN_ERROR` + 审计。主程序不受影响（12 §验收4）。
pub fn report_crash(state: &AppState, plugin_id: &str, reason: &str) -> Value {
    let repo = PluginRepo::new(state.db.clone());
    let _ = repo.audit(plugin_id, "plugin.crash", "error", &json!({ "reason": reason }));
    let _ = state.bus.publish(
        crate::event_bus::PLUGIN_ERROR,
        json!({ "pluginId": plugin_id, "reason": reason }),
    );
    tracing::warn!(plugin = %plugin_id, %reason, "插件已停止（崩溃或超时）");
    json!({ "reported": true })
}

// ---------------------------------------------------------------------------
// 权限网关（api_call）—— 插件能力的唯一入口

/// 判定插件是否持有某权限（可带 scope 需求）。
/// `need_scope` 为 Some 时，要求存在该权限且 scope 为空（全局）或包含 need_scope。
fn has_permission(granted: &[PermRow], permission: &str, need_scope: Option<&str>) -> bool {
    granted.iter().any(|p| {
        p.permission == permission
            && match need_scope {
                None => true,
                Some(s) => {
                    p.scope.is_empty()
                        || p.scope.split(',').any(|part| part.trim() == s)
                }
            }
    })
}

/// 网关入口（12 §A2 六类 API；契约 3.2.7）。每次调用（含拒绝）写审计；
/// 越权 → 发布 `PLUGIN_PERMISSION_DENIED` + 返回 403 语义错误。
pub async fn api_call(
    state: &Arc<AppState>,
    plugin_id: &str,
    api: &str,
    method: &str,
    payload: &Value,
) -> anyhow::Result<Value> {
    let root = plugins_root(state);
    let repo = PluginRepo::new(state.db.clone());

    let row = repo
        .get(plugin_id)?
        .ok_or_else(|| anyhow::anyhow!("插件未安装：{plugin_id}"))?;
    if !row.enabled {
        let _ = repo.audit(plugin_id, &format!("{api}.{method}"), "denied", &json!({ "reason": "插件已禁用" }));
        anyhow::bail!("插件已禁用：{plugin_id}");
    }
    let granted = repo.permissions(plugin_id)?;

    let action = format!("{api}.{method}");
    let result = dispatch(state, &root, plugin_id, &granted, api, method, payload).await;

    match &result {
        Ok(_) => {
            let _ = repo.audit(plugin_id, &action, "ok", &audit_detail(payload));
        }
        Err(e) => {
            let msg = e.to_string();
            if msg.starts_with("PERMISSION_DENIED:") {
                let permission = msg.trim_start_matches("PERMISSION_DENIED:").trim().to_string();
                let _ = repo.audit(plugin_id, &action, "denied", &json!({ "permission": permission }));
                let _ = state.bus.publish(
                    crate::event_bus::PLUGIN_PERMISSION_DENIED,
                    json!({ "pluginId": plugin_id, "permission": permission, "scope": Value::Null }),
                );
            } else {
                let _ = repo.audit(plugin_id, &action, "error", &json!({ "reason": msg }));
            }
        }
    }
    result
}

/// 审计摘要：只取小字段，禁止把大正文塞进审计（数据轻量化）。
fn audit_detail(payload: &Value) -> Value {
    match payload {
        Value::Object(map) => {
            let mut out = serde_json::Map::new();
            for (k, v) in map {
                let s = v.to_string();
                if s.len() <= 120 {
                    out.insert(k.clone(), v.clone());
                } else {
                    out.insert(k.clone(), json!("<omitted>"));
                }
            }
            Value::Object(out)
        }
        other => {
            let s = other.to_string();
            if s.len() <= 120 {
                other.clone()
            } else {
                json!("<omitted>")
            }
        }
    }
}

/// 分发前统一权限检查 + 执行。错误码 `PERMISSION_DENIED: <permission>` 由 `api_call` 翻译成事件。
#[allow(clippy::too_many_arguments)]
async fn dispatch(
    state: &Arc<AppState>,
    root: &Path,
    plugin_id: &str,
    granted: &[PermRow],
    api: &str,
    method: &str,
    payload: &Value,
) -> anyhow::Result<Value> {
    match (api, method) {
        // ---- UI API（宿主侧展示；core 只做权限判定与审计）----
        ("ui", "notify") => {
            require(granted, perms::UI_WIDGET, None)?;
            Ok(json!({ "notified": true }))
        }
        // ---- System API ----
        ("system", "appLaunch") => {
            require(granted, perms::APP_LAUNCH, None)?;
            let target = payload
                .get("nameOrId")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow::anyhow!("payload 需要 nameOrId（软件名称或 id）"))?;
            // 先按 id 数字找，再按名称找（apps 表排序契约无关紧要，这里只取第一个命中）
            let app_id = if let Ok(id) = target.parse::<i64>() {
                Some(id)
            } else {
                state
                    .apps
                    .list(None, Some(target))?
                    .first()
                    .map(|a| a.id)
            };
            let app_id = app_id.ok_or_else(|| anyhow::anyhow!("未找到软件：{target}"))?;
            crate::app_manager::launch_registered(state, app_id)
        }
        ("system", "windowRead") => {
            require(granted, perms::WINDOW_READ, None)?;
            let windows = crate::window_manager::list_windows();
            serde_json::to_value(windows).map_err(|e| anyhow::anyhow!("{e}"))
        }
        ("system", "mediaNow") => {
            require(granted, perms::SYSTEM_MEDIA, None)?;
            crate::life::media_now(state).await
        }
        ("system", "mediaControl") => {
            require(granted, perms::SYSTEM_MEDIA, None)?;
            let action = payload
                .get("action")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow::anyhow!("payload 需要 action"))?;
            crate::life::media_control(state, action).await
        }
        // ---- Data API（隔离存储：plugins/<id>/data/<key>.json，红线 V7 的落点）----
        ("data", "get") | ("data", "set") | ("data", "delete") | ("data", "keys") => {
            require(granted, perms::DATA_OWN, None)?;
            data_op(root, plugin_id, method, payload)
        }
        // ---- AI API（权限在 core 判定；实际调用由宿主桥走 ai_chat command，
        //      恒 consult 模式——AI 不走 HTTP 面，阶段5 订正口径的延伸）----
        ("ai", "invoke") => {
            require(granted, perms::AI_INVOKE, None)?;
            Ok(json!({ "delegated": "host", "mode": "consult" }))
        }
        // ---- File API（scope 目录白名单内）----
        ("file", "read") | ("file", "write") => {
            let (perm, path) = file_target(granted, payload)?;
            let perm_needed = if method == "read" { perms::FILE_READ } else { perms::FILE_WRITE };
            if perm != perm_needed {
                // file:read 只授了读、写操作需要 file:write —— 用明确的权限名报错
                return Err(anyhow::anyhow!("PERMISSION_DENIED: {perm_needed}"));
            }
            if method == "read" {
                let bytes = std::fs::read(&path)
                    .map_err(|e| anyhow::anyhow!("读取失败：{e}"))?;
                if bytes.len() > 1024 * 1024 {
                    anyhow::bail!("文件超过 1MB 上限（数据轻量化）");
                }
                Ok(json!({
                    "path": path.to_string_lossy(),
                    "content": String::from_utf8_lossy(&bytes),
                }))
            } else {
                let content = payload
                    .get("content")
                    .and_then(Value::as_str)
                    .ok_or_else(|| anyhow::anyhow!("payload 需要 content"))?;
                if let Some(parent) = path.parent() {
                    std::fs::create_dir_all(parent)?;
                }
                std::fs::write(&path, content).map_err(|e| anyhow::anyhow!("写入失败：{e}"))?;
                Ok(json!({ "written": true, "path": path.to_string_lossy() }))
            }
        }
        // ---- Network API（仅 http://；scope = 域名白名单）----
        ("net", "http") => {
            let url = payload
                .get("url")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow::anyhow!("payload 需要 url"))?;
            net_http(granted, url).await
        }
        _ => anyhow::bail!("未知 API：{api}.{method}（允许清单见契约 3.2.7）"),
    }
}

fn require(granted: &[PermRow], permission: &str, scope: Option<&str>) -> anyhow::Result<()> {
    if has_permission(granted, permission, scope) {
        Ok(())
    } else {
        Err(anyhow::anyhow!("PERMISSION_DENIED: {permission}"))
    }
}

/// Data API 实现。键名限 `[A-Za-z0-9_-]{1,64}`，落点 `plugins/<id>/data/<key>.json`。
fn data_op(root: &Path, plugin_id: &str, method: &str, payload: &Value) -> anyhow::Result<Value> {
    let dir = plugin_dir(root, plugin_id)
        .map_err(|e| anyhow::anyhow!(e))?
        .join("data");
    if method == "keys" {
        let mut keys = Vec::new();
        if let Ok(entries) = std::fs::read_dir(&dir) {
            for e in entries.flatten() {
                if let Some(name) = e.path().file_stem().and_then(|s| s.to_str()) {
                    keys.push(name.to_string());
                }
            }
        }
        keys.sort();
        return Ok(json!({ "keys": keys }));
    }
    let key = payload
        .get("key")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow::anyhow!("payload 需要 key"))?;
    if key.is_empty()
        || key.len() > 64
        || !key.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
    {
        anyhow::bail!("非法 data key（限 1~64 位字母/数字/下划线/连字符）：{key}");
    }
    let path = dir.join(format!("{key}.json"));
    match method {
        "get" => {
            let raw = std::fs::read_to_string(&path)
                .map_err(|_| anyhow::anyhow!("数据不存在：{key}"))?;
            let v: Value = serde_json::from_str(&raw).unwrap_or(Value::Null);
            Ok(json!({ "key": key, "value": v }))
        }
        "set" => {
            let value = payload.get("value").cloned().unwrap_or(Value::Null);
            std::fs::create_dir_all(&dir)?;
            std::fs::write(&path, serde_json::to_string_pretty(&value)?)?;
            Ok(json!({ "key": key, "saved": true }))
        }
        "delete" => {
            match std::fs::remove_file(&path) {
                Ok(()) => Ok(json!({ "key": key, "deleted": true })),
                Err(_) if !path.exists() => Ok(json!({ "key": key, "deleted": true })),
                Err(e) => anyhow::bail!("删除失败：{e}"),
            }
        }
        _ => unreachable!(),
    }
}

/// File API：路径必须在某个已授权 scope 目录之内（规范化 + 前缀校验）。
/// 返回（命中的权限名，规范路径）。
fn file_target(granted: &[PermRow], payload: &Value) -> anyhow::Result<(String, PathBuf)> {
    let raw = payload
        .get("path")
        .and_then(Value::as_str)
        .ok_or_else(|| anyhow::anyhow!("payload 需要 path"))?;
    let canonical = std::fs::canonicalize(raw)
        .map_err(|_| anyhow::anyhow!("路径不存在或不可访问：{raw}"))?;
    for scope_dir in granted
        .iter()
        .filter(|p| p.permission == perms::FILE_READ || p.permission == perms::FILE_WRITE)
        .flat_map(|p| p.scope.split(',').map(|s| s.trim().to_string()).collect::<Vec<_>>())
    {
        if scope_dir.is_empty() {
            continue; // file 权限无 scope = 无目录授权（不允许全局文件访问）
        }
        if let Ok(scope_canonical) = std::fs::canonicalize(&scope_dir) {
            if canonical.starts_with(&scope_canonical) {
                let perm = if granted.iter().any(|p| {
                    p.permission == perms::FILE_WRITE
                        && (p.scope.is_empty()
                            || p.scope.split(',').any(|s| s.trim() == scope_dir))
                }) {
                    perms::FILE_WRITE.to_string()
                } else {
                    perms::FILE_READ.to_string()
                };
                return Ok((perm, canonical));
            }
        }
    }
    Err(anyhow::anyhow!("PERMISSION_DENIED: file:read（路径不在任何已授权目录内）"))
}

/// Network API：仅 http://（无 TLS crate，https 明确不支持并返回结构化错误），
/// host 必须在 net:http 的 scope 域名白名单内。原始 TCP HTTP/1.1（同 sidecar::call 手法）。
async fn net_http(granted: &[PermRow], url: &str) -> anyhow::Result<Value> {
    let (host, port, path) = parse_http_url(url)?;
    let hosts: Vec<String> = granted
        .iter()
        .filter(|p| p.permission == perms::NET_HTTP)
        .flat_map(|p| p.scope.split(',').map(|s| s.trim().to_string()).collect::<Vec<_>>())
        .filter(|s| !s.is_empty())
        .collect();
    if !hosts.iter().any(|h| h == &host) {
        anyhow::bail!("PERMISSION_DENIED: net:http（域名 {host} 不在白名单）");
    }
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let addr = format!("{host}:{port}");
    let mut stream = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        tokio::net::TcpStream::connect(&addr),
    )
    .await
    .map_err(|_| anyhow::anyhow!("连接超时：{addr}"))?
    .map_err(|e| anyhow::anyhow!("连接失败（{addr}）：{e}"))?;
    let req = format!("GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n");
    stream.write_all(req.as_bytes()).await?;
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).await?;
    let text = String::from_utf8_lossy(&buf);
    let status = text
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse::<u16>().ok())
        .unwrap_or(0);
    let body = text.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
    Ok(json!({ "status": status, "body": body }))
}

/// 解析 `http://host[:port]/path`（仅 http；host 限字母数字点连字符，防注入）。
fn parse_http_url(url: &str) -> anyhow::Result<(String, u16, String)> {
    let rest = url
        .strip_prefix("http://")
        .ok_or_else(|| anyhow::anyhow!("PERMISSION_DENIED: net:http（https_unsupported：仅支持 http://）"))?;
    let (authority, path) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "/"),
    };
    let (host, port) = match authority.rsplit_once(':') {
        Some((h, p)) => (h.to_string(), p.parse::<u16>().unwrap_or(80)),
        None => (authority.to_string(), 80),
    };
    let host_ok = !host.is_empty()
        && host
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '.' || c == '-' || c == '_');
    if !host_ok {
        anyhow::bail!("非法 host：{host}");
    }
    Ok((host, port, path.to_string()))
}

/// 目录递归拷贝（安装用；跳过目标已存在文件）。
fn copy_dir_recursive(src: &Path, dest: &Path) -> anyhow::Result<()> {
    std::fs::create_dir_all(dest)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let ty = entry.file_type()?;
        let target = dest.join(entry.file_name());
        if ty.is_dir() {
            copy_dir_recursive(&entry.path(), &target)?;
        } else if ty.is_file() {
            std::fs::copy(entry.path(), &target)?;
        }
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// 插件文件服务（HTTP 面 + pwplugin:// 自定义协议共用）

/// 读取插件静态文件（路径守卫：拒绝 `..` 与越出插件目录；大小上限 5MB）。
/// 返回 (内容, mime)。供 `/api/v1/plugins/{id}/files/*path` 与 `pwplugin://` 协议共用。
pub fn serve_file(root: &Path, plugin_id: &str, rel: &str) -> Result<(Vec<u8>, &'static str), String> {
    let base = plugin_dir(root, plugin_id)?;
    if rel.contains("..") || rel.contains('\\') {
        return Err("非法路径".into());
    }
    let path = base.join(rel.trim_start_matches('/'));
    // base 与目标都规范化后再比前缀（防符号链接/相对路径绕过）
    let canonical = std::fs::canonicalize(&path).map_err(|_| "文件不存在".to_string())?;
    let base_canonical =
        std::fs::canonicalize(&base).map_err(|_| "插件目录不存在".to_string())?;
    if !canonical.starts_with(&base_canonical) {
        return Err("路径越出插件目录".into());
    }
    let bytes = std::fs::read(&canonical).map_err(|e| format!("读取失败：{e}"))?;
    if bytes.len() > 5 * 1024 * 1024 {
        return Err("文件超过 5MB 上限".into());
    }
    let mime = match canonical.extension().and_then(|e| e.to_str()).unwrap_or("") {
        "html" => "text/html; charset=utf-8",
        "js" | "mjs" => "text/javascript; charset=utf-8",
        "css" => "text/css; charset=utf-8",
        "json" => "application/json; charset=utf-8",
        "png" => "image/png",
        "svg" => "image/svg+xml",
        "ico" => "image/x-icon",
        _ => "application/octet-stream",
    };
    Ok((bytes, mime))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_plugin_manifest(dir: &Path, manifest: &str) -> PathBuf {
        std::fs::create_dir_all(dir).unwrap();
        std::fs::write(dir.join("manifest.json"), manifest).unwrap();
        dir.to_path_buf()
    }

    const GOOD_MANIFEST: &str = r#"{
        "pluginId": "com.test.good",
        "name": "Good",
        "version": "1.0.0",
        "entry": "main/index.js",
        "permissions": ["ui:widget", "data:own"],
        "ui": { "type": "widget", "size": "small", "route": "ui/index.html" },
        "minAppVersion": "0.1.0"
    }"#;

    #[test]
    fn manifest_valid_and_rejects_unknown_permission() {
        let tmp = std::env::temp_dir().join(format!("pw-manifest-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();

        let dir = write_plugin_manifest(&tmp.join("good"), GOOD_MANIFEST);
        let raw = std::fs::read_to_string(dir.join("manifest.json")).unwrap();
        let m = Manifest::from_json(&serde_json::from_str::<Value>(&raw).unwrap()).unwrap();
        assert!(m.validate(None).is_ok());

        // 未知权限 → 拒绝（12 §A3 入口守门）
        let bad = GOOD_MANIFEST.replace("\"data:own\"", "\"fs:everything\"");
        let m2 = Manifest::from_json(&serde_json::from_str::<Value>(&bad).unwrap()).unwrap();
        assert!(m2.validate(None).is_err());

        // 非法 pluginId（单段）→ 拒绝
        let bad_id = GOOD_MANIFEST.replace("com.test.good", "good");
        let m3 = Manifest::from_json(&serde_json::from_str::<Value>(&bad_id).unwrap()).unwrap();
        assert!(m3.validate(None).is_err());

        // minAppVersion 高于 core → 拒绝
        let bad_ver = GOOD_MANIFEST.replace("\"minAppVersion\": \"0.1.0\"", "\"minAppVersion\": \"99.0.0\"");
        let m4 = Manifest::from_json(&serde_json::from_str::<Value>(&bad_ver).unwrap()).unwrap();
        assert!(m4.validate(None).is_err());

        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn serve_file_blocks_traversal() {
        let tmp = std::env::temp_dir().join(format!("pw-serve-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        let root = tmp.clone();
        let dir = root.join("com.test.s");
        std::fs::create_dir_all(dir.join("ui")).unwrap();
        std::fs::write(dir.join("ui/index.html"), "<h1>hi</h1>").unwrap();
        std::fs::write(dir.join("secret.txt"), "s").unwrap();

        assert!(serve_file(&root, "com.test.s", "ui/index.html").is_ok());
        assert!(serve_file(&root, "com.test.s", "../com.test.s/secret.txt").is_err());
        assert!(serve_file(&root, "com.test.s", "../../etc/passwd").is_err());
        assert!(serve_file(&root, "com.other", "ui/index.html").is_err());
        let _ = std::fs::remove_dir_all(&tmp);
    }

    #[test]
    fn parse_http_url_rejects_https_and_bad_host() {
        assert!(parse_http_url("https://api.example.com/x").is_err());
        assert!(parse_http_url("http://api.example.com/x").is_ok());
        assert!(parse_http_url("http://localhost:8080/").is_ok());
        assert!(parse_http_url("http://bad host/x").is_err());
    }

    #[test]
    fn data_key_rules() {
        // data_op 的键名校验逻辑（直接构造调用）
        let tmp = std::env::temp_dir().join(format!("pw-data-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&tmp);
        std::fs::create_dir_all(&tmp).unwrap();
        let ok = data_op(
            &tmp,
            "com.test.d",
            "set",
            &json!({ "key": "session_1", "value": { "count": 3 } }),
        );
        assert!(ok.is_ok());
        // 越界 key（含点 = 路径穿越企图）
        let bad = data_op(&tmp, "com.test.d", "set", &json!({ "key": "../evil", "value": 1 }));
        assert!(bad.is_err());
        let got = data_op(&tmp, "com.test.d", "get", &json!({ "key": "session_1" })).unwrap();
        assert_eq!(got["value"]["count"], 3);
        assert!(tmp.join("com.test.d/data/session_1.json").is_file());
        let _ = std::fs::remove_dir_all(&tmp);
    }
}
