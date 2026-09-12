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

/// 本地时区 ISO8601 时间字符串，**含偏移**（契约 3.1 / 3.3，示例 `2026-09-12T17:30:00+08:00`）。
///
/// 修复（REVIEW-002 R-11）：原实现手写 Howard Hinnant 日期算法，但**未做任何时区换算**，
/// 实际产出 UTC 且不带偏移标识 —— 与注释、与契约 3.1「本地时区」均不符。
/// 现改用 `chrono::Local` 直接产出带偏移的本地时间。
fn iso_now() -> String {
    chrono::Local::now().format("%Y-%m-%dT%H:%M:%S%:z").to_string()
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
