# core/ —— Personal Workspace 核心（Rust · Tauri 宿主）

> 桌面壳 + 调度核心。SQLite 的**唯一写入者**（单一写入者原则，02 §2.4）。

## 架构

```
┌─────────────────────────── core (Rust, 常驻) ───────────────────────────┐
│  main.rs（仅装配）                                                       │
│    ├─ state/        全局状态：Db / EventBus / ConfigService / sidecar   │
│    ├─ db/           SQLite 访问层 + migrations + ConfigService          │
│    ├─ event_bus/    事件总线（契约 3.3；事件名常量在 events.rs）          │
│    ├─ api/          本地 HTTP（/api/v1 给 UI；/internal 给 sidecar）     │
│    ├─ sidecar/      Python sidecar 监管（拉起/健康检查/自动重启）        │
│    ├─ app_manager/  软件注册与启动（阶段2；ADR-001 = Rust）              │
│    ├─ window_manager/ 窗口控制（阶段3；ADR-001 = Rust）                  │
│    └─ scheduler/    工作模式状态机（阶段4 ★核心）                        │
└──────────────────────────────────────────────────────────────────────────┘
        │ HTTP 127.0.0.1:随机端口（写入 config: runtime.http_port）
        ▼
   ui/ (Vue3)          system/ (Python sidecar：媒体/性能/AI)
```

## 关键决策

- **ADR-001（已定稿）**：窗口控制与进程启动用 **Rust**（`windows` crate），Python sidecar 不做窗口/进程操作。
  决策记录：`docs/adr/ADR-001-窗口控制与进程启动实现语言.md`
- **目录树增量说明**：02 §2.2 强制树之外的 `src/api/`、`src/sidecar/` 为架构师裁量新增（HTTP 接口面与 sidecar 监管需要独立模块），在此登记。
- **devtools**：Tauri 2 在 release 构建默认禁用 devtools（未启用 devtools feature），满足 04 §1 要求。

## 运行（前置：Rust 工具链）

```bash
# ⚠️ 2026-09-12 实测：本机未安装 cargo/rustc，以下命令待工具链就绪后执行
# 需要：rustup (MSVC toolchain) + WebView2 Runtime

cd ui && npm install          # 前端依赖
cd ../core && cargo check     # 编译检查（补验项）
cargo tauri dev               # 开发态运行
cargo tauri build             # 产出安装包（验收项 7）
```

sidecar 的 Python 解释器可用环境变量 `PW_PYTHON` 指定（默认 PATH 上的 `python`）。
数据目录默认 `%APPDATA%/PersonalWorkspace`，可用 `PW_DATA_DIR` 覆盖（不硬编码用户路径）。

## 验收步骤（阶段1）

1. `npm --prefix ../ui run build` → 前端构建通过
2. `python ../system/service.py --announce` → stdout 首行输出 `{"event":"sidecar_ready","port":N}`，`GET /health` 返回 200
3. `cargo tauri dev` → 窗口出现（1280×800），Dashboard 渲染
4. 左侧 7 个导航项切换无白屏；`/plugins` 为占位页
5. 改主题 → 重启 → 主题保持（持久化走 config 表）
6. 首次启动自动建库：`%APPDATA%/PersonalWorkspace/workspace.db` 存在且 `config` 表有默认行

## 已知限制

- 本机无 Rust 工具链：`cargo check` / `tauri dev` / `tauri build` 未在本阶段执行（登记遗留，装好工具链后补验）。
- 阶段2~4 模块为接口占位（`anyhow::bail!("阶段N 实现…")`），不含业务逻辑。
