# PW-INTEGRATION-002 · Preflight（整合前置）

> 日期：2026-09-15 · 性质：**只设计，零代码修改**
> 遵守停止条件：不改业务代码 / 不改数据库 / 不做 migration / 不重构 Provider / 不接 Motion / 不做 Skin UI / 不做 View Transitions / 不实现"完成工作"
> 证据口径：所有"实测"项均标注 `文件:行号`，来自本轮实际读码

---

## 1. 三个产品决策落地情况

| # | 决策（已冻结） | 本轮动作 | 状态 |
|---|---------------|---------|------|
| 1 | 退出工作模式后**恢复进入前的完整工作台窗口快照** | 输出数据模型建议（§2）；**不做 migration** | ✅ 已冻结，设计就绪 |
| 2 | **Provider Registry 作为唯一事实来源**（Provider→Models→Current Provider→Current Model） | 输出 canonical source 建议（§3）；**不大改 UI** | ✅ 已冻结，设计就绪 |
| 3 | "完成工作"**不编码** | 登记为产品设计项 **PD-001** | ✅ 已登记（不发明按钮） |

---

## 2. Workspace Snapshot 数据模型建议

### 2.1 当前模型（实测）

| 项 | 现状 | 证据 |
|----|------|------|
| 快照结构 | `last_snapshot: Option<(String, Vec<i64>)>` —— 只有「模式名 + appId 集合」 | `core/src/scheduler/runner.rs:142` |
| 快照时机 | 切换模式前 `snapshot_before_switch(prev)` | `pipeline.rs:122-127`、`runner.rs:168-174` |
| 存储位置 | **内存**（`Mutex<RunInner>`），进程退出即丢 | `runner.rs:129-143` |
| 登记表 | `launched: HashMap<mode, Vec<appId>>`（R-01 唯一依据） | `runner.rs:140` |
| 会话结果 | `SlotResult{app, appId, status, pid, reason, retriable}` —— **有 pid，无 hwnd / 无 rect** | `runner.rs:31-42` |
| 窗口能力（已有） | `WindowInfo{hwnd, title, class_name, pid, visible, minimized, maximized, rect, area}`；`list_windows / find_main_window / find_by_title / get_rect / place / activate / is_foreground / minimize / open_path` | `window_manager/window.rs:26-37, 115-266` |
| 布局契约（已有） | `Layout{name, description, monitor, slots:[Slot{app, rect, z, alwaysOnTop, maximized}], aiSidebar}` | `window_manager/apply.rs:20-42` |
| layouts 表 | `id, name, description, slots(JSON), monitor, is_builtin, created_at, updated_at` | `0001_init.sql:45-54` |

**结论**：窗口级能力**已具备**（读几何/状态、写位置、枚举、激活），缺的是「把这些能力按快照语义组织起来 + 落盘 + 按窗口恢复」的那一层。这不是从零造能力，是接线 + 建模。

### 2.2 目标模型（建议，JSON 形态）

```jsonc
// WorkspaceSnapshot v1
{
  "schemaVersion": 1,
  "takenAt": 1757894400000,            // epoch ms
  "trigger": "enter_mode",             // enter_mode | before_switch
  "modeName": "AI开发模式",
  "desktop": {                          // ← 目标核心：进入前的"普通工作台"
    "monitors": [{ "index": 0, "primary": true, "workArea": {"x":0,"y":0,"w":2560,"h":1400} }],
    "foregroundHwnd": 123456,
    "windows": [ WindowEntry ]
  },
  "workspace": {                        // ← 退出时要收尾的对象
    "layoutName": "coding.json",
    "monitor": 0,
    "managed": [{ "appName": "VSCode", "appId": 3, "pid": 2211, "hwnd": 987654 }]
  }
}

// WindowEntry
{
  "hwnd": 987654,        // volatile：仅本次进程运行期内有效（跨重启需重认领）
  "pid": 2211,
  "appId": 3,            // 能按 exePath/title 匹配软件库时补；匹配不到为 null
  "exePath": "C:\\...\\Code.exe",  // 建议新增：跨重启的稳定标识
  "title": "main.rs - VSCode",
  "className": "Chrome_WidgetWin_1",
  "rect": {"x":100,"y":80,"w":1600,"h":900},
  "state": {"visible": true, "minimized": false, "maximized": false},
  "zIndex": 7            // ⚠️ 近似：EnumWindows 返回序，非精确 Z 序
}
```

