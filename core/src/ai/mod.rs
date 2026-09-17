//! AI 客户端（阶段5）：把 sidecar 的流式响应转成事件总线广播。
//!
//! 职责边界（02 §2.4 / ADR-001）：
//! - **真正的模型 HTTP 调用在 Python sidecar**（`ai/providers/*`），core 不直连任何模型；
//! - core 负责：① 装配上下文（**只有 core 有数据**）② 把请求转给 sidecar
//!   ③ 把 sidecar 的 NDJSON 逐行转成 `AI_STREAM_CHUNK` 事件广播给前端。
//!
//! 为什么由 core 装配上下文：单一写入者 + 数据都在 core（模式/项目/学习/档案）。
//! sidecar 若要自己取这些数据，就得调 core 的 /internal/db/*，
//! 那等于多绕一圈且让"咨询模式不得读数据"的边界分散在两处。
//! 集中在这里，红线 V2 只有一个关口（`scheduler::build_ai_context`）。

use std::time::Instant;

use serde_json::{json, Value};

use crate::event_bus::{AI_REQUEST, AI_RESPONSE, AI_STREAM_CHUNK};
use crate::state::AppState;

mod http;

/// 一次 AI 请求的参数（来自前端 invoke）。
#[derive(Debug, serde::Deserialize)]
pub struct AiChatArgs {
    pub provider: String,
    #[serde(default)]
    pub model: String,
    /// 对话历史（不含 system —— system 由上下文装配产生）
    pub messages: Vec<AiMessage>,
    /// `consult` | `workspace`
    pub mode: String,
    #[serde(default)]
    pub enabled_scopes: std::collections::HashMap<String, bool>,
    #[serde(default)]
    pub prompt_key: String,
    #[serde(default = "default_temperature")]
    pub temperature: f64,
    #[serde(default = "default_max_tokens")]
    pub max_tokens: i64,
    #[serde(default)]
    pub api_base: String,
}

fn default_temperature() -> f64 {
    0.7
}
fn default_max_tokens() -> i64 {
    2048
}

#[derive(Debug, serde::Deserialize, serde::Serialize)]
pub struct AiMessage {
    pub role: String,
    pub content: String,
}

/// sidecar 的流式响应行（NDJSON）。
#[derive(Debug, serde::Deserialize)]
#[serde(tag = "type")]
enum StreamLine {
    #[serde(rename = "start")]
    Start {
        #[serde(default)]
        #[allow(dead_code)]
        provider: String,
    },
    #[serde(rename = "chunk")]
    Chunk { delta: String },
    #[serde(rename = "done")]
    Done {
        #[serde(default)]
        tokens: Option<i64>,
    },
    #[serde(rename = "error")]
    Error {
        #[serde(default)]
        code: String,
        #[serde(default)]
        message: String,
    },
}

/// 执行一次 AI 对话：转给 sidecar，逐块广播事件。
///
/// **同步实现**（阻塞读 sidecar 的流）。调用方须用 `spawn_blocking` 包起来，
/// 避免阻塞 Tauri 主线程 —— 见 `commands::ai_chat`。
pub fn chat_stream(state: &AppState, args: AiChatArgs) -> anyhow::Result<AiChatOutcome> {
    let started = Instant::now();

    // ---- ① 装配上下文（红线 V2 的唯一关口） ----
    // consult 模式在这里就拿到 None —— assemble 不会去读任何用户数据。
    let context = crate::scheduler::build_ai_context(state, &args.mode, &args.enabled_scopes);

    // ---- ② 事件：AI_REQUEST（契约 3.3）----
    let conversation_id = format!("c{}", crate::event_bus::now_ms());
    let _ = state.bus.publish(
        AI_REQUEST,
        json!({
            "conversationId": conversation_id,
            "provider": args.provider,
            "mode": args.mode,
        }),
    );

    // ---- ③ 转给 sidecar ----
    let port = state
        .sidecar
        .port
        .lock()
        .map_err(|_| anyhow::anyhow!("sidecar 端口锁中毒"))?
        .ok_or_else(|| anyhow::anyhow!("sidecar 尚未就绪，请稍后重试"))?;

    let payload = json!({
        "provider": args.provider,
        "model": args.model,
        "messages": args.messages,
        "mode": args.mode,
        "context": context,
        "enabledScopes": args.enabled_scopes,
        "promptKey": args.prompt_key,
        "temperature": args.temperature,
        "maxTokens": args.max_tokens,
        "apiBase": args.api_base,
    });

    let url = format!("http://127.0.0.1:{port}/ai/chat");
    let body = serde_json::to_vec(&payload)?;

    // 用裸 TCP + 手工 HTTP/1.1：需要**边收边处理**（流式），
    // axum 的 reqwest 依赖未引入，而 std 的 TcpStream 足够且零新增依赖。
    let mut resp = crate::ai::http::post_streaming(&url, &body)?;

    // ---- ④ 逐行转事件 ----
    let mut full_text = String::new();
    let mut tokens: Option<i64> = None;
    let mut failed: Option<(String, String)> = None;
    let mut chunk_count = 0usize;

    while let Some(line) = resp.next_line()? {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let parsed: StreamLine = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(e) => {
                tracing::warn!(error = %e, line, "无法解析 sidecar 流式行");
                continue;
            }
        };
        match parsed {
            StreamLine::Start { .. } => {}
            StreamLine::Chunk { delta } => {
                chunk_count += 1;
                full_text.push_str(&delta);
                // 契约 3.3：AI_STREAM_CHUNK { conversationId, delta }
                let _ = state.bus.publish(
                    AI_STREAM_CHUNK,
                    json!({ "conversationId": conversation_id, "delta": delta }),
                );
            }
            StreamLine::Done { tokens: t } => {
                tokens = t;
            }
            StreamLine::Error { code, message } => {
                failed = Some((code, message));
            }
        }
    }

    let duration_ms = started.elapsed().as_millis() as i64;

    // ---- ⑤ 事件：AI_RESPONSE（契约 3.3：**不含正文**）----
    let _ = state.bus.publish(
        AI_RESPONSE,
        json!({
            "conversationId": conversation_id,
            "tokens": tokens,
            "durationMs": duration_ms,
        }),
    );

    if let Some((code, message)) = failed {
        anyhow::bail!("{code}: {message}");
    }

    Ok(AiChatOutcome {
        conversation_id,
        text: full_text,
        chunk_count,
        tokens,
        duration_ms,
    })
}

