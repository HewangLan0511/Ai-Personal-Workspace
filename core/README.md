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

## 运行（前置：Rust 工具链 + Node）

**推荐入口**（在仓库根执行，已封装 Tauri CLI 的工作目录切换）：

```bash
npm --prefix ui install                      # 前端依赖（含 @tauri-apps/cli）
python system/build_sidecar.py               # 先出 sidecar 产物，见下方说明
npm --prefix ui run tauri dev                # 开发态运行
npm --prefix ui run tauri build              # 产出安装包（验收项 7）
```

> ⚠️ **为什么必须先出 sidecar**：`core/tauri.conf.json` 的 `bundle.externalBin`
> 是 **tauri-build 在编译期校验**的资源。产物缺失时连 `cargo check` 都会失败：
> `resource path binaries\service-<triple>.exe doesn't exist`。
> `pyinstaller` 属构建期依赖，可用 `PW_PYTHON` 指向已装它的解释器。
> 门禁已为此加静态检查 **B120/B121**（编译前即可发现，不必烧一次完整编译）。

等价的底层命令（Tauri CLI 的 app 目录即本目录）：

```bash
cd ui && npm install
cd ../core && cargo check                    # 门禁 B100
cd ../core && cargo test                     # 4 条单元测试
```

sidecar 的 Python 解释器可用环境变量 `PW_PYTHON` 指定（默认 PATH 上的 `python`）。
数据目录默认 `%APPDATA%/PersonalWorkspace`，可用 `PW_DATA_DIR` 覆盖（不硬编码用户路径）。

## 验收步骤（阶段1）

1. `npm --prefix ui run build` → 前端构建通过
2. `python system/build_sidecar.py` → 产出 `core/binaries/service-<triple>.exe`
3. `python tools/verify_stage1.py` → 自动核验启动 / 启动耗时 / 建库 / sidecar / 持久化
4. `npm --prefix ui run tauri dev` → 窗口出现（1280×800），Dashboard 渲染
5. 左侧导航切换无白屏；`/plugins` 为占位页（本项需人工点，脚本不覆盖）
6. 首次启动自动建库：`%APPDATA%/PersonalWorkspace/workspace.db` 存在且 `config` 表有默认行

## 验收步骤（阶段2 · 软件管理）

```bash
# 1. 构建（sidecar 需单独打包，PyInstaller）
python system/build_sidecar.py                 # 产出 core/binaries/service-<triple>.exe
cd core && cargo build --release
cd ..

# 2. 端到端验收（05 的 8 项验收标准 + 2 项强化检查，全自动）
python tools/verify_stage2.py

# 3. 门禁
python tools/gate.py --stage 2 --build
```

覆盖：添加 / 启动（**pid 用 `tasklist` 复核**，不信 core 的返回值）/ 失败提示 / 状态同步 /
分类搜索 / 排序（含置顶）/ 注册表扫描 / 重启持久化，外加图标接口的**目录穿越防护**与
自动补全（`FileDescription` → `name`、内嵌图标 → PNG 缓存）。

> ⚠️ **改了 `system/` 下的 sidecar 代码后必须重新打包**并把产物同步到
> `core/target/release/service.exe`，否则 core 仍会启动**旧的**打包二进制。
> 阶段2 首次验收就栽在这里（`/apps/scan` 报"未知路径"，实为旧 exe）。

## 已知限制

- 阶段2~4 模块为接口占位（`anyhow::bail!("阶段N 实现…")`），不含业务逻辑；
  `cargo check` 会报约 30 条 `dead_code` 警告，来源即这些尚未接线的占位项与事件常量。
- 打包产物（`binaries/`、`target/`、`dist/`）均不入库（红线 V8）。
