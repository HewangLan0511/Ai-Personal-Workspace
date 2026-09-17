//! 本地 HTTP 服务：core 对 Python sidecar（/internal/*）与 UI（/api/v1/*）的唯一接口面。
//!
//! 契约：docs/agent-dev/03-数据契约与接口规范.md §3.4。
//! 统一返回 `{ ok, data?, error? { code, message } }`。
//!
//! 说明：02-架构与目录规范 §2.2 的强制目录树未列出 src/api/，
//! 本目录是架构师裁量新增（HTTP 接口面需要独立模块），已在 core/README.md 登记。

pub mod commands;

use std::sync::Arc;

use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::routing::{delete, get, post, put};
use axum::{Json, Router};
use serde_json::{json, Value};
use tauri::Manager;

use crate::db::WRITABLE_TABLES;
use crate::state::AppState;

fn ok(data: Value) -> Json<Value> {
    Json(json!({ "ok": true, "data": data }))
}

// ---------------------------------------------------------------- C4：core 实例身份事实
//
// Snapshot v1 的 `source` 需要三个真实出口（appVersion / corePid / runId 的原料），
// 而 core 此前**没有**任何进程身份出口（TECH-07-C4 审计结论）。这里给出最小实现：
//   - 只暴露**当前进程真实 pid** 与**本次实例真实启动时间**（epoch ms）；
//   - 不新增命令、不新增表、不新增迁移、不引入 session manager；
//   - `service` 字段保持存在 —— 既有 `/health` 消费者（UI `checkConnection`、
//     sidecar/agent 探活）不受影响。
static STARTED_AT_MS: std::sync::OnceLock<u64> = std::sync::OnceLock::new();

/// 在进程装配早期打点（main.rs 调用；未调用时按首次访问惰性兜底）。
pub fn mark_started_now() {
    let ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0);
    let _ = STARTED_AT_MS.set(ms);
}

fn started_at_ms() -> u64 {
    *STARTED_AT_MS.get_or_init(|| {
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_millis() as u64)
            .unwrap_or(0)
    })
}

/// `/health` 与 `ping` 共用的身份事实（`{ service, pid, started_at }`）。
pub fn identity_facts() -> Value {
    json!({
        "service": "pw-core",
        "pid": std::process::id(),
        "started_at": started_at_ms(),
    })
}

fn err(code: &str, message: &str, status: StatusCode) -> (StatusCode, Json<Value>) {
    (
        status,
        Json(json!({ "ok": false, "error": { "code": code, "message": message } })),
    )
}

