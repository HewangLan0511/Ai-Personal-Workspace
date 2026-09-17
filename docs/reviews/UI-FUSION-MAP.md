# UI-FUSION-MAP · 设计资产 → 真实程序 映射表（TECH-07-B）

> 依据：`personal-workspace-ui/`（单文件原型 + design-system / motion-system / skin-system / ui-handoff）
> ↔ `ui/`（Vue/Tauri）+ `core/`（Rust）。配套设计：`docs/tech/TECH-07-B-ui-fusion-design.md`。
> 融合基线很高：模型中心 / AI 助手 / 个人档案三轮已真实化；**缺口集中在 Workspace / Run / Window / Mode 的 UI 侧**。

---

## 一、领域映射总表

| 设计域 | 原型载体 | core 表 | core command | UI service | runtime / 状态 | 融合状态 | 主要缺口 |
|---|---|---|---|---|---|---|---|
| **Workspace**（工作空间） | `#/workspaces` ws-grid 卡片 + Dashboard「我的工作空间」 | ❌ 无专属表（**定案：运行态=RunRecord 内存 + `workspace.snapshot.last` 快照键，B-0 已设计**） | `modes_current` / `mode_apply` / `mode_exit` / `mode_restore` | `modeService.ts` | `ui/src/workspace/`（TECH-02 冻结内存态）+ core `RunRecord` | ◐ 半 | 原型工作空间卡（minimap/使用次数/size-l·m·s）无真实数据源；workspace 域零 core（有意），缺注入适配器 |
| **Run**（工作模式沉浸页） | `#/run` cinema：run-head（布局 seg 自由/自动/聚焦 + 排列 seg）+ `#runStatus` 状态栏 + appbar 软件标签页 + 窗口舞台 | `work_modes` / `layouts` | `mode_apply` / `mode_progress` / `mode_cancel` / `mode_exit` / `modes_capture_current` | `modeService.ts` | **真实应用无对应路由**（`DevWorkspaceHarness` 是 dev 固件，不进 IA） | ❌ 缺 | **最大缺口**：缺 `/run` 页；原型的窗口舞台是 DOM mock，真实化后 = 真实窗口的控制面+状态投影 |
| **Window**（窗口编排） | `.stage > .win`（拖拽/8 向缩放/吸附三类/置顶/appbar 双向同步/`customLayout` 保存恢复） | ❌ 无表（窗口是 volatile 事实） | `windows_list` / `windows_find` / `windows_rect` / `windows_place` / `windows_activate` + `monitors_list` | `layoutService.ts`（place/apply） | core `window_manager`（place/activate/find）；DOM 编排在原型 | ◐ 半 | core 侧能力齐（07-A 审计）；缺「DOM 编排动作 → windows_place/layout_upsert」桥；缺优雅关闭（WM_CLOSE） |
| **Application**（软件库） | `#/apps` GROUPS 分组网格 + 右键菜单（启动/加工作空间/设置） | `apps` 表（0001 建 / 0002 加 pinned） | `apps_list/add/update/delete` / `apps_launch` / `running` | `appsService.ts` | core `RunningApps`（appId→pid）+ `stores/apps.ts` | ✅ 基本融合 | 「加工作空间」动作缺落点（→ Mode apps 名单，走 modes_update） |
| **Layout**（布局） | 布局 seg（自由/自动整理/聚焦）+ `customLayout={ws,mode,rects}` | `layouts` 表（0001/0004 ai_sidebar）+ `config/layouts/*.json` 导出品 | `layouts_list/get/upsert` / `layout_apply` | `layoutService.ts` | core `LayoutRepo` + `window_manager::apply`（z 序/重试/步进） | ◐ 半 | 原型三布局模式的语义未映射：自动整理→tile slots、聚焦→focus slots、自由→customLayout；UI 布局编辑器（LayoutView）与原型交互形态未对齐 |
| **Mode**（工作模式模板） | `#/workspaces` 工作模式模板区（`state.wfModes` + applyWfMode）+ 模式创建抽屉 + prep overlay | `work_modes`（0001/0003 switch_policy） | `modes_*` 9 个 + `modes_remember_switch` | `modeService.ts` | core `scheduler`（七步流水线/状态机/策略）+ `ModeView.vue`（已接真实 apply/progress/exit/capture） | ✅ 大体融合 | prep overlay 三步点亮是纯视觉 mock → 应接 `mode_progress` 七步真值；模式卡片缺 useCount/lastUsedAt 展示接线 |
| **AI Sidebar**（AI dock） | `.ai-dock`（dock-rail 48px + dock-panel 360px，聊天/工作空间助手双模式） | canonical 键 `ai.provider.current` / `ai.model.current`（config） | `ai_chat` / `ai_cancel` / `ai_preview_context` / `get_config`/`put_config` | `ai/assistant/*`（bridge/service/session/transport）+ `stores/ai.ts` | `AiSidebar.vue`（TECH-05-D 真实对话） | ✅ 已融合 | 「工作空间助手」模式绑定当前工作空间上下文——依赖 Workspace 聚合视图（F2 后可接 `mode.context`） |
| **Profile**（个人档案） | `#/profile`（profileField 契约 + 原位编辑卡 + 头像 picker + 扩展块 pending 流） | `profile_basic/skills/projects/timeline` + `pending_suggestions` + config `profile.avatar` | `profile_*` + suggestions 命令族 | `profileService.ts` | `stores/profile.ts`（阶段 7 重写） | ✅ 已融合（TECH-06-B 审计确认真实持久化） | 原型扩展块（`#profileExts` 来源 chip）↔ `pending_suggestions` 已接；头像 `custom:<引用>` 上传语义未实现（占位） |
| **Model Center**（模型中心） | `#/models`（当前模型卡/模型网格/添加三选卡/来源记忆回跳 `models-back`） | `ai.models.registry`（契约 v13，TECH-06-B）+ 凭据存储 + canonical 双键 | `ai_info` / `ai_set_credential` / `ai_delete_credential` / `ai_list_models` / `get_config`/`put_config` | `ai/model/`（registry/ports/bridge/archive）+ `useCurrentModel.ts` | `ModelsView.vue`（TECH-05-C P0-1 + TECH-06 真实连接+持久化） | ✅ 已融合 | 探测状态不持久化（反假绿，**有意行为**）；延迟 chip 原型是演示值 → 接真实 check 耗时 |

