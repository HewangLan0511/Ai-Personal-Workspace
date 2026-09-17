//! Python sidecar 监管：拉起、解析端口、健康检查、崩溃自动重启。
//!
//! ADR-001 定稿后，sidecar 只承载媒体 / 性能 / AI（窗口与进程控制在 Rust core）。
//! 04 §5：随机端口（sidecar 绑定 0 号端口后把实际端口打到 stdout 首行 JSON，
//! core 解析并写入 config 表）；启动失败不影响主界面（降级模式）。

use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;

use crate::state::AppState;

const SIDECAR_SCRIPT: &str = "system/service.py";
const HEALTH_TIMEOUT_SECS: u64 = 10;

/// Python 解释器：优先环境变量 PW_PYTHON，缺省用 PATH 上的 python。
fn python_bin() -> std::ffi::OsString {
    std::env::var_os("PW_PYTHON").unwrap_or_else(|| std::ffi::OsString::from("python"))
}

/// sidecar 启动方式：打包态跑单文件二进制，开发态跑 Python 脚本。
enum Launcher {
    /// 打包后：Tauri `bundle.externalBin` 会把 sidecar 放到**主程序同目录**。
    Bundled(std::path::PathBuf),
    /// 开发态：解释器 + 仓库内脚本。
    Dev(std::ffi::OsString, std::path::PathBuf),
}

/// 解析 sidecar 启动方式（04 §5 + REVIEW-003 L-015）。
///
/// 顺序：开发态源码优先（见下）→ 打包态二进制兜底。
/// 失败时返回**全部尝试过的候选路径**——降级模式的警告必须能自诊
/// （2026-09-13 实测：单拷 core.exe 到桌面运行，两路全空，警告却只有一句话，
/// 排查要靠读源码；路径列表让"为什么找不到"一眼可见）。
///
/// **为什么开发态优先，而不是"打包态优先"**（阶段5 踩到的坑，L-043）：
/// 原实现按 `current_exe()` 的**同目录**找 `service.exe`，本意是"安装态"。
/// 但 `cargo build --release` 的输出目录 `core/target/release/` 里同样躺着
/// 一个 `service.exe`（PyInstaller 打的**快照**），于是**开发态跑 release 时被
/// 误判成安装态**，拉起几小时前的旧二进制：
///   改了 Python 代码 → 跑验收 → 测的是旧代码 → 接口 404
///   → 看上去像"路由没写"，实际是"跑的根本不是这份源码"。
///
/// **为什么路径锚在 exe 而不是 cwd**（第二个坑，同一个 L-043）：
/// 原实现用 `../system/service.py` 这种 **cwd 相对**路径。而 core 可能从
/// 仓库根、`core/`、任意目录被拉起 —— 路径能不能解析**取决于调用者的 cwd**，
/// 于是同一个二进制时好时坏（从仓库根跑就找不到 `../system/`）。
/// 改为以 `current_exe()` 所在目录为锚，向上找 `system/service.py`：
/// 无论从哪儿启动，解析结果都一致。
///
/// **`PW_SIDECAR_FORCE_DEV=1`**：无条件强制走源码，连仓库探测都跳过。
/// 验收脚本用它把 sidecar 钉死在当前源码上（防止任何环境差异导致测到旧码）。
///
/// **单拷主 exe 无法工作**（2026-09-13 用户实测）：前端资源嵌在 exe 里、
/// sidecar 是外部文件 —— 把 core.exe 单独拷走，sidecar 必然两路全空。
/// 绿色分发必须 `personal-workspace-core.exe` 与 `service.exe` 同目录成对出现。
fn resolve_launcher() -> Result<Launcher, Vec<String>> {
    let force_dev = std::env::var("PW_SIDECAR_FORCE_DEV")
        .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    // exe 所在目录：开发态是 `core/target/release`，安装态是安装目录。
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(|d| d.to_path_buf()));

    // 候选脚本位置：按"从 exe 目录向上逐级找仓库根"的方式枚举。
    // 覆盖两种开发布局：cwd/exe 在 `core/` 或其下一级的 target/<profile>/。
    let mut tried: Vec<String> = Vec::new();
    let mut script_candidates: Vec<std::path::PathBuf> = Vec::new();
    if let Some(dir) = &exe_dir {
        for up in 0..5 {
            let mut base = dir.clone();
            for _ in 0..up {
                base = match base.parent() {
                    Some(p) => p.to_path_buf(),
                    None => break,
                };
            }
            script_candidates.push(base.join("system").join("service.py"));
        }
    }
    // 兜底：cwd 相对（保留旧行为，兼容从仓库根直接跑的场景）
    script_candidates.push(std::path::PathBuf::from("../system/service.py"));
    script_candidates.push(std::path::PathBuf::from(SIDECAR_SCRIPT));

    // 1) 开发态：仓库内脚本存在就优先跑源码。
    //    判据是"仓库脚本是否存在"，而不是"我们觉得自己在什么模式" ——
    //    避免 `core/target/release/` 里那个同名 service.exe 把开发态骗成安装态。
    //
    //    ⚠️ `force_dev` 必须在这里**真的 return**：早期版本只在 else 分支打了一条
    //    日志就继续往下走，于是 `PW_SIDECAR_FORCE_DEV=1` 完全无效、照样拉起打包
    //    二进制 —— 又一次"跑的不是这份源码"（与 L-044 同源，只是换了个位置）。
    //    开关的意义就是"不许静默降级"，所以下面找不到脚本时直接失败。
    for p in &script_candidates {
        tried.push(p.display().to_string());
        if p.exists() {
            if force_dev {
                tracing::info!(script = %p.display(), "PW_SIDECAR_FORCE_DEV=1：强制走开发态源码");
            } else {
                tracing::info!(script = %p.display(), "sidecar 走开发态源码（仓库内存在脚本）");
            }
            return Ok(Launcher::Dev(python_bin(), p.clone()));
        }
    }
    if force_dev {
        // 强制开发态却找不到脚本 = 环境配置错误。**不退回打包二进制** ——
        // 那会让"我明明设了开关"与"跑的却是旧二进制"同时成立，排查成本极高。
        tracing::error!("PW_SIDECAR_FORCE_DEV=1 但未找到 {SIDECAR_SCRIPT}，拒绝退回打包二进制");
        return Err(tried);
    }

    // 2) 打包态：仓库脚本不存在（真安装包里没有 .py）才退回同目录二进制。
    if let Some(dir) = &exe_dir {
        let names: &[&str] = if cfg!(windows) {
            &["service.exe", "service"]
        } else {
            &["service", "service.exe"]
        };
        for name in names {
            let cand = dir.join(name);
            tried.push(cand.display().to_string());
            if cand.exists() {
                tracing::info!(path = %cand.display(), "sidecar 走打包态二进制");
                return Ok(Launcher::Bundled(cand));
            }
        }
    }
    Err(tried)
}