**三个必须显式承认的模型约束**（影响产品口径）：
1. **hwnd 是 volatile 的** —— 只在本进程运行期内有效。跨重启恢复必须靠 `exePath + title` 重认领（v2 能力），本轮快照按"同一次运行内退出恢复"设计。
2. **Z 序是近似的** —— 精确 Z 序需要额外枚举策略；v1 只保证位置/尺寸/状态/最大化。
3. **monitor 拓扑可能变** —— 快照按 index 记，恢复时按 §2.5 L2 降级。

### 2.3 当前 vs 目标 差异表

| 维度 | 当前 | 目标 | 差距性质 |
|------|------|------|---------|
| 覆盖范围 | 仅"模式拉起的 appId 集合" | 进入前**全部**可见窗口 + 模式管理对象 | 建模 |
| 持久化 | 内存 | 落盘（见 §2.4） | 需决策 |
| 窗口标识 | 无（只有 appId） | hwnd + pid + exePath + appId | 数据采集 |
| 几何 | 无 | rect（x/y/w/h） | 已有能力，未采集 |
| 窗口状态 | 无 | visible/minimized/maximized | 已有能力，未采集 |
| Z 序 | 无 | 近似 zIndex | 能力受限（已声明） |
| 多显示器 | 仅 layout 的 monitor 字段 | monitors 快照 + workArea | 部分已有（`monitors_list`） |
| 恢复语义 | 无（只有"回到上一个模式"） | 逐窗口 place + 状态复位 | **新增逻辑** |
| 生命周期 | 进程内 | 跨退出/重启策略待定 | 需决策 |

### 2.4 持久化边界建议

| 问题 | 建议 | 理由 |
|------|------|------|
| 谁写 | **core 独占**（沿用 db 单一写入者红线） | 现有纪律 |
| 存哪（三选） | **① config 表键 `workspace.snapshot.last`（JSON）← 推荐先用**；② layouts 表复用（`slots` 列语义不符，不推荐）；③ 新表 `0009_workspace_snapshots`（语义最正，需 migration） | ①零迁移、立即可用；③留给"需要历史快照"时再升级 |
| 何时写 | 进入模式流水线**动窗口之前**（pipeline 启动步的前置）；切模式同样先写 | 快照必须在改变桌面前完成 |
| 何时读 | `mode_exit` 时读取 | 退出即恢复 |
| 保留策略 | 只保最近 1 份（last），不做历史；写入失败**不阻塞**进入模式（降级为现行为） | 快照是体验增强，不是前置条件 |
| 体积控制 | 只存窗口元数据（无内容）；单条 ≤ 200 条窗口上限，超出取面积 Top N + 全部可见主窗口 | 防 JSON 膨胀 |
| 不写 | 窗口内容、标题全文可截断（≤120 字符）、任何用户数据 | 隐私 + 体积 |

### 2.5 恢复失败降级策略（分级，全部"只碰自己记录过的窗口"）

