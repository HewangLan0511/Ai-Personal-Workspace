//! 装配层：只负责模块组装与启动顺序，禁止业务逻辑（见 docs/agent-dev/AGENTS.md 禁止事项）。
//!
//! 启动顺序：
//! 1. AppState（数据库 + 事件总线 + 配置服务）
//! 2. 本地 HTTP 服务（/api/v1 与 /internal，契约见 docs/agent-dev/03-数据契约与接口规范.md）
//! 3. Python sidecar（媒体/性能/AI，ADR-001 后不再承载窗口与进程控制）
//! 4. Tauri 窗口

mod agents;
mod ai;
mod api;
mod app_manager;
mod db;
mod desktop_widget;
mod device;
mod event_bus;
mod learning;
mod life;
mod plugins;
mod profile;
mod project;
mod scheduler;
mod sidecar;
mod state;
mod window_manager;

use std::sync::Arc;

use tauri::Manager;

use crate::state::AppState;

fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .init();

    // C4：core 实例身份打点（Snapshot v1 `source.runId` 的原料之一）。
    // 必须在**任何窗口/服务创建之前**，保证它代表"本次 core 实例真实启动时刻"。
    api::mark_started_now();

    // ★ 必须在创建任何窗口之前声明 DPI 感知（07 §4 / 禁止事项）。
    // 漏掉它，125%/150% 缩放下 Win32 返回的是"虚拟化坐标"，布局比例会整体偏小，
    // 且现象隐蔽（100% 缩放的机器上一切正常）—— 阶段3 验收项 8 专测这一条。
    if !window_manager::enable_dpi_awareness() {
        tracing::warn!("DPI 感知声明未生效（可能已由 manifest 声明）；若窗口坐标异常优先查此处");
    }

    let app_state = Arc::new(AppState::initialize()?);

    api::spawn_server(app_state.clone());
    sidecar::spawn_and_watch(app_state.clone());
    app_manager::spawn_status_watcher(app_state.clone()); // 阶段2 §3：5s 轮询运行状态
    learning::spawn_reminder_watcher(app_state.clone()); // 阶段6 §5：长期未更新的学习提醒
    device::spawn_device_watcher(app_state.clone()); // 阶段8 §B2：硬件指标采集（默认 2s）
    life::spawn_usage_sampler(app_state.clone()); // 阶段8 §A4：前台应用时长采样（默认 30s）

    tauri::Builder::default()
        .manage(app_state.clone())
        // 阶段9：pwplugin 自定义协议 —— 插件静态资源（HTML/JS/CSS）经 core 的
        // serve_file 提供（canonicalize + 目录前缀校验 + 5MB 上限，见 plugins/mod.rs）。
        // 插件 iframe 因此是独立 origin（http://pwplugin.localhost），天然与宿主隔离。
        .register_uri_scheme_protocol("pwplugin", |ctx, request| {
            type Body = std::borrow::Cow<'static, [u8]>;
            let state = ctx.app_handle().state::<Arc<AppState>>();
            let path = request.uri().path().trim_start_matches('/').to_string();
            let not_found = |msg: &str| -> tauri::http::Response<Body> {
                tauri::http::Response::builder()
                    .status(404)
                    .header("Content-Type", "text/plain; charset=utf-8")
                    .body(Body::from(msg.as_bytes().to_vec()))
                    .unwrap_or_default()
            };
            match path.split_once('/') {
                Some((plugin_id, rel)) if !plugin_id.is_empty() && !rel.is_empty() => {
                    let root = crate::plugins::plugins_root(&state);
                    match crate::plugins::serve_file(&root, plugin_id, rel) {
                        Ok((bytes, mime)) => tauri::http::Response::builder()
                            .header("Content-Type", mime)
                            .body(Body::from(bytes))
                            .unwrap_or_default(),
                        Err(e) => not_found(&e),
                    }
                }
                _ => not_found("URI 形态须为 pwplugin://localhost/<pluginId>/<相对路径>"),
            }
        })
        // 阶段9：小组件窗口关闭时把最终边界落盘（拖动/缩放过程不写库，见 desktop_widget.rs）。
        .on_window_event(|window, event| {
            if window.label() == desktop_widget::WIDGET_LABEL {
                if let tauri::WindowEvent::CloseRequested { .. } = event {
                    let state = window.app_handle().state::<Arc<AppState>>();
                    desktop_widget::on_close_requested(window, &state);
                }
            }
        })
        // 06 §4 `autoApply`：应用启动时自动进入标记了该选项的模式。
        // 放在窗口创建之后、延时 1.5s —— 让 UI 与 sidecar 先就绪，避免自动流程与启动抢资源。
        .setup(|app| {
            let state = app.state::<Arc<AppState>>().inner().clone();

            // 阶段9：AppHandle 注入（小组件窗口创建/查询依赖）。此后 desktop_widget 的
            // HTTP 面与 command 面都可用。
            *state.app.lock().unwrap_or_else(|e| e.into_inner()) = Some(app.handle().clone());
            desktop_widget::auto_open_if_enabled(&state);

            // L-017 / L-032：把事件总线桥接到 webview。
            // 此前所有 publish() 只到进程内 broadcast，前端收不到（"发了没人收到"）。
            // 阶段5 的 AI_STREAM_CHUNK 必须走这条链路才能增量显示，故先补桥。
            crate::event_bus::bridge_to_webview(app.handle().clone(), state.bus.clone());

            std::thread::spawn(move || {
                std::thread::sleep(std::time::Duration::from_millis(1500));
                match crate::scheduler::ModeRepo::new(state.db.clone()).list() {
                    Ok(modes) => {
                        if let Some(m) = modes.iter().find(|m| m.auto_apply) {
                            tracing::info!(mode = %m.name, "autoApply：自动进入模式");
                            if let Err(e) = crate::scheduler::apply_mode(&state, m.id, None) {
                                tracing::warn!(error = %e, "autoApply 执行失败（不阻塞启动）");
                            }
                        }
                    }
                    Err(e) => tracing::warn!(error = %e, "autoApply 查询模式失败"),
                }
            });
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            api::commands::ping,
            api::commands::get_config,
            api::commands::put_config,
            api::commands::minimize_window,
            // ---- 阶段2：软件管理 ----
            api::commands::apps_list,
            api::commands::apps_categories,
            api::commands::apps_add,
            api::commands::apps_update,
            api::commands::apps_delete,
            api::commands::apps_launch,
            api::commands::apps_running,
            api::commands::apps_pick_file,
            api::commands::apps_probe,
            api::commands::apps_scan,
            api::commands::apps_icon_data,
            // ---- 阶段3：窗口管理 ----
            api::commands::monitors_list,
            api::commands::layouts_list,
            api::commands::layout_get,
            api::commands::layout_apply,
            api::commands::windows_list,
            api::commands::windows_find,
            api::commands::windows_rect,
            api::commands::windows_place,
            api::commands::windows_activate,
            // ---- 阶段4：工作模式引擎 ----
            api::commands::modes_list,
            api::commands::modes_capture_current,
            api::commands::modes_get,
            api::commands::modes_add,
            api::commands::modes_update,
            api::commands::modes_delete,
            api::commands::modes_duplicate,
            api::commands::modes_current,
            api::commands::mode_apply,
            api::commands::mode_cancel,
            api::commands::mode_progress,
            api::commands::modes_remember_switch,
            api::commands::mode_restore,
            api::commands::mode_exit,
            api::commands::db_layouts_list,
            api::commands::db_layout_get,
            api::commands::db_layout_upsert,
            // ---- 阶段5：AI 助手 ----
            api::commands::ai_chat,
            api::commands::ai_cancel,
            api::commands::ai_info,
            api::commands::ai_set_credential,
            api::commands::ai_delete_credential,
            api::commands::ai_list_models,
            api::commands::ai_permission_scope,
            api::commands::ai_preview_context,
            // ---- 阶段6：学习成长 ----
            api::commands::learning_goals_list,
            api::commands::learning_goal_get,
            api::commands::learning_goal_add,
            api::commands::learning_goal_update,
            api::commands::learning_goal_delete,
            api::commands::learning_nodes_list,
            api::commands::learning_roadmap_confirm,
            api::commands::learning_node_add,
            api::commands::learning_node_update,
            api::commands::learning_node_delete,
            api::commands::learning_node_move,
            api::commands::learning_updates_list,
            api::commands::learning_update_add,
            api::commands::learning_ai_suggest,
            api::commands::learning_check_reminders,
            // ---- 阶段6：项目管理 ----
            api::commands::projects_list,
            api::commands::project_get,
            api::commands::project_add,
            api::commands::project_update,
            api::commands::project_delete,
            api::commands::project_by_mode,
            // ---- 阶段7：个人数字档案 ----
            api::commands::profile_overview,
            api::commands::profile_basic_get,
            api::commands::profile_basic_save,
            api::commands::profile_skills_list,
            api::commands::profile_skill_add,
            api::commands::profile_skill_update,
            api::commands::profile_skill_remove,
            api::commands::profile_skill_confirm,
            api::commands::profile_projects_list,
            api::commands::profile_project_add,
            api::commands::profile_project_remove,
            api::commands::profile_project_confirm,
            api::commands::profile_timeline_list,
            api::commands::profile_timeline_add,
            api::commands::profile_timeline_remove,
            api::commands::profile_timeline_confirm,
            api::commands::profile_suggestions_list,
            api::commands::profile_suggestions_scan,
            api::commands::profile_suggestions_confirm,
            api::commands::profile_suggestions_ignore,
            api::commands::profile_suggestions_reject_kind,
            api::commands::profile_export_markdown,
            // ---- 阶段8：生活中心 ----
            api::commands::life_usage_today,
            api::commands::life_usage_week,
            api::commands::life_weather,
            api::commands::life_media_now,
            api::commands::life_media_control,
            api::commands::life_social_overview,
            api::commands::life_social_config_get,
            api::commands::life_social_config_put,
            // ---- 阶段8：设备中心 ----
            api::commands::device_metrics,
            api::commands::device_processes,
            api::commands::device_process_kill,
            api::commands::device_mode_health,
            // ---- 阶段9：插件系统 ----
            api::commands::plugins_list,
            api::commands::plugins_discover,
            api::commands::plugins_install,
            api::commands::plugins_import_zip,
            api::commands::plugins_set_enabled,
            api::commands::plugins_uninstall,
            api::commands::plugin_api,
            api::commands::plugin_crash,
            api::commands::plugin_audit_list,
            // ---- 阶段9：外部 Agent ----
            api::commands::agents_list,
            api::commands::agents_save,
            api::commands::agent_health,
            api::commands::agent_invoke,
            // ---- 阶段9：桌面小组件 ----
            api::commands::desktop_widget_toggle,
            api::commands::desktop_widget_status,
            api::commands::desktop_widget_save_bounds,
            api::commands::desktop_widget_set_always_on_top,
        ])
        .run(tauri::generate_context!())
        .map_err(|err| anyhow::anyhow!("tauri 启动失败: {err}"))?;

    Ok(())
}
