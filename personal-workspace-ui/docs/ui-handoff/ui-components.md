# UI 组件清单 · Personal Workspace

> 交接文档 2/6。所有组件在 `index.html` 中以内联 CSS + 模板字符串实现；类名即接口。
> 通用规则：视觉只允许消费 `tokens.css` 既有变量；交互时长只允许取 `--mt-dur-*` / `--dur-*`。

## Card（卡片）

- **类名**：`.card` / `.card--lg`（大内边距）/ `.card--ghost`（弱化提示）/ `.card--dashed`（虚线，AI 建议等）
- **使用场景**：一切内容分块的唯一载体 —— 当前模型卡、编辑资料卡、学习目标卡、扩展块……
- **视觉**：`surface-1` 底 + `border-subtle` + `r-xl` 圆角 + `pad-card` 内距；hover 只动 shadow（可选项）。
- **交互**：卡片本身不带点击（可点击块用 `.ws-card` 等专用类）；卡内按钮走 `btn` 家族。

## Button（按钮）

- **类名**：`.btn` + `.btn--primary` / `.btn--secondary` / `.btn--ghost` / `.btn--danger`；尺寸 `.btn--sm` / `.btn--lg`；`.icon-btn(.sm/.lg)` 纯图标钮。
- **使用场景**：primary=每屏一个主行动（保存/创建/继续学习）；secondary=次行动；ghost=低强度（取消/查看）；danger=删除类。
- **视觉**：`r-md` 圆角；icon+文字用 ico 内联；禁用态降透明度。
- **交互**：press 复用 `--mt-dur-press`（scale .985，无位移无回弹）；hover 复用 `--mt-dur-hover`。同一屏 primary 只有一个。

## Input（输入）

- **类名**：`.input(.lg)` 包裹 `input` / `textarea`；`.field > label.t-cap` 为字段标签；`.search` 搜索框。
- **使用场景**：所有文本输入（昵称、签名、模型 Endpoint、目标名等）。
- **视觉**：`surface-3` 底、无内描边；focus-within 才亮 `brand-400` 边 + `brand-50` 光圈。textarea 需 `height:auto` 覆盖（见 `.input textarea`）。
- **交互**：进入编辑态的输入框必须**自动聚焦并全选**；Enter 提交仅用于单值快捷场景（标签添加）；Esc 永远是取消。

## Chip（标签）

- **类名**：`.chip` / `.chip--brand` / `.chip--outline` / `.chip--removable`（带删除钮）；`.chip.mono` 等宽。
- **使用场景**：兴趣方向、技能、状态展示（● 已连接）、建议项、筛选。
- **视觉**：`r-full` 胶囊、26px 高、`fs-caption`；brand 变体为 `brand-50` 底。
- **交互**：可点击 chip 用 `button.chip`；带删除的用 `.chip--removable` + 内嵌 `button`（20px 圆钮，hover 才显背景）。

## Toast（反馈）

- **结构**：`#toastHost` 内 `.toast`（ico + 文案），`toast(msg, icon)` 唯一入口。
- **使用场景**：一切保存/删除/切换/演示反馈；**结果肉眼可见的连续操作（拖拽换位、排序）不弹 toast，只走 aria-live（announce）**。
- **视觉/交互**：底部居中；进 `--mt-dur-toast-in` 180ms / 出 120ms；存活 2200ms 自动退场；**最多 2 条，超额对最旧走同一淡出**；点击可提前关。
- **测试纪律**：e2e 判 toast 数量变化时注意 2.2s 存活期，长链路用例不能只查文本。

## Drawer（抽屉）

- **结构**：`layer.innerHTML = scrim + aside.drawer`，内含 `.drawer-head / .drawer-body / .drawer-foot`。
- **使用场景**：一切"选择/设置/查看"二级流 —— 目标设置、工作模式切换、头像 picker、模型切换/添加/查看、布局结构。
- **视觉**：右侧 420px（max 92vw）、`surface-overlay`、左描边 + 阴影。
- **交互**：推入 `--mt-dur-drawer` 240ms（24px 位移）；scrim 点击 = 关闭（`data-act="close-layer"`）；foot 右侧主按钮收尾；**关闭必须走 `closeLayer()`**（先播退场再清 layer），严禁直接清 innerHTML。

## Modal（居中弹窗）

