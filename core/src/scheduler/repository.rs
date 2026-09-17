//! 工作模式与布局的持久化（`work_modes` / `layouts` 表）。
//!
//! 红线（02 §2.4）：**数据库的唯一写入者是 Rust core**。
//!
//! ## 关于"双写"（06 §技术要点）
//! 模式引用的布局同时存在于**数据库**与 `config/layouts/*.json`。规则：
//! - **数据库是唯一真相**；
//! - 写库之后再**导出** JSON（供版本管理与分享）；
//! - **禁止只改 JSON 不同步数据库** —— 故本模块的 `layout_upsert` 是唯一写入口，
//!   它先写库、成功后导出；导出失败只记 `WARN`（JSON 是派生品，不是真相）。

use anyhow::Context;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::db::Db;

/// 模式引用的文件/目录入口（契约 3.2.1 的 `openTargets` 元素）。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct OpenTarget {
    pub path: String,
    #[serde(default)]
    pub label: Option<String>,
    #[serde(rename = "type", default)]
    pub kind: Option<String>,
}

/// 模式的 AI 配置（契约 3.2.1 的 `aiProfile`）。
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AiProfile {
    #[serde(default)]
    pub provider: String,
    #[serde(default, rename = "systemPromptKey")]
    pub system_prompt_key: String,
    #[serde(default, rename = "permissionScope")]
    pub permission_scope: Vec<String>,
}

impl Default for AiProfile {
    fn default() -> Self {
        Self { provider: String::new(), system_prompt_key: String::new(), permission_scope: vec![] }
    }
}

/// 工作模式（入库/出参形态）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkMode {
    pub id: i64,
    pub name: String,
    pub description: Option<String>,
    pub icon: Option<String>,
    /// 软件库里的软件**名**列表（路径必须来自软件注册表 —— 06 §禁止事项）
    pub apps: Vec<String>,
    #[serde(rename = "openTargets")]
    pub open_targets: Vec<OpenTarget>,
    /// 布局名（不含 `.json`）
    pub layout: Option<String>,
    #[serde(rename = "aiProfile")]
    pub ai_profile: Option<AiProfile>,
    #[serde(rename = "autoApply")]
    pub auto_apply: bool,
    /// `additive` | `exclusive` | `ask`（06 §3）
    #[serde(rename = "switchPolicy")]
    pub switch_policy: String,
    #[serde(rename = "useCount")]
    pub use_count: i64,
    #[serde(rename = "lastUsedAt")]
    pub last_used_at: Option<String>,
    #[serde(rename = "createdAt")]
    pub created_at: String,
    #[serde(rename = "updatedAt")]
    pub updated_at: String,
}

/// 创建入参。
#[derive(Debug, Clone, Deserialize)]
pub struct WorkModeInput {
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub icon: Option<String>,
    #[serde(default)]
    pub apps: Vec<String>,
    #[serde(default, rename = "openTargets")]
    pub open_targets: Vec<OpenTarget>,
    #[serde(default)]
    pub layout: Option<String>,
    #[serde(default, rename = "aiProfile")]
    pub ai_profile: Option<AiProfile>,
    #[serde(default, rename = "autoApply")]
    pub auto_apply: bool,
    #[serde(default, rename = "switchPolicy")]
    pub switch_policy: Option<String>,
}

/// 编辑入参：只覆盖显式给出的字段。
#[derive(Debug, Clone, Default, Deserialize)]
pub struct WorkModePatch {
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub icon: Option<String>,
    #[serde(default)]
    pub apps: Option<Vec<String>>,
    #[serde(default, rename = "openTargets")]
    pub open_targets: Option<Vec<OpenTarget>>,
    #[serde(default)]
    pub layout: Option<String>,
    #[serde(default, rename = "aiProfile")]
    pub ai_profile: Option<AiProfile>,
    #[serde(default, rename = "autoApply")]
    pub auto_apply: Option<bool>,
    #[serde(default, rename = "switchPolicy")]
    pub switch_policy: Option<String>,
}

/// 合法的切换策略（06 §3）。
pub const SWITCH_POLICIES: &[&str] = &["additive", "exclusive", "ask"];

const COLS: &str = "id, name, description, icon, apps, open_targets, layout, ai_profile, \
                    auto_apply, switch_policy, use_count, last_used_at, created_at, updated_at";

#[derive(Clone)]
pub struct ModeRepo {
    db: Db,
}

impl ModeRepo {
    pub fn new(db: Db) -> Self {
        Self { db }
    }

