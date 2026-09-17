# UI-04-B 验收报告 · 档案扩展系统 + 生活栏目插件化（2026-09-15）

范围：只设计 UI；不实现数据库（全部内存 mock）；不改 Skin/Motion；不新增动画体系。
执行后停留验收，不进入 UI-04-C。

---

## 一、档案页扩展系统设计

### 设计前
档案页是**固定三段**：头部（头像/标签/编辑）+ AI 建议卡 + 固定 grid（兴趣/技能 + 项目经历）。
内容写死在模板里，没有"段落"概念，AI 建议只能进顶部那张孤立卡片，无法承载"按需扩展的档案维度"。

### 设计后
档案 = **基础档案（固定）+ 扩展块系统（可增删）** 两层：

1. **基础档案不动**：兴趣方向、技能、项目经历保持原样 —— 这是档案的地基，不参与扩展。
2. **扩展块（profileExts）**：结构化段落，每块四要素——
   - `source` 来源：`ai`（AI 建议）/ `plugin`（插件同步，如"学习插件"）/ `manual`（手动添加）；
   - `status` 状态：`pending`（待确认，虚线卡+品牌底+"待确认"badge）/ `applied`（已写入）；
   - `items`：key/value 行（复用 setRow）；
   - 操作：pending → 确认写入 / 忽略；applied → 移除（trash icon-btn）。
3. **来源可追溯**：每块头部带来源 chip（AI 建议=品牌色 / 插件同步 / 手动添加），插件来源附插件名。
4. **添加入口两处**：扩展区 sec-head 的「添加扩展块」ghost 按钮 + 网格末尾 dashed 虚卡 → 同一抽屉。
5. **扩展块选择器抽屉**（复用 UI-04-A1 抽屉模式）：5 个模板（阅读清单/证书与认证/健康记录/习惯打卡/荣誉奖项），已添加显示「已添加」chip，未添加显示「添加」；添加后页面与抽屉当场同步。
6. **首屏预置 3 块**：证书与认证（手动/已写入）、课程进度（插件·学习插件/已写入）、阅读清单（AI/待确认）——三种来源、两种状态开箱可见。
7. 隐私横幅文案补一句："扩展块随时可以添加或移除"，与系统概念对齐。

### 新增/删除组件
- 新增：`#profileExts` 容器、扩展块卡（复用 card/card--dashed/setRow/chip/badge）、
  `profileExtsHtml()/refreshProfileExts()/profileExtCard()`、`openProfileExtPicker()` 抽屉、
  `PROFILE_EXT_LIBRARY`/`PROFILE_EXT_SEED`/`EXT_SRC` 常量、6 个 `profile-ext-*` handler、`state.profileExts`。
- 删除：无。基础档案与 AI 建议卡原样保留。

---

## 二、生活栏目插件化结构设计

### 设计前
`ROUTES.life` 的 5 张卡片**写死在模板里**：今日使用/天气/消息/正在播放/连接更多应用。
卡片与插件体系（PLUGINS：天气/音乐/消息插件）完全脱钩 —— 页面上看不到卡片来自谁，也没有显隐管理。

### 设计后
每张卡 = **一个插件槽位（slot）**，页面由 `state.lifeSlots` 驱动渲染：

1. **槽位定义表 `LIFE_SLOT_DEFS`**：7 个槽位 —— usage（系统）/ weather / message / music
   （对应已装插件）/ calendar / todo / clip（对应插件市场）。每个槽位：名称、来源标签、图标、
   跨度（span）、body 渲染函数（mock 内容与原页一致；新槽位为"连接后显示真实数据"的占位结果）。
2. **来源可追溯**：每张卡右上角 = 来源小字（系统 / 天气插件 / …）+ 槽位图标。延续"只展示结果，
   不展示配置"—— 配置只在抽屉里，卡片上只留一行来源标注。
3. **顺序即数组顺序**：`state.lifeSlots` 数组顺序驱动网格排布，为后续拖拽排序留好了结构位。
4. **管理卡片抽屉**（page-head「管理卡片」按钮）：全部槽位一行一条（图标+名称+来源+状态+switch），
   开关即时生效：隐藏→网格消失、恢复→回来（局部更新 #lifeGrid，不整页重绘）。
5. **市场引导虚卡插件化**：原「连接更多应用」泛泛虚卡 → 「从插件市场添加卡片」，列出未上槽位的
   MARKET 项（日程/待办/剪贴板），一键添加成真实槽位卡（占位结果态）；全部加完显示完结文案。
6. 默认槽位与原页视觉等价：usage(span2)+weather+message+music(span2)，观感不变，结构变了。

### 新增/删除组件
- 新增：`#lifeGrid` 容器、`LIFE_SLOT_DEFS`/`lifeGridHtml()/refreshLifeGrid()/lifeMarketHtml()`、
  `openLifeSlotManager()` 抽屉、`life-manage`/`life-slot-sw`/`life-slot-add` handler、`state.lifeSlots`。
- 删除：写死的 5 卡模板（内容等价迁移进槽位 body）、「连接应用」noop 按钮。

---

## 三、保留原则

1. **0 新 token、0 新动画**：全部复用既有 card/chip/badge/setRow/switch/drawer/seg/btn；
   交互反馈只走既有 toast，无新动效。
2. **S2 纪律**：所有交互（确认/忽略/移除/添加/开关）只重渲染 `#profileExts` / `#lifeGrid`
   容器的 innerHTML，容器节点身份不变（e2e 用 dataset.probe 实证）；抽屉内同步走重开抽屉函数
   （与 openPlugin 同一模式），不触发整页 render()。
3. **无数据库**：state 全部内存 mock，刷新即回默认；所有"写入"语义用 toast 表达。
4. **Skin/Motion 未动**：无新 CSS 变量、无新 keyframes；dashed/brand 底色复用既有 class。

## 四、动效使用说明
本批零新动效：确认写入/添加/移除/开关均为局部 innerHTML 替换 + 既有 toast；
抽屉开合沿用既有 drawer 进出场（scrims/drawer 原动画）。

## 五、验收结果（硬判据全绿）

| 门禁 | 结果 |
|---|---|
| 语法门禁（node vm.Script） | OK（4325 行） |
| `verify_ui04b.py`（新增，6 条） | 6/6 |
| `verify_s2_local_diff.py` | 6/6 |
| `verify_collapse_expand.py` | 7/7 |
| `verify_widget_dock.py` | 6/6 |
| `verify_toast.py` | 4/4 |
| `verify_win_front.py` | 4/4 |

verify_ui04b 判据摘要：T1 扩展区 3 块齐全+来源 chip+pending 入口；T2 确认写入 pending→applied
且容器身份保留；T3 抽屉添加/移除与页面同步、身份保留；T4a 来源标签+管理入口；T4b 天气开关
关→网格消失→开→回来、市场添加日程成真卡；T5 故障对照组 render() 必抹身份标记（探针有区分度）。

## 六、边界说明
- 扩展块/槽位顺序目前由数组驱动，「拖拽排序」未做（生活卡排序属交互增强，未在本批任务内；
  结构已按顺序数组留好位）。
- 档案页 AI 建议卡（顶部"加入技能"）保持原行为，未并入扩展块系统 —— 两条确认链路视觉与
  语义均清晰，合并属可选后续。
