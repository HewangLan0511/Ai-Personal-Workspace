//! 外部 Agent 接入（阶段9，12 §C / 契约 3.2.5）。
//!
//! 两个方向：
//! 1. core → Agent：健康检查（GET `{url}{healthCheck}`）与调用（POST `{url}/invoke`）；
//! 2. Agent → core：`/api/v1/agent/gateway`（header `X-Agent-Name`），action 白名单 +
//!    权限 + 审计；`mode.switch` **逐次确认**（payload.confirm === true，缺即 400）——
//!    "执行动作必须逐次确认"是红线（12 §C4 / 禁止事项⑤）。
//!
//! 安全默认（12 §C4）：外部 Agent 默认**无任何写权限**（permissions 白名单里就没有写类动作，
//! mode.switch 虽可被授予，但每次调用仍需显式 confirm）。注册清单存 config `agents.external`
//! （默认空 = 无任何外部 Agent）。所有调用（含被拒）写 `plugin_audit`（plugin_id = `agent:<name>`）。

use serde_json::{json, Value};
use std::sync::Arc;
use std::time::Duration;

use crate::state::AppState;

/// Agent 可被授予的能力（= 网关 action 白名单的权限名，12 §C3）。
pub const AGENT_PERMISSIONS: &[&str] = &[
    "mode:read",    // 读取工作模式
    "project:read", // 读取项目入口
    "profile:read", // 读取档案（需显式授权）
    "mode:switch",  // 触发模式切换（授予后仍需逐次 confirm）
    "ai:invoke",    // 调用 AI Provider（恒 consult，不注入用户数据）
];

/// 网关 action → 所需权限。
fn action_permission(action: &str) -> Option<&'static str> {
    match action {
        "mode.read" => Some("mode:read"),
        "project.read" => Some("project:read"),
        "profile.read" => Some("profile:read"),
        "mode.switch" => Some("mode:switch"),
        "ai.invoke" => Some("ai:invoke"),
        _ => None,
    }
}

/// 单个外部 Agent 的注册形态（契约 3.2.5）。
#[derive(Debug, Clone, serde::Serialize)]
pub struct AgentSpec {
    pub name: String,
    pub url: String,
    pub transport: String,
    #[serde(default)]
    pub permissions: Vec<String>,
    #[serde(rename = "healthCheck", default = "default_health")]
    pub health_check: String,
    #[serde(rename = "timeoutMs", default = "default_timeout")]
    pub timeout_ms: u64,
}

// 默认值（healthCheck=/health、timeoutMs=30000）在 from_json 内联给出；
// AgentSpec 只 Serialize（解析走手工 from_json），无需 serde default 函数。

impl AgentSpec {
    pub fn from_json(v: &Value) -> Result<Self, String> {
        let name = v
            .get("name")
            .and_then(Value::as_str)
            .ok_or("缺少 name")?
            .to_string();
        if name.is_empty() || name.len() > 32 || !name.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-') {
            return Err(format!("非法 Agent name（限 1~32 位字母/数字/_/-）：{name}"));
        }
        let url = v
            .get("url")
            .and_then(Value::as_str)
            .ok_or("缺少 url")?
            .to_string();
        if !url.starts_with("http://") {
            return Err(format!("url 必须以 http:// 开头（无 TLS 能力，https 不支持）：{url}"));
        }
        let transport = v
            .get("transport")
            .and_then(Value::as_str)
            .unwrap_or("http")
            .to_string();
        if transport != "http" {
            return Err(format!("transport 仅支持 http（WebSocket 预留，V3 未实现）：{transport}"));
        }
        let mut permissions = Vec::new();
        if let Some(arr) = v.get("permissions").and_then(Value::as_array) {
            for p in arr {
                let s = p
                    .as_str()
                    .ok_or("permissions 元素必须是字符串")?
                    .to_string();
                if !AGENT_PERMISSIONS.contains(&s.as_str()) {
                    return Err(format!("未知 Agent 权限：{s}（允许：{AGENT_PERMISSIONS:?}）"));
                }
                if permissions.contains(&s) {
                    return Err(format!("权限重复：{s}"));
                }
                permissions.push(s);
            }
        }
        Ok(Self {
            name,
            url: url.trim_end_matches('/').to_string(),
            transport,
            permissions,
            health_check: v
                .get("healthCheck")
                .and_then(Value::as_str)
                .unwrap_or("/health")
                .to_string(),
            timeout_ms: v.get("timeoutMs").and_then(Value::as_u64).unwrap_or(30_000).clamp(1_000, 60_000),
        })
    }

    fn has(&self, permission: &str) -> bool {
        self.permissions.iter().any(|p| p == permission)
    }
}

// ---------------------------------------------------------------------------
// 注册清单（config `agents.external`）