| 级别 | 场景 | 行为 |
|------|------|------|
| L0 | 全部有效 | 逐窗口 `place` + 状态复位（最大化/最小化/可见性） |
| L1 | 部分 hwnd 失效（进程已退出 / `IsWindow` 为假） | 跳过该窗口，记 `degraded: n`，UI 提示"N 个窗口已关闭，无法恢复" |
| L2 | 显示器拓扑变化 | 比例映射到主显示器 workArea；超界窗口夹回工作区内（复用 `apply.rs` 的 `degraded_monitor` 思路与 `layout.rs` 的像素换算） |
| L3 | 快照缺失 / JSON 损坏 / schemaVersion 不认 | **不恢复**，仅退出模式 + 提示；绝不猜、绝不清扫 |
| L4 | 恢复超时 | 与 pipeline 同口径（单窗口 15s / 总 45s）；超时中止，保留已恢复部分 |

**红线**：恢复**只动快照登记的 hwnd**，不无差别操作"同名软件"（R-01 精神的自然延伸）；恢复过程**不杀进程**（杀进程只由 `mode_exit` 的既有 `kill_registered` 负责，保持职责单一）。

---

## 3. AI Provider canonical source 建议

### 3.1 当前事实来源与调用链（实测）

| # | 来源 | 位置 | 读/写 | 证据 |
|---|------|------|-------|------|
| S1 | UI localStorage | `ui.ai.provider` / `ui.ai.model`（另有 `ui.ai.mode`、`ui.ai.width`、`ui.ai.collapsed`） | **读源** | `stores/ai.ts:84-86, 95, 131-132` |
| S2 | core config 表副本 | 同键名写 config 表 | **只写不读**（注释明说"UI 的读源保持单一（localStorage）"，core 不可达时静默降级） | `stores/ai.ts:109-123` |
| S3 | 模式 aiProfile | `work_modes.ai_profile` JSON：`{provider, systemPromptKey, permissionScope}` | 进入模式时使用 | `scheduler/repository.rs:28-40, 58`；`pipeline.rs:269` |
| S4 | 请求级参数 | `AiChatArgs{provider(必填), model, messages, mode, enabled_scopes, prompt_key, temperature, max_tokens}` | 每次调用传入 | `core/src/ai/mod.rs:24-38`；UI 传值 `stores/ai.ts:308-309` |
| S5 | Provider Registry（能力） | `ai/providers/registry.py`（openai/deepseek/compatible/lmstudio/ollama + 2 占位），core `ai_info` 投影能力与凭据状态 | UI 只读 | `commands.rs:613` |

**问题定位**：S1 与 S2 是**同一份数据的两处副本**（localStorage 为准、config 为影），S3 是**并行真相**（模式级 override），S4 是**运行期载体**。三处都可以主张自己是"当前 Provider"，没有一处是权威。

### 3.2 建议 canonical 划分（四层各司其职）

```
能力真相（read-only）
  ai/providers/registry.py  →  core ai_info  →  UI 只读
        Provider → Models（有哪些、需不需要 key、enabled）

用户意图真相（canonical 唯一）
  core config 表：ai.provider.current / ai.model.current
        ← 建议成为 canonical（core 是唯一写入者，重启/多窗口一致）
        localStorage 降级为**缓存**（core 不可达时的 fallback，非真相）

场景默认值（建议层，非真相）
  work_modes.ai_profile.provider
        → 进入模式时作为"建议值"，经用户确认或显式策略才改 current

运行期载体（只传不决策）
  AiChatArgs.provider / model  ← 由 store 从 current 注入
```

**优先级链（建议写进契约）**：
`请求显式传参（仅程序化调用）` > `current（用户意图）` > `模式 aiProfile（建议）` > `registry 默认（第一个 enabled）`

### 3.3 收口后各层职责

| 层 | 负责 | 不负责 |
|----|------|--------|
| Registry（Python + core 投影） | 有哪些 Provider/模型、凭据状态、能力元数据 | 不知道"用户在用什么" |
| Core | 持久化 current、校验请求 provider 合法（不在 registry → 报错不发请求）、模式 aiProfile 的读 | 不决定 UI 展示形态 |
| UI store | 读 current（启动时从 core）、注入请求、缓存 | 不独立持久化真相（不再以 localStorage 为准） |
| Request | 携带 provider/model 执行 | 不做选择、不做 fallback 决策（fallback 归 store） |