pub fn spawn_and_watch(state: Arc<AppState>) {
    std::thread::spawn(move || loop {
        if let Err(e) = run_once(&state) {
            tracing::warn!(error = %e, "sidecar 启动失败（主界面保持可用，降级模式）");
        }
        if let Ok(mut guard) = state.sidecar.healthy.lock() {
            *guard = false;
        }
        // 崩溃自动重启（ADR-001 选 A 后此项为加固项而非硬依赖）。
        std::thread::sleep(Duration::from_secs(2));
    });
}

/// 发布 sidecar 端口：写共享状态 **并**落 `config(runtime.sidecar_port)`。
///
/// 修复（REVIEW-005 · 04 验收项 5）：原实现把发布放在 `run_once` **返回之后**，
/// 而 `run_once` 内部的 `child.wait()` 会阻塞到 sidecar 退出 ——
/// 于是端口只在 sidecar 死掉时才被写入，运行期恒为 `null`，
/// 04 §5「随机端口写入 config 供双方读取」**从未成立**。
/// 发布必须发生在"读到 announce 端口"的那一刻，不能晚于 `wait()`。
fn publish_port(state: &Arc<AppState>, port: u16) {
    if let Ok(mut guard) = state.sidecar.port.lock() {
        *guard = Some(port);
    }
    if let Err(e) = state.config.set("runtime.sidecar_port", Value::from(port)) {
        tracing::warn!(error = %e, "写入 sidecar 端口失败");
    }
}