pub fn list(state: &AppState) -> anyhow::Result<Vec<Value>> {
    let raw = state.config.get("agents.external").as_str().unwrap_or("[]").to_string();
    let arr: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
    Ok(arr
        .into_iter()
        .filter_map(|v| AgentSpec::from_json(&v).ok().map(|s| serde_json::to_value(s).unwrap_or_default()))
        .collect())
}

/// 全量替换注册清单（PUT）。逐个校验 + name 唯一；通过后原样存 JSON 字符串。
pub fn save(state: &AppState, specs: &Value) -> anyhow::Result<Value> {
    let arr = specs
        .as_array()
        .ok_or_else(|| anyhow::anyhow!("body 必须是 Agent 数组"))?;
    let mut normalized: Vec<Value> = Vec::new();
    let mut names: Vec<String> = Vec::new();
    for s in arr {
        let spec = AgentSpec::from_json(s).map_err(|e| anyhow::anyhow!("Agent 校验失败：{e}"))?;
        if names.contains(&spec.name) {
            anyhow::bail!("Agent name 重复：{}", spec.name);
        }
        names.push(spec.name.clone());
        normalized.push(serde_json::to_value(&spec)?);
    }
    state
        .config
        .set("agents.external", Value::from(serde_json::to_string(&normalized)?))?;
    Ok(json!({ "saved": true, "count": normalized.len() }))
}

fn find(state: &AppState, name: &str) -> anyhow::Result<AgentSpec> {
    let raw = state.config.get("agents.external").as_str().unwrap_or("[]").to_string();
    let arr: Vec<Value> = serde_json::from_str(&raw).unwrap_or_default();
    arr.into_iter()
        .find_map(|v| AgentSpec::from_json(&v).ok().filter(|s| s.name == name))
        .ok_or_else(|| anyhow::anyhow!("外部 Agent 未注册：{name}"))
}

// ---------------------------------------------------------------------------
// 原始 HTTP 客户端（core → Agent；仅 http://，同 sidecar::call / plugins::net_http 手法）

async fn http_request(
    method: &str,
    url: &str,
    body: Option<&Value>,
    timeout: Duration,
) -> anyhow::Result<Value> {
    let rest = url
        .strip_prefix("http://")
        .ok_or_else(|| anyhow::anyhow!("仅支持 http://：{url}"))?;
    let (authority, path) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "/"),
    };
    let payload = body.map(|b| b.to_string()).unwrap_or_default();
    use tokio::io::{AsyncReadExt, AsyncWriteExt};
    let mut stream = tokio::time::timeout(timeout, tokio::net::TcpStream::connect(authority))
        .await
        .map_err(|_| anyhow::anyhow!("连接超时：{url}"))?
        .map_err(|e| anyhow::anyhow!("连接失败（{url}）：{e}"))?;
    let req = format!(
        "{method} {path} HTTP/1.1\r\nHost: {authority}\r\nContent-Type: application/json\r\n\
         Content-Length: {}\r\nConnection: close\r\n\r\n{payload}",
        payload.len()
    );
    stream.write_all(req.as_bytes()).await?;
    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).await?;
    let text = String::from_utf8_lossy(&buf);
    let status = text
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse::<u16>().ok())
        .unwrap_or(0);
    let body_text = text.split("\r\n\r\n").nth(1).unwrap_or("").trim().to_string();
    let parsed: Value = serde_json::from_str(&body_text).unwrap_or(json!(body_text));
    Ok(json!({ "status": status, "body": parsed }))
}

/// 审计（共用 plugin_audit 表；plugin_id = `agent:<name>`）。
fn audit(state: &AppState, name: &str, action: &str, outcome: &str, detail: &Value) {
    let repo = crate::plugins::PluginRepo::new(state.db.clone());
    let _ = repo.audit(&format!("agent:{name}"), action, outcome, detail);
}

// ---------------------------------------------------------------------------
// core → Agent

pub async fn health(state: &Arc<AppState>, name: &str) -> anyhow::Result<Value> {
    let spec = find(state, name)?;
    let url = format!("{}{}", spec.url, spec.health_check);
    let result = http_request("GET", &url, None, Duration::from_millis(spec.timeout_ms)).await;
    match result {
        Ok(v) => {
            let healthy = v.get("status").and_then(Value::as_u64) == Some(200);
            audit(state, name, "agent.health", if healthy { "ok" } else { "error" }, &json!({ "url": url, "status": v.get("status") }));
            if healthy {
                Ok(json!({ "healthy": true, "url": url }))
            } else {
                anyhow::bail!("健康检查未通过：{url} → {}", v.get("status").and_then(Value::as_u64).unwrap_or(0))
            }
        }
        Err(e) => {
            audit(state, name, "agent.health", "error", &json!({ "url": url, "reason": e.to_string() }));
            Err(e)
        }
    }
}

