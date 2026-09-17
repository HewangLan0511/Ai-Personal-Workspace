# TECH-07-B 设计：UI 融合架构（设计稿，等待审核后实施）

> 配套：`docs/reviews/UI-FUSION-MAP.md`（逐域映射表）。
> 前置：TECH-07-A（窗口能力审计）、TECH-07-B-0（Workspace Runtime 聚合层设计）。
> **本轮零编码**。约束自查见 §六。

---

## 一、融合基线与缺口总结

| 域 | 融合度 | 结论 |
|---|---|---|
| Model Center / AI Sidebar / Profile | ✅ 已融合 | 前三轮完成（TECH-05-D / 阶段7 / TECH-06），保留增量打磨项 |
| Application / Mode | ✅ 大体融合 | apps/scheduler 全链路真实；prep overlay mock、useCount 展示未接 |
| Layout / Window / Workspace | ◐ 半 | core 能力齐，UI 侧桥缺失 |
| **Run（#/run 沉浸页）** | ❌ 缺 | **唯一整页级缺口**；真实应用无对应路由 |

**缺口不等于从零做**：core 侧模式七步/窗口摆位/布局编排/快照契约全部就绪（07-A 审计），
缺的是 UI 侧的「页面壳 + 事实投影 + 动作桥」。

## 二、Workspace Runtime Adapter（中间层设计）

### 2.1 定位与不变量

```
原型/真实 UI 交互层（原接口，一字不改）
        │  只调 workspaceRuntime.* 与既有组件
        ▼
┌─ Workspace Runtime Adapter（ui/src/workspace/adapter/，域外新目录）─────────┐
│  职责三件事：                                                              │
│  ① facts-in  ：把 core 事实（modes/running/windows/snapshot）映射成 store 形状 │
│  ② acts-out  ：把 UI 编排动作翻译成 core 调用（place/activate/upsert/apply）  │
│  ③ mode-switch：dryRun → observe → actuate 三段开关（逐步放权，随时可回退）    │
└──────────────────────────────────────────────────────────────────────────┘
        │  经既有注入点 + 模块级注册函数（不破门禁）
        ▼
ui/src/workspace/{store,layout,snapshot,runtime}.ts（形状与门禁方法集合不动）
```

**不变量（验收锁）**：
- `workspaceRuntime` 门面方法集合与返回值冻结语义不变（`verify_tech02` T1d）；
- `store/layout/snapshot.ts` 零 `@/api` import（T1b/T1c 不破）——适配器在**域外**目录，是唯一被允许 import `@/api` 的邻接层；
- 注入走**模块级注册函数**（如 `registerFactProvider()`，独立 export，不挂在门面对象上）——
  实施时先核对 T1d 判据是否为超集检查，若为精确集则此设计天然安全；
- 视觉 Token 体系（tokens.css / skin-engine 契约键）零改动。

### 2.2 facts-in：真实事实 → store 形状（只读投影）

| store 形状 | 事实来源 | 映射规则 |
|---|---|---|
| `WorkspaceApp.status` | `RunningApps` + `windows_list` | `running`=pid 活且 hwnd 在；`waiting`=已登记无窗；`closed`=reap 判死 |
| `WorkspaceApp.windowId` | `hwnd` | `String(hwnd)`（volatile，仅运行期有效） |
| `WorkspaceApp.appId` | `apps.id` | `String(id)` |
| 布局/几何 | `layouts.slots` × `windows_rect` | 原型 DOM 几何语义替换为**真实窗口几何投影**（minimap/窗口树用同源数据） |
| 状态栏（goal/app chips/布局/模式） | `ModeRunAggregate`（B-0 §三） | `refreshRunStatus()` 式叶子刷新对应 Vue 叶子组件 |

### 2.3 acts-out：编排动作 → core 调用（逐步放权）

