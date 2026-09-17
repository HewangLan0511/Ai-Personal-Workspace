# system/ —— Python sidecar（系统调用 / AI / 数据处理）

> ADR-001 定稿后，本目录**不做窗口与进程控制**（归 Rust core）。
> 保留能力：媒体会话（SMTC）、性能计数、AI Provider 调用、已安装软件扫描（阶段2 起）。

- `service.py`：sidecar HTTP 服务入口（stdlib-only，随机端口，`--announce` 上报端口）
- `win/`：Windows 专用实现（阶段5/8 填充 media.py / perf.py）
- `requirements.txt`：**保持为空**。阶段5 引入 AI SDK 前先评估是否真的需要第三方依赖。

## 契约

`docs/agent-dev/03-数据契约与接口规范.md` §3.4：
sidecar 暴露 `/health`、`/sys/media/current`、`/sys/perf/metrics`、`/ai/chat`。
`/sys/process/*` 与 `/sys/window/*` 返回 410 `moved_to_core`（ADR-001）。

## 本地验证

```bash
python system/service.py --announce
# stdout: {"event": "sidecar_ready", "port": 5xxxx}
# 另开终端：GET http://127.0.0.1:<port>/health → {"ok":true,"data":{...}}
```

## 打包（04 §5 · PyInstaller 单文件）

```bash
python -m pip install pyinstaller        # 构建期依赖，不进 runtime
python system/build_sidecar.py           # 产出 core/binaries/service-<triple>.exe
python system/build_sidecar.py --check   # 只检查产物是否就绪
python system/build_sidecar.py --if-needed  # 产物不比源码旧则跳过（beforeBuildCommand 用）
```

- 产物名带**目标三元组**（如 `service-x86_64-pc-windows-msvc.exe`），与
  `core/tauri.conf.json` 的 `bundle.externalBin: ["binaries/service"]` 约定一致。
- `npm run tauri build` 的 `beforeBuildCommand` 已串上 `--if-needed`，
  **打包前会自动构建 sidecar**；产物已是最新则跳过（不重复烧 PyInstaller）。
- PyInstaller 装在 venv 里时，用 `PW_PYTHON` 指定该解释器：
  `PW_PYTHON=/path/to/venv/python python system/build_sidecar.py`
- ⚠️ `bundle.externalBin` 是 **tauri-build 的编译期校验资源**：产物缺失时
  连 `cargo check` 都会报 `resource path binaries\service-<triple>.exe doesn't exist`。
  门禁已加静态检查 **B120/B121**（编译前发现，不必烧一次完整编译）。
- core 侧启动顺序：**打包态优先**找主程序同目录的 `service.exe`，找不到才回退开发态
  `python ../system/service.py`（见 `core/src/sidecar/mod.rs::resolve_launcher`）。
- ⚠️ 打包**不能加 `--noconsole`**：core 靠读 sidecar 的 stdout 首行拿随机端口。

## 红线（ADR-001 合规检查点）

- 本目录出现 `win32gui` / `win32process` / `win32api` **或任何进程启动实现
  （`subprocess.Popen` / `os.startfile` / `os.system`）** → 架构违规
  （注：原检查点只点名 `win32*`，`subprocess` 曾借此漏过，REVIEW-002 R-03；已收窄）
- 本目录直连 SQLite（`sqlite3`）→ 违反单一写入者，数据走 core 的 `/internal/db/*`
