//! 学习成长模块（阶段6 · `09-阶段指令-学习成长.md`）。
//!
//! **定位一句话**：AI 规划，用户执行，系统提醒。
//!
//! ## 红线 V3 在代码结构上的落实
//!
//! "AI 提供建议，用户决定状态"不能只写在提示词里。本模块通过**函数边界**保证：
//!
//! | 路径 | 是否写库 | 说明 |
//! |------|:--------:|------|
//! | [`ai_suggest`] | **否** | 只读目标与进度用于组装提问，产出建议后返回给前端 |
//! | [`LearningRepo`] 的各写方法 | 是 | 只由**用户动作**（command）调用 |
//!
//! 也就是说：**没有任何一条从 AI 到数据库的代码路径**。建议要变成事实，
//! 必须经过用户点击 → 前端调 `roadmap_confirm` / `node_update` → 才落到库里。
//! 这条不变量由 `tools/verify_stage6.py` 的验收项 6 端到端断言（调用前后快照必须一致）。

mod reminder;
mod repository;
mod roadmap;

// 只 re-export 模块**对外**真正用到的符号（api/commands 与 main）。
// 其余（`should_remind` / `parse_dt` / 各枚举常量 / `Progress`）留在子模块内 ——
// 它们是实现细节与内部契约，多导一层只会制造 `unused_imports` 噪音。
pub use reminder::{scan as scan_reminders, spawn_watcher as spawn_reminder_watcher, ReminderHit};
pub use repository::{
    GoalInput, GoalPatch, LearningGoal, LearningRepo, NodeInput, NodePatch, RoadmapNode,
};
pub use roadmap::parse as parse_roadmap;
pub use roadmap::ParsedRoadmap;

use serde_json::{json, Value};

use crate::ai::{chat_stream, AiChatArgs, AiMessage};
use crate::event_bus::LEARNING_PROGRESS_UPDATED;
use crate::state::AppState;

/// 学习模块的写入口（**用户动作**）—— HTTP 与 Tauri command 两个入口共用这一份，
/// 避免"两边各发一次事件"或"有一边忘了发"（02 §2.2：双通道必须同源）。
///
/// 事件契约 3.3：`LEARNING_PROGRESS_UPDATED { goalId, nodeId, status }`。
/// `roadmap_confirmed` / `deleted` 这类非枚举状态也会出现在 `status` 里 ——
/// 订阅方只应把它当作"该刷新了"的信号，不要当作节点状态枚举使用。
pub fn apply_node_update(
    state: &AppState,
    id: i64,
    patch: &NodePatch,
) -> anyhow::Result<RoadmapNode> {
    let (node, status_changed) = LearningRepo::new(state.db.clone()).node_update(id, patch)?;
    if status_changed {
        let _ = state.bus.publish(
            LEARNING_PROGRESS_UPDATED,
            json!({ "goalId": node.goal_id, "nodeId": node.id, "status": node.status }),
        );
    }
    Ok(node)
}

/// 更新目标状态并发事件（"继续 / 暂停 / 归档"三个提醒动作最终都落到这里）。
pub fn apply_goal_update(
    state: &AppState,
    id: i64,
    patch: &GoalPatch,
) -> anyhow::Result<LearningGoal> {
    let repo = LearningRepo::new(state.db.clone());
    let before = repo.goal_get(id)?;
    let after = repo.goal_update(id, patch)?;
    let changed = before.as_ref().map(|g| g.status != after.status).unwrap_or(true);
    if changed {
        let _ = state.bus.publish(
            LEARNING_PROGRESS_UPDATED,
            json!({ "goalId": id, "nodeId": Value::Null, "status": after.status }),
        );
    }
    // 阶段7 §5 触发点：目标完成 → 档案时间线建议。**只入待确认队列**（红线 V3：
    // 档案是用户自我认知的记录，AI/系统不能替用户写）。重复触发由建议表的
    // 去重键兜底，同一目标只挂一条 pending。
    if after.status == "done" && before.as_ref().map(|g| g.status.as_str()) != Some("done") {
        crate::profile::collect_goal_done(state, id, &after.title, after.description.as_deref());
    }
    Ok(after)
}

/// AI 在学习模块里被允许做的三类事（09 §4）。超出这三类的用途不该走这里。
pub const AI_KINDS: &[&str] = &["roadmap", "optimize", "summary"];

/// AI 生成模式：走 `workspace`（允许携带上下文），并**由 `promptKey` 决定人格**。
///
/// 为什么不是 `consult`：这三个用途都需要知道用户的目标与进度才能给出有用的东西，
/// 属于用户**主动点击**的功能（不是背景咨询）。红线 V2 管的是"咨询模式不得读数据"，
/// 此处是用户显式发起的、结果只回给用户本人的建议生成。
const AI_MODE: &str = "workspace";