| 原型动作 | actuate 段的翻译 | 失败语义 |
|---|---|---|
| 窗口点击置顶 | `windows_place`→`windows_activate(hwnd)` | toast + 保持 DOM 现状 |
| 布局 seg「自动整理/聚焦」 | 取该模式 layout 的 tile/focus slots → `layout_apply`（走既有编排，含重试） | 单窗失败不阻塞（沿用 WINDOW_LAYOUT_FAILED 事件） |
| 自由模式拖拽松手落位 | 归一化几何 → 草稿 slot →（保存时）`layout_upsert(captured-*)` | 回滚 DOM 几何 + toast |
| 「保存布局」 | `layout_upsert` + 导出 JSON（既有双写纪律） | toast |
| 「恢复默认」 | `layout_apply(name)` | toast |
| appbar AI 标签 | 纯 UI（dock 开关），不经 core | — |
| 模式进入 | `mode_apply` + prep overlay 接 `mode_progress` 七步真值（三步点亮改为七步真实进度） | 校验失败即停在 overlay 并显示原因 |
| 退出模式 | `mode_exit`（**前置：core 优雅关闭 WM_CLOSE 落地**，07-A R-1） | 逐项上报关闭结果 |

### 2.4 mode-switch 三段开关（逐步接入，随时回退）

```
dryRun   （现状）：workspace 域纯内存，facts=种子数据 —— 一切验收照旧
observe  （F1~F2）：facts-in 打开 —— UI 显示真实 pid/hwnd/status/进度；acts 仍走 DOM
actuate  （F3+）  ：acts-out 打开 —— 编排动作落到真实窗口；DOM 几何成为真实几何的投影
```
开关是适配器内的显式常量/config 读值，不靠"代码改到一半"的隐式状态；每段独立出验收。

## 三、页面融合优先级（任务给定 1~5，附现状与剩余）

| # | 页面 | 现状 | 剩余工作 | 量级 |
|---|---|---|---|---|
| 1 | **模型中心** `/models` | ✅ 已融合（真实连接+持久化，TECH-06） | 延迟 chip 接真实 check 耗时；其余打磨项 | S |
| 2 | **AI 助手** `/ai` + dock | ✅ 已融合（TECH-05-D） | 「工作空间助手」上下文 = F2 后接聚合视图；来源记忆回跳对齐原型 `models-back` | S |
| 3 | **个人档案** `/profile` | ✅ 已融合（阶段 7 + 06-B 审计） | 头像上传 `custom:<引用>` 语义；其余对齐打磨 | S |
| 4 | **工作空间状态** `/mode` + Dashboard | ◐ | 工作空间卡接聚合视图（minimap=真实窗口投影）；useCount/lastUsedAt 接线；Dashboard 卡同源 | M |
| 5 | **工作模式真实运行** `/run`（新） | ❌ | F2 页面壳 + F3 摆窗桥 + F4 快照 + F5 恢复（见 §五） | L |

排序理由与任务给定一致：1~3 已真实化、只需对齐打磨（低风险收尾）；4 是 5 的数据地基；
5 依赖 4 的聚合视图与 core 优雅关闭前置，放最后。

## 四、新增评估：command / config / migration / service

| 类别 | 必须新增 | 可复用（零新增） | 依据 |
|---|---|---|---|
| **command** | ① `windows_close`（优雅关闭 WM_CLOSE→超时回退 terminate）② 快照聚合读（若 L2 组装在 core；备选=UI 组装则零新增）③「按快照恢复」编排（B-3 才需要，届时显式记账） | 模式族 9+2 / 布局族 / 窗口 5 / apps 族 / config 读写 / ai 族 —— **全部复用** | 07-A §五 + B-0 §五；读命令能省则省（UI 组装优先） |
| **config** | `workspace.snapshot.last`（string，白名单三处登记，契约 v14；B-0 已定案：键登记≠迁移≠命令） | `mode.current` / `mode.switch_memory` / `ai.provider.current` / `ai.model.current` / `profile.avatar` / `ai.models.registry` | B-0 §五边界 7 |
| **migration** | **零** | — | Workspace 运行态不落表（B-0 定案）；现有 0001~0008 覆盖全部需要 |
| **service** | UI 侧：`ui/src/workspace/adapter/`（facts-in / acts-out / mode-switch，域外新目录） | core 侧：零新模块（聚合在 scheduler/window_manager 现有模块组装）；`modeService/layoutService/appsService/profileService` 全复用 | 适配器是唯一允许 import `@/api` 的 workspace 邻接层 |
| **路由/页面** | `/run` 一个新路由 + RunView（原型 #/run 的真实化壳） | 其余 16 视图全部保留不动 | 页面映射表 §二 |