    /// 全部未删除的模式（**软删除过滤是硬要求**，见 REVIEW-010 R-02）。
    pub fn list(&self) -> anyhow::Result<Vec<WorkMode>> {
        let rows = self.db.query_json(
            &format!("SELECT {COLS} FROM work_modes WHERE deleted_at IS NULL ORDER BY use_count DESC, name ASC"),
            &[],
        )?;
        Ok(rows.iter().map(to_mode).collect())
    }

    pub fn get(&self, id: i64) -> anyhow::Result<Option<WorkMode>> {
        let rows = self.db.query_json(
            &format!("SELECT {COLS} FROM work_modes WHERE id = ? AND deleted_at IS NULL"),
            &[Value::from(id)],
        )?;
        Ok(rows.first().map(to_mode))
    }

    pub fn get_by_name(&self, name: &str) -> anyhow::Result<Option<WorkMode>> {
        let rows = self.db.query_json(
            &format!("SELECT {COLS} FROM work_modes WHERE name = ? AND deleted_at IS NULL"),
            &[Value::from(name)],
        )?;
        Ok(rows.first().map(to_mode))
    }

    pub fn add(&self, input: &WorkModeInput) -> anyhow::Result<WorkMode> {
        if input.name.trim().is_empty() {
            anyhow::bail!("模式名不能为空");
        }
        if self.find_by_name_including_deleted(&input.name)?.is_some() {
            anyhow::bail!("已存在同名模式：{}", input.name);
        }
        let policy = normalize_policy(input.switch_policy.as_deref())?;
        let id = self.db.insert(
            "INSERT INTO work_modes \
             (name, description, icon, apps, open_targets, layout, ai_profile, auto_apply, switch_policy, \
              use_count, created_at, updated_at) \
             VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,0,datetime('now','localtime'),datetime('now','localtime'))",
            &[
                Value::from(input.name.trim()),
                opt_s(&input.description),
                opt_s(&input.icon),
                serde_json::to_value(&input.apps)?,
                serde_json::to_value(&input.open_targets)?,
                opt_s(&input.layout),
                match &input.ai_profile {
                    Some(p) => serde_json::to_value(p)?,
                    None => Value::Null,
                },
                Value::from(if input.auto_apply { 1 } else { 0 }),
                Value::from(policy),
            ],
        )?;
        self.get(id)?.context("创建后应能读到模式")
    }

    pub fn update(&self, id: i64, patch: &WorkModePatch) -> anyhow::Result<WorkMode> {
        let cur = self.get(id)?.with_context(|| format!("模式不存在：id={id}"))?;
        let policy = match patch.switch_policy.as_deref() {
            Some(p) => normalize_policy(Some(p))?,
            None => cur.switch_policy.clone(),
        };
        self.db.exec(
            "UPDATE work_modes SET name=?1, description=?2, icon=?3, apps=?4, open_targets=?5, \
             layout=?6, ai_profile=?7, auto_apply=?8, switch_policy=?9, \
             updated_at=datetime('now','localtime') WHERE id=?10 AND deleted_at IS NULL",
            &[
                Value::from(patch.name.clone().unwrap_or(cur.name).trim()),
                opt_s(&patch.description.clone().or(cur.description)),
                opt_s(&patch.icon.clone().or(cur.icon)),
                serde_json::to_value(patch.apps.clone().unwrap_or(cur.apps))?,
                serde_json::to_value(patch.open_targets.clone().unwrap_or(cur.open_targets))?,
                opt_s(&patch.layout.clone().or(cur.layout)),
                match patch.ai_profile.clone().or(cur.ai_profile) {
                    Some(p) => serde_json::to_value(p)?,
                    None => Value::Null,
                },
                Value::from(if patch.auto_apply.unwrap_or(cur.auto_apply) { 1 } else { 0 }),
                Value::from(policy),
                Value::from(id),
            ],
        )?;
        self.get(id)?.context("编辑后应能读到模式")
    }

