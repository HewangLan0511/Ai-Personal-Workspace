//! 极简流式 HTTP 客户端（阶段5）
//!
//! **为什么不用 reqwest**：只需要"POST 一个 JSON、逐行读响应"这一个动作。
//! 引入 reqwest 会带进 tokio 的 TLS 栈与一堆依赖；而目标地址是**本机 sidecar**
//! （`127.0.0.1`），明文 HTTP/1.1 足够。
//!
//! 限制（明确写出来，避免误用）：
//! - 仅支持 `http://`（不支持 https —— 本机通信不需要）
//! - 仅支持 HTTP/1.1，不支持 chunked 之外的传输编码（sidecar 用 Content-Length 或直接关闭连接）
//! - 不跟随重定向（本机服务不该有重定向）
//!
//! 为什么要自己解析：`std::net::TcpStream` 只给字节流，
//! HTTP 的"响应头/响应体"分界、以及 chunked 编码的拆帧都得自己处理。

use std::io::{BufRead, BufReader, Read, Write};
use std::net::TcpStream;

/// 流式响应读取器：逐行产出响应体。
pub struct StreamingResponse {
    reader: BufReader<TcpStream>,
    /// 剩余待读字节数（`Content-Length` 模式）；`None` 表示读到连接关闭为止
    remaining: Option<usize>,
    /// 是否 chunked 传输编码
    chunked: bool,
    /// chunked 模式下的当前块剩余字节
    chunk_left: usize,
    done: bool,
}

impl StreamingResponse {
    /// 读下一行（不含换行符）。返回 `Ok(None)` 表示流结束。
    pub fn next_line(&mut self) -> anyhow::Result<Option<String>> {
        if self.done {
            return Ok(None);
        }

        // chunked 模式下，每块的**长度行**不属于内容，需先消费掉。
        if self.chunked && self.chunk_left == 0 {
            self.read_chunk_header()?;
            if self.done {
                return Ok(None);
            }
        }

        let mut line = String::new();
        let n = self.reader.read_line(&mut line)?;
        if n == 0 {
            self.done = true;
            return Ok(None);
        }

        if self.chunked {
            self.chunk_left = self.chunk_left.saturating_sub(n);
        } else if let Some(rem) = self.remaining.as_mut() {
            *rem = rem.saturating_sub(n);
            if *rem == 0 {
                self.done = true;
            }
        }
        Ok(Some(line))
    }

    /// 把整个响应体读成字符串（chunked 会被解码）。
    pub fn read_to_string(&mut self) -> anyhow::Result<String> {
        let mut out = String::new();
        while let Some(line) = self.next_line()? {
            out.push_str(&line);
        }
        Ok(out)
    }

    /// 读一个 chunked 的长度行；`0` 表示流结束。
    fn read_chunk_header(&mut self) -> anyhow::Result<()> {
        let mut size_line = String::new();
        loop {
            size_line.clear();
            if self.reader.read_line(&mut size_line)? == 0 {
                self.done = true;
                return Ok(());
            }
            // chunked 的块之间可能夹空行（上一个块的回车）
            if !size_line.trim().is_empty() {
                break;
            }
        }
        let size_str = size_line.trim().split(';').next().unwrap_or("0");
        let size = usize::from_str_radix(size_str.trim(), 16).unwrap_or(0);
        if size == 0 {
            self.done = true;
        } else {
            self.chunk_left = size;
        }
        Ok(())
    }
}

/// POST JSON 并获得流式响应。`url` 形如 `http://127.0.0.1:8080/ai/chat`。
pub fn post_streaming(url: &str, body: &[u8]) -> anyhow::Result<StreamingResponse> {
    let rest = url
        .strip_prefix("http://")
        .ok_or_else(|| anyhow::anyhow!("仅支持 http:// （本机 sidecar 通信），收到：{url}"))?;

    let (authority, path) = match rest.find('/') {
        Some(idx) => (&rest[..idx], &rest[idx..]),
        None => (rest, "/"),
    };

    let mut stream = TcpStream::connect(authority)
        .map_err(|e| anyhow::anyhow!("连接 sidecar 失败（{authority}）：{e}"))?;
    // 读超时给足：模型生成可能持续数十秒（08 §7 超时由 Provider 自己管）
    stream.set_read_timeout(Some(std::time::Duration::from_secs(300)))?;
    stream.set_write_timeout(Some(std::time::Duration::from_secs(30)))?;

    let head = format!(
        "POST {path} HTTP/1.1\r\n\
         Host: {authority}\r\n\
         Content-Type: application/json\r\n\
         Content-Length: {len}\r\n\
         Connection: close\r\n\
         \r\n",
        path = path,
        authority = authority,
        len = body.len()
    );
    stream.write_all(head.as_bytes())?;
    stream.write_all(body)?;
    stream.flush()?;

    let mut reader = BufReader::new(stream);

    // ---- 解析状态行 ----
    let mut status_line = String::new();
    reader.read_line(&mut status_line)?;
    let status = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse::<u16>().ok())
        .ok_or_else(|| anyhow::anyhow!("无法解析 HTTP 状态行：{status_line:?}"))?;

    // ---- 解析响应头 ----
    let mut content_length: Option<usize> = None;
    let mut chunked = false;
    loop {
        let mut line = String::new();
        if reader.read_line(&mut line)? == 0 {
            break;
        }
        let trimmed = line.trim_end();
        if trimmed.is_empty() {
            break;
        }
        let lower = trimmed.to_ascii_lowercase();
        if let Some(v) = lower.strip_prefix("content-length:") {
            content_length = v.trim().parse::<usize>().ok();
        } else if let Some(v) = lower.strip_prefix("transfer-encoding:") {
            if v.contains("chunked") {
                chunked = true;
            }
        }
    }

    if status >= 400 {
        // 错误响应通常是一次性 JSON，整体读出来即可
        let mut buf = String::new();
        let _ = reader.read_to_string(&mut buf);
        let msg = extract_error_message(&buf);
        anyhow::bail!("sidecar 返回 {status}：{msg}");
    }

    Ok(StreamingResponse {
        reader,
        remaining: content_length,
        chunked,
        chunk_left: 0,
        done: false,
    })
}

/// 从错误响应体里取 message（尽力而为，取不到就返回原文片段）。
fn extract_error_message(body: &str) -> String {
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(body) {
        if let Some(m) = v
            .get("error")
            .and_then(|e| e.get("message"))
            .and_then(|m| m.as_str())
        {
            return m.to_string();
        }
        if let Some(m) = v.get("message").and_then(|m| m.as_str()) {
            return m.to_string();
        }
    }
    body.chars().take(200).collect()
}