/// 拉起一次 sidecar 并阻塞等待其退出（返回解析到的端口）。
fn run_once(state: &Arc<AppState>) -> anyhow::Result<Option<u16>> {
    let launcher = resolve_launcher().map_err(|tried| {
        anyhow::anyhow!(
            "找不到 sidecar：既无打包二进制，也无源码脚本（主 exe 被单独拷出仓库/安装目录时必然如此，\
             请成对分发 core.exe + service.exe 或使用安装包）。已尝试：{}",
            tried.join(" ；")
        )
    })?;

    let mut cmd = match &launcher {
        Launcher::Bundled(path) => {
            tracing::info!(path = %path.display(), "以打包二进制方式启动 sidecar");
            std::process::Command::new(path)
        }
        Launcher::Dev(python, script) => {
            tracing::info!(script = %script.display(), "以开发脚本方式启动 sidecar");
            let mut c = std::process::Command::new(python);
            c.arg(script);
            c
        }
    };

    let mut child = cmd
        .arg("--announce")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::null())
        .spawn()?;

    let port = read_announced_port(&mut child);
    if let Some(p) = port {
        publish_port(state, p); // ★ 立即发布 —— 不能等下面那个 child.wait()
        let healthy = wait_health(p, HEALTH_TIMEOUT_SECS);
        if let Ok(mut guard) = state.sidecar.healthy.lock() {
            *guard = healthy;
        }
        tracing::info!(port = p, healthy, "sidecar 已就绪");
    }
    let _ = child.wait(); // 阻塞到 sidecar 退出，随后外层循环重启
    Ok(port)
}

/// 读取 stdout 首行 announce JSON：{"event":"sidecar_ready","port":N}
fn read_announced_port(child: &mut std::process::Child) -> Option<u16> {
    use std::io::BufRead;
    let stdout = child.stdout.take()?;
    let reader = std::io::BufReader::new(stdout);
    for line in reader.lines() {
        let line = line.ok()?;
        if let Ok(v) = serde_json::from_str::<Value>(&line) {
            if v.get("event").and_then(Value::as_str) == Some("sidecar_ready") {
                return v.get("port").and_then(Value::as_u64).map(|p| p as u16);
            }
        }
    }
    None
}

fn wait_health(port: u16, timeout_secs: u64) -> bool {
    let deadline = std::time::Instant::now() + Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if health_probe(port) {
            return true;
        }
        std::thread::sleep(Duration::from_millis(500));
    }
    false
}

fn health_probe(port: u16) -> bool {
    std::net::TcpStream::connect(("127.0.0.1", port)).is_ok()
}

/// 调用 sidecar 的 HTTP 接口（core → sidecar，内部使用）。
///
/// **为什么不引 `reqwest`/`hyper`**：项目禁止事项要求「不要引入需要联网才能运行的依赖」，
/// 而这里只需一个本机回环、固定 JSON 协议的 POST —— 手写 HTTP/1.1 足够，零新依赖。
///
/// 阶段2 用途：`/apps/scan`（注册表扫描）、`/apps/probe`（图标与名称自动补全）。
pub async fn call(state: &Arc<AppState>, path: &str, body: Value) -> anyhow::Result<Value> {
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    let port = state
        .sidecar
        .port
        .lock()
        .ok()
        .and_then(|g| *g)
        .ok_or_else(|| anyhow::anyhow!("sidecar 尚未就绪（端口未知），请稍后重试"))?;

    let addr = format!("127.0.0.1:{port}");
    let mut stream = tokio::net::TcpStream::connect(&addr)
        .await
        .map_err(|e| anyhow::anyhow!("连接 sidecar 失败（{addr}）：{e}"))?;

    let payload = serde_json::to_string(&body)?;
    let req = format!(
        "POST {path} HTTP/1.1\r\nHost: {addr}\r\nContent-Type: application/json\r\n\
         Content-Length: {}\r\nConnection: close\r\n\r\n{payload}",
        payload.len()
    );
    stream.write_all(req.as_bytes()).await?;
    stream.flush().await?;

    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).await?;
    let text = String::from_utf8_lossy(&buf);
    // 跳过状态行与响应头，只取 body（Connection: close ⇒ 读到底即为 body）
    let body_text = text.split("\r\n\r\n").nth(1).unwrap_or("").trim();
    let value: Value = serde_json::from_str(body_text)
        .map_err(|e| anyhow::anyhow!("sidecar 返回非 JSON：{e}"))?;

    if value.get("ok").and_then(Value::as_bool) != Some(true) {
        let msg = value
            .pointer("/error/message")
            .and_then(Value::as_str)
            .unwrap_or("sidecar 调用失败");
        anyhow::bail!("{msg}");
    }
    Ok(value.get("data").cloned().unwrap_or(Value::Null))
}
