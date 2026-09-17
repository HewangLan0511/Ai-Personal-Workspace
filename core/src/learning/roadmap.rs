//! AI 路线输出的**解析与降级**（09 §2）。
//!
//! 指令要求"必须让模型输出严格 JSON"，但**模型不守规矩是常态**：
//! 它可能包一层 ```json 围栏、前面加一句"好的，这是你的路线"、
//! 把 `title` 写成 `name`、或者干脆回一段自然语言。
//!
//! 本模块的策略是**尽量救、救不了就降级，绝不给用户看解析错误**（09 §2）：
//! 1. 剥代码围栏 / 括号配对抽出 JSON 片段；
//! 2. 容忍常见字段名变体（`title|name`、`estimated|estimate`）；
//! 3. 全部失败 → `degraded = true`，把**原始文本**交回给 UI 做文本展示 + 手动录入。
//!
//! 为什么要容忍变体而不是"提示词写死了就不管"：提示词是**软约束**。
//! 把容错做在这一层，比要求每个模型都听话可靠得多。

use serde_json::Value;

use super::repository::NodeInput;

/// 一次解析的结果。
#[derive(Debug, Clone, PartialEq)]
pub struct ParsedRoadmap {
    /// 解析出的节点（`degraded = true` 时为空）
    pub nodes: Vec<NodeInput>,
    /// 是否降级（true 表示"没解析出结构，请走文本展示 + 手动录入"）
    pub degraded: bool,
    /// 降级原因（给人看的，不上 UI 的报错弹窗）
    pub reason: Option<String>,
}

impl ParsedRoadmap {
    fn ok(nodes: Vec<NodeInput>) -> Self {
        Self { nodes, degraded: false, reason: None }
    }

    fn degraded(reason: impl Into<String>) -> Self {
        Self { nodes: Vec::new(), degraded: true, reason: Some(reason.into()) }
    }
}

/// 解析 AI 输出。**不写库、不改任何状态**（红线 V3）。
pub fn parse(raw: &str) -> ParsedRoadmap {
    let text = raw.trim();
    if text.is_empty() {
        return ParsedRoadmap::degraded("模型返回为空");
    }

    let Some(candidate) = extract_json(text) else {
        return ParsedRoadmap::degraded("未找到 JSON 片段");
    };
    let value: Value = match serde_json::from_str(&candidate) {
        Ok(v) => v,
        Err(e) => return ParsedRoadmap::degraded(format!("JSON 语法错误：{e}")),
    };

    // 形态一：`{ "nodes": [...] }`（指令 §2 规定的形态）
    // 形态二：`[...]`（模型"顺手"只给数组，同样可用）
    let arr = match &value {
        Value::Object(obj) => match obj.get("nodes") {
            Some(Value::Array(a)) => a.clone(),
            Some(_) => return ParsedRoadmap::degraded("nodes 不是数组"),
            None => return ParsedRoadmap::degraded("缺少 nodes 字段"),
        },
        Value::Array(a) => a.clone(),
        _ => return ParsedRoadmap::degraded("顶层既不是对象也不是数组"),
    };

    let mut with_order: Vec<(Option<i64>, NodeInput)> = Vec::new();
    for item in &arr {
        // 允许节点是纯字符串（模型简化输出）—— 那它就是标题
        if let Some(s) = item.as_str() {
            let t = s.trim();
            if !t.is_empty() {
                with_order.push((None, NodeInput { title: t.to_string(), ..Default::default() }));
            }
            continue;
        }
        let Some(title) = pick_str(item, &["title", "name", "stage", "阶段", "阶段名"]) else {
            continue; // 没标题的节点无从展示，跳过而不是整条失败
        };
        let title = title.trim().to_string();
        if title.is_empty() {
            continue;
        }
        let resources = pick_resources(item);
        with_order.push((
            item.get("order")
                .or_else(|| item.get("sort"))
                .or_else(|| item.get("index"))
                .and_then(Value::as_i64),
            NodeInput {
                title,
                status: None,
                note: None,
                estimated: pick_str(item, &["estimated", "estimate", "duration", "预估", "预计"]),
                resources,
            },
        ));
    }

    if with_order.is_empty() {
        return ParsedRoadmap::degraded("没有任何可用的节点（都缺 title）");
    }

    // 只在**所有**节点都带 order 时才按它排序 —— 部分缺失时按原序更稳
    if with_order.iter().all(|(o, _)| o.is_some()) {
        with_order.sort_by_key(|(o, _)| o.unwrap_or(0));
    }

    ParsedRoadmap::ok(with_order.into_iter().map(|(_, n)| n).collect())
}

fn pick_str(v: &Value, keys: &[&str]) -> Option<String> {
    for k in keys {
        if let Some(s) = v.get(*k).and_then(Value::as_str) {
            if !s.trim().is_empty() {
                return Some(s.to_string());
            }
        }
    }
    None
}

fn pick_resources(v: &Value) -> Vec<String> {
    for k in ["resources", "resource", "资料", "refs"] {
        match v.get(k) {
            Some(Value::Array(a)) => {
                let list: Vec<String> = a
                    .iter()
                    .filter_map(|x| x.as_str().map(str::to_string))
                    .filter(|s| !s.trim().is_empty())
                    .collect();
                if !list.is_empty() {
                    return list;
                }
            }
            // 模型有时给单个字符串
            Some(Value::String(s)) if !s.trim().is_empty() => return vec![s.clone()],
            _ => {}
        }
    }
    Vec::new()
}

