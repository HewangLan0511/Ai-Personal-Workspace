//! 全局状态：模式状态、运行中应用、共享服务的唯一容器。
//!
//! 设计约束（02-架构与目录规范 §2.3）：core 不含业务语义，
//! 这里只持有"事实"（什么东西在运行、哪个模式激活），不解释它们的意义。

use std::path::PathBuf;
use std::sync::Mutex;

use crate::db::Db;
use crate::db::ConfigService;
use crate::event_bus::EventBus;

/// Python sidecar 的动态端口（启动后由 sidecar 上报，写入 config 表供各端读取）。
pub struct SidecarState {
    pub port: Mutex<Option<u16>>,
    pub healthy: Mutex<bool>,
}

pub struct AppState {
    pub db: Db,
    pub config: ConfigService,
    pub bus: EventBus,
    pub sidecar: SidecarState,
}

impl AppState {
    /// 初始化数据库、事件总线与配置服务；首次启动自动建库 + migration + 种子数据。
    pub fn initialize() -> anyhow::Result<Self> {
        let data_dir = Self::resolve_data_dir()?;
        std::fs::create_dir_all(&data_dir)?;

        let db = Db::open(&data_dir.join("workspace.db"))?;
        db.initialize()?; // 首次启动：migration + 默认配置种子（契约 3.1 / 3.5）
        let bus = EventBus::new(256);
        let config = ConfigService::new(db.clone(), bus.clone());

        let state = Self {
            db,
            config,
            bus,
            sidecar: SidecarState {
                port: Mutex::new(None),
                healthy: Mutex::new(false),
            },
        };
        Ok(state)
    }

    /// 数据目录：`%APPDATA%/PersonalWorkspace`（不硬编码用户路径）。
    /// 优先级：环境变量 `PW_DATA_DIR` > `dirs::data_dir` > 当前目录下 `pw-data`。
    fn resolve_data_dir() -> anyhow::Result<PathBuf> {
        if let Some(dir) = std::env::var_os("PW_DATA_DIR") {
            return Ok(PathBuf::from(dir));
        }
        match dirs::data_dir() {
            Some(base) => Ok(base.join("PersonalWorkspace")),
            None => Ok(std::env::current_dir()?.join("pw-data")),
        }
    }
}