### 3.4 应改为"只读"的位置

- `AiSidebar` Provider 下拉（`AiSidebar.vue:130-137`）→ 只读 `ai_info`，不写真相
- `SettingsView` 模型列表（`SettingsView.vue`）→ 只读 `ai_list_models`
- 模式编辑页 AI 区块 → 读+写 `mode.aiProfile`（写的是"建议"，不是 current）
- **任何页面不得自行持久化 provider/model**

### 3.5 最小收口路径（不大改 UI，按依赖排序）

1. core 侧：current 的读写投影（config 键 `ai.provider.current` / `ai.model.current`）——**纯新增，零 UI 改动**
2. `stores/ai.ts`：启动读 core、写走 core、localStorage 降级为缓存（改变读源，不动组件）
3. `AiSidebar`/`SettingsView` 改为只读 + 写 current 经 store
4. 模式切换时的建议逻辑（`aiProfile.provider ≠ current` → 询问）——**依赖统一 Toast，排在浮层统一之后**

---

## 4. UI-04 对接矩阵

> 说明：UI-04 八个方向逐项对照 core/service 现状。**A=可直接接 · B=需先定契约 · C=Core 真缺口 · D=等 UI 设计**

| UI-04 项 | A 已有能力（可直接接） | B 需先定契约 | C Core 缺口 | D 等 UI 设计 |
|---|---|---|---|---|
| **学习目标入口** | 15 个 `learning_*` 命令（goals/nodes/roadmap_confirm/updates/reminders/ai_suggest）+ `stores/learning.ts` 已存在 | 若需"跳转定位到某目标"：建议 URL 约定 `?goal=<id>`（纯前端） | 无 | 入口形态（卡片/按钮/列表） |
| **导航中的设备入口** | `device_metrics/processes/mode_health` + `deviceService` + `DeviceView` 已存在 | 无 | ⚠️ `device_process_kill` 的**双闸不能弱化**（UI 弹窗 + `confirm:true`，红线 V5）——新入口复用时须保留 | 导航排序/图标 |
| **独立 AI 助手页面** | `ai_chat` + 事件流（`AI_STREAM_CHUNK`/`AI_RESPONSE`）+ ai store 已完整 | ✅ **需要**：独立页与 AiSidebar 是否共享会话？需定：会话 id、历史条数上限、**流式互斥**（同时只允许一个 stream）、宽度状态是否共用 | 无 | 页面布局 |
| **工作模式窗口 Resize** | 若指**外部软件窗口**：`windows_place/rect/list/find/activate` + `Layout.slots` 契约完备 → 可直接接 | — | 若指**主应用窗口自身** resize/position：**真缺口**（core 仅有 `minimize_window`，`commands.rs:41`；无 set_size/set_position）→ 需新增 1–2 命令 | 若指布局编辑器内槽位拖拽，交互需 UI 先定 |
| **档案扩展接口** | 22 个 `profile_*` 命令（overview/basic/skills/projects/timeline/suggestions/export_markdown） | 若"扩展"= 自定义字段：需定键值约定 | ⚠️ **小缺口**：`profile_basic` 表只有 `name/direction/interests/motto`（`0001_init.sql:88-95`），**无扩展 JSON 列** → 最小方案：config 键 `profile.ext.*`（零迁移）或迁移加 `extras` 列 | 扩展内容的展示形态 |
| **生活插件区域** | `life_usage_today/week`、`life_weather`、`life_media_now/control`、`life_social_overview/config` + 插件系统（插件可提供 widget） | ✅ **需要**：life 区域容纳"插件卡片"用哪套机制——复用 dashboard widget 机制，还是 life 专属 slot？（建议定 contract 再动手） | 无（媒体走通用插件通路，阶段9 已声明） | 区域布局 |
| **首页响应式** | 纯前端（widget 布局来自 config 键 `ui.dashboard.*`） | 无 | 无 | 断点/每行卡片数 → 预计不需要 core 参与 |
| **页面滚动体验** | 纯前端（各 view 自带滚动容器） | 无 | 无 | 待 UI。⚠️ 提醒：滚动锚定与 S2 局部更新纪律有交叉（`overflow-anchor` 已有先例），别在滚动容器引入 remount |