/// 调用外部 Agent（POST `{url}/invoke`，契约 §C2）。
pub async fn invoke(state: &Arc<AppState>, name: &str, action: &str, payload: &Value) -> anyhow::Result<Value> {
    let spec = find(state, name)?;
    let body = json!({
        "action": action,
        "payload": payload,
        "context": { "agent": name, "ts": crate::event_bus::iso_now() },
    });
    let result = http_request(
        "POST",
        &format!("{}/invoke", spec.url),
        Some(&body),
        Duration::from_millis(spec.timeout_ms),
    )
    .await;
    match &result {
        Ok(v) => audit(state, name, &format!("invoke.{action}"), "ok", &json!({ "status": v.get("status") })),
        Err(e) => audit(state, name, &format!("invoke.{action}"), "error", &json!({ "reason": e.to_string() })),
    }
    result
}

// ---------------------------------------------------------------------------
// Agent → core 网关

/// 网关入口（header X-Agent-Name 由调用方取出传入）。
pub async fn gateway(state: &Arc<AppState>, agent_name: &str, action: &str, payload: &Value) -> anyhow::Result<Value> {
    let spec = find(state, agent_name)?;
    let permission = action_permission(action)
        .ok_or_else(|| anyhow::anyhow!("未知 gateway action：{action}（白名单见契约 §C3）"))?;
    if !spec.has(permission) {
        audit(state, agent_name, &format!("gateway.{action}"), "denied", &json!({ "permission": permission }));
        anyhow::bail!("PERMISSION_DENIED: {permission}");
    }

    let result = gateway_dispatch(state, agent_name, action, payload).await;
    match &result {
        Ok(_) => audit(state, agent_name, &format!("gateway.{action}"), "ok", &audit_detail(payload)),
        Err(e) => {
            let msg = e.to_string();
            if msg.starts_with("PERMISSION_DENIED:") {
                audit(state, agent_name, &format!("gateway.{action}"), "denied", &json!({ "permission": msg.trim_start_matches("PERMISSION_DENIED:").trim() }));
            } else {
                audit(state, agent_name, &format!("gateway.{action}"), "error", &json!({ "reason": msg }));
            }
        }
    }
    result
}

fn audit_detail(payload: &Value) -> Value {
    let s = payload.to_string();
    if s.len() <= 120 {
        payload.clone()
    } else {
        json!("<omitted>")
    }
}

async fn gateway_dispatch(
    state: &Arc<AppState>,
    agent_name: &str,
    action: &str,
    payload: &Value,
) -> anyhow::Result<Value> {
    match action {
        "mode.read" => {
            let current = state.config.get("mode.current").as_str().unwrap_or("").to_string();
            let modes = crate::scheduler::ModeRepo::new(state.db.clone())
                .list()?
                .into_iter()
                .map(|m| json!({ "id": m.id, "name": m.name, "description": m.description }))
                .collect::<Vec<_>>();
            Ok(json!({ "current": current, "modes": modes }))
        }
        "project.read" => {
            let projects = crate::project::ProjectRepo::new(state.db.clone())
                .list(Some("ongoing"), None)?
                .into_iter()
                .map(|p| json!({ "id": p.id, "name": p.name, "modeName": p.mode_name, "directory": p.directory }))
                .collect::<Vec<_>>();
            Ok(json!({ "projects": projects }))
        }
        "profile.read" => {
            // 档案读取需显式授权（C3）；只回基础信息与已确认技能，不含建议队列
            let db = state.db.clone();
            let basic = db.query_json("SELECT name, direction, interests, motto FROM profile_basic LIMIT 1", &[])?;
            let skills = db.query_json(
                "SELECT name, level, category FROM profile_skills WHERE confirmed = 1 ORDER BY level DESC LIMIT 50",
                &[],
            )?;
            Ok(json!({ "basic": basic.first().cloned().unwrap_or(Value::Null), "skills": skills }))
        }
        "mode.switch" => {
            // ★ 红线：即使已授予 mode:switch，**每次**仍需 payload.confirm === true
            if payload.get("confirm").and_then(Value::as_bool) != Some(true) {
                anyhow::bail!("mode.switch 需要逐次确认（payload.confirm === true），本次已拒绝");
            }
            let target = payload
                .get("modeName")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow::anyhow!("payload 需要 modeName"))?;
            let mode = crate::scheduler::ModeRepo::new(state.db.clone())
                .list()?
                .into_iter()
                .find(|m| m.name == target)
                .ok_or_else(|| anyhow::anyhow!("模式不存在：{target}"))?;
            let mode_id = mode.id;
            let st = state.clone();
            // apply_mode 是同步阻塞（含窗口等待），放进阻塞线程避免占住异步 worker
            let outcome = tokio::task::spawn_blocking(move || crate::scheduler::apply_mode(&st, mode_id, None))
                .await
                .map_err(|e| anyhow::anyhow!("{e}"))??;
            tracing::info!(agent = %agent_name, mode = %target, "外部 Agent 触发模式切换（已逐次确认）");
            serde_json::to_value(&outcome).map_err(|e| anyhow::anyhow!("{e}"))
        }
        "ai.invoke" => {
            // 恒 consult 模式（不注入用户数据）；走 core → sidecar 的既有通道（AI 不开 HTTP 面）
            let prompt = payload
                .get("prompt")
                .and_then(Value::as_str)
                .ok_or_else(|| anyhow::anyhow!("payload 需要 prompt"))?;
            let provider = state.config.get("ai.default_provider").as_str().unwrap_or("").to_string();
            let body = json!({
                "provider": provider,
                "messages": [{ "role": "user", "content": prompt }],
                "mode": "consult",
            });
            ai_chat_collect(state, &body).await
        }
        _ => unreachable!(),
    }
}