    /// 复制模式（06 §1「支持复制模式」）。副本名加 ` 副本`，重名时递增序号。
    pub fn duplicate(&self, id: i64) -> anyhow::Result<WorkMode> {
        let src = self.get(id)?.with_context(|| format!("模式不存在：id={id}"))?;
        let mut name = format!("{} 副本", src.name);
        let mut n = 2;
        while self.find_by_name_including_deleted(&name)?.is_some() {
            name = format!("{} 副本{}", src.name, n);
            n += 1;
            if n > 99 {
                anyhow::bail!("副本名冲突过多，请先清理同名模式");
            }
        }
        self.add(&WorkModeInput {
            name,
            description: src.description,
            icon: src.icon,
            apps: src.apps,
            open_targets: src.open_targets,
            layout: src.layout,
            ai_profile: src.ai_profile,
            auto_apply: false, // 副本不继承"开机自动进入"，避免出现两个自动模式
            switch_policy: Some(src.switch_policy),
        })
    }

    /// 软删除（06 §1）。
    pub fn soft_delete(&self, id: i64) -> anyhow::Result<()> {
        let n = self.db.exec(
            "UPDATE work_modes SET deleted_at=datetime('now','localtime'), \
             updated_at=datetime('now','localtime') WHERE id=?1 AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        if n == 0 {
            anyhow::bail!("模式不存在或已删除：id={id}");
        }
        Ok(())
    }

    /// 成功应用后累加使用次数（**只应在成功路径调用**，见 REVIEW-010 R-07）。
    pub fn touch_used(&self, id: i64) -> anyhow::Result<()> {
        self.db.exec(
            "UPDATE work_modes SET use_count = use_count + 1, \
             last_used_at = datetime('now','localtime'), \
             updated_at = datetime('now','localtime') WHERE id=?1 AND deleted_at IS NULL",
            &[Value::from(id)],
        )?;
        Ok(())
    }

    fn find_by_name_including_deleted(&self, name: &str) -> anyhow::Result<Option<Value>> {
        let rows = self
            .db
            .query_json("SELECT id FROM work_modes WHERE name = ?", &[Value::from(name)])?;
        Ok(rows.into_iter().next())
    }
}

// ---------------------------------------------------------------- 布局（DB 为真相）

/// 布局记录（`layouts` 表）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LayoutRecord {
    pub id: i64,
    pub name: String,
    pub description: Option<String>,
    /// 契约 3.2.2 的 slots 数组（原样 JSON）
    pub slots: Value,
    pub monitor: i64,
    /// 契约 3.2.2 的 `aiSidebar`（AI 侧栏留位）。
    ///
    /// 此前表里没有这一列 → 从数据库读布局时**丢掉侧栏配置**，
    /// 导致阶段3 验收过的「侧栏留位」在阶段4 的库路径上回归失效（迁移 0004 补列）。
    #[serde(rename = "aiSidebar")]
    pub ai_sidebar: Option<Value>,
    #[serde(rename = "isBuiltin")]
    pub is_builtin: bool,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Clone)]
pub struct LayoutRepo {
    db: Db,
    /// 导出 JSON 的目标目录。
    ///
    /// **测试必须注入临时目录** —— 否则 `cargo test` 会往真实项目的
    /// `config/layouts/` 里塞垃圾文件（本模块第一版就污染过项目目录，
    /// 还是 git status 抓出来的）。
    export_dir: Option<std::path::PathBuf>,
}

impl LayoutRepo {
    pub fn new(db: Db) -> Self {
        Self { db, export_dir: None }
    }

    /// 测试用：把 JSON 导出重定向到指定目录（生产代码不应调用）。
    pub fn with_export_dir(db: Db, dir: std::path::PathBuf) -> Self {
        Self { db, export_dir: Some(dir) }
    }

    /// `layouts` 表的查询列（含 `ai_sidebar`，见迁移 0004）。
    const SELECT_COLS: &'static str =
        "id, name, description, slots, monitor, ai_sidebar, is_builtin, created_at, updated_at";

    pub fn list(&self) -> anyhow::Result<Vec<LayoutRecord>> {
        let rows = self.db.query_json(
            &format!("SELECT {} FROM layouts ORDER BY name ASC", Self::SELECT_COLS),
            &[],
        )?;
        Ok(rows.iter().map(to_layout).collect())
    }

    pub fn get(&self, name: &str) -> anyhow::Result<Option<LayoutRecord>> {
        let rows = self.db.query_json(
            &format!("SELECT {} FROM layouts WHERE name = ?", Self::SELECT_COLS),
            &[Value::from(name)],
        )?;
        Ok(rows.first().map(to_layout))
    }