### 4.1 按四类归总

- **A 可直接接（4 项）**：学习目标入口、导航设备入口、独立 AI 页（数据面）、首页响应式
- **B 需先定契约（3 项）**：独立 AI 页会话共享、生活插件区域机制、档案扩展字段键值
- **C Core 真缺口（2 项）**：主应用窗口 resize 命令（若 UI-04 指主窗口）、档案扩展列（可用 config 键绕过）
- **D 等 UI 设计（全部 8 项都有视觉面）**：任何视觉改动都等 UI-04 定稿

### 4.2 需要白宇澄清的一项

**"工作模式窗口 Resize" 指哪一个？** 三种可能，对应完全不同的工作量：
1. 外部软件窗口（布局槽位）→ **零 Core 工作**，`windows_place` 已有
2. 主应用窗口自身（进入 workspace 时变窄/移位）→ 需新增 core 命令
3. 布局编辑器内的槽位拖拽交互 → 前端为主 + 需 UI 设计

---

## 5. Motion 第一批接线候选

> 立场：**不因为"底座已建成"就把所有页面改一遍。** 只接"有明确收益且不改视觉"的点位。

| 优先级 | 业务动作 | 现有 Motion primitive | 触发点 / 依赖 | 等 UI-04？ |
|:---:|---|---|---|:---:|
| 1 | **Workspace Cinema**（进入/退出工作模式） | `startCinema()` + `whenInteractive`(240ms Gate) + `notifyResize` | 订阅 `MODE_CHANGED` / `MODE_APPLY_PROGRESS`；Cinema 是**布局级**动画，依赖 UI-04 工作模式页定稿 | ✅ 等 |
| 2 | **Drag / Resize** | `claim('drag')`（Conflict Guard）+ `runInterruptible` | `AiSidebar` 宽度拖拽（`.ai-resizer` 已存在，改动面小）；LayoutView 槽位拖拽 | ❌ 不等（AiSidebar 可先接，不改视觉） |
| 3 | **Page Transition** | `createPageTransitionHooks`（**已接线** App.vue） | 剩余工作：把 `:key="$route.path"` 的 remount 语义与 S2 边界写进文档 + `?motion=novt` 回归 | ❌ 不等（仅文档+回归） |
| 4 | **Toast / Modal / Drawer** | `claim('overlay')` + `runInterruptible` | **必须先统一浮层（§6）**，否则一次接线只覆盖 1/3 实现 | ✅ 等（视觉会变） |
| 5 | **其他局部状态**（loading / empty / 列表项进出） | 只用 token（`--mt-dur-quick` / `--mt-stagger`），**不引入新 primitive** | 等组件定稿 | ✅ 等 |

**明确不做**：全量页面 Motion 改造；View Transition 转默认路径（继续只作增强）。

---

## 6. 浮层统一方案

### 6.1 现状清单（实测）