/// 从模型输出里抽出 JSON 片段：先剥 ``` 围栏，再做**括号配对扫描**。
///
/// 括号扫描必须跳过字符串内部的括号，否则 `{"title":"CNN (卷积)"}`
/// 这类内容会让配对提前结束（那是"解析失败"最常见的假原因）。
fn extract_json(text: &str) -> Option<String> {
    if let Some(start) = text.find("```") {
        let rest = &text[start + 3..];
        let rest = match rest.find('\n') {
            Some(i) => &rest[i + 1..], // 跳过 ```json 这类语言标识行
            None => rest,
        };
        if let Some(end) = rest.find("```") {
            let inner = rest[..end].trim();
            if !inner.is_empty() {
                return Some(inner.to_string());
            }
        }
    }

    let bytes = text.as_bytes();
    let start = text.char_indices().find(|(_, c)| *c == '{' || *c == '[').map(|(i, _)| i)?;
    let open = bytes[start];
    let close = if open == b'{' { b'}' } else { b']' };
    let mut depth: i32 = 0;
    let mut in_str = false;
    let mut escaped = false;
    for (i, b) in bytes.iter().enumerate().skip(start) {
        if in_str {
            if escaped {
                escaped = false;
            } else if *b == b'\\' {
                escaped = true;
            } else if *b == b'"' {
                in_str = false;
            }
            continue;
        }
        match *b {
            b'"' => in_str = true,
            x if x == open => depth += 1,
            x if x == close => {
                depth -= 1;
                if depth == 0 {
                    return Some(text[start..=i].to_string());
                }
            }
            _ => {}
        }
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_canonical_shape() {
        let raw = r#"{
          "goal": "学习计算机视觉并完成项目",
          "nodes": [
            { "title": "Python 基础", "order": 1, "estimated": "2周", "resources": ["官方教程"] },
            { "title": "OpenCV", "order": 2, "estimated": "3周" },
            { "title": "CNN", "order": 3, "estimated": "3周" }
          ]
        }"#;
        let p = parse(raw);
        assert!(!p.degraded, "标准形态必须解析成功");
        assert_eq!(p.nodes.len(), 3);
        assert_eq!(p.nodes[0].title, "Python 基础");
        assert_eq!(p.nodes[0].estimated.as_deref(), Some("2周"));
        assert_eq!(p.nodes[0].resources, vec!["官方教程"]);
        assert!(p.nodes[1].resources.is_empty());
    }

    #[test]
    fn survives_markdown_fence_and_chatter() {
        let raw = "好的，我为你规划了如下路线：\n```json\n{\"nodes\":[{\"title\":\"A\"},{\"title\":\"B\"}]}\n```\n希望对你有帮助！";
        let p = parse(raw);
        assert!(!p.degraded);
        assert_eq!(p.nodes.iter().map(|n| n.title.as_str()).collect::<Vec<_>>(), vec!["A", "B"]);
    }

    #[test]
    fn tolerates_field_variants_and_bare_array() {
        let raw = r#"[{"name":"阶段一","estimate":"1周"},{"name":"阶段二"}]"#;
        let p = parse(raw);
        assert!(!p.degraded);
        assert_eq!(p.nodes.len(), 2);
        assert_eq!(p.nodes[0].title, "阶段一");
        assert_eq!(p.nodes[0].estimated.as_deref(), Some("1周"));
    }

    #[test]
    fn respects_order_only_when_complete() {
        // 全部带 order → 按 order 重排
        let p = parse(r#"{"nodes":[{"title":"B","order":2},{"title":"A","order":1}]}"#);
        assert_eq!(p.nodes[0].title, "A");
        // 部分缺 order → 保持原序，不猜
        let p2 = parse(r#"{"nodes":[{"title":"B","order":2},{"title":"A"}]}"#);
        assert_eq!(p2.nodes[0].title, "B");
    }

    #[test]
    fn parentheses_inside_strings_do_not_break_scan() {
        let p = parse(r#"前缀 {"nodes":[{"title":"CNN (卷积) [上]","estimated":"2周"}]} 后缀"#);
        assert!(!p.degraded, "字符串里的括号不应导致配对提前结束");
        assert_eq!(p.nodes[0].title, "CNN (卷积) [上]");
    }

    #[test]
    fn degrades_gracefully_on_garbage() {
        for raw in [
            "抱歉，我无法完成这个请求。",
            "",
            "{\"nodes\": \"不是数组\"}",
            "{\"foo\": 1}",
            "[{\"something\": 1}]",
            "{\"nodes\":[{\"title\":\"   \"}]}",
        ] {
            let p = parse(raw);
            assert!(p.degraded, "应降级：{raw:?}");
            assert!(p.nodes.is_empty());
            assert!(p.reason.is_some(), "降级必须带原因（便于排查，但不给用户看）");
        }
    }

    #[test]
    fn degradation_never_panics_on_truncated_json() {
        // 流式被中断 / 输出被截断的最坏情况
        let p = parse(r#"{"nodes":[{"title":"A","resour"#);
        assert!(p.degraded);
        assert!(p.nodes.is_empty());
    }
}