pub fn spawn_server(state: Arc<AppState>) {
    tauri::async_runtime::spawn(async move {
        // 随机端口绑定后写入 config（runtime.http_port），由 UI/侧车读取。
        let listener = match tokio::net::TcpListener::bind("127.0.0.1:0").await {
            Ok(l) => l,
            Err(e) => {
                tracing::error!(error = %e, "HTTP 服务绑定失败");
                return;
            }
        };
        let port = listener
            .local_addr()
            .map(|addr| addr.port())
            .unwrap_or_default();
        if port != 0 {
            if let Err(e) = state.config.set("runtime.http_port", json!(port)) {
                tracing::error!(error = %e, "写入 http 端口失败");
            }
        }
        tracing::info!(port, "core HTTP 服务已启动");

        let app = Router::new()
            // ---- UI（契约 3.4）----
            .route("/api/v1/config/{key}", get(get_config).put(put_config))
            // ---- 软件管理（阶段2）。契约 3.4 的 /api/v1 面，供非浏览器客户端
            // （curl / 脚本 / 自动化验收）使用；UI 走 invoke 同名命令，逻辑同源。
            .route("/api/v1/apps", get(api_apps_list).post(api_apps_add))
            .route("/api/v1/apps/categories", get(api_apps_categories))
            .route("/api/v1/apps/running", get(api_apps_running))
            // 图标独立成顶层路径：避免与 `/apps/{id}` 的参数段冲突（matchit 路由冲突会 panic）
            .route("/api/v1/icon", get(api_icon))
            // 扫描/探测也走顶层：同样为避免与 `/apps/{id}` 混用静态段与参数段
            .route("/api/v1/scan", post(api_apps_scan))
            .route("/api/v1/probe", post(api_apps_probe))
            .route("/api/v1/apps/{id}", put(api_apps_update).delete(api_apps_delete))
            .route("/api/v1/apps/{id}/launch", post(api_apps_launch))
            // ---- 窗口管理（阶段3）----
            .route("/api/v1/monitors", get(api_monitors))
            .route("/api/v1/layouts", get(api_layouts))
            .route("/api/v1/layouts/{name}", get(api_layout_get))
            .route("/api/v1/layouts/{name}/apply", post(api_layout_apply))
            .route("/api/v1/windows", get(api_windows))
            .route(
                "/api/v1/windows/{hwnd}",
                get(api_window_rect).post(api_window_place),
            )
            .route("/api/v1/windows/{hwnd}/activate", post(api_window_activate))
            // ---- 工作模式引擎（阶段4）----
            // 注意：`current` / `cancel` / `progress` / `capture` 走**单数顶层** `/api/v1/mode/*`，
            // 避免与 `/api/v1/modes/{id}` 的静态段/参数段混用（matchit 冲突会 panic）。
            .route("/api/v1/mode/capture", post(api_modes_capture))
            .route("/api/v1/modes", get(api_modes_list).post(api_modes_add))
            .route(
                "/api/v1/modes/{id}",
                get(api_modes_get).put(api_modes_update).delete(api_modes_delete),
            )
            .route("/api/v1/modes/{id}/duplicate", post(api_modes_duplicate))
            .route("/api/v1/modes/{id}/apply", post(api_mode_apply))
            .route("/api/v1/mode/current", get(api_mode_current))
            .route("/api/v1/mode/cancel", post(api_mode_cancel))
            .route("/api/v1/mode/progress", get(api_mode_progress))
            .route("/api/v1/mode/restore", post(api_mode_restore))
            .route("/api/v1/mode/remember", post(api_mode_remember))
            .route("/api/v1/mode/exit", post(api_mode_exit))
            .route("/api/v1/db/layouts", get(api_db_layouts).post(api_db_layout_upsert))
            // ---- 学习成长（阶段6）----
            .route("/api/v1/learning/goals", get(api_learning_goals).post(api_learning_goal_add))
            .route(
                "/api/v1/learning/goals/{id}",
                get(api_learning_goal_get)
                    .put(api_learning_goal_update)
                    .delete(api_learning_goal_delete),
            )
            .route("/api/v1/learning/goals/{id}/nodes", get(api_learning_nodes))
            .route(
                "/api/v1/learning/goals/{id}/roadmap",
                post(api_learning_roadmap_confirm),
            )
            .route("/api/v1/learning/goals/{id}/updates", get(api_learning_updates))
            .route("/api/v1/learning/nodes", post(api_learning_node_add))
            .route(
                "/api/v1/learning/nodes/{id}",
                put(api_learning_node_update).delete(api_learning_node_delete),
            )
            .route("/api/v1/learning/nodes/{id}/move", post(api_learning_node_move))
            .route("/api/v1/learning/updates", post(api_learning_update_add))
            .route("/api/v1/learning/suggest", post(api_learning_suggest))
            .route("/api/v1/learning/reminders/check", post(api_learning_reminders_check))
            // ---- 项目管理（阶段6 §6）----
            .route("/api/v1/projects", get(api_projects).post(api_project_add))
            // 单数顶层，避开与 `/projects/{id}` 的静态段/参数段混用（matchit 冲突会 panic）
            .route("/api/v1/project/by-mode", get(api_project_by_mode))
            .route(
                "/api/v1/projects/{id}",
                get(api_project_get).put(api_project_update).delete(api_project_delete),
            )
            // ---- 个人数字档案（阶段7）----
            .route("/api/v1/profile", get(api_profile_overview))
            .route("/api/v1/profile/basic", get(api_profile_basic_get).put(api_profile_basic_save))
            .route("/api/v1/profile/skills", get(api_profile_skills).post(api_profile_skill_add))
            .route(
                "/api/v1/profile/skills/{id}",
                put(api_profile_skill_update).delete(api_profile_skill_remove),
            )
            .route("/api/v1/profile/skills/{id}/confirm", post(api_profile_skill_confirm))
            .route("/api/v1/profile/projects", get(api_profile_projects).post(api_profile_project_add))
            .route(
                "/api/v1/profile/projects/{id}",
                delete(api_profile_project_remove).post(api_profile_project_confirm),
            )
            .route("/api/v1/profile/timeline", get(api_profile_timeline).post(api_profile_timeline_add))
            .route(
                "/api/v1/profile/timeline/{id}",
                delete(api_profile_timeline_remove).post(api_profile_timeline_confirm),
            )
            .route("/api/v1/profile/suggestions", get(api_profile_suggestions))
            .route("/api/v1/profile/suggestions/scan", post(api_profile_suggestions_scan))
            .route(
                "/api/v1/profile/suggestions/confirm",
                post(api_profile_suggestions_confirm),
            )
            .route(
                "/api/v1/profile/suggestions/ignore",
                post(api_profile_suggestions_ignore),
            )
            .route(
                "/api/v1/profile/suggestions/reject-kind",
                post(api_profile_suggestions_reject_kind),
            )
            .route("/api/v1/profile/export/markdown", get(api_profile_export_markdown))
            // ---- 生活中心（阶段8 §A）----
            .route("/api/v1/life/usage/today", get(api_life_usage_today))
            .route("/api/v1/life/usage/week", get(api_life_usage_week))
            .route("/api/v1/life/weather", get(api_life_weather))
            .route("/api/v1/life/media", get(api_life_media))
            .route("/api/v1/life/media/control", post(api_life_media_control))
            .route("/api/v1/life/social/overview", get(api_life_social_overview))
            .route(
                "/api/v1/life/social/config",
                get(api_life_social_config).put(api_life_social_config_put),
            )
            // ---- 设备中心（阶段8 §B）----
            .route("/api/v1/device/metrics", get(api_device_metrics))
            .route("/api/v1/device/processes", get(api_device_processes))
            .route("/api/v1/device/processes/kill", post(api_device_process_kill))
            .route("/api/v1/device/mode-health", get(api_device_mode_health))
            // ---- 插件系统（阶段9 §A）。全静态路径，避开 matchit 参数段混用 ----
            .route("/api/v1/plugins", get(api_plugins_list))
            .route("/api/v1/plugins/discover", get(api_plugins_discover))
            .route("/api/v1/plugins/install", post(api_plugins_install))
            .route("/api/v1/plugins/import", post(api_plugins_import))
            .route("/api/v1/plugins/enabled", post(api_plugins_set_enabled))
            .route("/api/v1/plugins/uninstall", post(api_plugins_uninstall))
            .route("/api/v1/plugin/api", post(api_plugin_api))
            .route("/api/v1/plugin/crash", post(api_plugin_crash))
            .route("/api/v1/plugin/audit", get(api_plugin_audit))
            // ---- 外部 Agent（阶段9 §C）----
            .route("/api/v1/agents", get(api_agents_list).put(api_agents_save))
            .route("/api/v1/agent/health", post(api_agent_health))
            .route("/api/v1/agent/invoke", post(api_agent_invoke))
            .route("/api/v1/agent/gateway", post(api_agent_gateway))
            // ---- 桌面小组件（阶段9 §B）----
            .route(
                "/api/v1/desktop-widget/toggle",
                post(api_desktop_widget_toggle),
            )
            .route("/api/v1/desktop-widget/status", get(api_desktop_widget_status))
            .route("/api/v1/desktop-widget/bounds", post(api_desktop_widget_bounds))
            .route(
                "/api/v1/desktop-widget/always-on-top",
                post(api_desktop_widget_always_on_top),
            )
            // ---- Python sidecar（契约 3.4）----
            .route("/internal/config/{key}", get(get_config))
            .route("/internal/db/query", post(internal_db_query))
            .route("/internal/db/exec", post(internal_db_exec))
            .route("/internal/event/publish", post(internal_event_publish))
            // C4：`/health` 增加 `pid` / `started_at`（Snapshot `source` 的真实出口）。
            // `service` 保持原值 —— 兼容既有消费者。
            .route("/health", get(|| async { ok(identity_facts()) }))
            .with_state(state);

        if let Err(e) = axum::serve(listener, app).await {
            tracing::error!(error = %e, "HTTP 服务退出");
        }
    });
}

async fn get_config(State(state): State<Arc<AppState>>, Path(key): Path<String>) -> Json<Value> {
    ok(state.config.get(&key))
}

async fn put_config(
    State(state): State<Arc<AppState>>,
    Path(key): Path<String>,
    Json(value): Json<Value>,
) -> Json<Value> {
    match state.config.set(&key, value) {
        Ok(_) => ok(json!({ "key": key })),
        Err(e) => Json(json!({ "ok": false, "error": { "code": "config_write_failed", "message": e.to_string() } })),
    }
}

