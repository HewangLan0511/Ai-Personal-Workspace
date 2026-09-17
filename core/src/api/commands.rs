//! Tauri commands：UI 经 invoke 调用的桥接层（与 `/api/v1` 等价，双通道）。
//!
//! **UI 侧首选本通道**（见 `ui/src/api/`）：
//! Tauri invoke 不经过 HTTP，因此**不受 core 随机端口影响** —— 这是 REVIEW-002 R-02
//! 「UI ↔ core 端口链路断裂」的根因修复。契约 3.4 允许 UI 走 Tauri command 或 `/api/v1`，
//! 此处选定 command 通道为主路径。
//!
//! 阶段2 新增 `apps_*` 系列（05-阶段指令-软件管理）。**这两个通道必须同源**：
//! 同一份业务逻辑（`app_manager` / `AppsRepo`），只是入口不同 —— 不要在任一侧另写一套。

use std::sync::Arc;

use serde_json::{json, Value};
use tauri::{Manager, State};

use crate::app_manager::{AppInput, AppPatch};
use crate::state::AppState;

/// 探活命令：UI 判断 core 是否在线（替代浏览器环境下的 `/health`）。
///
/// C4：返回值为 `/health` 同形的身份事实 JSON 字符串（`{service,pid,started_at}`）。
/// 为什么改这里而不是新增命令：Tauri 主路径不经过 HTTP（UI 无从得知 core 的随机端口），
/// `ping` 是 invoke 侧既有的探活口 —— 复用它即可在桌面端拿到 Snapshot `source`
/// 所需的真实进程事实，**不新增命令、不新增表、不新增迁移**。
/// 兼容性：唯一消费者（`client.ts::checkConnection`）只判断"是否抛错"，不解析该字符串。
#[tauri::command]
pub fn ping() -> String {
    crate::api::identity_facts().to_string()
}

#[tauri::command]
pub fn get_config(state: State<'_, Arc<AppState>>, key: String) -> Value {
    state.config.get(&key)
}

#[tauri::command]
pub fn put_config(
    state: State<'_, Arc<AppState>>,
    key: String,
    value: Value,
) -> Result<Value, String> {
    state.config.set(&key, value).map_err(e2s)
}

/// 最小化主窗口（04 §2 顶栏「最小化」按钮，修复 REVIEW-002 R-06）。
#[tauri::command]
pub fn minimize_window(window: tauri::WebviewWindow) -> Result<(), String> {
    window.minimize().map_err(e2s)
}

// ---------------------------------------------------------------- 阶段2：软件管理

/// 软件列表（分类过滤 + 名称模糊搜索）。排序见 `AppsRepo::list`（05 §4）。
#[tauri::command]
pub fn apps_list(
    state: State<'_, Arc<AppState>>,
    category: Option<String>,
    search: Option<String>,
) -> Result<Value, String> {
    let rows = state
        .apps
        .list(category.as_deref(), search.as_deref())
        .map_err(e2s)?;
    to_value(rows)
}

#[tauri::command]
pub fn apps_categories(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(state.apps.categories().map_err(e2s)?)
}

#[tauri::command]
pub fn apps_add(state: State<'_, Arc<AppState>>, input: AppInput) -> Result<Value, String> {
    let row = state.apps.add(&input).map_err(e2s)?;
    // 契约 3.3：APP_REGISTERED { appId, name, path }
    let _ = state.bus.publish(
        crate::event_bus::APP_REGISTERED,
        json!({ "appId": row.id, "name": row.name, "path": row.path }),
    );
    to_value(row)
}

#[tauri::command]
pub fn apps_update(
    state: State<'_, Arc<AppState>>,
    id: i64,
    patch: AppPatch,
) -> Result<Value, String> {
    to_value(state.apps.update(id, &patch).map_err(e2s)?)
}

