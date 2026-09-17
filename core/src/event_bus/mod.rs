//! 事件总线：跨模块解耦的唯一通知通道（契约 3.3）。
//!
//! 规则（02-架构与目录规范 §2.6）：
//! 1. 事件是"已发生的事实"，不是命令；
//! 2. payload 必须可序列化；
//! 3. 发起方不等待订阅方返回。

mod events;

pub use events::*;

use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use tauri::Emitter;
use tokio::sync::broadcast;

/// 统一事件信封（契约 3.3 外层结构）。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Envelope {
    pub event: String,
    /// 本地时区 ISO8601（契约 3.1 时间约定）。
    pub ts: String,
    pub payload: Value,
}

#[derive(Clone)]
pub struct EventBus {
    tx: std::sync::Arc<broadcast::Sender<Envelope>>,
}

impl EventBus {
    pub fn new(capacity: usize) -> Self {
        let (tx, _rx) = broadcast::channel(capacity);
        Self {
            tx: std::sync::Arc::new(tx),
        }
    }

    /// 发布事件。无订阅者不算错误（事实已发生即可）。
    pub fn publish(&self, event: &str, payload: Value) -> anyhow::Result<()> {
        let envelope = Envelope {
            event: event.to_string(),
            ts: iso_now(),
            payload,
        };
        // 发送失败仅意味着当前无订阅者，忽略。
        let _ = self.tx.send(envelope);
        Ok(())
    }

    pub fn subscribe(&self) -> broadcast::Receiver<Envelope> {
        self.tx.subscribe()
    }
}

/// 把事件总线桥接到前端 webview（**L-017 / L-032 修复**）。
///
/// 背景：`publish()` 只把事件送到进程内的 tokio broadcast，webview 是另一个 JS 上下文，
/// **收不到**。此前阶段1~4 的所有事件（CONFIG_CHANGED / APP_OPENED / MODE_CHANGED …）
/// 实际都是"发了没人收到"。
///
/// 契约 3.3 的 Envelope 结构原样透传，前端用 `listen('pw://event')` 收，
/// 再按 `envelope.event` 自行分发（见 `ui/src/api/eventBridge.ts`）。
///
/// 注意：此处**不做任何过滤或语义解释** —— 桥只负责搬运，"哪些事件谁关心"
/// 是订阅方的事（02 §2.6：事件是已发生的事实，不是命令）。
pub fn bridge_to_webview(app: tauri::AppHandle, bus: EventBus) {
    tauri::async_runtime::spawn(async move {
        let mut rx = bus.subscribe();
        loop {
            match rx.recv().await {
                Ok(envelope) => {
                    if let Err(e) = app.emit(EVENT_TO_WEBVIEW, &envelope) {
                        tracing::debug!(error = %e, "事件转发到 webview 失败（窗口可能未就绪）");
                    }
                }
                // 慢消费者导致的追赶丢弃不算错误：事件是事实通知，不是可靠消息队列。
                Err(broadcast::error::RecvError::Lagged(n)) => {
                    tracing::warn!(skipped = n, "事件桥落后，已跳过部分事件");
                }
                Err(broadcast::error::RecvError::Closed) => break,
            }
        }
    });
}

/// 前端监听用的事件名（Tauri event 总通道，单一入口避免事件名爆炸）。
pub const EVENT_TO_WEBVIEW: &str = "pw://event";

/// 本地时区 ISO8601 时间字符串，**含偏移**（契约 3.1 / 3.3，示例 `2026-09-12T17:30:00+08:00`）。
///
/// 修复（REVIEW-002 R-11）：原实现手写 Howard Hinnant 日期算法，但**未做任何时区换算**，
/// 实际产出 UTC 且不带偏移标识 —— 与注释、与契约 3.1「本地时区」均不符。
/// 现改用 `chrono::Local` 直接产出带偏移的本地时间。
/// 阶段9 起公开（plugins/agents 审计时间戳与事件同源，禁止各处再手写时间）。
pub fn iso_now() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%:z").to_string()
}

/// 当前毫秒时间戳（用于生成会话 id 等**非契约**用途）。
///
/// 注意：契约 3.1 要求事件时间戳用带偏移的本地 ISO8601（见 `iso_now`）；
/// 本函数只服务内部 id 生成，不写进事件字段。
pub fn now_ms() -> i64 {
    chrono::Local::now().timestamp_millis()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// 契约 3.1：时间必须带时区偏移标识（+08:00 / -05:00 之类），不能是裸时间或 Z 结尾。
    #[test]
    fn iso_now_carries_local_offset() {
        let ts = iso_now();
        let bytes = ts.as_bytes();
        // 形如 YYYY-MM-DDTHH:MM:SS±HH:MM，长度 25
        assert_eq!(ts.len(), 25, "unexpected ts format: {ts}");
        assert_eq!(bytes[10], b'T');
        assert!(
            bytes[19] == b'+' || bytes[19] == b'-',
            "ts 必须带时区偏移标识: {ts}"
        );
        assert_eq!(bytes[22], b':');
    }
}