#[derive(Debug, serde::Serialize)]
pub struct AiChatOutcome {
    pub conversation_id: String,
    /// 完整文本（流式期间前端已收到增量；这里返回给非流式调用方/验收脚本）
    pub text: String,
    pub chunk_count: usize,
    pub tokens: Option<i64>,
    pub duration_ms: i64,
}

/// 只做上下文装配与提示词渲染的"预演"（不真的发请求）。
///
/// 用途：① 验收脚本断言双模式隔离；② UI 显示"本次会发送什么上下文"让用户可核对（08 §5 权限透明）。
/// **不返回任何密钥**。
pub fn preview_context(
    state: &AppState,
    mode: &str,
    enabled: &std::collections::HashMap<String, bool>,
) -> Value {
    let ctx = crate::scheduler::build_ai_context(state, mode, enabled);
    let scopes = if ctx.is_some() {
        enabled
            .iter()
            .filter(|(_, v)| **v)
            .map(|(k, _)| k.clone())
            .collect::<Vec<_>>()
    } else {
        Vec::new()
    };
    json!({ "mode": mode, "context": ctx, "usedScopes": scopes })
}

// ---------------------------------------------------------------------------
// 与 sidecar 的一次性 JSON 交互（Provider 列表 / 凭据 / 模型列表）

/// 取 sidecar 端口（未就绪时报可读错）。
fn sidecar_port(state: &AppState) -> anyhow::Result<u16> {
    state
        .sidecar
        .port
        .lock()
        .map_err(|_| anyhow::anyhow!("sidecar 端口锁中毒"))?
        .ok_or_else(|| anyhow::anyhow!("sidecar 尚未就绪，请稍后重试"))
}

/// POST 一个 JSON 到 sidecar 并取回 `data` 字段。
fn sidecar_post(state: &AppState, path: &str, payload: &Value) -> anyhow::Result<Value> {
    let port = sidecar_port(state)?;
    let url = format!("http://127.0.0.1:{port}{path}");
    let body = serde_json::to_vec(payload)?;
    let mut resp = http::post_streaming(&url, &body)?;
    let text = resp.read_to_string()?;

    let envelope: Value = serde_json::from_str(&text)
        .map_err(|e| anyhow::anyhow!("sidecar 响应非 JSON：{e}（原文：{}）", &text[..text.len().min(200)]))?;

    if envelope.get("ok").and_then(|v| v.as_bool()) == Some(true) {
        Ok(envelope.get("data").cloned().unwrap_or(Value::Null))
    } else {
        let msg = envelope
            .get("error")
            .and_then(|e| e.get("message"))
            .and_then(|m| m.as_str())
            .unwrap_or("未知错误");
        anyhow::bail!("{msg}")
    }
}

/// Provider 列表 + 凭据掩码 + 模板列表（UI 用）。
pub fn provider_info(state: &AppState) -> anyhow::Result<Value> {
    sidecar_post(state, "/ai/providers", &json!({}))
}

/// 写入凭据（转发给 sidecar，由它写系统凭据库）。
pub fn set_credential(state: &AppState, provider: &str, secret: &str) -> anyhow::Result<Value> {
    sidecar_post(
        state,
        "/ai/credential",
        &json!({ "provider": provider, "secret": secret }),
    )
}

/// 删除凭据（传空 secret，sidecar 语义：空 = 删除）。
pub fn delete_credential(state: &AppState, provider: &str) -> anyhow::Result<Value> {
    sidecar_post(
        state,
        "/ai/credential",
        &json!({ "provider": provider, "secret": "" }),
    )
}

/// 拉取模型列表。
pub fn list_models(
    state: &AppState,
    provider: &str,
    api_base: Option<&str>,
) -> anyhow::Result<Value> {
    sidecar_post(
        state,
        "/ai/models",
        &json!({ "provider": provider, "apiBase": api_base.unwrap_or("") }),
    )
}

/// 权限范围（与上下文装配判据同源，保证 UI 提示不失真）。
pub fn permission_scope(
    _state: &AppState,
    mode: &str,
    enabled: std::collections::HashMap<String, bool>,
) -> Value {
    // 与 scheduler::is_data_allowed 同一判据 —— 不重复实现
    if !crate::scheduler::is_data_allowed(mode) {
        return json!({ "mode": mode, "scopes": [] });
    }
    let mut scopes: Vec<String> = enabled
        .iter()
        .filter(|(_, v)| **v)
        .map(|(k, _)| k.clone())
        .collect();
    if scopes.is_empty() {
        // 未显式传开关时，默认全部可用（与 ai/context.py 的默认一致）
        scopes = ["mode", "apps", "project", "learning", "profile"]
            .iter()
            .map(|s| s.to_string())
            .collect();
    }
    scopes.sort();
    json!({ "mode": mode, "scopes": scopes })
}
