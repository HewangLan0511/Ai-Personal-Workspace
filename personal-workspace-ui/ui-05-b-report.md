# UI-05-B 验收报告 · 工作空间状态系统

日期：2026-09-15　范围：`personal-workspace-ui/index.html`（单文件原型，纯内存 mock）

---

## 一、修改前后对比

| 位置 | 改前 | 改后 |
|---|---|---|
| run-head | `工作空间 · N 个应用` 一行静态文字 | 文字移除，工具栏保持原样（返回/emoji/名称/工作中/布局 seg/排列 seg/保存恢复/时钟） |
| run-head 下方 | 无 | **新增第二行状态栏 `#runStatus`**：当前任务 + 应用（状态点+三态文字）+ 布局 + 模式 + 布局结构入口 |
| 工作目标 | 不存在 | `未设置工作目标`（点击开 drawer 设置/建议 chip）⇄ `正在进行：RGB-T 视觉项目`（brand chip） |
| 应用状态 | 不存在（appbar 只有标签页） | 每应用 chip：● 运行中 / ● 等待打开 / ● 已关闭，默认按舞台窗口派生，点击三态循环（mock） |
| 布局状态 | 只在 seg 按钮上 | 状态栏 `布局：自动布局 / 手动调整 · 自由布局（自动整理/聚焦）`，与 seg/拖拽/吸附双向同步 |
| 工作空间页 | 只有 ws-grid | 顶部新增 **工作模式** 区：编程模式 / 学习模式 模板卡 + `创建模式` 虚线卡 |
| 切换模式 | 无此概念 | 页卡/抽屉点击 → `.run-prep` overlay（spinner + 恢复应用/恢复布局/同步状态 逐步点亮）→ 进入 run + toast「工作空间已准备完成」 |
| 布局结构 | 无 | drawer 按舞台 inline 几何实时推导：`VS Code ├ 左侧 60% · 顶 4%`，重叠 >30% 判 `浮动` |

## 二、新增/删除组件

**新增**
- `.run-status` 状态栏（`.rs-item/.rs-k/.rs-app/.rs-dot/.rs-st`）—— run-head 第二行
- `.wf-row/.wf-mode(.wf-mode--new)` —— 工作空间页模板卡
- `.run-prep/.rp-steps/.rp-step` —— 准备工作空间 overlay（独立于 layer，避免 layer 异步退场定时器误清）
- 函数：`runStatusHTML / refreshRunStatus / appStatusOf / runPrepSequence / applyWfMode / openRunGoal / openRunModes / openRunModeCreate / openRunStruct`
- ACTIONS：`run-goal-open / run-goal-suggest / run-goal-save / run-app-status / run-mode-open / run-mode-apply / run-mode-create / run-mode-ws / run-mode-app / run-mode-create-save / run-struct`
- 状态：`state.run.{goal, modeId, appState}`、`state.wfModes`（2 预设模板）、`modeDraft`

**删除**
- run-head 的 `工作空间 · N 个应用` t-cap 文字（信息升级进状态栏）

**未动**：Skin Runtime、Motion Token、tile/focus/吸附布局算法、S2 渲染管线、信息架构。

## 三、是否新增 token / 动画

**均为 0。**
- 全部颜色/字号/圆角/间距走既有变量（`--success/--warning/--text-4/--brand-*/--fs-caption` 等）
- 动效只复用既有 `fadeIn`（cinema 入场补一条 `.run-status` 规则，同一 token）、`@keyframes spin`（既有 `.spinner` 类）、`--dur-micro` hover 过渡
- 准备反馈的"逐步点亮"是 `classList.add('done')` + 既有 opacity/color 变量，无新 keyframes

## 四、验收结果（verify_ui05b.py，9/9 绿）

| # | 用例 | 结果 |
|---|---|---|
| T1 | 进入工作模式：状态栏含 当前任务/应用列表(4 chip)/布局状态 | PASS |
| T2 | 设置目标：drawer → 建议 chip → 保存 → `正在进行：RGB-T 视觉项目`；**#runStatus 壳节点身份不变**；窗口数 3 不变 | PASS |
| T3 | 应用状态 chip 三态循环 运行中→等待打开→已关闭→运行中，仅状态变化 | PASS |
| T4 | 布局结构 drawer：行数=窗口数(3)，含 `├ 左侧/右侧/顶` 描述 | PASS |
| T5 | 切自动排列 → 状态栏同步 `自动布局` | PASS |
| T6 | 工作空间页：2 预设模板 + 创建模式 → 创建「自定义模式」→ 页内即时出现新卡（3→4） | PASS |
| T7 | 点编程模式：prep overlay 出现且步骤点亮 → 进入 run，目标/模式/应用同步，3 窗几何全部在界内，toast 出现 | PASS |
| T8 | run 内经状态栏「模式」切学习模式：目标=课程学习，窗口重建为 chrome+word 且几何合法、win-bar 可拖 | PASS |
| T9 | 响应式 1920/1366/900：run 页 `scrollWidth == innerWidth`，无横向溢出 | PASS |

**全量回归**：语法门禁 PASS（3415 行 script）；既有 10 套 e2e 全绿 ——
S2 局部更新 6、折叠展开 7、widget/dock 6、toast 4、win_front 4、UI-04-B 6、UI-04-C 6、UI-04-C-P0 6、UI-05-P0 7、UI-05-snap 6 = **58/58**。合计 **67/67**。

**S2 纪律落实**：状态栏所有变化走 `refreshRunStatus()` 局部重写（T2/T3 断言壳节点 DOM 身份不变）；拖拽起手转手动态、`applyRunLayout` 落位均只局部同步状态栏，不 render、不碰舞台窗口节点。

## 五、下一步风险建议

1. **appState 与窗口真实状态可能"说谎"**：三态是纯 mock，用户把「VS Code」点成已关闭但窗口还在舞台。P4 接入真实 Application State（appId/status/windowId/layoutNode）时，派生逻辑 `appStatusOf` 是唯一替换点，已收敛。
2. **模板绑定工作空间是浅绑定**：模板只记 `ws` id，不复制布局快照；该空间的 customLayout 变化会自然带到模板。若 UI-05-C 要"模板冻结布局"，需要给模板加 rects 快照。
3. **prep overlay 时长固定 1.4s**：三步节奏写死（340ms 步进），未来接真实启动流程时改为按事件推进即可，结构已按步骤拆好。
4. **900px 宽下状态栏换行两行**：flex-wrap 保证不溢出（T9 验证），但状态栏高度会压缩舞台约 36px，属预期；若嫌挤可在 COMPACT 态隐藏「布局结构」按钮（未做，留给 UI-05-C）。

按约定停留验收，不进入 UI-05-C。
