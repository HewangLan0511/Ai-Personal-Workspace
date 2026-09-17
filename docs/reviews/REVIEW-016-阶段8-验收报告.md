# REVIEW-016 · 阶段8（生活中心与设备中心）验收报告

> 日期：2026-09-13 · 审核人：监制（肉编器001号）

## §〇 独立性声明

**本报告 = 自审 + 机器门禁，不具独立审核效力**（角色合并状态，M-5 裁决下的效力等级）。
判定依据全部来自本轮**独立重跑**的机器证据（未引用交付方数字）与**强制调用点检索**。
如需独立效力，白宇可下口令「申请独立复核阶段 8」。

**基线漂移检查**：审核开始前扫描 core/src、ui/src、system、tools、modules、database、core/migrations
全部源码的 mtime —— 自最后一次已验证的 release 构建（2026-09-13 15:36）与 sidecar 发行产物（15:30）后**零漂移**，审核基线有效。

---

## §一 判定：✅ 通过（按白宇 2026-09-12 22:35 验收唯一标准）

### ① 目标达成 ✅

11 定位一句话「把电脑所处的物理环境与使用习惯纳入工作空间」，生活四项 + 设备三块全部落地：

- **生活**：天气（Open-Meteo，**手动城市、绝不自动定位**，30 分钟内存缓存）、使用时间（前台采样 → 日/周聚合，`usage_stats` 三列聚合表）、音乐（SMTC 可选依赖，未装 winsdk 时 `available:false` 优雅降级）、消息概览（IMAP `STATUS (UNSEEN)` 只取计数 + demo 源，密码走系统凭据库）；
- **设备**：纯 Win32 指标（CPU/内存/磁盘，**零第三方 crate**，内存与 psutil 对照偏差 0.0%）、进程列表（跨请求 CPU 差分）、结束进程（**UI 弹窗 + API `confirm:true` 双闸**）、模式健康。
- 8 组验收全部机器可判，`verify_stage8.py` **21/21**（release 产物，本轮独立重跑）。
- 插件形态口径如实：以 core 模块交付，阶段9 迁移路径已在 `modules/{life,device}/README.md` 声明，core 内 `plugin_id ==` 零特判（验收 8b）。

### ② 无致命漏洞 ✅

红线 V1~V8 **0 命中**（V2/V3 本阶段不涉及）：

- **V5（破坏性操作二次确认）= 双闸**：UI `askKill`/`confirmKill` 弹窗是第一道，API/HTTP 强制 `confirm:true` 是第二道。验收 7b 实测：`confirm=false` → 400，`confirm=true` → 真结束且进程死亡确认。
- **V1（无明文凭据）**：IMAP 密码只进系统凭据库（`social_credential_ref`/`resolve_password` 只认 credRef），不进配置、不进数据库。
- **隐私**：数据库无任何消息/聊天内容表（验收 5a，可疑表=无）；`usage_stats` 只有 `day/app_name/seconds` 聚合列，无时间点明细（5b）。
- **数据安全**：迁移 `0007` 只增不改（`usage_stats` 为阶段8 首个写入方，`DROP TABLE` 针对无数据的旧预设，无数据丢失风险）；媒体控制 action 白名单在 core 与 sidecar 双侧校验。
- **不可恢复架构错误**：无。ADR-001 合规（进程控制全在 Rust；sidecar 只做注册表/SMTC/IMAP 访问），单一写入者未破坏。

### ③ 无冗余垃圾 ✅

- 门禁 **0 WARN**（交付轮曾有 4 条 `expect()` WARN，已在送审前按项目惯用法改为 `unwrap_or_else(into_inner)`）；
- 调用点检索无"零调用即功能不成立"项（见 §三·附）；
- `PW_WEATHER_FAKE` 走环境变量开关，默认关闭，不产生假数据路径；验收临时数据目录自清。

---

## §二 硬证据（全部本轮独立重跑，2026-09-13 16:04~16:06）