| 实现 | 位置 | 形态 | 计时 | 动画 |
|------|------|------|------|------|
| ModeView toast | `ModeView.vue:25-33`（`notify()`）、`:678`、`.mv-toast` `:996` | `<p>` 文本 | 4000ms timer | 无（v-if 直切） |
| SoftwareView toast | `SoftwareView.vue:22-28`（同款 `notify()`，**逻辑逐字复制**）、`:359`、`.apps-toast` `:611` | `<p>` 文本 | 4000ms timer | 无 |
| SettingsView saved-toast | `SettingsView.vue:252,256` + `base.css:342` | 内联 `<p>`/`<span>` | 无 | 无 |
| degraded-banner | `base.css:347` | 常驻横幅 | 无 | 无 |
| Modal（两套） | ModeView `mv-modal-mask/mv-modal` `:519-540`；SoftwareView `apps-modal-mask/apps-modal` `:304-352`（ModeView 还复用了 `apps-modal-head/foot` 类名 → 明显复制痕迹） | 遮罩 + 面板 | — | **无 enter/leave**（`v-if` 直切） |
| Drawer | **不存在**（全仓无实现） | — | — | — |
| ContextMenu | **不存在**（全仓无实现） | — | — | — |
| Desktop widget 窗口 | core 独立 Tauri webview 窗口（`desktop_widget.rs`） | 非 DOM 浮层 | — | — |

### 6.2 判定：哪些是"真缺失"，哪些只是"页面没用"

| 项 | 判定 |
|----|------|
| Toast | **重复实现**（2 套全功能 + 1 处静态变体）；不是缺失 |
| Modal | **重复实现**（2 套），且都无过渡动画 |
| Drawer | **真缺失** —— 没有任何实现（`AiSidebar` 是常驻侧栏，不是 Drawer） |
| ContextMenu | **真缺失** —— 零需求、零实现（先不造） |
| degraded-banner | **另一类**：系统常驻状态，语义上不属于瞬时反馈 |

### 6.3 统一方案（只定 Contract，不重构）

**建议 canonical Toast 形态 = 现有 ModeView / SoftwareView 行为**（4000ms 自动消失 + 单条文本）——理由：它已是主流用法（2/3 处 + 逻辑最完整），统一时应让少数派向它靠，而不是反过来。

```
Toast Contract（建议）
  语义入口：notify({ level: 'info'|'success'|'warn'|'error', text, sticky?, dedupeKey?, action? })
  宿主：PwfToastHost（单例，挂 App 根部，全局只此一个）
  默认：4000ms 自动消失；sticky=true 需手动关闭
  队列：同 dedupeKey 覆盖；不同 key 最多堆叠 N 条（N 由 UI-04 定）
  迁移映射：
    ModeView.notify / SoftwareView.notify  → 语义入口（行为不变）
    SettingsView.saved-toast               → level:'success' 短 toast
    degraded-banner                        → **不并入**，独立 PwfBanner（常驻系统状态）

Modal Contract（建议）
  语义入口：宿主组件 open/close + 内容 slot；core/业务只发"打开什么"的语义
  统一行为：mask click 关闭（现状两处都是 @click.self）、Esc 关闭、focus 陷阱
  形态：面板结构由组件决定（这是未来 Skin 能换组件形态的前提）
  优先级：注册 Conflict Guard 'overlay'

Drawer / ContextMenu
  本轮**不造**。待 UI-04 明确需求后按同一 overlay 优先级纳入同一 Host。

Motion 接口（一次接线覆盖全部浮层）
  宿主统一消费 claim('overlay') + runInterruptible → 这也是浮层统一要排在 Motion 接线之前的原因
```

---

## 7. Core 缺口

| # | 缺口 | 性质 | 说明 |
|---|------|------|------|
| C1 | 主应用窗口 resize / position 命令 | **真缺口（待确认）** | core 仅有 `minimize_window`（`commands.rs:41`）；只有 desktop widget 窗口能建/移。若 UI-04 的"工作模式窗口 Resize"指主窗口则必须新增 |
| C2 | 快照持久化 + 恢复逻辑 | **真缺口**（设计已就绪 §2） | 窗口原子能力齐备，缺"采集→落盘→恢复"编排 |
| C3 | 档案扩展字段 | **小缺口（可绕过）** | `profile_basic` 无扩展列（`0001_init.sql:88-95`）；最小方案用 config 键 `profile.ext.*`，零迁移 |
| C4 | AI current 的 core 侧投影 | **不是缺口，是接线** | `get_config/put_config` 已有（`commands.rs:26-39`），只差键约定与读写路径 |
| C5 | 精确 Z 序恢复 | **能力边界**（非缺口） | `EnumWindows` 序为近似；v1 不承诺精确 Z 序 |
| C6 | 跨重启窗口重认领 | **能力边界**（非缺口） | hwnd volatile；需 `exePath` 匹配策略（v2） |
| — | "完成工作" | **产品设计项 PD-001** | 按指令**不列为缺口**、不发明按钮 |

