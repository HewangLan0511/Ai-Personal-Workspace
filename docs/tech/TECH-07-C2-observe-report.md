# TECH-07-C2 实施报告 —— Workspace Runtime Observe 接线

> 日期：2026-09-16 · 状态：**已完成，verify_tech07c2.py 25/25 全绿**
> 视觉基线：UI-06~UI-08 + `docs/ui/UI-FUSION-STANDARD.md` + C1 RunView（零视觉变化）
> 停止点：Observe 接通即止，未进入任何窗口控制（C3 未开工）。

---

## 一、数据流（本阶段达成形态）

```text
真实 core 进程（随机端口 / Tauri invoke）
        ↓  既有命令：windows_list / modes_current / mode_progress /
        ↓            modes_list / apps_list / layouts_list / monitors_list
ui/src/api services（layoutService / modeService / appsService）
        ↓  ↓ 唯一允许 import @/api 的边界
ui/src/workspace/runtime/
  ├ boundary.ts    白名单(+apps_list) / 黑名单 / observe 段位（不变）
  ├ projection.ts  ★C2 新增：core DTO → UI 投影（映射不伪造）
  ├ facts.ts       ★C2 改造：透传 → 聚合投影 + 连接态三档
  ├ actions.ts     不变（observe 段全拒绝）
  └ index.ts       出口补投影类型
        ↓  WorkspaceFacts（投影后）
RunView.vue（2s 轮询 snapshot）
        ↓
现有 UI 区域：run-head / run-status / run-stage / appbar / minimap（骨架零改动）
```

## 二、Adapter 变更说明

| 项 | C1 | C2 |
|---|---|---|
| windows facts | core `WindowInfo` 原样透传 | `RunWindowFacts` 投影：hwnd/pid/title/className/state(normal|minimized|maximized)/rect/belongsToMode/manageable；**exe 恒为 null**（core 未提供，如实缺口，见风险 R-1） |
| mode facts | `ModeCurrent` 透传 | `RunModeFacts` 聚合：running/description/icon/layout/apps[]/previous |
| app 运行状态 | 无（只有 `应用 #id`） | `RunAppFacts`：name + runState（running/launching/failed/skipped/unknown）+ windowCount。**证据链**：progress.slots 的 pid × windows_list 的 pid；无 pid 证据 → unknown（不伪造 running） |
| 归属判据 | 无 | belongsToMode = 窗口 pid ∈ 流水线已登记 pid 集合；无证据一律 false（禁止按标题猜） |
| 连接态 | failures 字符串数组 | connected / degraded / offline 三档；offline 判据 = **6 项 core 事实全失败**（apps_list 有 localStorage 降级语义，不算 core 连接证据） |
| 白名单 | 9 命令 | +`apps_list`（既有读命令）；黑名单 8 命令不变，observe 段位不变，actions 全拒绝 |

## 三、真实环境验证证据（D 段，非 mock）

真实 core（cargo build debug）以临时数据目录启动（不污染真实库），Edge headless 打开
`VITE_CORE_BASE=''` 验证构建产物（同源代理转发 core 随机端口）：

- **D1** core 启动 + `/health` OK（port=54138，临时库）
- **D2** 启动 charmap.exe → core 差集反查真实 pid=20356 / title='字符映射表' → **RunView 舞台出现该真实窗口投影（ui=True）**
- **D3** UI 投影 7 条 ⊆ core 真实窗口 11 条，**伪造=0**
- **D4** ≥2 个 facts 轮询周期后 run-stage/appbar/minimap/head **DOM identity 全保持**（S2 局部更新）
- **D5** 关闭目标软件 → UI 投影同步消失
- **D6** 停 core → UI 显示「未连接」，**0 个伪造窗口**

## 四、风险列表

- **R-1 exe 缺口**：core `WindowInfo` 无进程映像路径，`RunWindowFacts.exe` 恒 null。需 core 增加字段（后续阶段与 windows_close 一起议），C2 不新增 core 命令。
- **R-2 无流水线时 app 状态为 unknown**：modes_current 只有 launchedAppIds 无 pid 映射，流水线未跑/已清时无法给出 running 证据 —— 如实展示「状态未知」，不伪造。
- **R-3 验证构建与产品构建的 dist 差异**：C2 验收用 `VITE_CORE_BASE=''` 构建（仅影响浏览器降级通道基地址）；Tauri 产品走 invoke 主路径不受影响。产品发版前按原流程构建即可。
- **R-4 dist 从不清理**：ui/dist/assets 累积 412 个历史 chunk（多轮构建残留）。不影响运行（index.html 只引用新 hash），建议后续加 `build.emptyOutDir` 清理。
- **R-5 charmap 代替 notepad**：Win11 notepad 为 Store stub（Popen pid 立即退出、沙箱下无窗口），验证脚本改用 charmap.exe（纯 Win32，title 固定），语义等价（真实第三方窗口 → core → UI）。

## 五、回归结果

| 套件 | 结果 |
|---|---|
| verify_tech07c.py（C1 基线） | **16/16 PASS** |
| verify_tech02_workspace.py（T1a-T6，最终产物） | **11/11 PASS** |
| verify_tech07c2.py（本阶段，A17+R2+D6） | **25/25 PASS** |

## 六、交付清单

**新增文件：**
- `ui/src/workspace/runtime/projection.ts`（投影层）
- `tools/verify_tech07c2.py`（验收脚本，25 项）
- `docs/tech/TECH-07-C2-observe-report.md`（本报告）

**修改文件：**
- `ui/src/workspace/runtime/facts.ts`（透传 → 聚合投影 + 连接态）
- `ui/src/workspace/runtime/index.ts`（出口补 projection/apps）
- `ui/src/workspace/runtime/boundary.ts`（白名单 +apps_list）
- `ui/src/views/RunView.vue`（**只换数据消费**：投影 facts、真实软件名 + 三态点、未连接态文案；布局/样式/交互结构零改动）

**未修改文件：**
- 视觉基线四 CSS（tokens/motion-tokens/primitives/base，hash 冻结判定一致）
- core 全部 Rust 代码（零新命令、零新迁移）
- actions.ts / workspace 冻结域（store/layout/snapshot/runtime 门面）
- UI-FUSION-STANDARD.md / C1 交付物

**事实陈述：**
- 真实 Core 是否参与：**是**（D1-D6 真实进程 + HTTP 随机端口）
- 真实窗口是否参与：**是**（charmap 真实窗口进 UI 投影）
- 是否执行任何窗口控制：**否**（无 place/close/restore/launch/terminate/activate；拖拽保持 UI 原行为，窗口矩形 pointer-events:none）
- UI 是否发生视觉变化：**否**（骨架/布局/类名零改动；仅数据文案：软件名、runState 点=既有 pw-dot、窗口计数、未连接文案）
- Token 是否增加：**否**（hash 冻结判定）
- Animation 是否增加：**否**
- C1 是否保持：**是 16/16**
- TECH-02 是否保持：**是 11/11**