**明确不新增**：任何第二事实源、任何 localStorage 键（模型域红线延续）、任何数据库表。

## 五、实施阶段（审核通过后执行）

| 阶段 | 内容 | 出口判据（验收锚） |
|---|---|---|
| **F0 优雅关闭**（core 前置） | `window.rs` 加 close(hwnd)：PostMessage WM_CLOSE → 超时回退 terminate；`mode_exit`/exclusive 改走优雅关闭 | 真启动记事本→exit→进程退出且无僵尸；07-A R-1 关闭 |
| **F1 observe 接通** | 适配器 facts-in + 聚合视图；`/mode` 工作空间卡、状态栏接真值；useCount 接线 | verify_tech02 全绿（门禁不破）；ModeView 显示真实 running/waiting/closed |
| **F2 Run 页壳** | 新增 `/run` 路由：run-head + 状态栏（真值）+ appbar（真实运行软件标签）+ 窗口树 drawer（windows_list 投影）+ prep overlay 接七步进度；**本阶段不做 DOM 编排** | 原型交互红线逐条对齐（映射表 §三）；事件桥不可用时轮询兜底 |
| **F3 actuate 摆窗桥** | 布局 seg→layout_apply；拖拽落位→草稿 slot + windows_place；appbar⇄前台双向同步；保存/恢复布局→layout_upsert/apply | 真窗口摆位后 `windows_rect` 比对（容差）；S2 叶子刷新判据 |
| **F4 快照采集落盘** | core 快照聚合 + `workspace.snapshot.last` 登记与写入（触发=enter_mode）+ 契约 v14 | 真 core：写入→terminate→重启→直读一致（TECH-06-B C6 同法） |
| **F5 恢复执行** | 身份再定位→wait_ready→rectNorm 摆位→拓扑降级；recovery.executable 真值驱动 | 端到端：enter_mode→保存→退出→重启→恢复→几何比对（容差 0.02） |

每阶段独立出验收脚本/判据，**F1~F3 之间可随时停在 observe 段交付**（三段开关保证）。

## 六、约束自查与审核问题

| 禁止项 | 自查 |
|---|---|
| 不删除原 UI 结构 | ✅ 16 视图零删除；`/run` 是新增不是替换；原型交互红线全部继承为验收判据（映射表 §三） |
| 不降低交互复杂度 | ✅ 拖拽/吸附三类/双向同步/Esc 链/toast 纪律逐条保留，且给出真实化后的增量化语义（松手落位→windows_place） |
| 不替换为简单页面 | ✅ Run 页按原型完整信息架构实现（run-head + 状态栏 + appbar + 窗口树 + prep overlay） |
| 不修改视觉 Token | ✅ tokens.css / skin-engine 契约键零改动；新页面只消费既有变量 |
| 不直接开始大量编码 | ✅ 本轮仅文档；F0~F5 待审核批准后逐段执行 |

**请审核**：① `/run` 新增路由是否批准（原型唯一整页缺口）；② 新增 command 清单（windows_close / 快照聚合读 / 恢复编排）是否接受按显式记账逐个登记；③ F 阶段排序是否认可（F0 优雅关闭前置）。
