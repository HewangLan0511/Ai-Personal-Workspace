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
/// 顺序：打包态二进制优先（安装包里没有 python 脚本）→ 开发态脚本兜底。
fn resolve_launcher() -> Option<Launcher> {
    // 1) 打包态：主程序同目录下的 service.exe / service
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let names: &[&str] = if cfg!(windows) {
                &["service.exe", "service"]
            } else {
                &["service", "service.exe"]
            };
            for name in names {
                let cand = dir.join(name);
                if cand.exists() {
                    return Some(Launcher::Bundled(cand));
                }
            }
        }
    }
    // 2) 开发态：仓库内脚本（相对 core/ 上溯一级）
    for rel in ["../system/service.py", SIDECAR_SCRIPT] {
        let p = std::path::Path::new(rel);
        if p.exists() {
            return Some(Launcher::Dev(python_bin(), p.to_path_buf()));
        }
    }
    None
}

pub fn spawn_and_watch(state: Arc<AppState>) {
    std::thread::spawn(move || loop {
        match run_once(&state) {
            Ok(port) => {
                if let Some(p) = port {
                    if let Ok(mut guard) = state.sidecar.port.lock() {
                        *guard = Some(p);
                    }
                    let _ = state.config.set("runtime.sidecar_port", Value::from(p));
                }
            }
            Err(e) => {
                tracing::warn!(error = %e, "sidecar 启动失败（主界面保持可用，降级模式）");
            }
        }
        if let Ok(mut guard) = state.sidecar.healthy.lock() {
            *guard = false;
        }
        // 崩溃自动重启（ADR-001 选 A 后此项为加固项而非硬依赖）。
        std::thread::sleep(Duration::from_secs(2));
    });
}

/// 拉起一次 sidecar 并阻塞等待其退出（返回解析到的端口）。
fn run_once(state: &Arc<AppState>) -> anyhow::Result<Option<u16>> {
    let launcher = resolve_launcher().ok_or_else(|| {
        anyhow::anyhow!("找不到 sidecar：既无打包二进制，也无 {SIDECAR_SCRIPT}")
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
