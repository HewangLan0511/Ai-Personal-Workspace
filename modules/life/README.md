# life/ —— 生活中心模块（阶段8 · 11 §A）

> 位置说明：代码在 `core/src/life/`（采样 + 代理）与 `system/life.py`（天气/音乐/社交）。
> 以**核心模块**形态实现；阶段9（12 §验收11「生活中心迁移」）再把它们迁移成插件 ——
> 与 11 §验收8"插件形式"的口径差已在交付报告如实声明。

## 职责边界

| 能力 | 位置 | 依据 |
|------|------|------|
| 前台采样器（30s tick，可配） | `core/src/life/mod.rs::spawn_usage_sampler` | 本机能力归 Rust（ADR-001） |
| `usage_stats` 表（按天+应用聚合） | `core/src/life/repository.rs` + 迁移 `0007` | 单一写入者 = core |
| 天气（Open-Meteo + 30min 缓存 + fake 开关） | `system/life.py::weather`，core 代理 | 网络/系统 API 归 Python（02 §2.4） |
| 音乐 SMTC（winsdk 可选导入） | `system/life.py::media_now / media_control` | 同上；winsdk 缺失 → `available:false` 降级 |
| 社交概览（IMAP UNSEEN / demo） | `system/life.py::social_overview` | 只取未读计数，**不下载正文、不落库** |

## 不变量（红线在模块内的体现）

1. **定位 privacy**：天气城市只来自用户输入（`life.weather.city` 配置或请求参数），代码路径里不存在系统定位调用。
2. **密码不落库**（V1）：IMAP 密码只进 keyring（`ai.credentials` store，ref = `social.imap.<name>`）；
   config 表里的服务 JSON 不含密码字段；`resolve_password` 只认 `credRef`。
3. **不存聊天内容**：社交概览输出只有 `{name, type, unread, summary}`；IMAP 只发 `STATUS (UNSEEN)`。
4. **聚合不存明细**：`usage_stats` 主键 (day, app_name)，采样器只 UPSERT 累加秒数。

## API（双通道同源）

| Tauri command | HTTP | 说明 |
|---------------|------|------|
| `life_usage_today` | GET `/api/v1/life/usage/today` | 今日总量 + 排行 |
| `life_usage_week` | GET `/api/v1/life/usage/week` | 近 7 天每日总量 |
| `life_weather` | GET `/api/v1/life/weather?city=` | 城市；缺省读配置，无城市返回 `no_city` |
| `life_media_now` | GET `/api/v1/life/media` | SMTC 当前会话 |
| `life_media_control` | POST `/api/v1/life/media/control` | play/pause/next/previous |
| `life_social_overview` | GET `/api/v1/life/social/overview` | 未读数概览 |
| `life_social_config_get/put` | GET/PUT `/api/v1/life/social/config` | 服务清单（无密码） |

## 配置键（三处登记：KEYS / expected_type / default_for）

`life.weather.city`（string，""）· `life.usage_sample_interval_sec`（number，30）·
`life.break_remind_hours`（number，0=关）· `life.social.services`（string JSON 数组）。

## 验收步骤（机器部分见 `tools/verify_stage8.py`）

1. `PW_WEATHER_FAKE=1` 下设城市 → 返回固定 mock（含来源标注）；无城市 → `no_city`。
2. 采样间隔设 1s → 等 5s → `usage/today` 出现前台进程条目；重启 core 数据仍在。
3. 社交：添加 demo 服务 → overview 返回未读数；全库无消息正文。
4. 音乐：winsdk 可用时开播放器人工核对；不可用时端点返回 `available:false`（降级路径机器验证）。

## 边界（如实声明）

- GPU / 温度：Windows 无免驱动的通用通道，**不提供**，不造假数据。
- 休息提醒（A4 可选）：以"今日总时长跨阈值"为口径（每天最多提醒一次），非"连续使用"时长。
- 真实天气 API / 真实 IMAP：网络与账号依赖，机器验收用 fake/demo，真实路径需人工。