## 二、页面级映射

| 原型路由 | 真实路由 | 视图 | 状态 |
|---|---|---|---|
| `#/home` | `/dashboard` | DashboardView | ✅（widget 数据源部分 mock） |
| `#/ai` | `/ai` | AiView | ✅ 真实对话 |
| `#/models` | `/models` | ModelsView | ✅ 真实连接+持久化 |
| `#/profile` | `/profile` | ProfileView | ✅ 真实持久化 |
| `#/workspaces` | `/mode` | ModeView | ◐ 模板区真实 / 工作空间卡区缺 |
| `#/run` | **（缺）** | — | ❌ 最大缺口（F2 新增，不删任何既有结构） |
| `#/learn` | `/learning` | LearningView | ✅ |
| `#/life` | `/life` | LifeView | ✅ |
| `#/apps` | `/software` | SoftwareView | ✅ |
| `#/project` | `/project` | ProjectView | ✅ |
| `#/device` | `/device` | DeviceView | ✅ |
| `#/plugins` | `/plugins` | PluginsView | ✅ |
| `#/settings` | `/settings` | SettingsView | ✅ |
| — | `/layout` | LayoutView | 真实应用独有（布局编辑器），原型无对应——保留，作为 Run 布局 seg 的深编辑入口 |
| — | `/dev/motion` `/dev/workspace` | dev 固件 | 保留（不进 IA） |

## 三、原型交互红线 → 融合验收判据（不降低复杂度的具体含义）

| 原型红线（ui-interaction / ui-components） | 融合后的验收判据 |
|---|---|
| 窗口拖动/缩放 1:1 跟手、绝无过渡；`.snap-ghost` 只在拖动中显示、松手才落位 | DOM 拖拽层行为不变；松手落位时新增「几何 → windows_place」调用，失败回滚 DOM 几何并 toast |
| 吸附三类（edge 半区+邻居填充 / swap≥55% / insert 贴缘对半） | 交互完全保留；落位语义增量映射：edge/insert → 归一化 slot 写回 layout 草稿；swap 为纯前端几何互换 |
| appbar 标签 ⇄ 窗口点击双向同步（active 一致） | 标签点击 → `windows_activate(hwnd)`；窗口前台变化 ← 事件/轮询反向同步 active |
| S2 局部 diff（禁止整页 render，容器节点身份不变） | Run 页状态栏沿用 `refreshRunStatus()` 式叶子刷新；Vue 侧对应「按叶子组件更新」，不做整页重挂载 |
| Esc 优先级链（Layer > 页面编辑卡）；drawer 先退场再清 DOM | Vue 弹层体系按同一优先级实现；不简化为单一 modal |
| toast 纪律（≤2 条 / 2200ms / 一条一事；肉眼可见的连续操作只 aria-live） | `useToast` 已对齐；Run 页新增反馈沿用 |
| 模型 Key 永不回显明文 | 已对齐（TECH-06 凭据掩码） |
| profileField 契约（`data-field/data-editable/data-type` 投影） | 已对齐（阶段 7 profileService） |

## 四、原型状态接入口索引 → 真实数据源

| 原型接入口（handoff §状态数据命名空间） | 真实数据源 |
|---|---|
| `state.run` + `WS`（`applyRunLayout` / `customLayout`） | `ModeRunAggregate`（B-0 设计）+ `layoutService.apply/place`；customLayout → `layout_upsert`（captured 草稿） |
| `state.wfModes`（`applyWfMode`） | `modeService.list/apply`（已接） |
| `state.models` + `currentModel` | `ModelRegistry` + canonical（已接，TECH-06） |
| `state.profile.fields[]`（`fieldOf`/`profile-save`） | `profileService` + `stores/profile`（已接） |
| `state.lifeSlots` + `LIFE_SLOT_DEFS` | `lifeService`（已接，TECH 阶段 7/8） |
| `state.learnGoal` | `learningService`（已接） |
| `state.profileExts` | `pending_suggestions`（已接） |
