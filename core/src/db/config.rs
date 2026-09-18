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
            bus,
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

/// 数据契约版本在 config 表中的键名。
///
/// 与 `migrations::MIGRATION_VERSION_KEY`（迁移台账）**必须分开**：
/// 前者是"契约版本"（03 §3.5，由 `db::initialize` 按常量写），
/// 后者是"已执行的 DDL 序号"（只有迁移执行器写）。混用会导致两者互相覆盖。
pub const SCHEMA_VERSION_KEY: &str = "schema_version";

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
    // ---- 阶段4（06 §4 模式状态管理）----
    // 全局唯一 current_mode：**存模式名**（验收 V-10 要显示"上次使用：开发模式"）；
    // 空串表示"无当前模式"。存名而非 id 是因为模式名会展示给用户，id 对用户无意义。
    "mode.current",
    // 模式切换策略记忆（06 §3 的 `ask`：首次询问并记住选择）
    "mode.switch_memory",
    // 当前生效的 AI 配置（06 §2 步骤⑥「加载 AI」写入；阶段5 的 AI 助手消费）
    "ai.active_profile",
    // ---- 阶段5（08 §5 AI 侧栏持久化）----
    // 侧栏宽度 / 收起状态 / 上次选择的 Provider、模型、模式（验收项 9）。
    // **类型一律 string**：前端 localStorage 只能存字符串（`'480'` / `'1'`），
    // core 这侧作为**权威副本**与之同构 —— 若这里登记成 number/boolean，
    // 两个副本的表示就会不一致（写 A 读 B 必然对不上）。
    "ui.ai.width",
    "ui.ai.collapsed",
    "ui.ai.provider",
    "ui.ai.model",
    "ui.ai.mode",
    // ---- TECH-04 §一：canonical 的**正式落点**（PW-INTEGRATION-003 §3.2 的冻结键）----
    // TECH-03-A/B 期间这两个键未登记 ⇒ `ConfigService::set` 会 bail ⇒ canonical 只能落到
    // 上面的过渡镜像键，并在 UI 上长期显示"待同步"。TECH-04 正式登记后 L1 成为唯一落点。
    // **镜像键 `ui.ai.provider` / `ui.ai.model` 刻意保留**（不删不弃）：
    //   ① UI 的 localStorage 兜底与 core 副本必须同构（见阶段5 的类型约定）；
    //   ② 老数据（仅写过镜像的用户）仍能读出来 —— 迁移路径见 `ui/src/ai/model/bridge.ts`
    //      的 `migrateIfNeeded()`（一次性前向搬运，不删旧值）。
    "ai.provider.current",
    "ai.model.current",
    // ---- 阶段6（09 §5 提醒机制）----
    // `remind_after_days` = 多久算"长期未更新"（天）；`remind_enabled` = 总开关。
    // 总开关是必需的：09 §禁止事项「不要做强制提醒（用户关不掉）」——
    // 没有开关就只能靠把天数设成负数来关，属反直觉的隐式行为。
    "learning.remind_after_days",
    "learning.remind_enabled",
    // ---- 阶段7（10 §5 建议的权利之四：永久拒绝某类建议）----
    // string 存 JSON 数组（如 `["timeline"]`），与 `ui.ai.*` 的字符串同构约定一致。
    "profile.rejected_kinds",
    // ---- TECH-05-C §P0-2：档案头像 ----
    // `profile_basic` 表**不新增列**（P0-2 明确禁止改数据库 schema）；头像是一个
    // 「单值偏好」而非档案结构化字段，因此落在已登记的 config 键上：
    //   值 = 空串（用昵称首字母）或一个预设 emoji（如 `"💻"`）。
    // 与 `ui.ai.*` 的字符串同构约定一致 —— 不做类型特例。
    "profile.avatar",
    // ---- 阶段8（11 §A1 天气 / §B2 设备指标 / §A4 健康生活）----
    // 天气城市：**用户手动设置**（禁止默认获取系统定位，隐私优先）。
    "life.weather.city",
    // 设备指标刷新间隔（秒）。11 §禁止事项：< 1s 的高频轮询会明显影响性能 ⇒ 下限 1。
    "device.metrics_interval_sec",
    // 前台采样间隔（秒）。默认 30s（11 §A4）；验收脚本可调小以便机器复现。
    "life.usage_sample_interval_sec",
    // 休息提醒：今日累计使用超过 N 小时提醒（0 = 关闭，11 §A4 默认关闭）。
    "life.break_remind_hours",
    // 社交服务配置：string 存 JSON 数组（同构约定），由用户显式添加，
    // 绝不存聊天内容（红线：不保存聊天内容 / 不自动发送 / 不无授权爬取）。
    "life.social.services",
    // ---- 阶段9（12 §C 外部 Agent / §B 桌面小组件）----
    // 外部 Agent 注册清单：string 存 JSON 数组（契约 3.2.5 形态），
    // 每个 agent 自带 permissions 白名单；默认空 = 无任何外部 Agent。
    "agents.external",
    // 桌面小组件开关（独立 Tauri 窗口，默认关闭）。
    "widget.desktop.enabled",
    // 桌面小组件配置：string 存 JSON（位置/大小/缩放/透明度/显示项/主题），
    // 与 `ui.ai.*` 的字符串同构约定一致。位置缩放重启后保持（12 §验收9）。
    "widget.desktop.config",
    // ---- TECH-06-B Part 1（模型清单唯一持久化来源）----
    // string 存 JSON：`{"v":1,"models":[...]}`（形态由 `ui/src/ai/model/archive.ts` 唯一定义）。
    // 读写**只**经 ModelRegistry 的 archive 端口（add/update/remove/clear 落盘），
    // 页面与 AI 侧栏不得直连 —— 禁止出现第二事实源。
    // 刻意**不含探测状态**（available/lastCheck/lastError）：重启后如显示「已连接/失败」
    // 即假状态 —— 恢复出的模型一律回到「未测试」，等真实探测给结论。
    "ai.models.registry",
    // ---- TECH-07-C4（Workspace Snapshot v1 持久化落点）----
    // **唯一持久化落点**：`workspace.snapshot.last`（PW-INTEGRATION-003 冻结键）。
    // 类型 `object` = 直接存 Snapshot v1 文档本体（形态由
    // `docs/contracts/workspace-snapshot.v1.schema.json` 唯一定义，
    // 前端镜像在 TECH-02 冻结域 `ui/src/workspace/snapshot.ts`）。
    // 刻意**不新建表 / 不新增迁移** —— 快照是"单值历史状态"，不是业务实体。
    // 默认 `{}` = "从未写入过"（validate 会因缺 schemaVersion 直接拒绝，
    // 语义等价于空快照，但不会被误当成一份合法快照）。
    "workspace.snapshot.last",
    // ---- UI-FUSION-FULL（设计稿壳层并入：三档宽度 + 插件组件区清单）----
    // 设计稿 `RESIZE_CONF` 的三档宽度里，AI 档已由 `ui.ai.width` 承载（阶段5 登记）。
    // 这里补上导航 / 组件区两档。**类型用 number**（不是 `ui.ai.width` 那种 string）：
    // `ui.ai.*` 用 string 是因为它们要同时兼容"localStorage 只能存字符串"的老约定；
    // 这两个键是本轮新增，没有历史副本，直接按真实语义登记为数值，不做无谓同构。
    "ui.shell.nav_w",
    "ui.shell.widget_w",
    // 插件组件区（设计稿 `WIDGETS`）的**顺序 + 启用状态**，`array` 存
    // `[{id,name,icon,on}]` —— 与 `ui.dashboard.widgets` 同为 `array`（同类事物同类型）。
    // 与首页 Widget 网格**不是同一份数据**：那份是内容区的卡片布局，这份是右侧挂件列。
    "ui.shell.widgets",
];