    /// **唯一写入口**（06 §技术要点）：先写库，成功后导出 JSON。
    ///
    /// 导出失败只 `WARN` —— JSON 是派生品，数据库才是真相。
    pub fn upsert(
        &self,
        name: &str,
        description: Option<&str>,
        slots: &Value,
        monitor: i64,
        // 契约 3.2.2 的 `aiSidebar`（迁移 0004 补列）——不传则清空侧栏配置
        ai_sidebar: Option<&Value>,
        is_builtin: bool,
    ) -> anyhow::Result<LayoutRecord> {
        if name.trim().is_empty() || name.contains("..") || name.contains('/') || name.contains('\\')
        {
            anyhow::bail!("非法的布局名：{name}");
        }
        if !slots.is_array() {
            anyhow::bail!("slots 必须是数组");
        }
        let existed = self.get(name)?.is_some();
        if existed {
            self.db.exec(
                "UPDATE layouts SET description=?1, slots=?2, monitor=?3, ai_sidebar=?4, \
                 updated_at=datetime('now','localtime') WHERE name=?5",
                &[
                    opt_s(&description.map(str::to_string)),
                    slots.clone(),
                    Value::from(monitor),
                    ai_sidebar.cloned().unwrap_or(Value::Null),
                    Value::from(name),
                ],
            )?;
        } else {
            self.db.insert(
                "INSERT INTO layouts (name, description, slots, monitor, ai_sidebar, is_builtin, created_at, updated_at) \
                 VALUES (?1,?2,?3,?4,?5,?6,datetime('now','localtime'),datetime('now','localtime'))",
                &[
                    Value::from(name),
                    opt_s(&description.map(str::to_string)),
                    slots.clone(),
                    Value::from(monitor),
                    ai_sidebar.cloned().unwrap_or(Value::Null),
                    Value::from(if is_builtin { 1 } else { 0 }),
                ],
            )?;
        }
        let rec = self.get(name)?.context("写入后应能读到布局")?;
        let dir = self
            .export_dir
            .clone()
            .unwrap_or_else(crate::window_manager::layouts_dir);
        if let Err(e) = export_json(&dir, name, description, slots, monitor, ai_sidebar) {
            tracing::warn!(error = %e, name, "布局已写入数据库，但导出 JSON 失败（JSON 是派生品，不影响真相）");
        }
        Ok(rec)
    }
}

/// 导出布局 JSON 到 `<dir>/<name>.json`。
///
/// `dir` 由调用方给定（生产 = `config/layouts/`；测试 = 临时目录），
/// 避免测试污染项目目录。
fn export_json(
    dir: &std::path::Path,
    name: &str,
    description: Option<&str>,
    slots: &Value,
    monitor: i64,
    ai_sidebar: Option<&Value>,
) -> anyhow::Result<()> {
    std::fs::create_dir_all(dir)?;
    let mut doc = serde_json::json!({
        "name": name,
        "description": description,
        "monitor": monitor,
        "slots": slots,
    });
    // 侧栏配置必须一起导出，否则"导出的 JSON"与"库里的布局"不一致
    // （这也正是 quad.json 被覆盖时丢掉 aiSidebar 的原因）
    if let Some(sb) = ai_sidebar {
        if !sb.is_null() {
            doc["aiSidebar"] = sb.clone();
        }
    }
    let path = dir.join(format!("{name}.json"));
    std::fs::write(&path, serde_json::to_string_pretty(&doc)?)?;
    Ok(())
}

// ---------------------------------------------------------------- helpers

fn normalize_policy(p: Option<&str>) -> anyhow::Result<String> {
    match p {
        None | Some("") => Ok("additive".to_string()),
        Some(v) if SWITCH_POLICIES.contains(&v) => Ok(v.to_string()),
        Some(v) => anyhow::bail!("非法的切换策略：{v}（可选 {SWITCH_POLICIES:?}）"),
    }
}

fn opt_s(v: &Option<String>) -> Value {
    match v {
        Some(s) if !s.is_empty() => Value::from(s.as_str()),
        _ => Value::Null,
    }
}

fn json_str_array(v: Option<&Value>) -> Vec<String> {
    v.and_then(Value::as_array)
        .map(|a| a.iter().filter_map(|x| x.as_str().map(str::to_string)).collect())
        .unwrap_or_default()
}

/// 取一个"JSON 存在 TEXT 列里"的字段。
///
/// ⚠️ **必须二次解析**：`apps` / `open_targets` / `ai_profile` / `slots` 在数据库里是
/// **TEXT（JSON 字符串）**，而 `Db::query_json` 只做一层 SQL→JSON 转换 ——
/// 拿到的会是 `Value::String("[\"VSCode\"]")` 而不是 `Value::Array`。
/// 少了这一步，读出来的 `apps` 永远是空数组（本模块单测抓到的真实 bug）。
fn json_field(v: Option<&Value>) -> Value {
    match v {
        Some(Value::String(s)) => serde_json::from_str(s).unwrap_or(Value::Null),
        Some(other) => other.clone(),
        None => Value::Null,
    }
}