#[tauri::command]
pub fn apps_delete(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    state.apps.soft_delete(id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

/// 当前运行中的软件（`appId → pid`），供 UI 上色"运行中"。
#[tauri::command]
pub fn apps_running(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(state.running.snapshot())
}

/// 启动软件。逻辑与 HTTP 入口共用 `app_manager::launch_registered`（05 §2）。
#[tauri::command]
pub fn apps_launch(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    crate::app_manager::launch_registered(&state, id).map_err(e2s)
}

/// 弹出文件选择器（05 §1 添加方式一）。
///
/// **刻意写成同步命令**：Tauri 的同步 command 跑在主线程，而 Windows 模态对话框
/// 必须由 UI 线程发起（见 `files.rs` 注释）。改成 async 会让对话框行为异常。
#[tauri::command]
pub fn apps_pick_file() -> Result<Value, String> {
    match crate::app_manager::pick_executable("选择要添加的软件", None) {
        Ok(Some(path)) => Ok(json!({ "path": path })),
        Ok(None) => Ok(json!({ "path": Value::Null })), // 用户取消：不是错误
        Err(e) => Err(e2s(e)),
    }
}

/// 自动补全（05 §1）：探测名称（FileDescription）+ 提取图标。
/// 走 sidecar（注册表/文件属性属系统集成，02 §2.4 归 Python）。
#[tauri::command]
pub async fn apps_probe(state: State<'_, Arc<AppState>>, path: String) -> Result<Value, String> {
    let out_dir = state.icons_dir().to_string_lossy().to_string();
    crate::sidecar::call(&state, "/apps/probe", json!({ "path": path, "out_dir": out_dir }))
        .await
        .map_err(e2s)
}

/// 扫描本机已安装软件（05 §1 添加方式二）。**结果只返回给用户勾选，不自动入库**。
#[tauri::command]
pub async fn apps_scan(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    crate::sidecar::call(&state, "/apps/scan", json!({}))
        .await
        .map_err(e2s)
}

/// 读图标缓存并转 data URL（供 `<img src>` 使用）。
///
/// webview 不能直接加载本地文件路径，故由 core 读出来转 base64。
/// 只允许读 `icons_dir` 内的文件（见 `app_manager/icon.rs` 的目录穿越防护）。
#[tauri::command]
pub fn apps_icon_data(state: State<'_, Arc<AppState>>, path: String) -> Result<String, String> {
    crate::app_manager::read_icon_data_url(&state.icons_dir(), &path).map_err(e2s)
}

// ---------------------------------------------------------------- 阶段3：窗口管理

/// 显示器列表（07 验收项 7 多屏 / 8 高 DPI 的核验入口）。
#[tauri::command]
pub fn monitors_list() -> Result<Value, String> {
    to_value(crate::window_manager::list_monitors())
}

/// 内置布局**全文**（名字 + 槽位 + 侧栏），供 UI 直接渲染预览。
#[tauri::command]
pub fn layouts_list() -> Result<Value, String> {
    let items: Vec<crate::window_manager::Layout> = crate::window_manager::list_builtin_layouts()
        .iter()
        .filter_map(|n| crate::window_manager::load_layout(n).ok())
        .collect();
    to_value(items)
}

#[tauri::command]
pub fn layout_get(name: String) -> Result<Value, String> {
    to_value(crate::window_manager::load_layout(&name).map_err(e2s)?)
}

/// 应用布局。
///
/// **会阻塞**（含 50~100ms 分步延时与失败重试），故：
/// - 放进 `spawn_blocking`，不占用异步 worker；
/// - 写成 `async` command，避免 Tauri 把它调度到 UI 主线程上（同步 command 在主线程执行）。
#[tauri::command]
pub async fn layout_apply(
    state: State<'_, Arc<AppState>>,
    name: String,
    // 覆盖布局文件里的 `monitor`（07 §6「显示器选择（多屏时）」）
    monitor: Option<usize>,
) -> Result<Value, String> {
    let st = state.inner().clone();
    let join = tauri::async_runtime::spawn_blocking(move || {
        let mut layout = crate::window_manager::load_layout(&name)?;
        if let Some(m) = monitor {
            layout.monitor = m;
        }
        crate::window_manager::apply_layout(&st, &layout)
    })
    .await
    .map_err(|e| format!("任务调度失败：{e}"))?;
    to_value(join.map_err(e2s)?)
}

/// 当前所有可管理的顶层窗口（07 §1 的过滤结果）。
#[tauri::command]
pub fn windows_list() -> Result<Value, String> {
    to_value(crate::window_manager::list_windows())
}

/// 按 pid 或标题关键词查找窗口；两者都不给则返回全部可管理窗口。
#[tauri::command]
pub fn windows_find(pid: Option<u32>, title: Option<String>) -> Result<Value, String> {
    if let Some(p) = pid {
        // 验收项 1 明确要求：无窗口时返回 null，不报错
        return to_value(crate::window_manager::find_main_window(p));
    }
    if let Some(kw) = title.filter(|s| !s.trim().is_empty()) {
        return to_value(crate::window_manager::find_by_title(&kw));
    }
    to_value(crate::window_manager::list_windows())
}

/// 取窗口当前像素矩形（验收项 2「±2px」的复核手段）。
#[tauri::command]
pub fn windows_rect(hwnd: i64) -> Result<Value, String> {
    Ok(match crate::window_manager::get_rect(hwnd as isize) {
        Some(r) => serde_json::to_value(r).unwrap_or(Value::Null),
        None => Value::Null,
    })
}

/// 定位单个窗口（验收项 2 / 4）。
#[tauri::command]
pub fn windows_place(
    hwnd: i64,
    rect: crate::window_manager::PxRect,
    always_on_top: Option<bool>,
    maximized: Option<bool>,
) -> Result<Value, String> {
    let r = rect;
    crate::window_manager::place(
        hwnd as isize,
        r,
        always_on_top.unwrap_or(false),
        maximized.unwrap_or(false),
    )
    .map_err(e2s)?;
    to_value(r)
}

/// 激活并置前（验收项 5）。
#[tauri::command]
pub fn windows_activate(hwnd: i64) -> Result<Value, String> {
    crate::window_manager::activate(hwnd as isize).map_err(e2s)?;
    Ok(json!({
        "hwnd": hwnd,
        "foreground": crate::window_manager::is_foreground(hwnd as isize)
    }))
}

// ---------------------------------------------------------------- 阶段4：工作模式引擎

fn mode_repo(state: &AppState) -> crate::scheduler::ModeRepo {
    crate::scheduler::ModeRepo::new(state.db.clone())
}

#[tauri::command]
pub fn modes_list(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(mode_repo(&state).list().map_err(e2s)?)
}

#[tauri::command]
pub fn modes_get(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(mode_repo(&state).get(id).map_err(e2s)?)
}

#[tauri::command]
pub fn modes_add(
    state: State<'_, Arc<AppState>>,
    input: crate::scheduler::WorkModeInput,
) -> Result<Value, String> {
    to_value(mode_repo(&state).add(&input).map_err(e2s)?)
}

#[tauri::command]
pub fn modes_update(
    state: State<'_, Arc<AppState>>,
    id: i64,
    patch: crate::scheduler::WorkModePatch,
) -> Result<Value, String> {
    to_value(mode_repo(&state).update(id, &patch).map_err(e2s)?)
}

#[tauri::command]
pub fn modes_delete(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    mode_repo(&state).soft_delete(id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

#[tauri::command]
pub fn modes_duplicate(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(mode_repo(&state).duplicate(id).map_err(e2s)?)
}

/// 模式状态：`configured`（config 里的"上次使用"）+ `running`（本次进程内当前模式）。
///
/// 06 §4：重启后**默认不自动重新应用**，只在 UI 显示"上次使用的模式"并提供一键恢复 ——
/// 所以这里把两者分开返回，UI 才能区分"上次用过"与"现在正开着"。
#[tauri::command]
pub fn modes_current(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let configured = state.config.get("mode.current");
    let running = state.modes_run.current();
    let launched = running
        .as_deref()
        .map(|m| state.modes_run.launched_by(m))
        .unwrap_or_default();
    Ok(json!({
        "configured": configured,
        "running": running,
        "launchedAppIds": launched,
        "lastSnapshot": state.modes_run.last_snapshot(),
    }))
}

/// 应用模式。**阻塞**（含等待窗口就绪），故放阻塞线程池。
#[tauri::command]
pub async fn mode_apply(
    state: State<'_, Arc<AppState>>,
    mode_id: i64,
    policy: Option<String>,
) -> Result<Value, String> {
    let st = state.inner().clone();
    let join = tauri::async_runtime::spawn_blocking(move || {
        crate::scheduler::apply_mode(&st, mode_id, policy)
    })
    .await
    .map_err(|e| format!("任务调度失败：{e}"))?;
    to_value(join.map_err(e2s)?)
}

/// 取消进行中的应用流程（06 §2「可取消」）。
#[tauri::command]
pub fn mode_cancel(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let guard = state.mode_session.lock().unwrap_or_else(|e| e.into_inner());
    match guard.as_ref() {
        Some(s) => {
            s.cancel_token().cancel();
            Ok(json!({ "cancelled": true, "modeName": s.mode_name }))
        }
        None => Ok(json!({ "cancelled": false, "reason": "当前没有进行中的应用流程" })),
    }
}

/// 当前应用进度（供 UI 进度面板轮询）。
#[tauri::command]
pub fn mode_progress(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let guard = state.mode_session.lock().unwrap_or_else(|e| e.into_inner());
    match guard.as_ref() {
        Some(s) => {
            let st = s.state();
            Ok(json!({
                "active": !st.is_terminal(),
                "modeId": s.mode_id,
                "modeName": s.mode_name,
                "state": st,
                "slots": s.slots(),
                // F-38「步骤清单」：apply 很快，外部轮询抓不全中间态，故由会话自己记轨迹
                "history": s.history(),
            }))
        }
        None => Ok(json!({ "active": false, "state": { "phase": "idle" }, "slots": [] })),
    }
}

/// 记住用户对"从 `from` 切到 `to`"的切换策略选择（06 §3 `ask`：首次询问并记住）。
#[tauri::command]
pub fn modes_remember_switch(
    state: State<'_, Arc<AppState>>,
    from: String,
    to: String,
    policy: String,
) -> Result<Value, String> {
    if !crate::scheduler::SWITCH_POLICIES.contains(&policy.as_str()) {
        return Err(format!("非法的切换策略：{policy}"));
    }
    let mut mem = state.config.get("mode.switch_memory");
    if !mem.is_object() {
        mem = json!({});
    }
    let key = format!("{from}>{to}");
    mem[&key] = json!(policy);
    state.config.set("mode.switch_memory", mem).map_err(e2s)?;
    Ok(json!({ "key": key, "policy": policy }))
}

/// 一键恢复"上次使用的模式"（06 §4：重启后**不自动应用**，但提供一键恢复）。
#[tauri::command]
pub async fn mode_restore(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let raw = state.config.get("mode.current");
    let name = raw.as_str().unwrap_or("").trim().to_string();
    if name.is_empty() {
        return Err("没有可恢复的『上次使用模式』".into());
    }
    let m = mode_repo(&state)
        .get_by_name(&name)
        .map_err(e2s)?
        .ok_or_else(|| format!("上次使用的模式「{name}」已不存在（可能已被删除）"))?;
    let id = m.id;
    let st = state.inner().clone();
    let join =
        tauri::async_runtime::spawn_blocking(move || crate::scheduler::apply_mode(&st, id, None))
            .await
            .map_err(|e| format!("任务调度失败：{e}"))?;
    to_value(join.map_err(e2s)?)
}

/// 退出当前模式：关闭**该模式自己拉起的**软件（06 §4；用户手动开的一个都不碰）。
#[tauri::command]
pub fn mode_exit(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(crate::scheduler::exit_mode(&state).map_err(e2s)?)
}

// ---- 布局（数据库为真相；06 §技术要点）----

#[tauri::command]
pub fn db_layouts_list(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(
        crate::scheduler::LayoutRepo::new(state.db.clone())
            .list()
            .map_err(e2s)?,
    )
}

#[tauri::command]
pub fn db_layout_get(state: State<'_, Arc<AppState>>, name: String) -> Result<Value, String> {
    to_value(
        crate::scheduler::LayoutRepo::new(state.db.clone())
            .get(&name)
            .map_err(e2s)?,
    )
}

/// 布局写入（**唯一写入口**：先写库，再导出 JSON）。
#[tauri::command]
pub fn db_layout_upsert(
    state: State<'_, Arc<AppState>>,
    name: String,
    description: Option<String>,
    slots: Value,
    monitor: Option<i64>,
) -> Result<Value, String> {
    to_value(
        crate::scheduler::LayoutRepo::new(state.db.clone())
            .upsert(
                &name,
                description.as_deref(),
                &slots,
                monitor.unwrap_or(0),
                // UI 的布局编辑器暂不产出 AI 侧栏配置；传 None（不去覆盖已有值需另加参数）
                None,
                false,
            )
            .map_err(e2s)?,
    )
}

/// 「从当前工作环境创建模式」交互原则落地（2026-09-13 重构）：
/// 用户只给模式名，系统负责识别当前打开的应用与窗口布局。
/// 实现：枚举可见主窗口 → 过滤壳窗口/自身 → 记录进程名与矩形（归一化到主屏工作区，
/// 与 arrange 的换算基准一致）→ 布局入库（captured-<时间戳>）→ 建 work_mode 并绑定该布局。
#[tauri::command]
pub fn modes_capture_current(
    state: State<'_, Arc<AppState>>,
    name: String,
) -> Result<Value, String> {
    modes_capture_current_inner(&state, name)
}

/// 供 Tauri command 与 HTTP 路由共用的实现主体。
pub fn modes_capture_current_inner(
    state: &Arc<AppState>,
    name: String,
) -> Result<Value, String> {
    let name = name.trim().to_string();
    if name.is_empty() {
        return Err("请先给模式起个名字".into());
    }
    let own_pid = std::process::id();
    let (work, _) = crate::window_manager::work_area_of(0)
        .ok_or_else(|| "无法获取主显示器工作区".to_string())?;

    const SHELL_PROCESSES: &[&str] = &[
        "explorer.exe",
        "applicationframehost.exe",
        "textinputhost.exe",
        "searchhost.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "systemsettings.exe",
    ];

    // 候选：可见、有 rect、非自身进程、非系统壳、面积够大（过滤通知弹窗类）
    let mut picked: Vec<(String, crate::window_manager::PxRect)> = Vec::new();
    for w in crate::window_manager::list_windows() {
        if w.pid == own_pid || w.minimized {
            continue;
        }
        let Some(rect) = w.rect else { continue };
        if rect.w < 200 || rect.h < 150 {
            continue;
        }
        let Some(exe) = crate::device::processes::process_image_name(w.pid) else {
            continue;
        };
        if SHELL_PROCESSES.contains(&exe.as_str()) {
            continue;
        }
        let display = exe.trim_end_matches(".exe").to_string();
        // 同名进程多窗口：保留面积最大者
        if let Some(slot) = picked.iter_mut().find(|(n, _)| *n == display) {
            if (rect.w as i64) * (rect.h as i64) > (slot.1.w as i64) * (slot.1.h as i64) {
                slot.1 = rect;
            }
            continue;
        }
        picked.push((display, rect));
    }
    if picked.is_empty() {
        return Err("没有找到可记录的工作窗口（只统计普通应用窗口）".into());
    }
    // 面积大的先排（z 小者靠后铺底）
    picked.sort_by_key(|(_, r)| std::cmp::Reverse((r.w as i64) * (r.h as i64)));

    let slots: Vec<Value> = picked
        .iter()
        .enumerate()
        .map(|(i, (app, r))| {
            json!({
                "app": app,
                "rect": {
                    "x": ((r.x as i64 - work.x as i64) as f64 / work.w as f64).clamp(0.0, 1.0),
                    "y": ((r.y as i64 - work.y as i64) as f64 / work.h as f64).clamp(0.0, 1.0),
                    "w": (r.w as f64 / work.w as f64).clamp(0.05, 1.0),
                    "h": (r.h as f64 / work.h as f64).clamp(0.05, 1.0),
                },
                "z": i + 1,
            })
        })
        .collect();

    let layout_name = format!(
        "captured-{}",
        chrono::Local::now().format("%m%d-%H%M")
    );
    let description = format!("从工作环境捕获（{} 个软件）", picked.len());
    crate::scheduler::LayoutRepo::new(state.db.clone())
        .upsert(
            &layout_name,
            Some(description.as_str()),
            &Value::Array(slots),
            0,
            None,
            false,
        )
        .map_err(e2s)?;

    let input = crate::scheduler::WorkModeInput {
        name: name.clone(),
        description: Some(description),
        icon: None,
        apps: picked.iter().map(|(n, _)| n.clone()).collect(),
        open_targets: Vec::new(),
        layout: Some(layout_name.clone()),
        ai_profile: None,
        auto_apply: false,
        switch_policy: Some("additive".to_string()),
    };
    let mode = mode_repo(&state).add(&input).map_err(e2s)?;
    Ok(json!({
        "mode": mode,
        "layout": layout_name,
        "captured": picked.iter().map(|(n, _)| n.clone()).collect::<Vec<_>>(),
    }))
}

// ---------------------------------------------------------------- 阶段5：AI 助手

/// 执行一次 AI 对话（流式）。
///
/// **用 `spawn_blocking` 包装**：`ai::chat_stream` 内部是阻塞式读 sidecar 的流，
/// 直接放在 async command 里会卡住 tokio 的工作线程。Tauri 的 async command
/// 跑在 tokio 运行时上，故必须转移到阻塞线程池。
///
/// 前端不必等这个 command 返回才看到内容 —— 增量通过 `AI_STREAM_CHUNK`
/// 事件（经事件桥 → `pw://event`）实时推送；command 的返回值是"完整结果"，
/// 供非流式场景（如验收脚本）使用。
#[tauri::command]
pub async fn ai_chat(
    state: State<'_, Arc<AppState>>,
    args: crate::ai::AiChatArgs,
) -> Result<Value, String> {
    let st = state.inner().clone();
    let join = tauri::async_runtime::spawn_blocking(move || crate::ai::chat_stream(&st, args))
        .await
        .map_err(|e| format!("任务调度失败：{e}"))?;
    to_value(join.map_err(e2s)?)
}

/// 取消当前 AI 生成。
///
/// 实现方式：**断开的是前端到 core 的等待** —— 前端停止监听事件即可。
/// core 到 sidecar 的连接会因前端不再消费而继续到自然结束（sidecar 检测到
/// 写失败后停止产出，见 `service.py::_stream_line`）。
/// 这样做的原因：Rust 侧强杀进行中的 TCP 读需要引入额外状态机，
/// 而"用户点停止 → 立刻停止显示"的体验目标已由前端断连达成。
#[tauri::command]
pub fn ai_cancel(_state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    Ok(json!({ "cancelled": true }))
}

/// Provider 列表 + 凭据状态 + 模板列表（设置页与侧栏用）。
///
/// **不返回任何明文密钥**，只回掩码（红线 V1）。
#[tauri::command]
pub fn ai_info(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    crate::ai::provider_info(&state).map_err(e2s)
}

/// 写入某个 Provider 的 API Key（红线 V1：只进系统凭据库）。
#[tauri::command]
pub fn ai_set_credential(
    state: State<'_, Arc<AppState>>,
    provider: String,
    secret: String,
) -> Result<Value, String> {
    crate::ai::set_credential(&state, &provider, &secret).map_err(e2s)
}

/// 删除某个 Provider 的 API Key。
#[tauri::command]
pub fn ai_delete_credential(
    state: State<'_, Arc<AppState>>,
    provider: String,
) -> Result<Value, String> {
    crate::ai::delete_credential(&state, &provider).map_err(e2s)
}

/// 拉取模型列表（本地模型服务可能未启动 → 返回空列表，不报错）。
#[tauri::command]
pub async fn ai_list_models(
    state: State<'_, Arc<AppState>>,
    provider: String,
    api_base: Option<String>,
) -> Result<Value, String> {
    let st = state.inner().clone();
    let join = tauri::async_runtime::spawn_blocking(move || {
        crate::ai::list_models(&st, &provider, api_base.as_deref())
    })
    .await
    .map_err(|e| format!("任务调度失败：{e}"))?;
    to_value(join.map_err(e2s)?)
}

/// 权限范围查询（UI 顶部"🔓 已授权：…"提示用）。
/// 与真正装配上下文的判据同源（`scheduler::is_data_allowed`），故提示不会失真。
#[tauri::command]
pub fn ai_permission_scope(
    state: State<'_, Arc<AppState>>,
    mode: String,
    enabled_scopes: Option<std::collections::HashMap<String, bool>>,
) -> Result<Value, String> {
    to_value(crate::ai::permission_scope(
        &state,
        &mode,
        enabled_scopes.unwrap_or_default(),
    ))
}

/// 上下文预演：**不真的发请求**，只返回"本次会发送哪些上下文"。
/// 供 UI 让用户核对（08 §5 权限透明）与验收脚本断言剪裁逻辑。
#[tauri::command]
pub fn ai_preview_context(
    state: State<'_, Arc<AppState>>,
    mode: String,
    enabled_scopes: Option<std::collections::HashMap<String, bool>>,
) -> Result<Value, String> {
    Ok(crate::ai::preview_context(
        &state,
        &mode,
        &enabled_scopes.unwrap_or_default(),
    ))
}

// ---------------------------------------------------------------- 阶段6：学习成长 + 项目管理
//
// 红线 V3 的落实：**读 / 写 / AI 建议是三组分开的命令**。
// AI 建议（`learning_ai_suggest`）没有任何写库动作，建议要落地必须由用户
// 走 `learning_roadmap_confirm` / `learning_node_*` —— 这些才是写入口。

fn learning_repo(state: &AppState) -> crate::learning::LearningRepo {
    crate::learning::LearningRepo::new(state.db.clone())
}

fn project_repo(state: &AppState) -> crate::project::ProjectRepo {
    crate::project::ProjectRepo::new(state.db.clone())
}

#[tauri::command]
pub fn learning_goals_list(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(learning_repo(&state).goals_list().map_err(e2s)?)
}

#[tauri::command]
pub fn learning_goal_get(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(learning_repo(&state).goal_get(id).map_err(e2s)?)
}

#[tauri::command]
pub fn learning_goal_add(
    state: State<'_, Arc<AppState>>,
    input: crate::learning::GoalInput,
) -> Result<Value, String> {
    to_value(learning_repo(&state).goal_add(&input).map_err(e2s)?)
}

#[tauri::command]
pub fn learning_goal_update(
    state: State<'_, Arc<AppState>>,
    id: i64,
    patch: crate::learning::GoalPatch,
) -> Result<Value, String> {
    to_value(crate::learning::apply_goal_update(&state, id, &patch).map_err(e2s)?)
}

#[tauri::command]
pub fn learning_goal_delete(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    learning_repo(&state).goal_delete(id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

#[tauri::command]
pub fn learning_nodes_list(state: State<'_, Arc<AppState>>, goal_id: i64) -> Result<Value, String> {
    to_value(learning_repo(&state).nodes_list(goal_id).map_err(e2s)?)
}

/// 确认采纳一条路线（**用户动作** —— 09 §2 的最后一步）。
///
/// `replace` 为 false 且已有节点时会被拒；UI 必须在用户二次确认后
/// 才传 true（覆盖会重置已标记的进度，红线 V5）。
#[tauri::command]
pub fn learning_roadmap_confirm(
    state: State<'_, Arc<AppState>>,
    goal_id: i64,
    nodes: Vec<crate::learning::NodeInput>,
    replace: Option<bool>,
    raw: Option<String>,
) -> Result<Value, String> {
    let nodes = learning_repo(&state)
        .roadmap_confirm(goal_id, &nodes, replace.unwrap_or(false), raw.as_deref())
        .map_err(e2s)?;
    let _ = state.bus.publish(
        crate::event_bus::LEARNING_PROGRESS_UPDATED,
        json!({ "goalId": goal_id, "nodeId": Value::Null, "status": "roadmap_confirmed" }),
    );
    to_value(nodes)
}

#[tauri::command]
pub fn learning_node_add(
    state: State<'_, Arc<AppState>>,
    goal_id: i64,
    input: crate::learning::NodeInput,
) -> Result<Value, String> {
    to_value(learning_repo(&state).node_add(goal_id, &input).map_err(e2s)?)
}

/// 更新节点（**用户手动**改状态 / 改名 / 调序 / 附备注）。
#[tauri::command]
pub fn learning_node_update(
    state: State<'_, Arc<AppState>>,
    id: i64,
    patch: crate::learning::NodePatch,
) -> Result<Value, String> {
    to_value(crate::learning::apply_node_update(&state, id, &patch).map_err(e2s)?)
}

#[tauri::command]
pub fn learning_node_delete(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    let repo = learning_repo(&state);
    let goal_id = repo.node_get(id).map_err(e2s)?.map(|n| n.goal_id);
    repo.node_delete(id).map_err(e2s)?;
    if let Some(gid) = goal_id {
        let _ = state.bus.publish(
            crate::event_bus::LEARNING_PROGRESS_UPDATED,
            json!({ "goalId": gid, "nodeId": id, "status": "deleted" }),
        );
    }
    Ok(json!({ "id": id }))
}

#[tauri::command]
pub fn learning_node_move(
    state: State<'_, Arc<AppState>>,
    id: i64,
    delta: i64,
) -> Result<Value, String> {
    to_value(learning_repo(&state).node_move(id, delta).map_err(e2s)?)
}

#[tauri::command]
pub fn learning_updates_list(
    state: State<'_, Arc<AppState>>,
    goal_id: i64,
    limit: Option<i64>,
) -> Result<Value, String> {
    to_value(
        learning_repo(&state)
            .updates_list(goal_id, limit.unwrap_or(50))
            .map_err(e2s)?,
    )
}

#[tauri::command]
pub fn learning_update_add(
    state: State<'_, Arc<AppState>>,
    goal_id: i64,
    node_id: Option<i64>,
    content: String,
) -> Result<Value, String> {
    let id = learning_repo(&state)
        .update_add(goal_id, node_id, &content)
        .map_err(e2s)?;
    Ok(json!({ "id": id }))
}

/// 让 AI 产出**建议**（路线 / 优化 / 总结）。**不写任何学习数据**（红线 V3）。
///
/// 阻塞（读 sidecar 的流），故放阻塞线程池 —— 与 `ai_chat` 同理。
#[tauri::command]
pub async fn learning_ai_suggest(
    state: State<'_, Arc<AppState>>,
    goal_id: Option<i64>,
    kind: String,
    provider: String,
    model: Option<String>,
    api_base: Option<String>,
    extra: Option<String>,
) -> Result<Value, String> {
    let st = state.inner().clone();
    let join = tauri::async_runtime::spawn_blocking(move || {
        crate::learning::ai_suggest(
            &st,
            goal_id,
            &kind,
            &provider,
            model.as_deref().unwrap_or(""),
            api_base.as_deref().unwrap_or(""),
            extra.as_deref().unwrap_or(""),
        )
    })
    .await
    .map_err(|e| format!("任务调度失败：{e}"))?;
    join.map_err(e2s)
}

/// 立即执行一次提醒扫描（返回本轮命中的提醒）。
///
/// 除验收用途外也有产品价值：用户改完 `remind_after_days` 后不必等 10 分钟的
/// 后台轮询才看到效果。
#[tauri::command]
pub fn learning_check_reminders(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let hits: Vec<crate::learning::ReminderHit> =
        crate::learning::scan_reminders(&state).map_err(e2s)?;
    to_value(hits)
}

// ---- 项目管理（09 §6）----

#[tauri::command]
pub fn projects_list(
    state: State<'_, Arc<AppState>>,
    status: Option<String>,
    mode_name: Option<String>,
) -> Result<Value, String> {
    to_value(
        project_repo(&state)
            .list(status.as_deref(), mode_name.as_deref())
            .map_err(e2s)?,
    )
}

#[tauri::command]
pub fn project_get(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(project_repo(&state).get(id).map_err(e2s)?)
}

#[tauri::command]
pub fn project_add(
    state: State<'_, Arc<AppState>>,
    input: crate::project::ProjectInput,
) -> Result<Value, String> {
    to_value(crate::project::apply_add(&state, &input).map_err(e2s)?)
}

#[tauri::command]
pub fn project_update(
    state: State<'_, Arc<AppState>>,
    id: i64,
    patch: crate::project::ProjectPatch,
) -> Result<Value, String> {
    to_value(crate::project::apply_update(&state, id, &patch).map_err(e2s)?)
}

#[tauri::command]
pub fn project_delete(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    project_repo(&state).soft_delete(id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

/// 模式绑定的项目（09 §6 联动：进入模式时显示当前项目）。
#[tauri::command]
pub fn project_by_mode(
    state: State<'_, Arc<AppState>>,
    mode_name: String,
) -> Result<Value, String> {
    to_value(project_repo(&state).by_mode(&mode_name).map_err(e2s)?)
}

// ---------------------------------------------------------------- 个人档案（阶段7）

// 与 HTTP 侧逻辑同源：写路径都走 `profile::apply_*`（发 PROFILE_UPDATED），
// 读路径直连 `ProfileRepo`（只读不发事件）。

#[tauri::command]
pub fn profile_overview(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    crate::profile::overview(&state).map_err(e2s)
}

#[tauri::command]
pub fn profile_basic_get(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(crate::profile::ProfileRepo::new(state.db.clone()).basic_get().map_err(e2s)?)
}

#[tauri::command]
pub fn profile_basic_save(
    state: State<'_, Arc<AppState>>,
    input: crate::profile::BasicInput,
) -> Result<Value, String> {
    to_value(crate::profile::apply_basic_save(&state, &input).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_skills_list(
    state: State<'_, Arc<AppState>>,
    confirmed_only: Option<bool>,
) -> Result<Value, String> {
    to_value(
        crate::profile::ProfileRepo::new(state.db.clone())
            .skills_list(confirmed_only.unwrap_or(false))
            .map_err(e2s)?,
    )
}

#[tauri::command]
pub fn profile_skill_add(
    state: State<'_, Arc<AppState>>,
    input: crate::profile::SkillInput,
) -> Result<Value, String> {
    to_value(crate::profile::apply_skill_add(&state, &input).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_skill_update(
    state: State<'_, Arc<AppState>>,
    id: i64,
    patch: crate::profile::SkillPatch,
) -> Result<Value, String> {
    to_value(crate::profile::apply_skill_update(&state, id, &patch).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_skill_remove(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    crate::profile::apply_skill_remove(&state, id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

#[tauri::command]
pub fn profile_skill_confirm(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(crate::profile::apply_skill_confirm(&state, id).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_projects_list(
    state: State<'_, Arc<AppState>>,
    confirmed_only: Option<bool>,
) -> Result<Value, String> {
    to_value(
        crate::profile::ProfileRepo::new(state.db.clone())
            .projects_list(confirmed_only.unwrap_or(false))
            .map_err(e2s)?,
    )
}

#[tauri::command]
pub fn profile_project_add(
    state: State<'_, Arc<AppState>>,
    input: crate::profile::ProjectEntryInput,
) -> Result<Value, String> {
    to_value(crate::profile::apply_project_entry_add(&state, &input).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_project_remove(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    crate::profile::apply_project_entry_remove(&state, id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

#[tauri::command]
pub fn profile_project_confirm(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(crate::profile::apply_project_entry_confirm(&state, id).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_timeline_list(
    state: State<'_, Arc<AppState>>,
    confirmed_only: Option<bool>,
) -> Result<Value, String> {
    to_value(
        crate::profile::ProfileRepo::new(state.db.clone())
            .timeline_list(confirmed_only.unwrap_or(false))
            .map_err(e2s)?,
    )
}

#[tauri::command]
pub fn profile_timeline_add(
    state: State<'_, Arc<AppState>>,
    input: crate::profile::TimelineInput,
) -> Result<Value, String> {
    to_value(crate::profile::apply_timeline_add(&state, &input).map_err(e2s)?)
}

#[tauri::command]
pub fn profile_timeline_remove(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    crate::profile::apply_timeline_remove(&state, id).map_err(e2s)?;
    Ok(json!({ "id": id }))
}

#[tauri::command]
pub fn profile_timeline_confirm(state: State<'_, Arc<AppState>>, id: i64) -> Result<Value, String> {
    to_value(crate::profile::apply_timeline_confirm(&state, id).map_err(e2s)?)
}

/// 待确认建议列表（不传 status = 全部）。
#[tauri::command]
pub fn profile_suggestions_list(
    state: State<'_, Arc<AppState>>,
    status: Option<String>,
) -> Result<Value, String> {
    to_value(
        crate::profile::ProfileRepo::new(state.db.clone())
            .suggestions_list(status.as_deref())
            .map_err(e2s)?,
    )
}

/// 扫描式采集：高频软件 → 技能建议。返回新增的建议数。
#[tauri::command]
pub fn profile_suggestions_scan(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let added = crate::profile::scan_app_usage(&state).map_err(e2s)?;
    Ok(json!({ "added": added }))
}

/// 确认建议（**建议 → 档案的唯一通路**；ids 非空 = 批量确认）。
#[tauri::command]
pub fn profile_suggestions_confirm(
    state: State<'_, Arc<AppState>>,
    ids: Vec<i64>,
) -> Result<Value, String> {
    if ids.len() > 1 {
        let n = crate::profile::apply_suggestion_batch_confirm(&state, &ids).map_err(e2s)?;
        Ok(json!({ "confirmed": n }))
    } else {
        let id = *ids.first().ok_or("ids 不能为空")?;
        let sug = crate::profile::apply_suggestion_confirm(&state, id).map_err(e2s)?;
        Ok(json!({ "confirmed": 1, "suggestion": sug }))
    }
}

#[tauri::command]
pub fn profile_suggestions_ignore(
    state: State<'_, Arc<AppState>>,
    ids: Vec<i64>,
) -> Result<Value, String> {
    let mut n = 0;
    for id in &ids {
        crate::profile::apply_suggestion_ignore(&state, *id).map_err(e2s)?;
        n += 1;
    }
    Ok(json!({ "ignored": n }))
}

/// 永久拒绝某类建议（10 §5 用户权利之四）。
#[tauri::command]
pub fn profile_suggestions_reject_kind(
    state: State<'_, Arc<AppState>>,
    kind: String,
) -> Result<Value, String> {
    let n = crate::profile::apply_reject_kind(&state, &kind).map_err(e2s)?;
    Ok(json!({ "kind": kind, "ignored": n }))
}

/// 导出 Markdown（返回文本；写文件由前端触发下载，core 不碰用户文件系统）。
#[tauri::command]
pub fn profile_export_markdown(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let md = crate::profile::export_markdown(&state).map_err(e2s)?;
    Ok(json!({ "markdown": md }))
}

// ---- 阶段8：生活中心（11 §A）----

/// 今日使用时长排行（A4）。
#[tauri::command]
pub fn life_usage_today(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let repo = crate::life::repository::UsageRepo::new(state.db.clone());
    let ranking = repo.ranking(&today, 20).map_err(e2s)?;
    let total = repo.total_seconds(&today).map_err(e2s)?;
    Ok(json!({ "day": today, "totalSeconds": total, "ranking": ranking }))
}

/// 最近 7 天每日总量（A4 周趋势）。
#[tauri::command]
pub fn life_usage_week(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let rows = crate::life::repository::UsageRepo::new(state.db.clone())
        .daily_totals(7)
        .map_err(e2s)?;
    Ok(json!({ "days": rows }))
}

/// 天气（A1）。city 参数可选覆盖；默认读配置 `life.weather.city`。
#[tauri::command]
pub async fn life_weather(
    state: State<'_, Arc<AppState>>,
    city: Option<String>,
) -> Result<Value, String> {
    crate::life::weather(&state, city.as_deref())
        .await
        .map_err(e2s)
}

/// 当前媒体会话（A2 SMTC）。
#[tauri::command]
pub async fn life_media_now(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    crate::life::media_now(&state).await.map_err(e2s)
}

/// 媒体控制（A2 可选）。action ∈ play|pause|next|previous。
#[tauri::command]
pub async fn life_media_control(
    state: State<'_, Arc<AppState>>,
    action: String,
) -> Result<Value, String> {
    crate::life::media_control(&state, &action).await.map_err(e2s)
}

/// 社交概览（A3，只含未读数与来源摘要）。
#[tauri::command]
pub async fn life_social_overview(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    crate::life::social_overview(&state).await.map_err(e2s)
}

/// 社交服务配置读取。
#[tauri::command]
pub fn life_social_config_get(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    crate::life::social_config(&state).map_err(e2s)
}

/// 社交服务配置保存（用户显式添加；绝不存聊天内容）。
#[tauri::command]
pub fn life_social_config_put(
    state: State<'_, Arc<AppState>>,
    services: Value,
) -> Result<Value, String> {
    crate::life::social_config_put(&state, &services).map_err(e2s)
}

// ---- 阶段8：设备中心（11 §B）----

/// 当前指标 + 最近 5 分钟历史（B2，环形缓冲不落库）。
#[tauri::command]
pub fn device_metrics(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    Ok(crate::device::metrics_snapshot(&state))
}

/// 系统进程列表（B3，CPU% 为跨请求差分）。
#[tauri::command]
pub fn device_processes(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(crate::device::process_list(&state))
}

/// 结束进程（B3）。**confirm 必须 = true**（红线 V5 双保险）。
#[tauri::command]
pub fn device_process_kill(
    state: State<'_, Arc<AppState>>,
    pid: u32,
    confirm: bool,
) -> Result<Value, String> {
    crate::device::kill_process(&state, pid, confirm).map_err(e2s)?;
    Ok(json!({ "killed": pid }))
}

/// 模式健康度（B4 轻实现：启动次数 + 今日使用秒数）。
#[tauri::command]
pub fn device_mode_health(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(crate::device::mode_health(&state))
}

// ---- 阶段9：插件系统（12 §A）----

/// 已安装插件列表（含启用状态与 manifest 公开字段）。
#[tauri::command]
pub fn plugins_list(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let rows = crate::plugins::list(&state).map_err(e2s)?;
    to_value(rows)
}

/// 扫描插件目录发现未安装的插件（只读，不写库）。
#[tauri::command]
pub fn plugins_discover(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let root = crate::plugins::plugins_root(&state);
    to_value(crate::plugins::discover(&root))
}

/// 安装（从目录）。校验 manifest + 复制 + 注册 + 按 manifest 授权 + 审计。
#[tauri::command]
pub fn plugins_install(
    state: State<'_, Arc<AppState>>,
    source_dir: String,
) -> Result<Value, String> {
    let v = crate::plugins::install(&state, std::path::Path::new(&source_dir)).map_err(e2s)?;
    to_value(v)
}

/// 从 zip 导入：sidecar 安全解包 → core 安装 → 清理临时目录。
/// 安装/授权的信任边界始终在 core；sidecar 只做解包这一通用文件 IO。
#[tauri::command]
pub async fn plugins_import_zip(
    state: State<'_, Arc<AppState>>,
    zip_path: String,
) -> Result<Value, String> {
    let data_dir = state.data_dir.to_string_lossy().to_string();
    let extracted = crate::sidecar::call(
        state.inner(),
        "/plugin/import",
        json!({ "zipPath": zip_path, "dataDir": data_dir }),
    )
    .await
    .map_err(e2s)?;
    let dir = extracted
        .get("dir")
        .and_then(Value::as_str)
        .ok_or("sidecar 返回缺少 dir")?
        .to_string();
    let temp_root = extracted
        .get("tempRoot")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    let installed =
        crate::plugins::install(&state, std::path::Path::new(&dir)).map_err(e2s)?;
    // 临时目录清不清不影响正确性，失败静默（下次启动可被 tmp 清理覆盖）。
    let _ = std::fs::remove_dir_all(&temp_root);
    to_value(installed)
}

/// 启用/禁用。启用发布 PLUGIN_LOADED。
#[tauri::command]
pub fn plugins_set_enabled(
    state: State<'_, Arc<AppState>>,
    plugin_id: String,
    enabled: bool,
) -> Result<Value, String> {
    let v = crate::plugins::set_enabled(&state, &plugin_id, enabled).map_err(e2s)?;
    to_value(v)
}

/// 卸载（物理删除插件目录；plugin_audit 保留 —— 审计不可篡改）。
#[tauri::command]
pub fn plugins_uninstall(state: State<'_, Arc<AppState>>, plugin_id: String) -> Result<Value, String> {
    let v = crate::plugins::uninstall(&state, &plugin_id).map_err(e2s)?;
    to_value(v)
}

/// 插件能力网关（唯一入口）。越权返回 `PERMISSION_DENIED: <permission>` 并发事件。
#[tauri::command]
pub async fn plugin_api(
    state: State<'_, Arc<AppState>>,
    plugin_id: String,
    api: String,
    method: String,
    payload: Value,
) -> Result<Value, String> {
    crate::plugins::api_call(state.inner(), &plugin_id, &api, &method, &payload)
        .await
        .map_err(e2s)
}

/// 插件宿主上报崩溃（发布 PLUGIN_ERROR + 审计；主程序不受影响）。
#[tauri::command]
pub fn plugin_crash(
    state: State<'_, Arc<AppState>>,
    plugin_id: String,
    reason: String,
) -> Result<Value, String> {
    to_value(crate::plugins::report_crash(&state, &plugin_id, &reason))
}

/// 插件审计流水（最近 limit 条；卸载后仍可查）。
#[tauri::command]
pub fn plugin_audit_list(
    state: State<'_, Arc<AppState>>,
    plugin_id: String,
    limit: Option<i64>,
) -> Result<Value, String> {
    let repo = crate::plugins::PluginRepo::new(state.db.clone());
    let rows = repo.audit_list(&plugin_id, limit.unwrap_or(50)).map_err(e2s)?;
    to_value(rows)
}

// ---- 阶段9：外部 Agent（12 §C）----

/// 外部 Agent 注册清单（config `agents.external`，默认空 = 无任何外部 Agent）。
#[tauri::command]
pub fn agents_list(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let rows = crate::agents::list(&state).map_err(e2s)?;
    to_value(rows)
}

/// 全量替换注册清单（逐个校验 + name 唯一）。
#[tauri::command]
pub fn agents_save(state: State<'_, Arc<AppState>>, specs: Value) -> Result<Value, String> {
    let v = crate::agents::save(&state, &specs).map_err(e2s)?;
    to_value(v)
}

/// 健康检查（core → Agent，GET {url}{healthCheck}）。
#[tauri::command]
pub async fn agent_health(state: State<'_, Arc<AppState>>, name: String) -> Result<Value, String> {
    let state = state.inner().clone();
    crate::agents::health(&state, &name).await.map_err(e2s)
}

/// 调用外部 Agent（POST {url}/invoke）。
#[tauri::command]
pub async fn agent_invoke(
    state: State<'_, Arc<AppState>>,
    name: String,
    action: String,
    payload: Value,
) -> Result<Value, String> {
    let state = state.inner().clone();
    crate::agents::invoke(&state, &name, &action, &payload)
        .await
        .map_err(e2s)
}

// ---- 阶段9：桌面小组件（12 §B）----

/// 开/关小组件窗口（幂等语义：按当前开闭状态翻转）。
#[tauri::command]
pub fn desktop_widget_toggle(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    let open = state
        .app
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .as_ref()
        .and_then(|app| app.get_webview_window(crate::desktop_widget::WIDGET_LABEL))
        .is_some();
    let result = if open {
        crate::desktop_widget::close(&state)
    } else {
        crate::desktop_widget::open(&state)
    };
    result.map_err(e2s)
}

#[tauri::command]
pub fn desktop_widget_status(state: State<'_, Arc<AppState>>) -> Result<Value, String> {
    to_value(crate::desktop_widget::status(&state))
}

#[tauri::command]
pub fn desktop_widget_save_bounds(
    state: State<'_, Arc<AppState>>,
    x: f64,
    y: f64,
    w: f64,
    h: f64,
) -> Result<Value, String> {
    let v = crate::desktop_widget::save_bounds(&state, x, y, w, h).map_err(e2s)?;
    to_value(v)
}

#[tauri::command]
pub fn desktop_widget_set_always_on_top(
    state: State<'_, Arc<AppState>>,
    on: bool,
) -> Result<Value, String> {
    let v = crate::desktop_widget::set_always_on_top(&state, on).map_err(e2s)?;
    to_value(v)
}

// ---------------------------------------------------------------- helpers

fn e2s<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

fn to_value<T: serde::Serialize>(v: T) -> Result<Value, String> {
    serde_json::to_value(v).map_err(e2s)
}