---

## 8. 等待 UI Skill 的事项

### 视觉实现冻结范围（UI-04 期间我方不碰）

| 页面/文件 | 冻结原因 |
|-----------|---------|
| `LearningView.vue` | 学习目标入口 |
| `NavSide.vue` | 导航设备入口 |
| 新增的独立 AI 助手页 | 新页面 |
| `ModeView.vue` / `ModeBar.vue` | 工作模式窗口 Resize 相关 UI |
| `ProfileView.vue` | 档案扩展接口 |
| `LifeView.vue` | 生活插件区域 |
| `DashboardView.vue` + `widgets/*` | 首页响应式 |
| 所有 view 的滚动容器样式 | 页面滚动体验 |

### 可并行安全区（我方现在就能动）

- `core/`（与 UI 视觉无关的部分，如 AI current 投影、快照数据模型骨架）
- `tools/`（验收脚本整理与回归）
- `docs/`
- `ui/src/motion/`（引擎内部增强，不动消费方）
- `DevMotionHarness.vue`（dev-only）

### 交接口径

UI-04 交付后，我方做 **"接线 not 重画"**：只加 Motion/Skin token 与契约调用，不改视觉实现。若发现必须改视觉，先提方案等确认。

---

## 9. 建议下一阶段施工顺序

### 9.1 依赖关系（为什么是这个顺序）

```
统一浮层 ──┬─→ Toast 接 overlay Motion
           ├─→ Skin 换组件形态的前提
           └─→ AI Provider 模式建议提示（§3.5 第 4 步）
服务收口 ──→ 后续所有页面改动的安全网
Cinema 接线 ──→ 依赖 UI-04 的工作模式页定稿
快照持久化 ──→ 独立于前端，但恢复 UI 依赖 UI-04
```

### 9.2 排期建议

**A. UI-04 进行期间（只做安全区，零视觉冲突）**
1. `core`：AI current 读写投影（新增 config 键路径，零 UI 改动）
2. `core`：Workspace Snapshot 数据模型定稿评审（§2）+ 采集函数骨架（不接线、不落盘）
3. `ui/src/api`：UI Contract v1 常量表（命令名/事件名，**纯新增文件**）
4. `tools`：回归脚本清单化（verify_tech01 / skin_engine / perf 三件套编排）
5. `docs`：S2 边界与 remount 语义文档（§5 第 3 项剩余工作）

**B. UI-04 交付后（按序）**
- IP1 浮层统一（Toast/Modal 组件 + overlay Motion 接线）
- IP2 service 收口（aiService + contracts 落地 + 3 处越层收编）
- IP3 Motion 接线（Cinema 接真实链路 → Drag/Resize → 局部状态 token 化）
- IP4 Skin 产品入口（Settings 选择器 + config 持久化）
- IP5 Workspace 退出恢复（快照落盘 + 恢复降级链）
- IP6 core 双通道同源试点（3 模块）
- IP7 安全加固（插件桥 origin 校验 + sidecar 契约校验）

### 9.3 需要白宇拍板的三件事

1. **"工作模式窗口 Resize" 指哪一种**（§4.2）——决定是否新增 Core 命令
2. **快照存储策略**：先走 config 键（零迁移）还是直接上新表 0009（语义更正，需迁移）
3. **AI current 的 canonical 落点**：确认采用 §3.2 的"core config 为准、localStorage 降级为缓存"

---

*本轮零代码修改。所有"实测"结论均可在标注的文件:行号处复核。*