| 项 | 结果 |
|----|------|
| `python tools/gate.py --stage 8 --build` | **FAIL=0 · WARN=0 · PASS=22**（含 cargo check + 前端 typecheck + B131 sidecar 产物新鲜度） |
| `python tools/verify_stage8.py`（**release 产物**） | **21/21 PASS**（8 组验收：天气 no_city + fake 缓存 1a/1b · SMTC 降级 + action 拒绝 2a/2b · 概览仅未读数 3a/3b · 采样聚合 4a/4b/4c · 隐私 5a/5b · 指标对照 6a~6d · kill 双闸 7a/7b · 插件形态 8a/8b） |
| `python tools/verify_sidecar_bundle.py`（**发行态**） | **8/8 PASS**（单文件 exe 独立启动 + AI 流式 + 模板 + V2 consult 隔离 + ADR-001 410） |
| `cargo test`（core） | **77 passed; 0 failed**（含 3 个阶段8 新增：`add_seconds` 累积、按日隔离、social 非 array 拒绝） |
| 基线漂移 | 末次已验证构建（15:36）之后源码零改动 |

> 首轮交付时 verify8 曾 18/21：1b 为脚本未编码非 ASCII query（脚本 bug）、2a 为 `/life/media` 只注册在 GET（真 bug）、2b 为 winsdk 缺失时 action 校验次序错误（真缺陷）。三项均已在送审前修复并重验，本轮复跑全部通过。

## §三·附 强制调用点检索（零调用 = 功能不成立）

| # | 功能符号 | 调用点 | 结论 |
|---|----------|--------|------|
| 1 | 12 个 `life_*`/`device_*` Tauri command | 定义 `api/commands.rs` + 注册 `main.rs` + HTTP 同源路由 `api/mod.rs` | 已接线 |
| 2 | 9 组 `/api/v1/{life,device}/*` 路由 | `api/mod.rs` route 注册（verify8 端到端实跑） | 已接线 |
| 3 | `lifeApi` / `deviceApi`（前端聚合） | `lifeService.ts` / `deviceService.ts` 定义，`LifeView.vue`（9 处）/ `DeviceView.vue`（5 处）消费，路由 `router/index.ts` 挂载 | 已接线 |
| 4 | 12 个前端 API 方法 | `LifeView.vue` / `DeviceView.vue` 内逐一调用（usageToday/weather/mediaNow/mediaControl/socialOverview/socialConfigGet/Put/metrics/processes/killProcess/modeHealth） | 已接线 |
| 5 | `DEVICE_METRICS_UPDATED` 事件 | core `device/mod.rs:3` publish → `events.rs` 常量 → 前端 `DeviceView.vue` 订阅（eventBridge） | 已接线 |
| 6 | `spawn_device_watcher` / `spawn_usage_sampler` | `main.rs` 装配 + 各自模块定义 | 已接线 |
| 7 | `check_break_remind` | `life/mod.rs:53`（sampler 循环内调用，`reminded_day` 内存去重） | 已接线 |
| 8 | sidecar `/life/*` 路由 + life 模块装配 | `service.py` GET/POST 双侧注册 + `import life as life_mod` + `_WEATHER_CACHE` | 已接线 |

无"零调用即功能不成立"项。

## §四 阻塞项

**无。**

记录在案（不阻塞、不处理）：

1. **`lifeApi.usageWeek` 前端零 invoke**：有 HTTP 路由 + command + 验收 4c 端到端调用（周趋势数据链路完整），仅 LifeView 未做周视图。与阶段6 `learning_goal_get`/`project_get` 同类。
2. **`LIFE_BREAK_REMIND` 事件无前端 listen**：11 §标注休息提醒为**可选项**（默认 `life.break_remind_hours=0` 关闭），core 侧采样循环内已接线并按日去重；事件运行时投递到 webview 与阶段6/7 同源（仅接线级证据，无真窗口断言）。
3. **winsdk 未安装**（MSVC 编译问题），SMTC 真实播放（曲目/进度/控制生效）未做人工核对；验收 2a 断言的是 `available:false` 降级路径——依赖缺失时功能正确降级，不构成阻塞。
