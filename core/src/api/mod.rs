//! 本地 HTTP 服务：core 对 Python sidecar（/internal/*）与 UI（/api/v1/*）的唯一接口面。
//!
//! 契约：docs/agent-dev/03-数据契约与接口规范.md §3.4。
//! 统一返回 `{ ok, data?, error? { code, message } }`。
//!
//! 说明：02-架构与目录规范 §2.2 的强制目录树未列出 src/api/，
//! 本目录是架构师裁量新增（HTTP 接口面需要独立模块），已在 core/README.md 登记。

pub mod commands;

use std::sync::Arc;

use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::routing::{get, post, put};
use axum::{Json, Router};
use serde_json::{json, Value};

use crate::db::WRITABLE_TABLES;
use crate::state::AppState;

fn ok(data: Value) -> Json<Value> {
    Json(json!({ "ok": true, "data": data }))
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
            // ---- Python sidecar（契约 3.4）----
            .route("/internal/config/{key}", get(get_config))
            .route("/internal/db/query", post(internal_db_query))
            .route("/internal/db/exec", post(internal_db_exec))
            .route("/internal/event/publish", post(internal_event_publish))
            .route("/health", get(|| async { ok(json!({ "service": "pw-core" })) }))
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
