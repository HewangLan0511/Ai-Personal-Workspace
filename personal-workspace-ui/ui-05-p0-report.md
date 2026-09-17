# UI-05-P0 验收报告 · Workspace Engine 窗口系统升级（2026-09-15）

Workspace 从"可拖动窗口容器"升级为"桌面级窗口编排系统"。
完成后停止，等待验收，不进入 UI-05-P1。

---

## 一、修改说明

### 1. 布局模式（Task 1）
- 工作模式顶部工具栏新增布局 seg：**[自由] [自动整理] [聚焦]**（`data-act="run-layout"`）。
- `state.run.layoutMode: 'free' | 'tile' | 'focus'`；切换只写窗口 inline 几何 + seg on 态，
  **不 render()（S2 保持）**；切换后自动进入"手动调整"态（手柄显现，可继续微调）。

### 2. 自动排列 / 聚焦（Tile Layout）
- `tileRects(n)` 通用算法，**按数量推导不写死**：
  - n=1 全屏；n=2 左右分屏（Case 1）；
  - 偶数 n：均分网格（4→2×2、6→3×2）；
  - 奇数 n≥3：主窗左侧 62% 大区 + 其余右列均分（3→主+2，Case 2）。
- **排槽规则考虑当前窗口大小**：active 窗口优先占主位，其余按当前面积降序。
- 聚焦布局 `focusRects(n)`：active 74% 大区 + 其余右列 26% 条带（Stage Manager 式）。
- 应用时逐窗 `flash()`（复用 just-swap 高亮）作为状态变化反馈。

### 3. 窗口吸附（Task 2 / Snap）
- 拖动靠近**舞台左缘→左半区、右缘→右半区、顶部→最大化**，以及**邻窗边界→与其同高的一侧区域**
  （垂直中心需在重叠范围内），28px 进入范围。
- 吸附预览 `.snap-ghost`：品牌虚线框+浅底，`pointer-events:none`，**纯视觉反馈层**——
  拖动过程 1:1 跟手完全不受影响（e2e 实证：中途无预览且位置精确跟手），松手才落位。

### 4. Active Window（Task 3）
- 点击窗口立即 active（沿用 `frontWin` 递增 z-index），进入工作模式即默认 active 当前标签页窗口。
- active 表现：边框强化 + shadow-lg + 3px 品牌环（全部既有 token）；**非活动窗 opacity 0.85**
  （用 `:not(.carrying)` 避让，拖拽时其余窗 0.72 的降权优先级不受影响）。

### 5. 窗口状态栏（Task 6）
- 标题栏新增 `.win-role`：active 常显「● 当前工作窗口」（品牌色），其余窗口**悬停才显**
  「辅助窗口」——按需显露，不加重视觉负担。

### 6. 布局保存升级（Task 7 / 8）
- `customLayout` 扩展为 `{ws, mode, rects}`（见数据结构），自由/平铺/聚焦都可保存。
- **重进恢复**：带着已保存布局重进工作模式 → 几何恢复 + 布局模式 seg 恢复 + 进入手动态。
- "自动排列"（run-mode auto）语义不变：清空自定义布局回默认，同时 layoutMode 归位 free。

## 二、新增组件说明

| 组件 | 说明 |
|---|---|
| 布局 seg | run-head 内 3 键，复用 .seg / ico('grid'/'auto'/'square') |
| `tileRects(n)` / `focusRects(n)` | 纯函数布局算法，输出 %-矩形数组 |
| `applyRunLayout(mode)` | 槽位排序 + 写 inline 几何 + flash + customLayout 持久化 + seg 局部同步 |
| `updateSnap(win)` / `clearSnap()` / `snapZone` | 拖动中吸附区计算与预览层管理 |
| `.snap-ghost` | 吸附预览层（absolute，z=5，pointer-events:none） |
| `.win-role` | 标题栏角色标注（CSS content，无 JS） |
| `state.run.layoutMode` / `state.rsMini` 等 | 见数据结构 |

**未删除任何既有组件**；DOM 结构、拖拽逻辑、resize 逻辑、customLayout 结构全部原样扩展。

## 三、数据结构说明

```js
// customLayout v2（向后兼容：缺 mode 视为 'free'）
state.run.customLayout = {
  ws: 'ai',                    // 所属工作空间
  mode: 'free' | 'tile' | 'focus',
  rects: [ {app:'vscode', x:0, y:0, w:62, h:100}, ... ]   // 百分比几何
};
state.run.layoutMode = 'free' | 'tile' | 'focus';
```
- 保存时 rects 从 DOM inline 几何读回（与 v1 同源）；
- 重进时 `mode` 驱动 seg on 态与 `state.run.mode='manual'`；
- run-mode=auto / reset-layout 清空 customLayout 并复位 layoutMode='free'。

## 四、动效使用说明

**零新增 token、零新增 keyframes。** 用到的动效全部既有：
- 吸附预览淡入 = 既有 `fadeIn` + `--dur-fast`；
- 排列/吸附落位反馈 = 既有 `flash()`（just-swap，--mt-dur-highlight）；
- 无窗口飞行动画、无大量 transform、无 3D 效果。

## 五、验收结果（硬判据全绿）

| 门禁 | 结果 |
|---|---|
| 语法门禁 | OK（4605 行） |
| `verify_ui05p0.py`（新增，7 条） | 7/7 |
| 回归 8 套件（S2/折叠展开/widget-dock/toast/win_front/ui04b/ui04c/ui04cp0） | 45/45 |

Case 对照：Case1 tileRects(2)=左右分屏 ✓（算法级）；Case2 3 窗自动整理=主+右两列 ✓；
Case3 拖近边缘出预览、松手正确吸附 ✓（且中途 1:1 跟手无预览）；Case4 点击即突出（sel+z 最高+
他窗 0.85+角色标注）✓；Case5 保存→退出→重进，几何与布局模式完整恢复 ✓。
技术约束：resize/拖动回归锚点通过 ✓、S2 通过（stageGrid 身份保留）✓、0 新 token ✓、
响应式状态机套件（ui04c/ui04cp0）全绿 ✓。

## 六、未完成风险

1. **邻窗吸附的插槽宽度**：当前邻窗边界吸附预览"与其同高、延伸到舞台边缘"，未做 Windows
   Snap 的"四分之一区"与多级分区——属 P1 深化空间。
2. **tile/focus 后手动微调**：微调后 layoutMode 仍是 tile/focus 但几何已偏移；保存时会如实
   保存当前几何（mode 字段保留），语义上"模式的最后一次排列结果+手动偏移"。是否需要
   "微调即自动转 free"待产品定夺。
3. **窗口数量动态变化**（本阶段无关闭/新开窗口交互）：tileRects 已按任意 n 通用，未来接入
   窗口增删时重排无需改算法。
4. **键盘编排**（Win+方向键式快捷键）未做，属无障碍/效率增强，建议 P1。
