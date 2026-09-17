//! 成长档案导出（10 §6：Markdown 优先，用于分享或写简历）。
//!
//! **只导出 confirmed = 1 的内容** —— 未确认的是 AI 建议，导出去就等于
//! "AI 替用户发言了"（隐私 + 红线 V3 的边界）。文件头部明确告知导出范围。

use crate::profile::repository::{ProfileBasic, ProfileProjectEntry, ProfileSkill, TimelineEvent};

/// 组装 Markdown 文本（纯函数，便于单测：不碰库、不碰时钟）。
pub fn build_markdown(
    basic: &ProfileBasic,
    skills: &[ProfileSkill],
    projects: &[ProfileProjectEntry],
    timeline: &[TimelineEvent],
) -> String {
    let mut md = String::new();
    md.push_str("# 个人档案\n\n");
    md.push_str("> 本文件由 Personal Workspace 导出，包含：基础信息、技能、项目经历、成长时间线。\n");
    md.push_str("> 仅含你已确认的档案内容；未确认的 AI 建议不会出现在这里。\n\n");

    md.push_str("## 基础信息\n\n");
    if !basic.name.is_empty() {
        md.push_str(&format!("- **名称**：{}\n", basic.name));
    }
    if !basic.direction.is_empty() {
        md.push_str(&format!("- **方向**：{}\n", basic.direction));
    }
    if !basic.interests.is_empty() {
        md.push_str(&format!("- **兴趣**：{}\n", basic.interests.join(" · ")));
    }
    if !basic.motto.is_empty() {
        md.push_str(&format!("\n> {}\n", basic.motto));
    }
    if basic.name.is_empty() && basic.direction.is_empty() && basic.motto.is_empty() {
        md.push_str("（未填写）\n");
    }
    md.push('\n');

    md.push_str("## 技能\n\n");
    if skills.is_empty() {
        md.push_str("（暂无）\n\n");
    } else {
        for s in skills {
            let filled = (s.level / 10) as usize;
            let bar = format!("{}{}", "█".repeat(filled), "░".repeat(10 - filled));
            md.push_str(&format!("- **{}**（{}）{} {}\n", s.name, s.level, bar, s.level));
        }
        md.push('\n');
    }

    md.push_str("## 项目经历\n\n");
    if projects.is_empty() {
        md.push_str("（暂无）\n\n");
    } else {
        for p in projects {
            let period = match (p.start_date.as_deref(), p.end_date.as_deref()) {
                (Some(a), Some(b)) => format!("{a} ~ {b}"),
                (Some(a), None) => format!("{a} ~"),
                (None, Some(b)) => format!("~ {b}"),
                (None, None) => String::new(),
            };
            md.push_str(&format!("### {}{}\n\n", p.name, if period.is_empty() { String::new() } else { format!("（{period}）") }));
            if let Some(role) = p.role.as_deref().filter(|s| !s.trim().is_empty()) {
                md.push_str(&format!("- **角色**：{role}\n"));
            }
            if let Some(summary) = p.summary.as_deref().filter(|s| !s.trim().is_empty()) {
                md.push_str(&format!("- **简介**：{summary}\n"));
            }
            if !p.tech_stack.is_empty() {
                md.push_str(&format!("- **技术栈**：{}\n", p.tech_stack.join("、")));
            }
            md.push('\n');
        }
    }

    md.push_str("## 成长时间线\n\n");
    if timeline.is_empty() {
        md.push_str("（暂无）\n");
    } else {
        // timeline_list 已按 event_date DESC 排序；导出保持同一顺序
        let mut last_ym = String::new();
        for e in timeline {
            let ym = e.event_date.get(..7).unwrap_or(&e.event_date).to_string();
            if ym != last_ym {
                md.push_str(&format!("### {}\n\n", ym));
                last_ym = ym;
            }
            let desc = e
                .description
                .as_deref()
                .filter(|s| !s.trim().is_empty())
                .map(|s| format!(" —— {s}"))
                .unwrap_or_default();
            md.push_str(&format!("- **{}**（{}）{}{}\n", e.title, e.event_date, e.kind, desc));
        }
    }
    md
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::profile::repository::BasicInput;

    fn sample() -> (ProfileBasic, Vec<ProfileSkill>, Vec<ProfileProjectEntry>, Vec<TimelineEvent>) {
        let basic = ProfileBasic {
            name: "白宇".into(),
            direction: "AI 工程".into(),
            interests: vec!["Rust".into(), "本地优先".into()],
            motto: "少废话".into(),
            updated_at: String::new(),
        };
        let skills = vec![ProfileSkill {
            id: 1,
            name: "Python".into(),
            level: 70,
            category: "lang".into(),
            source: "user".into(),
            confirmed: true,
            updated_at: String::new(),
        }];
        let projects = vec![ProfileProjectEntry {
            id: 1,
            name: "Personal Workspace".into(),
            role: Some("负责人".into()),
            summary: Some("个人智能工作空间".into()),
            tech_stack: vec!["Rust".into(), "Vue".into()],
            start_date: Some("2026-09-01".into()),
            end_date: None,
            status: "ongoing".into(),
            source: "user".into(),
            confirmed: true,
            created_at: String::new(),
            updated_at: String::new(),
        }];
        let timeline = vec![TimelineEvent {
            id: 1,
            event_date: "2026-09-13".into(),
            title: "完成学习目标：CV".into(),
            description: None,
            kind: "learning".into(),
            source: "ai_suggested".into(),
            confirmed: true,
            created_at: String::new(),
        }];
        (basic, skills, projects, timeline)
    }

    #[test]
    fn markdown_contains_confirmed_content_and_privacy_note() {
        let (b, s, p, t) = sample();
        let md = build_markdown(&b, &s, &p, &t);
        assert!(md.contains("# 个人档案"));
        assert!(md.contains("仅含你已确认的档案内容"), "必须有隐私告知");
        assert!(md.contains("白宇") && md.contains("少废话"));
        assert!(md.contains("Python") && md.contains("███████░░░ 70"));
        assert!(md.contains("Personal Workspace") && md.contains("Rust、Vue"));
        assert!(md.contains("### 2026-09"), "时间线应按年月分组");
        assert!(md.contains("完成学习目标：CV"));
    }

    #[test]
    fn empty_profile_still_valid_markdown() {
        let basic = ProfileBasic {
            name: String::new(),
            direction: String::new(),
            interests: Vec::new(),
            motto: String::new(),
            updated_at: String::new(),
        };
        let md = build_markdown(&basic, &[], &[], &[]);
        assert!(md.contains("（未填写）"));
        assert!(md.contains("（暂无）"));
        // 用到 BasicInput 的 Default，保持 import 不悬空
        let _ = BasicInput::default();
    }
}