fn to_mode(v: &Value) -> WorkMode {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    let n = |k: &str| v.get(k).and_then(Value::as_i64);
    let apps = json_field(v.get("apps"));
    let targets = json_field(v.get("open_targets"));
    let profile = json_field(v.get("ai_profile"));
    WorkMode {
        id: n("id").unwrap_or(0),
        name: s("name").unwrap_or_default(),
        description: s("description"),
        icon: s("icon"),
        apps: json_str_array(Some(&apps)),
        open_targets: serde_json::from_value::<Vec<OpenTarget>>(targets).unwrap_or_default(),
        layout: s("layout"),
        ai_profile: serde_json::from_value::<AiProfile>(profile).ok(),
        auto_apply: n("auto_apply").unwrap_or(0) != 0,
        switch_policy: s("switch_policy").unwrap_or_else(|| "additive".into()),
        use_count: n("use_count").unwrap_or(0),
        last_used_at: s("last_used_at"),
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

fn to_layout(v: &Value) -> LayoutRecord {
    let s = |k: &str| v.get(k).and_then(Value::as_str).map(str::to_string);
    LayoutRecord {
        id: v.get("id").and_then(Value::as_i64).unwrap_or(0),
        name: s("name").unwrap_or_default(),
        description: s("description"),
        // 同上：slots 也是存在 TEXT 列里的 JSON，必须二次解析
        slots: json_field(v.get("slots")),
        monitor: v.get("monitor").and_then(Value::as_i64).unwrap_or(0),
        // ai_sidebar 同属 TEXT 列存的 JSON（可能为 NULL）
        ai_sidebar: match json_field(v.get("ai_sidebar")) {
            Value::Null => None,
            other => Some(other),
        },
        is_builtin: v.get("is_builtin").and_then(Value::as_i64).unwrap_or(0) != 0,
        created_at: s("created_at").unwrap_or_default(),
        updated_at: s("updated_at").unwrap_or_default(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn repo() -> (ModeRepo, LayoutRepo, std::path::PathBuf) {
        let dir = std::env::temp_dir().join(format!(
            "pw-mode-test-{}-{:?}",
            std::process::id(),
            std::thread::current().id()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let db = Db::open(&dir.join("t.db")).unwrap();
        db.initialize().unwrap();
        // 导出目录指向临时目录 —— 否则单测会往项目的 config/layouts/ 里塞文件
        (
            ModeRepo::new(db.clone()),
            LayoutRepo::with_export_dir(db, dir.join("layouts")),
            dir,
        )
    }

    fn input(name: &str, apps: &[&str]) -> WorkModeInput {
        WorkModeInput {
            name: name.into(),
            description: Some("测试".into()),
            icon: None,
            apps: apps.iter().map(|s| s.to_string()).collect(),
            open_targets: vec![],
            layout: Some("quad".into()),
            ai_profile: Some(AiProfile {
                provider: "deepseek".into(),
                system_prompt_key: "dev".into(),
                permission_scope: vec!["file:read".into()],
            }),
            auto_apply: false,
            switch_policy: None,
        }
    }

    #[test]
    fn crud_roundtrip_keeps_json_fields() {
        let (modes, _, dir) = repo();
        let m = modes.add(&input("开发模式", &["VSCode", "Chrome"])).unwrap();
        assert_eq!(m.apps, vec!["VSCode", "Chrome"]);
        assert_eq!(m.ai_profile.as_ref().unwrap().provider, "deepseek");
        assert_eq!(m.switch_policy, "additive", "缺省切换策略应为 additive");

        let got = modes.get(m.id).unwrap().unwrap();
        assert_eq!(got.name, "开发模式");
        assert_eq!(got.apps.len(), 2);

        modes.update(m.id, &WorkModePatch {
            apps: Some(vec!["VSCode".into()]),
            switch_policy: Some("exclusive".into()),
            ..Default::default()
        }).unwrap();
        let after = modes.get(m.id).unwrap().unwrap();
        assert_eq!(after.apps, vec!["VSCode"]);
        assert_eq!(after.switch_policy, "exclusive");
        assert_eq!(after.description.as_deref(), Some("测试"), "未给的字段不应被清空");

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// R-02：软删除的模式**不得**再出现在 list / get 里（否则幽灵模式会被 apply）。
    #[test]
    fn soft_deleted_mode_is_invisible() {
        let (modes, _, dir) = repo();
        let m = modes.add(&input("待删模式", &[])).unwrap();
        modes.soft_delete(m.id).unwrap();
        assert!(modes.list().unwrap().is_empty(), "软删除后 list 不应含它");
        assert!(modes.get(m.id).unwrap().is_none(), "软删除后 get 应返回 None");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn duplicate_gets_unique_name_and_does_not_inherit_auto_apply() {
        let (modes, _, dir) = repo();
        let mut i = input("开发模式", &["VSCode"]);
        i.auto_apply = true;
        let m = modes.add(&i).unwrap();

        let d1 = modes.duplicate(m.id).unwrap();
        assert_eq!(d1.name, "开发模式 副本");
        assert!(!d1.auto_apply, "副本不得继承自动进入（否则会有两个自动模式）");
        assert_eq!(d1.apps, vec!["VSCode"]);

        let d2 = modes.duplicate(m.id).unwrap();
        assert_eq!(d2.name, "开发模式 副本2", "重名应递增序号");

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn rejects_illegal_switch_policy_and_duplicate_name() {
        let (modes, _, dir) = repo();
        let mut bad = input("X", &[]);
        bad.switch_policy = Some("whatever".into());
        assert!(modes.add(&bad).unwrap_err().to_string().contains("非法的切换策略"));

        modes.add(&input("Y", &[])).unwrap();
        assert!(modes.add(&input("Y", &[])).unwrap_err().to_string().contains("同名"));
        // 软删后同名仍占用（name UNIQUE），不得静默新建出两条同名记录
        let y = modes.get_by_name("Y").unwrap().unwrap();
        modes.soft_delete(y.id).unwrap();
        assert!(modes.add(&input("Y", &[])).is_err(), "软删后同名仍应被拒（避免歧义）");

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// R-07：`touch_used` 只在成功路径被调用；这里验证计数与时间真的被写入。
    #[test]
    fn touch_used_updates_counter_and_timestamp() {
        let (modes, _, dir) = repo();
        let m = modes.add(&input("计数", &[])).unwrap();
        assert_eq!(m.use_count, 0);
        modes.touch_used(m.id).unwrap();
        modes.touch_used(m.id).unwrap();
        let after = modes.get(m.id).unwrap().unwrap();
        assert_eq!(after.use_count, 2);
        assert!(after.last_used_at.is_some(), "last_used_at 应被写入");

        let _ = std::fs::remove_dir_all(&dir);
    }

    /// F-42：布局写入必须**先落库**（真相），JSON 只是派生品。
    #[test]
    fn layout_upsert_writes_db_and_exports_json() {
        let (_, layouts, dir) = repo();
        let slots = serde_json::json!([
            {"app": "A", "rect": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0}, "z": 1}
        ]);
        let rec = layouts.upsert("unit-test-layout", Some("单测"), &slots, 0, None, false).unwrap();
        assert_eq!(rec.name, "unit-test-layout");
        assert!(rec.slots.is_array());

        let again = layouts
            .upsert("unit-test-layout", Some("改名"), &slots, 1, None, false)
            .unwrap();
        assert_eq!(again.id, rec.id, "同名应更新而非新建");
        assert_eq!(again.monitor, 1);

        assert!(
            layouts.upsert("../evil", None, &slots, 0, None, false).is_err(),
            "路径穿越必须被拒"
        );
        assert!(
            layouts.upsert("x", None, &serde_json::json!({}), 0, None, false).is_err(),
            "slots 必须是数组"
        );

        // 侧栏配置必须能往返（迁移 0004 补列的原因：此前从库读会丢 aiSidebar）
        let sb = serde_json::json!({"enabled": true, "edge": "right", "width": 0.25});
        layouts
            .upsert("unit-test-sidebar", None, &slots, 0, Some(&sb), false)
            .unwrap();
        let got = layouts.get("unit-test-sidebar").unwrap().unwrap();
        assert_eq!(
            got.ai_sidebar.as_ref().and_then(|v| v.get("width")).and_then(Value::as_f64),
            Some(0.25),
            "aiSidebar 必须能在库中往返（否则侧栏留位在库路径上失效）"
        );

        let _ = std::fs::remove_dir_all(&dir);
    }
}