/// 让 AI 产出**建议**（路线 / 优化 / 总结）。**只读不写**（红线 V3）。
///
/// 返回结构（`advisory: true` 是关键字段 —— UI 必须据此打上"AI 建议，待确认"标记）：
/// ```json
/// { "kind": "roadmap", "advisory": true, "raw": "…模型原文…",
///   "degraded": false, "reason": null, "nodes": [ … ], "chunkCount": 12, "durationMs": 3400 }
/// ```
pub fn ai_suggest(
    state: &AppState,
    goal_id: Option<i64>,
    kind: &str,
    provider: &str,
    model: &str,
    api_base: &str,
    extra: &str,
) -> anyhow::Result<Value> {
    if !AI_KINDS.contains(&kind) {
        anyhow::bail!("不支持的建议类型：{kind}（可选 {AI_KINDS:?}）");
    }
    if provider.trim().is_empty() {
        anyhow::bail!("请先在「设置 → AI」中选择一个 Provider");
    }

    let repo = LearningRepo::new(state.db.clone());
    let goal = match goal_id {
        Some(id) => Some(
            repo.goal_get(id)?
                .ok_or_else(|| anyhow::anyhow!("学习目标不存在：id={id}"))?,
        ),
        None => None,
    };
    let nodes = match goal_id {
        Some(id) => repo.nodes_list(id)?,
        None => Vec::new(),
    };

    let prompt_key = match kind {
        "roadmap" => "roadmap_generate",
        // 优化建议与阶段总结都是"基于现状给建议"的自然语言产出，共用学习助手人格
        _ => "study_assistant",
    };

    let chat = chat_stream(
        state,
        AiChatArgs {
            provider: provider.to_string(),
            model: model.to_string(),
            messages: vec![AiMessage {
                role: "user".into(),
                content: build_question(goal.as_ref(), &nodes, kind, extra),
            }],
            mode: AI_MODE.to_string(),
            // 生成路线需要"当前学习/项目背景"，否则建议与用户处境脱节
            enabled_scopes: [
                ("mode".to_string(), true),
                ("apps".to_string(), false),
                ("project".to_string(), true),
                ("learning".to_string(), true),
                ("profile".to_string(), false),
            ]
            .into_iter()
            .collect(),
            prompt_key: prompt_key.to_string(),
            // 路线拆解要稳不要飘 —— 温度过高会让同一目标每次生成差异巨大
            temperature: if kind == "roadmap" { 0.4 } else { 0.6 },
            max_tokens: 2048,
            api_base: api_base.to_string(),
        },
    )?;

    // 只有"生成路线"需要结构化；另外两类是给人读的文本，不做 JSON 解析
    let parsed = if kind == "roadmap" {
        crate::learning::parse_roadmap(&chat.text)
    } else {
        ParsedRoadmap { nodes: Vec::new(), degraded: false, reason: None }
    };

    Ok(json!({
        "kind": kind,
        // ★ 前端必须据此展示"AI 建议，待确认"（09 §禁止事项第 2 条）
        "advisory": true,
        "promptKey": prompt_key,
        "raw": chat.text,
        "degraded": parsed.degraded,
        "reason": parsed.reason,
        "nodes": parsed.nodes,
        "chunkCount": chat.chunk_count,
        "durationMs": chat.duration_ms,
    }))
}

/// 组装提问文本。
///
/// 把"现状"写进用户消息而不是 system：system 由提示词模板占据
/// （模板是产品的稳定人格，不该被数据污染），现状是每次请求的可变部分。
fn build_question(
    goal: Option<&LearningGoal>,
    nodes: &[RoadmapNode],
    kind: &str,
    extra: &str,
) -> String {
    let mut q = String::new();
    match goal {
        Some(g) => {
            q.push_str(&format!("学习目标：{}\n", g.title));
            if let Some(d) = g.description.as_deref().filter(|s| !s.trim().is_empty()) {
                q.push_str(&format!("目标说明：{d}\n"));
            }
            if let Some(e) = g.expected_at.as_deref().filter(|s| !s.trim().is_empty()) {
                q.push_str(&format!("期望完成时间：{e}\n"));
            }
            q.push_str(&format!(
                "当前状态：{}（进度 {}/{}）\n",
                g.status, g.progress.done, g.progress.total
            ));
            if !nodes.is_empty() {
                q.push_str("现有节点：\n");
                for n in nodes {
                    let note = n
                        .note
                        .as_deref()
                        .filter(|s| !s.trim().is_empty())
                        .map(|s| format!("（备注：{s}）"))
                        .unwrap_or_default();
                    q.push_str(&format!("  {}. [{}] {}{}\n", n.sort_order, n.status, n.title, note));
                }
            }
        }
        None => {
            // 还没有目标：允许"先出路线，再建目标"的用法
            q.push_str("用户还没有创建学习目标。\n");
        }
    }
    if !extra.trim().is_empty() {
        q.push_str(&format!("补充说明：{}\n", extra.trim()));
    }
    q.push_str(match kind {
        "roadmap" => "\n请为上述学习目标生成学习路线（严格按模板要求的 JSON 格式输出）。",
        "optimize" => "\n请基于上述现状，给出**路线优化建议**（指出该补的前置、该砍的冗余、该调整的顺序）。",
        _ => "\n请基于上述现状与备注，生成一份**阶段总结草稿**，供用户复盘时修改使用。",
    });
    q
}