/// 内部参数化查询：只允许 SELECT（契约 3.4 禁止任意 SQL 拼接）。
async fn internal_db_query(
    State(state): State<Arc<AppState>>,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let sql = body.get("sql").and_then(Value::as_str).unwrap_or_default();
    let params = body.get("params").and_then(Value::as_array).cloned().unwrap_or_default();
    if !sql.trim_start().to_ascii_uppercase().starts_with("SELECT") {
        return err("forbidden_sql", "仅允许 SELECT 查询", StatusCode::FORBIDDEN);
    }
    match state.db.query_json(sql, &params) {
        Ok(rows) => (StatusCode::OK, ok(Value::Array(rows))),
        Err(e) => err("query_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// 内部写入：仅限白名单表（WRITABLE_TABLES）。
async fn internal_db_exec(
    State(state): State<Arc<AppState>>,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let sql = body.get("sql").and_then(Value::as_str).unwrap_or_default();
    let params = body.get("params").and_then(Value::as_array).cloned().unwrap_or_default();
    let head = sql.trim_start().to_ascii_uppercase();
    let allowed_prefix =
        head.starts_with("INSERT") || head.starts_with("UPDATE") || head.starts_with("DELETE");
    // 修复（REVIEW-002 R-12）：原实现用 `sql.contains(table)` 子串匹配白名单，
    // `DELETE FROM config_backup` 之类可绕过。现改为解析出真正的目标表名再**全等**比对。
    let table_ok = matches!(target_table(sql).as_deref(), Some(t) if WRITABLE_TABLES.contains(&t));
    if !allowed_prefix || !table_ok {
        return err(
            "forbidden_table",
            &format!("写入仅限白名单表：{WRITABLE_TABLES:?}"),
            StatusCode::FORBIDDEN,
        );
    }
    match state.db.exec(sql, &params) {
        Ok(n) => (StatusCode::OK, ok(json!({ "affected": n }))),
        Err(e) => err("exec_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// 从写语句中解析目标表名（修复 REVIEW-002 R-12）。
///
/// 取 `FROM` / `INTO` / `UPDATE` 之后的首个标识符，与白名单做**全等**比对，
/// 避免原实现 `contains()` 子串匹配被 `config_backup` 这类名字绕过。
fn target_table(sql: &str) -> Option<String> {
    let tokens: Vec<String> = sql
        .split(|c: char| !c.is_ascii_alphanumeric() && c != '_')
        .filter(|s| !s.is_empty())
        .map(|s| s.to_ascii_lowercase())
        .collect();
    tokens.iter().enumerate().find_map(|(i, tok)| {
        if matches!(tok.as_str(), "from" | "into" | "update") {
            tokens.get(i + 1).cloned()
        } else {
            None
        }
    })
}

/// 内部事件发布：Python sidecar 向总线发布事件的入口。
async fn internal_event_publish(
    State(state): State<Arc<AppState>>,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let event = body.get("event").and_then(Value::as_str).unwrap_or_default();
    let payload = body.get("payload").cloned().unwrap_or(Value::Null);
    if event.is_empty() {
        return err("bad_event", "event 不能为空", StatusCode::BAD_REQUEST);
    }
    match state.bus.publish(event, payload) {
        Ok(_) => (StatusCode::OK, ok(json!({ "event": event }))),
        Err(e) => err("publish_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---------------------------------------------------------------- 软件管理（阶段2）
//
// 与 `commands.rs` 的 `apps_*` **逻辑同源**：两者都调 `app_manager` / `AppsRepo`，
// 不允许在任一侧另写一套。本组端点服务于非浏览器客户端（curl / 验收脚本）。

#[derive(serde::Deserialize)]
struct AppsQuery {
    category: Option<String>,
    search: Option<String>,
}

async fn api_apps_list(
    State(state): State<Arc<AppState>>,
    Query(q): Query<AppsQuery>,
) -> (StatusCode, Json<Value>) {
    match state.apps.list(q.category.as_deref(), q.search.as_deref()) {
        Ok(rows) => (StatusCode::OK, ok(to_json(rows))),
        Err(e) => err("apps_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_apps_categories(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match state.apps.categories() {
        Ok(c) => (StatusCode::OK, ok(to_json(c))),
        Err(e) => err("apps_categories_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_apps_running(State(state): State<Arc<AppState>>) -> Json<Value> {
    ok(to_json(state.running.snapshot()))
}

async fn api_apps_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::app_manager::AppInput>,
) -> (StatusCode, Json<Value>) {
    match state.apps.add(&input) {
        Ok(row) => {
            // 契约 3.3：APP_REGISTERED { appId, name, path }
            let _ = state.bus.publish(
                crate::event_bus::APP_REGISTERED,
                json!({ "appId": row.id, "name": row.name, "path": row.path }),
            );
            (StatusCode::OK, ok(to_json(row)))
        }
        Err(e) => err("apps_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_apps_update(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(patch): Json<crate::app_manager::AppPatch>,
) -> (StatusCode, Json<Value>) {
    match state.apps.update(id, &patch) {
        Ok(row) => (StatusCode::OK, ok(to_json(row))),
        Err(e) => err("apps_update_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_apps_delete(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match state.apps.soft_delete(id) {
        Ok(_) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("apps_delete_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_apps_launch(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::app_manager::launch_registered(&state, id) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("apps_launch_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---------------------------------------------------------------- 窗口管理（阶段3）

async fn api_monitors() -> (StatusCode, Json<Value>) {
    (StatusCode::OK, ok(to_json(crate::window_manager::list_monitors())))
}

/// 内置布局名单 + 各自摘要（供 UI 列表直接渲染）。
async fn api_layouts() -> (StatusCode, Json<Value>) {
    let items: Vec<Value> = crate::window_manager::list_builtin_layouts()
        .iter()
        .filter_map(|n| crate::window_manager::load_layout(n).ok())
        .map(to_json)
        .collect();
    (StatusCode::OK, ok(Value::Array(items)))
}

async fn api_layout_get(Path(name): Path<String>) -> (StatusCode, Json<Value>) {
    match crate::window_manager::load_layout(&name) {
        Ok(l) => (StatusCode::OK, ok(to_json(l))),
        Err(e) => err("layout_not_found", &e.to_string(), StatusCode::NOT_FOUND),
    }
}

/// 应用布局。**会阻塞**（分步延时 + 失败重试），故放进 `spawn_blocking`。
async fn api_layout_apply(
    State(state): State<Arc<AppState>>,
    Path(name): Path<String>,
) -> (StatusCode, Json<Value>) {
    let st = state.clone();
    let joined = tokio::task::spawn_blocking(move || {
        let layout = crate::window_manager::load_layout(&name)?;
        crate::window_manager::apply_layout(&st, &layout)
    })
    .await;

    match joined {
        Ok(Ok(outcome)) => (StatusCode::OK, ok(to_json(outcome))),
        Ok(Err(e)) => err("layout_apply_failed", &e.to_string(), StatusCode::BAD_REQUEST),
        Err(e) => err("join_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

#[derive(serde::Deserialize)]
struct WinQuery {
    pid: Option<u32>,
    title: Option<String>,
}

async fn api_windows(Query(q): Query<WinQuery>) -> (StatusCode, Json<Value>) {
    if let Some(p) = q.pid {
        // 验收项 1：无窗口时 data 为 null（而不是 4xx）
        return (StatusCode::OK, ok(to_json(crate::window_manager::find_main_window(p))));
    }
    if let Some(kw) = q.title.filter(|s| !s.trim().is_empty()) {
        return (StatusCode::OK, ok(to_json(crate::window_manager::find_by_title(&kw))));
    }
    (StatusCode::OK, ok(to_json(crate::window_manager::list_windows())))
}

async fn api_window_rect(Path(hwnd): Path<i64>) -> (StatusCode, Json<Value>) {
    match crate::window_manager::get_rect(hwnd as isize) {
        Some(r) => (StatusCode::OK, ok(to_json(r))),
        None => (StatusCode::OK, ok(Value::Null)),
    }
}

#[derive(serde::Deserialize)]
struct PlaceBody {
    x: i32,
    y: i32,
    w: i32,
    h: i32,
    #[serde(default, rename = "alwaysOnTop")]
    always_on_top: bool,
    #[serde(default)]
    maximized: bool,
}

async fn api_window_place(
    Path(hwnd): Path<i64>,
    Json(b): Json<PlaceBody>,
) -> (StatusCode, Json<Value>) {
    let rect = crate::window_manager::PxRect { x: b.x, y: b.y, w: b.w, h: b.h };
    match crate::window_manager::place(hwnd as isize, rect, b.always_on_top, b.maximized) {
        Ok(()) => (StatusCode::OK, ok(to_json(rect))),
        Err(e) => err("place_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_window_activate(Path(hwnd): Path<i64>) -> (StatusCode, Json<Value>) {
    match crate::window_manager::activate(hwnd as isize) {
        Ok(()) => (
            StatusCode::OK,
            ok(json!({
                "hwnd": hwnd,
                "foreground": crate::window_manager::is_foreground(hwnd as isize)
            })),
        ),
        Err(e) => err("activate_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---------------------------------------------------------------- 工作模式引擎（阶段4）

fn mode_repo(state: &AppState) -> crate::scheduler::ModeRepo {
    crate::scheduler::ModeRepo::new(state.db.clone())
}

async fn api_modes_list(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match mode_repo(&state).list() {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("modes_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_modes_get(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match mode_repo(&state).get(id) {
        Ok(Some(m)) => (StatusCode::OK, ok(to_json(m))),
        Ok(None) => err("mode_not_found", "模式不存在或已删除", StatusCode::NOT_FOUND),
        Err(e) => err("mode_get_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_modes_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::scheduler::WorkModeInput>,
) -> (StatusCode, Json<Value>) {
    match mode_repo(&state).add(&input) {
        Ok(m) => (StatusCode::OK, ok(to_json(m))),
        Err(e) => err("mode_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// HTTP 兜底：从当前工作环境创建模式（复用 command 实现；blocking call 转 spawn_blocking）。
async fn api_modes_capture(
    State(state): State<Arc<AppState>>,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let name = body
        .get("name")
        .and_then(Value::as_str)
        .unwrap_or("")
        .to_string();
    match tauri::async_runtime::spawn_blocking(move || {
        crate::api::commands::modes_capture_current_inner(&state, name)
    })
    .await
    {
        Ok(Ok(v)) => (StatusCode::OK, ok(to_json(v))),
        Ok(Err(e)) => err("mode_capture_failed", &e, StatusCode::BAD_REQUEST),
        Err(e) => err("mode_capture_join", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn api_modes_update(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(patch): Json<crate::scheduler::WorkModePatch>,
) -> (StatusCode, Json<Value>) {
    match mode_repo(&state).update(id, &patch) {
        Ok(m) => (StatusCode::OK, ok(to_json(m))),
        Err(e) => err("mode_update_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_modes_delete(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match mode_repo(&state).soft_delete(id) {
        Ok(()) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("mode_delete_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_modes_duplicate(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match mode_repo(&state).duplicate(id) {
        Ok(m) => (StatusCode::OK, ok(to_json(m))),
        Err(e) => err("mode_duplicate_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// 模式状态：`configured`（上次使用）vs `running`（本次进程内）。
async fn api_mode_current(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let running = state.modes_run.current();
    let launched = running
        .as_deref()
        .map(|m| state.modes_run.launched_by(m))
        .unwrap_or_default();
    (
        StatusCode::OK,
        ok(json!({
            "configured": state.config.get("mode.current"),
            "running": running,
            "launchedAppIds": launched,
            "previous": state.modes_run.previous(),
            "lastSnapshot": state.modes_run.last_snapshot(),
        })),
    )
}

/// 应用模式（阻塞 → spawn_blocking）。
async fn api_mode_apply(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    let st = state.clone();
    let joined = tokio::task::spawn_blocking(move || crate::scheduler::apply_mode(&st, id, None)).await;
    match joined {
        Ok(Ok(outcome)) => (StatusCode::OK, ok(to_json(outcome))),
        Ok(Err(e)) => err("mode_apply_failed", &e.to_string(), StatusCode::BAD_REQUEST),
        Err(e) => err("join_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn api_mode_cancel(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let guard = state.mode_session.lock().unwrap_or_else(|e| e.into_inner());
    match guard.as_ref() {
        Some(s) => {
            s.cancel_token().cancel();
            (StatusCode::OK, ok(json!({ "cancelled": true, "modeName": s.mode_name })))
        }
        None => (
            StatusCode::OK,
            ok(json!({ "cancelled": false, "reason": "当前没有进行中的应用流程" })),
        ),
    }
}

async fn api_mode_progress(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let guard = state.mode_session.lock().unwrap_or_else(|e| e.into_inner());
    match guard.as_ref() {
        Some(s) => {
            let st = s.state();
            (
                StatusCode::OK,
                ok(json!({
                    "active": !st.is_terminal(),
                    "modeId": s.mode_id,
                    "modeName": s.mode_name,
                    "state": st,
                    "slots": s.slots(),
                    "history": s.history(),
                })),
            )
        }
        None => (StatusCode::OK, ok(json!({ "active": false, "state": { "phase": "idle" }, "slots": [] }))),
    }
}

/// 一键恢复"上次使用的模式"（06 §4）。
async fn api_mode_restore(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let raw = state.config.get("mode.current");
    let name = raw.as_str().unwrap_or("").trim().to_string();
    if name.is_empty() {
        return err("no_last_mode", "没有可恢复的『上次使用模式』", StatusCode::BAD_REQUEST);
    }
    let m = match mode_repo(&state).get_by_name(&name) {
        Ok(Some(m)) => m,
        Ok(None) => {
            return err(
                "mode_gone",
                &format!("上次使用的模式「{name}」已不存在（可能已被删除）"),
                StatusCode::NOT_FOUND,
            )
        }
        Err(e) => return err("mode_restore_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    };
    let st = state.clone();
    let id = m.id;
    let joined =
        tokio::task::spawn_blocking(move || crate::scheduler::apply_mode(&st, id, None)).await;
    match joined {
        Ok(Ok(o)) => (StatusCode::OK, ok(to_json(o))),
        Ok(Err(e)) => err("mode_apply_failed", &e.to_string(), StatusCode::BAD_REQUEST),
        Err(e) => err("join_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

#[derive(serde::Deserialize)]
struct RememberBody {
    from: String,
    to: String,
    policy: String,
}

/// 记住 06 §3 `ask` 策略的选择。
async fn api_mode_remember(
    State(state): State<Arc<AppState>>,
    Json(b): Json<RememberBody>,
) -> (StatusCode, Json<Value>) {
    if !crate::scheduler::SWITCH_POLICIES.contains(&b.policy.as_str()) {
        return err(
            "bad_policy",
            &format!("非法的切换策略：{}", b.policy),
            StatusCode::BAD_REQUEST,
        );
    }
    let mut mem = state.config.get("mode.switch_memory");
    if !mem.is_object() {
        mem = json!({});
    }
    let key = format!("{}>{}", b.from, b.to);
    mem[&key] = json!(b.policy);
    match state.config.set("mode.switch_memory", mem) {
        Ok(_) => (StatusCode::OK, ok(json!({ "key": key, "policy": b.policy }))),
        Err(e) => err("remember_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// 退出当前模式（关闭该模式拉起的软件）。
async fn api_mode_exit(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::scheduler::exit_mode(&state) {
        Ok(closed) => (StatusCode::OK, ok(json!({ "closed": closed }))),
        Err(e) => err("mode_exit_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_db_layouts(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::scheduler::LayoutRepo::new(state.db.clone()).list() {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("layouts_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct LayoutUpsertBody {
    name: String,
    #[serde(default)]
    description: Option<String>,
    slots: Value,
    #[serde(default)]
    monitor: Option<i64>,
}

async fn api_db_layout_upsert(
    State(state): State<Arc<AppState>>,
    Json(b): Json<LayoutUpsertBody>,
) -> (StatusCode, Json<Value>) {
    match crate::scheduler::LayoutRepo::new(state.db.clone()).upsert(
        &b.name,
        b.description.as_deref(),
        &b.slots,
        b.monitor.unwrap_or(0),
        // 见 commands.rs 同名说明：UI 编辑器暂不产出侧栏配置
        None,
        false,
    ) {
        Ok(rec) => (StatusCode::OK, ok(to_json(rec))),
        Err(e) => err("layout_upsert_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// 序列化辅助：内部结构一定能转 JSON，失败给 Null 而不是 panic。
fn to_json<T: serde::Serialize>(v: T) -> Value {
    serde_json::to_value(v).unwrap_or(Value::Null)
}

#[derive(serde::Deserialize)]
struct IconQuery {
    path: String,
}

/// 读图标缓存 → data URL。仅允许读 `icons_dir` 内的文件。
async fn api_icon(
    State(state): State<Arc<AppState>>,
    Query(q): Query<IconQuery>,
) -> (StatusCode, Json<Value>) {
    match crate::app_manager::read_icon_data_url(&state.icons_dir(), &q.path) {
        Ok(url) => (StatusCode::OK, ok(Value::from(url))),
        Err(e) => err("icon_read_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

/// 扫描已安装软件（转发 sidecar；注册表读取属 Python 侧系统集成）。
async fn api_apps_scan(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::sidecar::call(&state, "/apps/scan", json!({})).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("scan_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct ProbeBody {
    path: String,
}

/// 探测名称 + 提取图标（转发 sidecar）。
async fn api_apps_probe(
    State(state): State<Arc<AppState>>,
    Json(body): Json<ProbeBody>,
) -> (StatusCode, Json<Value>) {
    let out_dir = state.icons_dir().to_string_lossy().to_string();
    match crate::sidecar::call(
        &state,
        "/apps/probe",
        json!({ "path": body.path, "out_dir": out_dir }),
    )
    .await
    {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("probe_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---------------------------------------------------------------- 学习成长（阶段6）
//
// 与 `commands.rs` 的 `learning_*` **逻辑同源**：都调 `LearningRepo` / `learning::apply_*`，
// 不允许任一侧另写一套（02 §2.2 双通道约定）。

fn learning_repo(state: &AppState) -> crate::learning::LearningRepo {
    crate::learning::LearningRepo::new(state.db.clone())
}

fn project_repo(state: &AppState) -> crate::project::ProjectRepo {
    crate::project::ProjectRepo::new(state.db.clone())
}

async fn api_learning_goals(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).goals_list() {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("learning_goals_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_goal_get(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).goal_get(id) {
        Ok(Some(g)) => (StatusCode::OK, ok(to_json(g))),
        Ok(None) => err("goal_not_found", "学习目标不存在或已删除", StatusCode::NOT_FOUND),
        Err(e) => err("goal_get_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_goal_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::learning::GoalInput>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).goal_add(&input) {
        Ok(g) => (StatusCode::OK, ok(to_json(g))),
        Err(e) => err("goal_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_goal_update(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(patch): Json<crate::learning::GoalPatch>,
) -> (StatusCode, Json<Value>) {
    match crate::learning::apply_goal_update(&state, id, &patch) {
        Ok(g) => (StatusCode::OK, ok(to_json(g))),
        Err(e) => err("goal_update_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_goal_delete(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).goal_delete(id) {
        Ok(()) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("goal_delete_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_nodes(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).nodes_list(id) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("nodes_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct RoadmapConfirmBody {
    nodes: Vec<crate::learning::NodeInput>,
    #[serde(default)]
    replace: bool,
    #[serde(default)]
    raw: Option<String>,
}

/// 确认采纳路线（HTTP 面）。`replace` 为 false 且已有节点时会被拒 —— 见 repo 注释。
async fn api_learning_roadmap_confirm(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(b): Json<RoadmapConfirmBody>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).roadmap_confirm(id, &b.nodes, b.replace, b.raw.as_deref()) {
        Ok(v) => {
            let _ = state.bus.publish(
                crate::event_bus::LEARNING_PROGRESS_UPDATED,
                json!({ "goalId": id, "nodeId": Value::Null, "status": "roadmap_confirmed" }),
            );
            (StatusCode::OK, ok(to_json(v)))
        }
        Err(e) => err("roadmap_confirm_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct NodeAddBody {
    #[serde(rename = "goalId")]
    goal_id: i64,
    input: crate::learning::NodeInput,
}

async fn api_learning_node_add(
    State(state): State<Arc<AppState>>,
    Json(b): Json<NodeAddBody>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).node_add(b.goal_id, &b.input) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("node_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_node_update(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(patch): Json<crate::learning::NodePatch>,
) -> (StatusCode, Json<Value>) {
    match crate::learning::apply_node_update(&state, id, &patch) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("node_update_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_learning_node_delete(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    let repo = learning_repo(&state);
    let goal_id = repo.node_get(id).ok().flatten().map(|n| n.goal_id);
    match repo.node_delete(id) {
        Ok(()) => {
            if let Some(gid) = goal_id {
                let _ = state.bus.publish(
                    crate::event_bus::LEARNING_PROGRESS_UPDATED,
                    json!({ "goalId": gid, "nodeId": id, "status": "deleted" }),
                );
            }
            (StatusCode::OK, ok(json!({ "id": id })))
        }
        Err(e) => err("node_delete_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct NodeMoveBody {
    delta: i64,
}

async fn api_learning_node_move(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(b): Json<NodeMoveBody>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).node_move(id, b.delta) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("node_move_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct LimitQuery {
    limit: Option<i64>,
}

async fn api_learning_updates(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Query(q): Query<LimitQuery>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).updates_list(id, q.limit.unwrap_or(50)) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("updates_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct UpdateAddBody {
    #[serde(rename = "goalId")]
    goal_id: i64,
    #[serde(default, rename = "nodeId")]
    node_id: Option<i64>,
    content: String,
}

async fn api_learning_update_add(
    State(state): State<Arc<AppState>>,
    Json(b): Json<UpdateAddBody>,
) -> (StatusCode, Json<Value>) {
    match learning_repo(&state).update_add(b.goal_id, b.node_id, &b.content) {
        Ok(id) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("update_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct SuggestBody {
    #[serde(default, rename = "goalId")]
    goal_id: Option<i64>,
    kind: String,
    provider: String,
    #[serde(default)]
    model: Option<String>,
    #[serde(default, rename = "apiBase")]
    api_base: Option<String>,
    #[serde(default)]
    extra: Option<String>,
}

/// AI 建议（HTTP 面）——**只读不写**（红线 V3）。阻塞，故走 `spawn_blocking`。
async fn api_learning_suggest(
    State(state): State<Arc<AppState>>,
    Json(b): Json<SuggestBody>,
) -> (StatusCode, Json<Value>) {
    let st = state.clone();
    let joined = tokio::task::spawn_blocking(move || {
        crate::learning::ai_suggest(
            &st,
            b.goal_id,
            &b.kind,
            &b.provider,
            b.model.as_deref().unwrap_or(""),
            b.api_base.as_deref().unwrap_or(""),
            b.extra.as_deref().unwrap_or(""),
        )
    })
    .await;
    match joined {
        Ok(Ok(v)) => (StatusCode::OK, ok(v)),
        Ok(Err(e)) => err("suggest_failed", &e.to_string(), StatusCode::BAD_REQUEST),
        Err(e) => err("join_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn api_learning_reminders_check(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::learning::scan_reminders(&state) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("reminders_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---------------------------------------------------------------- 项目管理（阶段6）

#[derive(serde::Deserialize)]
struct ProjectsQuery {
    status: Option<String>,
    #[serde(rename = "modeName")]
    mode_name: Option<String>,
}

async fn api_projects(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ProjectsQuery>,
) -> (StatusCode, Json<Value>) {
    match project_repo(&state).list(q.status.as_deref(), q.mode_name.as_deref()) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("projects_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_project_get(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match project_repo(&state).get(id) {
        Ok(Some(p)) => (StatusCode::OK, ok(to_json(p))),
        Ok(None) => err("project_not_found", "项目不存在或已删除", StatusCode::NOT_FOUND),
        Err(e) => err("project_get_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_project_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::project::ProjectInput>,
) -> (StatusCode, Json<Value>) {
    match crate::project::apply_add(&state, &input) {
        Ok(p) => (StatusCode::OK, ok(to_json(p))),
        Err(e) => err("project_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_project_update(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(patch): Json<crate::project::ProjectPatch>,
) -> (StatusCode, Json<Value>) {
    match crate::project::apply_update(&state, id, &patch) {
        Ok(p) => (StatusCode::OK, ok(to_json(p))),
        Err(e) => err("project_update_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_project_delete(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match project_repo(&state).soft_delete(id) {
        Ok(()) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("project_delete_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct ByModeQuery {
    #[serde(rename = "modeName")]
    mode_name: String,
}

async fn api_project_by_mode(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ByModeQuery>,
) -> (StatusCode, Json<Value>) {
    match project_repo(&state).by_mode(&q.mode_name) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("project_by_mode_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---------------------------------------------------------------- 个人档案（阶段7）
//
// 与 `commands.rs` 的 `profile_*` 逻辑同源：写路径都走 `profile::apply_*`
// （落库 + 发 PROFILE_UPDATED），读路径直连 `ProfileRepo`。

fn profile_repo(state: &AppState) -> crate::profile::ProfileRepo {
    crate::profile::ProfileRepo::new(state.db.clone())
}

#[derive(serde::Deserialize)]
struct ListQuery {
    #[serde(rename = "confirmedOnly")]
    confirmed_only: Option<bool>,
    status: Option<String>,
}

async fn api_profile_overview(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::profile::overview(&state) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("profile_overview_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_basic_get(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match profile_repo(&state).basic_get() {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_basic_get_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_basic_save(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::profile::BasicInput>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_basic_save(&state, &input) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_basic_save_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_skills(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ListQuery>,
) -> (StatusCode, Json<Value>) {
    match profile_repo(&state).skills_list(q.confirmed_only.unwrap_or(false)) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_skills_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_skill_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::profile::SkillInput>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_skill_add(&state, &input) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_skill_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_skill_update(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
    Json(patch): Json<crate::profile::SkillPatch>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_skill_update(&state, id, &patch) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_skill_update_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_skill_remove(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_skill_remove(&state, id) {
        Ok(()) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("profile_skill_remove_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_skill_confirm(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_skill_confirm(&state, id) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_skill_confirm_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_projects(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ListQuery>,
) -> (StatusCode, Json<Value>) {
    match profile_repo(&state).projects_list(q.confirmed_only.unwrap_or(false)) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_projects_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_project_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::profile::ProjectEntryInput>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_project_entry_add(&state, &input) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_project_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_project_remove(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_project_entry_remove(&state, id) {
        Ok(()) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("profile_project_remove_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_project_confirm(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_project_entry_confirm(&state, id) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_project_confirm_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_timeline(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ListQuery>,
) -> (StatusCode, Json<Value>) {
    match profile_repo(&state).timeline_list(q.confirmed_only.unwrap_or(false)) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_timeline_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_timeline_add(
    State(state): State<Arc<AppState>>,
    Json(input): Json<crate::profile::TimelineInput>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_timeline_add(&state, &input) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_timeline_add_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_timeline_remove(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_timeline_remove(&state, id) {
        Ok(()) => (StatusCode::OK, ok(json!({ "id": id }))),
        Err(e) => err("profile_timeline_remove_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_timeline_confirm(
    State(state): State<Arc<AppState>>,
    Path(id): Path<i64>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_timeline_confirm(&state, id) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_timeline_confirm_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_suggestions(
    State(state): State<Arc<AppState>>,
    Query(q): Query<ListQuery>,
) -> (StatusCode, Json<Value>) {
    let status = q.status.as_deref().filter(|s| !s.trim().is_empty());
    match profile_repo(&state).suggestions_list(status) {
        Ok(v) => (StatusCode::OK, ok(to_json(v))),
        Err(e) => err("profile_suggestions_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_suggestions_scan(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::profile::scan_app_usage(&state) {
        Ok(added) => (StatusCode::OK, ok(json!({ "added": added }))),
        Err(e) => err("profile_scan_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct IdsBody {
    #[serde(default)]
    ids: Vec<i64>,
}

async fn api_profile_suggestions_confirm(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IdsBody>,
) -> (StatusCode, Json<Value>) {
    if body.ids.is_empty() {
        return err("bad_request", "ids 不能为空", StatusCode::BAD_REQUEST);
    }
    let result = if body.ids.len() > 1 {
        crate::profile::apply_suggestion_batch_confirm(&state, &body.ids)
            .map(|n| json!({ "confirmed": n }))
    } else {
        crate::profile::apply_suggestion_confirm(&state, body.ids[0])
            .map(|s| json!({ "confirmed": 1, "suggestion": to_json(s) }))
    };
    match result {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("profile_confirm_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_suggestions_ignore(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IdsBody>,
) -> (StatusCode, Json<Value>) {
    if body.ids.is_empty() {
        return err("bad_request", "ids 不能为空", StatusCode::BAD_REQUEST);
    }
    let repo = profile_repo(&state);
    let mut n = 0;
    for id in &body.ids {
        if let Err(e) = repo.suggestion_ignore(*id) {
            return err("profile_ignore_failed", &e.to_string(), StatusCode::BAD_REQUEST);
        }
        n += 1;
    }
    (StatusCode::OK, ok(json!({ "ignored": n })))
}

#[derive(serde::Deserialize)]
struct RejectBody {
    kind: String,
}

async fn api_profile_suggestions_reject_kind(
    State(state): State<Arc<AppState>>,
    Json(body): Json<RejectBody>,
) -> (StatusCode, Json<Value>) {
    match crate::profile::apply_reject_kind(&state, &body.kind) {
        Ok(n) => (StatusCode::OK, ok(json!({ "kind": body.kind, "ignored": n }))),
        Err(e) => err("profile_reject_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_profile_export_markdown(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::profile::export_markdown(&state) {
        Ok(md) => (StatusCode::OK, ok(json!({ "markdown": md }))),
        Err(e) => err("profile_export_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---- 阶段8：生活中心（11 §A）----

async fn api_life_usage_today(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let repo = crate::life::repository::UsageRepo::new(state.db.clone());
    match repo.ranking(&today, 20).and_then(|r| Ok((repo.total_seconds(&today)?, r))) {
        Ok((total, ranking)) => (
            StatusCode::OK,
            ok(json!({ "day": today, "totalSeconds": total, "ranking": ranking })),
        ),
        Err(e) => err("life_usage_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn api_life_usage_week(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::life::repository::UsageRepo::new(state.db.clone()).daily_totals(7) {
        Ok(days) => (StatusCode::OK, ok(json!({ "days": days }))),
        Err(e) => err("life_usage_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

#[derive(serde::Deserialize)]
struct CityQuery {
    #[serde(default)]
    city: Option<String>,
}

async fn api_life_weather(
    State(state): State<Arc<AppState>>,
    axum::extract::Query(q): axum::extract::Query<CityQuery>,
) -> (StatusCode, Json<Value>) {
    match crate::life::weather(&state, q.city.as_deref()).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("life_weather_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    }
}

async fn api_life_media(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::life::media_now(&state).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("life_media_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    }
}

#[derive(serde::Deserialize)]
struct MediaControlBody {
    action: String,
}

async fn api_life_media_control(
    State(state): State<Arc<AppState>>,
    Json(body): Json<MediaControlBody>,
) -> (StatusCode, Json<Value>) {
    // 白名单先拦（非法 action 是客户端错误，直接 400，不落到 sidecar 再转 502）
    if !matches!(body.action.as_str(), "play" | "pause" | "next" | "previous") {
        return err(
            "invalid_action",
            "action 必须是 play/pause/next/previous",
            StatusCode::BAD_REQUEST,
        );
    }
    match crate::life::media_control(&state, &body.action).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("life_media_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    }
}

async fn api_life_social_overview(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::life::social_overview(&state).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("life_social_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    }
}

async fn api_life_social_config(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::life::social_config(&state) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("life_social_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn api_life_social_config_put(
    State(state): State<Arc<AppState>>,
    Json(body): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let services = body.get("services").cloned().unwrap_or(Value::Null);
    match crate::life::social_config_put(&state, &services) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("life_social_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---- 阶段8：设备中心（11 §B）----

async fn api_device_metrics(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, ok(crate::device::metrics_snapshot(&state)))
}

async fn api_device_processes(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, ok(json!({ "processes": crate::device::process_list(&state) })))
}

#[derive(serde::Deserialize)]
struct KillBody {
    pid: u32,
    #[serde(default)]
    confirm: bool,
}

async fn api_device_process_kill(
    State(state): State<Arc<AppState>>,
    Json(body): Json<KillBody>,
) -> (StatusCode, Json<Value>) {
    match crate::device::kill_process(&state, body.pid, body.confirm) {
        Ok(()) => (StatusCode::OK, ok(json!({ "killed": body.pid }))),
        Err(e) => err("device_kill_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_device_mode_health(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, ok(crate::device::mode_health(&state)))
}

// ---- 阶段9：插件系统（12 §A）----
//
// 与 `commands.rs` 的 `plugins_*` / `plugin_*` **逻辑同源**（都调 `plugins::*`），
// HTTP 面主要服务验收脚本与非浏览器客户端；UI 走 invoke 同名命令。

async fn api_plugins_list(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::plugins::list(&state) {
        Ok(rows) => (StatusCode::OK, ok(to_json(rows))),
        Err(e) => err("plugins_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_plugins_discover(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let root = crate::plugins::plugins_root(&state);
    (StatusCode::OK, ok(to_json(crate::plugins::discover(&root))))
}

#[derive(serde::Deserialize)]
struct InstallBody {
    #[serde(rename = "sourceDir")]
    source_dir: String,
}

async fn api_plugins_install(
    State(state): State<Arc<AppState>>,
    Json(b): Json<InstallBody>,
) -> (StatusCode, Json<Value>) {
    match crate::plugins::install(&state, std::path::Path::new(&b.source_dir)) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("plugins_install_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_plugins_import(
    State(state): State<Arc<AppState>>,
    Json(b): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let zip_path = b.get("zipPath").and_then(Value::as_str).unwrap_or_default();
    let data_dir = state.data_dir.to_string_lossy().to_string();
    let extracted = match crate::sidecar::call(
        &state,
        "/plugin/import",
        json!({ "zipPath": zip_path, "dataDir": data_dir }),
    )
    .await
    {
        Ok(v) => v,
        Err(e) => return err("plugins_import_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    };
    let dir = match extracted.get("dir").and_then(Value::as_str) {
        Some(d) => d.to_string(),
        None => return err("plugins_import_failed", "sidecar 返回缺少 dir", StatusCode::BAD_GATEWAY),
    };
    let temp_root = extracted.get("tempRoot").and_then(Value::as_str).unwrap_or_default().to_string();
    match crate::plugins::install(&state, std::path::Path::new(&dir)) {
        Ok(v) => {
            let _ = std::fs::remove_dir_all(&temp_root);
            (StatusCode::OK, ok(v))
        }
        Err(e) => err("plugins_install_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct EnabledBody {
    #[serde(rename = "pluginId")]
    plugin_id: String,
    enabled: bool,
}

async fn api_plugins_set_enabled(
    State(state): State<Arc<AppState>>,
    Json(b): Json<EnabledBody>,
) -> (StatusCode, Json<Value>) {
    match crate::plugins::set_enabled(&state, &b.plugin_id, b.enabled) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("plugins_set_enabled_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_plugins_uninstall(
    State(state): State<Arc<AppState>>,
    Json(b): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let plugin_id = b.get("pluginId").and_then(Value::as_str).unwrap_or_default();
    match crate::plugins::uninstall(&state, plugin_id) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("plugins_uninstall_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct PluginApiBody {
    #[serde(rename = "pluginId")]
    plugin_id: String,
    api: String,
    method: String,
    #[serde(default)]
    payload: Value,
}

async fn api_plugin_api(
    State(state): State<Arc<AppState>>,
    Json(b): Json<PluginApiBody>,
) -> (StatusCode, Json<Value>) {
    match crate::plugins::api_call(&state, &b.plugin_id, &b.api, &b.method, &b.payload).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => {
            let msg = e.to_string();
            if msg.starts_with("PERMISSION_DENIED:") {
                err("plugin_permission_denied", &msg, StatusCode::FORBIDDEN)
            } else {
                err("plugin_api_failed", &msg, StatusCode::BAD_REQUEST)
            }
        }
    }
}

#[derive(serde::Deserialize)]
struct PluginCrashBody {
    #[serde(rename = "pluginId")]
    plugin_id: String,
    reason: String,
}

async fn api_plugin_crash(
    State(state): State<Arc<AppState>>,
    Json(b): Json<PluginCrashBody>,
) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, ok(crate::plugins::report_crash(&state, &b.plugin_id, &b.reason)))
}

#[derive(serde::Deserialize)]
struct PluginAuditQuery {
    #[serde(rename = "pluginId")]
    plugin_id: String,
    limit: Option<i64>,
}

async fn api_plugin_audit(
    State(state): State<Arc<AppState>>,
    Query(q): Query<PluginAuditQuery>,
) -> (StatusCode, Json<Value>) {
    let repo = crate::plugins::PluginRepo::new(state.db.clone());
    match repo.audit_list(&q.plugin_id, q.limit.unwrap_or(50)) {
        Ok(rows) => (StatusCode::OK, ok(to_json(rows))),
        Err(e) => err("plugin_audit_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

// ---- 阶段9：外部 Agent（12 §C）----

async fn api_agents_list(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    match crate::agents::list(&state) {
        Ok(rows) => (StatusCode::OK, ok(to_json(rows))),
        Err(e) => err("agents_list_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

async fn api_agents_save(
    State(state): State<Arc<AppState>>,
    Json(specs): Json<Value>,
) -> (StatusCode, Json<Value>) {
    match crate::agents::save(&state, &specs) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("agents_save_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct AgentNameBody {
    name: String,
}

async fn api_agent_health(
    State(state): State<Arc<AppState>>,
    Json(b): Json<AgentNameBody>,
) -> (StatusCode, Json<Value>) {
    match crate::agents::health(&state, &b.name).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("agent_health_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    }
}

#[derive(serde::Deserialize)]
struct AgentInvokeBody {
    name: String,
    action: String,
    #[serde(default)]
    payload: Value,
}

async fn api_agent_invoke(
    State(state): State<Arc<AppState>>,
    Json(b): Json<AgentInvokeBody>,
) -> (StatusCode, Json<Value>) {
    match crate::agents::invoke(&state, &b.name, &b.action, &b.payload).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("agent_invoke_failed", &e.to_string(), StatusCode::BAD_GATEWAY),
    }
}

/// Agent → core 网关入口。身份取 header `X-Agent-Name`（契约 §C3）。
async fn api_agent_gateway(
    State(state): State<Arc<AppState>>,
    headers: axum::http::HeaderMap,
    Json(b): Json<Value>,
) -> (StatusCode, Json<Value>) {
    let name = headers
        .get("X-Agent-Name")
        .and_then(|v| v.to_str().ok())
        .unwrap_or_default()
        .to_string();
    if name.is_empty() {
        return err("agent_unauthenticated", "缺少 X-Agent-Name 头", StatusCode::UNAUTHORIZED);
    }
    let action = b.get("action").and_then(Value::as_str).unwrap_or_default().to_string();
    let payload = b.get("payload").cloned().unwrap_or(Value::Null);
    match crate::agents::gateway(&state, &name, &action, &payload).await {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => {
            let msg = e.to_string();
            if msg.starts_with("PERMISSION_DENIED:") {
                err("agent_permission_denied", &msg, StatusCode::FORBIDDEN)
            } else if msg.contains("未注册") {
                err("agent_unregistered", &msg, StatusCode::UNAUTHORIZED)
            } else {
                err("agent_gateway_failed", &msg, StatusCode::BAD_REQUEST)
            }
        }
    }
}

// ---- 阶段9：桌面小组件（12 §B）----

async fn api_desktop_widget_toggle(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    let open = state
        .app
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .as_ref()
        .and_then(|app| app.get_webview_window(crate::desktop_widget::WIDGET_LABEL))
        .is_some();
    let result = if open {
        crate::desktop_widget::close(&state)
    } else {
        crate::desktop_widget::open(&state)
    };
    match result {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("widget_toggle_failed", &e.to_string(), StatusCode::INTERNAL_SERVER_ERROR),
    }
}

async fn api_desktop_widget_status(State(state): State<Arc<AppState>>) -> (StatusCode, Json<Value>) {
    (StatusCode::OK, ok(crate::desktop_widget::status(&state)))
}

#[derive(serde::Deserialize)]
struct BoundsBody {
    x: f64,
    y: f64,
    w: f64,
    h: f64,
}

async fn api_desktop_widget_bounds(
    State(state): State<Arc<AppState>>,
    Json(b): Json<BoundsBody>,
) -> (StatusCode, Json<Value>) {
    match crate::desktop_widget::save_bounds(&state, b.x, b.y, b.w, b.h) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("widget_bounds_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}

#[derive(serde::Deserialize)]
struct AlwaysOnTopBody {
    on: bool,
}

async fn api_desktop_widget_always_on_top(
    State(state): State<Arc<AppState>>,
    Json(b): Json<AlwaysOnTopBody>,
) -> (StatusCode, Json<Value>) {
    match crate::desktop_widget::set_always_on_top(&state, b.on) {
        Ok(v) => (StatusCode::OK, ok(v)),
        Err(e) => err("widget_aot_failed", &e.to_string(), StatusCode::BAD_REQUEST),
    }
}
