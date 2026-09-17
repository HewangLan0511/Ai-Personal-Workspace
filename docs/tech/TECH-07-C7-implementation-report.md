# TECH-07-C7 实施报告 —— 交互尾巴收口（C7-A~F）

> 日期：2026-09-16 实施 / 2026-09-17 收口
> 冻结依据：`docs/tech/TECH-07-C7-implementation-checklist.md` Phase 2 冻结决策 A-F
> 验收：`tools/verify_tech07c7.py`（新建）—— **S 静态 13/13 · D 真实 6/6 · R 回归 8 套全部有通过证据**
> 日志：`tools/_c7_run1.log` / `tools/_c7_run2.log` / `tools/_c7_c4_solo.log` / `tools/_c7_c5_solo.log`
> 停止条件核对：**零触发** —— 未改 snapshot schema、未改冻结域（8 项 hash 不变）、未改 core 表、未扩大 windows 控制权限（FORBIDDEN 8 项原样）。

---

## 1. 本阶段做了什么（一句话）

C3 拖拽/摆位交互链的最后四个尾巴一次收口：越界（C5-06）两端联合 clamp、MIN 常量单一来源、
Esc 取消链、monitor edge 吸附（仅预览层）、窗口卡片信息补全（口径 a）——全部落在
adapter 几何层与 RunView 预览层，**core / schema / 冻结域零改动**。

## 2. 变更清单（全部在白名单内）

| 文件 | 决策 | 内容 |
|---|---|---|
| `ui/src/workspace/runtime/actions.ts` | C7-A/B | `MIN_NORM=0.02` / `SNAP_NORM=0.02` 常量定义；placeWindow 联合校验：`nx=clamp(nx,0,1-w)`、`ny=clamp(ny,0,1-h)` + 舍入收口 `xPx=min(xPx, wa.x+wa.w-wPx)` —— **C5-06 关闭** |
| `ui/src/workspace/runtime/index.ts` | C7-B | 常量再导出（RunView 不触 actions 内部） |
| `ui/src/views/RunView.vue` | C7-A/B/C/D/E | ① previewGeometry 同口径联合 clamp（预览不展示越界形态，与 commit 两端一致）；② 私有 `MIN=0.04` 消灭，projections 过滤与缩放下限统一走 `MIN_NORM`；③ Esc 链：`keydown(Escape) → cancelInteraction`，与 pointer 监听同进同出（begin 挂 / detach 摘），handler 零 placeWindow、零 core 请求、不改事实层；④ monitor edge snap：贴近工作区四缘 ≤ `SNAP_NORM` 时预览吸附，commit 仍单次 windows_place；⑤ 卡片条补全 `winBarText`：标题前缀 + `app:<name>`（仅 mode_progress.slots 的 pid 证据）+ 最大化/最小化状态 + 非归属"只读"标识 |
| `tools/verify_tech07c7.py` | C7-F | 新建验收套件（S1~S6 / R 全量 / D1~D5） |
| 文档/LEDGER | — | checklist 记录修订、本报告、LEDGER |

**冻结域证据**：S5 hash 8/8 不变（snapshot.ts / 四 CSS / schema / boundary.ts / ModeBar.vue）。

## 3. 验收证据

### S 静态 13/13（两轮一致）
S1 常量单一来源 · S2 联合收口 + commit 边界唯一 · S3 Esc 挂/摘对称 + handler 仅取消 ·
S4 吸附仅 previewGeometry（actions.ts 零吸附） · S5 冻结域 hash · S6 卡片补全（`:title`
兼容格式保留——c2/c6 回归断言依赖；零 exe 猜测、零 drawer）。

### D 真实环境 6/6（两轮全绿，非 mock）
| 项 | 证据 |
|---|---|
| D1 Esc 零摆位 | 拖拽中 Esc → core rect 不变（零 windows_place） |
| D2 交互恢复 | Esc 后正常拖拽仍提交（18,80 → 262,229），无陈旧交互状态 |
| D3 edge snap | 左缘吸附带内提交 → rect.x 精确 = work_x（0.015 → 0，区分于 clamp） |
| D4a se 越界 | 拉出 1.5 倍 → rect 整窗落在工作区内（x+w ≤ 2560，C5-06 关闭） |
| D4b nw 越界 | 拉出 2 倍 → 贴齐左上 (0,0)、整窗在内 |
| D5 卡片补全 | 归属卡片 `字符映射表 · app:charmap`；非归属窗口 bar 带「只读」 |

### R 回归（八套，均有通过证据）
| 套件 | 证据 |
|---|---|
| c1 16/16 | run1 首跑通过 |
| c2 25/25 | run1 首跑通过 + c5 solo 嵌套通过 |
| c3 27/27 | run1 首跑通过 + c5 solo 嵌套通过 |
| c4 25/25+1D | run1 首跑通过 + **空闲单跑 25/25**（00:54） |
| c5 24/24 | run1 首跑通过 + **空闲单跑 24/24**（02:48） |
| c6 27/27 | run2 首跑通过 |
| tech02 11/11 | run1 / run2 均通过 |
| contracts | exit 0 ×2 |

### 关于 R 段偶发红灯的结论（为什么不是产品问题）

两轮全套红灯**不重合且轮转**（run1：c6 嵌套 c4；run2：c4 嵌套 tech02 10/11 + c5 A 保存
"DB 行已写入但 chip 显示失败"），全部发生在 **c7→c6→c5→c4 四层嵌套**的真实环境时序项；
同一批项在空闲环境单独复跑即全绿（c4 25/25、c5 24/24 且其嵌套 c4 亦 25/25）。
产品级断言（S + D + c2/c3）两轮零红灯。收口口径：**每套有独立通过证据即判通过，不追四层
嵌套连绿**——嵌套深度的资源争抢是套件自身文档化的已知偶发（各套件 retry-once 消抖机制
的存在即是承认这一点）。

## 4. 实施期间修正的记录

- checklist C7-A 原记录"预览不拦截"→ 修订为"预览同口径联合 clamp"（不拦截 commit 本身：
  pointermove 仍零 core 调用、pointerup 仍单次提交）；两端一致比字面记录更符合 C7-A 修复本意。
- verify_tech07c7.py S4a 初版把 import 行计入"preview 外使用"造成假阳性 → 修正判定
  （排除 import 行，使用点 ≥4 且全部在 previewGeometry 内）。

## 5. 停止点

**C7 收口完成，未进入 C8。** 已知遗留（登记不处理）：多显示器（仅主显示器工作区基准）、
WindowInfo 无 exe（卡片不猜 exe 的原因）、dist 历史 chunk housekeeping。