- **结构**：`layer` 内 `.modal`（可配 `.modal-head/body/foot`）。
- **使用场景**：需要强聚焦的短流程（准备工作空间 overlay 是独立于 layer 的特例 `#runPrep`）。
- **交互**：进 `--mt-dur-modal` 180ms scale .98→1；Esc 关闭（弹层优先级高于页面内编辑态）。

## Sidebar（导航）

- **结构**：`.sidebar` 内 `.nav-group / .nav-item(.active) / .nav-group-title`，底部 `.nav-foot`（设置 + 设备线）。
- **交互**：点击切路由（`.active` 同步）；工作模式进入时自动收窄 `.mini`（图标态，文字 width/opacity 过渡隐藏，非 display:none）；用户手动展开过则本次不再自动收。
- **响应式**：COMPACT 限宽 `min(用户设定,180px)` 保留文字；COLLAPSED 以下 `.mini`。

## AI Dock（全局 AI 侧栏）

- **结构**：`.ai-dock` = `.dock-rail`（48px 竖条，常驻入口）+ `.dock-panel`（360px，聊天/工作空间助手双内容）。
- **交互**：展开 260ms 宽度先行、内容 120ms 后现；收起反之；工作模式 appbar 的 AI 标签 = dock 开关；`applyDockLocal()` 局部切换，绝不 render()。

## Widget Col（组件区）

- **结构**：`.widget-col`，内含 `WIDGETS`（天气/待办/正在播放/剪贴板/专注）小卡，开关走自定义抽屉。
- **定位**：**增值侧挂，非核心结构** —— COMPACT 以下整列让路（width 0 收起，非删除）。

## Workspace Window（工作模式窗口）

- **结构**：`.stage > .stage-grid > .win[data-w]`；`.win-bar`（拖拽手柄+grip）、`.win-body`（mock 内容）、8 向 `.rz-*` 热区、`.win-size` HUD、`.win-role` 标注。
- **视觉**：`r-lg` 卡片窗；active（`.sel`）= brand 描边 + shadow-lg；非活动 0.85 透明度。
- **交互**（红线级）：
  - 拖动/缩放 **1:1 跟手，绝无过渡**；拖动中 `.carried/.carrying` 过程反馈只动阴影与邻居透明度。
  - 吸附三类：edge（松手占半区 + `fillRemaining` 他窗填充）/ swap（覆盖 ≥55% 几何互换）/ insert（贴缘对半分），预览层 `.snap-ghost` pointer-events:none，**只在松手落位**。
  - 点击窗口 = 置顶（`winZTop` 递增）+ 同步 appbar 标签；appbar 点标签反向置顶窗口。
  - 布局三模式 seg：自由 / 自动整理（`tileRects`）/ 聚焦（`focusRects`），`applyRunLayout` 只写 inline 几何不 render；`customLayout={ws,mode,rects}` 保存与恢复。

## 其他复用件

- **badge-emoji**：emoji 圆角块（工作空间/模板头像）；**avatar**（.sm/.lg，档案首字或 emoji）。
- **seg（分段控件）**：互斥切换（布局模式/排列模式/主题）；`.switch` 开关；`.checkbox` 勾选。
- **progress**：进度条（.thin/.ok 变体）；**timeline（.tl-item done/cur/todo）**：学习路线/项目经历。
- **minimap**：窗口排布缩略图（ws-card 与状态区复用）；**ctx-menu**：右键菜单（100ms scale .98）。
- **pick/pick-grid**：向导选择卡（创建工作空间、添加模型类型复用）。
- **stat/spark/skel/spinner**：数值块、迷你 sparkline、骨架屏、加载圈（唯一 spin keyframes）。

## 状态数据命名空间（Runtime 接入口索引）

| 域 | state | 接入口（只换数据读写，不动 UI） |
|---|---|---|
| 工作模式 | `state.run` + `WS` | `applyRunLayout` / `customLayout` 读写 |
| 工作模式模板 | `state.wfModes` | `applyWfMode` |
| 模型 | `state.models` + `currentModel` | `fieldOf`-式的 `models.find` + `model-test/model-switch` |
| 档案 | `state.profile.fields[]`（profileField 结构） | `fieldOf(id)` + `profile-save` + `avatar-set/save` |
| 生活槽位 | `state.lifeSlots` + `LIFE_SLOT_DEFS` | 槽位开关 |
| 学习目标 | `state.learnGoal` | goal 编辑器保存 |
| 档案扩展 | `state.profileExts` | 确认/忽略回调 |