/// 调 sidecar `/ai/chat`（NDJSON 流）并聚合为一次完整回答（供网关的 ai.invoke）。
/// 与 `sidecar::call` 同样的原始 TCP 手法，但按行解析流式协议：
/// `{"type":"chunk","delta":...}` 累加，`{"type":"done",...}` 结束，`{"type":"error",...}` 报错。
async fn ai_chat_collect(state: &Arc<AppState>, body: &Value) -> anyhow::Result<Value> {
    let port = state
        .sidecar
        .port
        .lock()
        .ok()
        .and_then(|g| *g)
        .ok_or_else(|| anyhow::anyhow!("sidecar 尚未就绪"))?;
    let payload = serde_json::to_string(body)?;
    use tokio::io::{AsyncBufReadExt, AsyncWriteExt};
    let mut stream = tokio::net::TcpStream::connect(format!("127.0.0.1:{port}")).await?;
    let req = format!(
        "POST /ai/chat HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nContent-Type: application/json\r\n\
         Content-Length: {}\r\nConnection: close\r\n\r\n{payload}",
        payload.len()
    );
    stream.write_all(req.as_bytes()).await?;
    let mut lines = tokio::io::BufReader::new(stream).lines();
    // 跳过响应头（空行分隔）
    loop {
        let line = lines.next_line().await?;
        match line {
            None => anyhow::bail!("sidecar 连接提前断开"),
            Some(l) if l.is_empty() => break,
            _ => {}
        }
    }
    let mut text = String::new();
    let mut chunks = 0usize;
    loop {
        match lines.next_line().await? {
            None => break,
            Some(line) if line.trim().is_empty() => continue,
            Some(line) => {
                let v: Value = match serde_json::from_str(&line) {
                    Ok(v) => v,
                    Err(_) => continue,
                };
                match v.get("type").and_then(Value::as_str) {
                    Some("chunk") => {
                        text.push_str(v.get("delta").and_then(Value::as_str).unwrap_or(""));
                        chunks += 1;
                    }
                    Some("done") => break,
                    Some("error") => anyhow::bail!(
                        "AI 调用失败：{}",
                        v.pointer("/error/message").and_then(Value::as_str).unwrap_or("unknown")
                    ),
                    _ => {}
                }
            }
        }
    }
    Ok(json!({ "text": text, "chunks": chunks, "mode": "consult" }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn agent_spec_validation() {
        let good = json!({
            "name": "MyAgent", "url": "http://localhost:8000",
            "permissions": ["mode:read", "project:read"], "timeoutMs": 5000
        });
        let s = AgentSpec::from_json(&good).unwrap();
        assert_eq!(s.health_check, "/health");
        assert_eq!(s.timeout_ms, 5000);

        // https 拒绝（无 TLS 能力，如实拒绝而不是静默降级）
        let https = json!({ "name": "A", "url": "https://localhost:8000" });
        assert!(AgentSpec::from_json(&https).is_err());

        // 未知权限拒绝
        let badp = json!({ "name": "A", "url": "http://localhost:1", "permissions": ["db:write"] });
        assert!(AgentSpec::from_json(&badp).is_err());

        // 非法 name
        let badn = json!({ "name": "坏 名字", "url": "http://localhost:1" });
        assert!(AgentSpec::from_json(&badn).is_err());
    }

    #[test]
    fn gateway_actions_map_to_permissions() {
        assert_eq!(action_permission("mode.switch"), Some("mode:switch"));
        assert_eq!(action_permission("db.drop"), None);
    }
}