/// 配置项期望类型（04 §4 类型校验）。`number|null` 表示可空数值。
///
/// ⚠️ 新增键时**必须同时**登记 `KEYS` / `expected_type` / `default_for` 三处，
/// 漏掉 `expected_type` 会静默落到 `_ => "any"`（等于没有类型校验）。
/// 这正是 `ui.dashboard.layout_locked` 曾经的情况 —— 已修，并由
/// `every_registered_key_has_an_explicit_type` 测试锁死这一类漏登。
pub fn expected_type(key: &str) -> &'static str {
    match key {
        SCHEMA_VERSION_KEY | "runtime.http_port" => "number",
        "ui.theme" | "app.data_dir" | "ai.default_provider" => "string",
        "ui.nav.collapsed"
        | "app.autostart"
        | "privacy.telemetry"
        | "ui.dashboard.layout_locked" => "boolean",
        "ui.dashboard.widgets" => "array",
        "ui.dashboard.usage" => "object",
        "runtime.sidecar_port" => "number|null",
        // 阶段4：模式状态
        "mode.current" => "string",
        "mode.switch_memory" => "object",
        "ai.active_profile" => "object",
        // 阶段5：AI 侧栏持久化（与前端 localStorage 同构，均为字符串）
        "ui.ai.width" | "ui.ai.collapsed" | "ui.ai.provider" | "ui.ai.model" | "ui.ai.mode" => {
            "string"
        }
        // TECH-04 §一：canonical 正式落点（与 `ui.ai.*` 同为字符串 —— 保持两份副本表示一致）
        "ai.provider.current" | "ai.model.current" => "string",
        // 阶段6：学习提醒（阈值天数 / 总开关）
        "learning.remind_after_days" => "number",
        "learning.remind_enabled" => "boolean",
        // 阶段7：永久拒绝的建议类型清单（JSON 数组的字符串形态）
        "profile.rejected_kinds" => "string",
        // TECH-05-C §P0-2：头像（空串 = 首字母头像 / 预设 emoji 字符）
        "profile.avatar" => "string",
        // 阶段8：生活与设备
        "life.weather.city" => "string",
        "device.metrics_interval_sec" => "number",
        "life.usage_sample_interval_sec" => "number",
        "life.break_remind_hours" => "number",
        "life.social.services" => "string",
        // 阶段9：外部 Agent / 桌面小组件
        "agents.external" => "string",
        "widget.desktop.enabled" => "boolean",
        "widget.desktop.config" => "string",
        // TECH-06-B Part 1：模型清单（string 存 JSON —— 与 widget.desktop.config 同构约定）
        "ai.models.registry" => "string",
        // TECH-07-C4：Workspace Snapshot v1 文档本体（object —— 非空即"写过"）
        "workspace.snapshot.last" => "object",
        // UI-FUSION-FULL：壳层三档宽度之二 + 插件组件区清单
        "ui.shell.nav_w" | "ui.shell.widget_w" => "number",
        "ui.shell.widgets" => "array",
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
        SCHEMA_VERSION_KEY => serde_json::json!(0),
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
        // 阶段4：无当前模式 = 空串（不用 null，以便与"未设置"区分并复用同一条类型规则）
        "mode.current" => serde_json::json!(""),
        "mode.switch_memory" => serde_json::json!({}),
        "ai.active_profile" => serde_json::json!({}),
        // 阶段5：默认值与前端 `ui/src/stores/ai.ts` 的 lsGet fallback 保持一致
        "ui.ai.width" => serde_json::json!("360"),
        "ui.ai.collapsed" => serde_json::json!("0"),
        "ui.ai.provider" => serde_json::json!(""),
        "ui.ai.model" => serde_json::json!(""),
        "ui.ai.mode" => serde_json::json!("consult"),
        // TECH-04 §一：canonical 默认空串 = "尚未设置"（与前端 `lsGet(..., '')` 的兜底一致）
        "ai.provider.current" => serde_json::json!(""),
        "ai.model.current" => serde_json::json!(""),
        // 阶段6：默认 30 天、默认开启（09 §5 的默认值）
        "learning.remind_after_days" => serde_json::json!(30),
        "learning.remind_enabled" => serde_json::json!(true),
        "profile.rejected_kinds" => serde_json::json!("[]"),
        // TECH-05-C §P0-2：默认空串 = 首字母头像（不猜用户偏好，不预置 emoji）
        "profile.avatar" => serde_json::json!(""),
        // 阶段8：生活与设备（11 §A1/B2/A4 默认值）
        "life.weather.city" => serde_json::json!(""),
        "device.metrics_interval_sec" => serde_json::json!(2),
        "life.usage_sample_interval_sec" => serde_json::json!(30),
        "life.break_remind_hours" => serde_json::json!(0),
        "life.social.services" => serde_json::json!("[]"),
        // 阶段9：外部 Agent（默认无）/ 桌面小组件（默认关闭 + 空配置）
        "agents.external" => serde_json::json!("[]"),
        "widget.desktop.enabled" => serde_json::json!(false),
        "widget.desktop.config" => serde_json::json!("{}"),
        // TECH-06-B Part 1：默认空串 = "从未写过"。
        // ⚠️ 不能用 "[]"：归档信封是 {"v":1,"models":[...]}，顶层不是数组；
        // 空串对应 parseArchive 的"从未写过"分支（干净返回空清单、零 issue）。
        "ai.models.registry" => serde_json::json!(""),
        // TECH-07-C4：默认空对象 = 从未写过（validate 会因缺 schemaVersion 拒绝，
        // 不会被当成合法快照；**绝不能**用 null —— 测试要求登记键有显式非 null 默认值）
        "workspace.snapshot.last" => serde_json::json!({}),
        // UI-FUSION-FULL：三档宽度的初值 = 设计稿 RESIZE_CONF.def（nav 236 / widget 224）。
        // 空数组 = "从未调过顺序"，前端回落到设计稿 WIDGETS 的原始顺序与开关。
        "ui.shell.nav_w" => serde_json::json!(236),
        "ui.shell.widget_w" => serde_json::json!(224),
        "ui.shell.widgets" => serde_json::json!([]),
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

    /// 契约约束：每个登记键都必须有**显式**类型规则，不得落到 `_ => "any"`。
    ///
    /// 加这条的原因：`ui.dashboard.layout_locked` 曾漏登 expected_type，
    /// 于是它的"类型校验"实际是 `any`（任何类型都写进去）。
    /// 这与 default 那条是同类漏登，必须一并锁死。
    #[test]
    fn every_registered_key_has_an_explicit_type() {
        for key in KEYS {
            assert_ne!(
                expected_type(key),
                "any",
                "登记键 {key} 未登记 expected_type（会静默变成无类型校验）"
            );
        }
    }

    /// 契约约束（**反向**）：`expected_type` / `default_for` 里出现过的键，
    /// 必须全都在 `KEYS` 白名单内。
    ///
    /// 加这条的原因：`ai.models.registry` 曾同时登记了 `expected_type` 与 `default_for`，
    /// 却**漏在 `KEYS` 数组**里 —— 结果 `ConfigService::set` 直接拒绝写入
    /// （"未登记的配置键"），而上面两条正向测试查不出来：它们是"遍历 KEYS 再查
    /// type/default"，漏掉的那一项压根不在 KEYS 里，永远不会被遍历到。
    ///
    /// 本测试直接扫源码文本（`include_str!` 自身），方向与正向测试相反 ——
    /// 键只要在 match 臂里出现，就必须在 KEYS 里。自维护：无需再抄一份键清单。
    #[test]
    fn every_typed_key_is_in_whitelist() {
        const SRC: &str = include_str!("config.rs");
        // ⚠️ 下面两根"针"**必须拼出来**，源码里绝不能出现"f n expected_type"
        // 这样的连续字面量（即"fn "紧接类型表函数名）：`tools/verify_tech04.py`、
        // `verify_tech05c.py`、`verify_model_registry.py` 三个门禁都用
        // `config_rs.split(...)` 以该字面量为分隔符截取函数体。本文件里只要再多一处，
        // 它们就会取到**测试段之后**的空区间 ⇒ 类型表恒判"未登记"
        // （本轮亲身踩过：tech04 44→43、tech05c 34→33、model_registry 32→31）。
        let needle_type = format!("fn {}", "expected_type");
        let start = SRC
            .find(&needle_type)
            .expect("测试失效：找不到类型表函数");
        let end = SRC
            .find("#[cfg(test)]")
            .expect("测试失效：找不到 tests 段起点");
        let body = &SRC[start..end];

        // 只认"像键"的字面量：含 `.`，且字符集为 [a-z0-9_.]。
        // 这可自然排除类型值（number/string/boolean/array/object/number|null/any）
        // 与 default 值（"light"/"360"/""/"[]"/"consult" 等 —— 都不含 `.`）。
        let looks_like_key = |s: &str| {
            s.len() >= 3
                && s.contains('.')
                && s.chars()
                    .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '.' || c == '_')
        };

        let mut checked = 0usize;
        for lit in body.split('"').skip(1).step_by(2) {
            if !looks_like_key(lit) {
                continue;
            }
            assert!(
                KEYS.contains(&lit),
                "键 {lit} 已在 expected_type/default_for 登记，却不在 KEYS 白名单里 —— \
                 ConfigService::set 会拒绝写入（漏登 KEYS）"
            );
            checked += 1;
        }
        assert!(
            checked >= 20,
            "反向扫描只取到 {checked} 个键字面量，测试本身可能已失效（正则/文本被改）"
        );
    }

    /// layout_locked 必须是 boolean（回归：曾落到 any）。
    #[test]
    fn layout_locked_is_boolean_and_enforced() {
        assert_eq!(expected_type("ui.dashboard.layout_locked"), "boolean");
        assert!(type_ok(&serde_json::json!(true), expected_type("ui.dashboard.layout_locked")));
        assert!(!type_ok(
            &serde_json::json!("true"),
            expected_type("ui.dashboard.layout_locked")
        ));
    }
}
