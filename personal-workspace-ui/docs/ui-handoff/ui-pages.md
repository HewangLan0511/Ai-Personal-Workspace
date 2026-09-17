# 逐页结构说明 · Personal Workspace

> 交接文档 3/6。每页给出布局、信息优先级与不可破坏点。路由顺序按使用频率排列。

## 首页 `#/home`

**布局**（`.ws-home` + `.home-split`）：
```
Hero（当前工作大卡，唯一视觉焦点，t-display 问候语）
├─ 左主列：最近使用（.grid-recent，6 列 app 方块，可拖拽排序）
└─ 右列（minmax(272px,1fr)）：今天（行动中心：日程/待办摘要 + 设备 ghost）
我的工作空间（ws-grid 卡片网格 + 新建虚线卡）
```
- **信息优先级**：问候+当前工作 > 最近使用 > 行动中心 > 工作空间卡。Hero 是页面唯一 display 级标题，禁止再加同级元素。
- **可定制**：`HOME_SECTIONS`（当前工作/最近使用/我的工作空间/今天）可开关；`WIDGETS` 组件区 5 卡可开关排序；「最近使用」顺序可拖。
- **响应式规则**：`data-cw` 档位收紧时 Hero 与右列**纵向堆叠**，内容零删除；`grid-recent` 6→3→2 列。**任何档位禁止标题竖排/模块挤压**（列 minmax(0,…) 护栏是结构性的，不许删）。

## AI 助手页 `#/ai`

- **结构**：page-head（标题 + 聊天/工作空间助手 tabs + `当前模型：X ▼` chip→模型管理）+ `.ai-grid`（左：历史会话列表；右：聊天卡）。
- **双模式区别**：
  - **聊天**（`aiTab='chat'`）：聚焦会话、多轮讨论；副标强调「随手一问用右侧 dock」。
  - **工作空间助手**（`aiTab='ws'`）：头部亮「已允许访问当前工作空间」live 徽章；会话列表过滤 `mode='ws'`；与当前工作空间上下文绑定。
- **模型 chip**：点击跳模型管理（来源记忆回跳）；AI dock 面板内是同域双模式切换（`ai-mode`），与页面 tabs 独立。

## 模型管理页 `#/models`

- **定位**：工作台的模型控制中心，**不是开发者配置页**；用户只见 OpenAI / 本地模型 / 个人Agent。
- **当前模型区**：card--lg —— 名称 + 状态 chip（●已连接/●本地运行/○未配置）+ Provider chip + 延迟 chip（演示）+ 切换模型按钮（drawer）。
- **模型列表**：`.model-grid` 卡片（名称/Provider 展示名/状态/延迟 + 查看·设为默认·测试连接·删除）；底部虚线添加入口；空态 = 「还没有添加模型 / 连接一个AI模型，让工作台拥有自己的智能」+ 空态内添加按钮。
- **添加流程**：类型三选卡（API🌐/本地💻/Agent🤖）→ 按型出字段（API=Provider/Endpoint/Key；本地=地址/模型名称；Agent=名称/通讯方式）→ 添加即时上卡。Key 只显示「已保存/未配置」，永不回显明文。
- **返回**：来源记忆 `models-back`（AI 页进→回 AI 页；设置进→回设置；直链→设置）。

## 个人档案页 `#/profile`

- **展示态**：page-head（avatar + 昵称 t-page + 方向副标 + 签名行）+ 编辑资料按钮 + AI 建议卡（确认/忽略）+ 兴趣方向 & 技能 chips（g2 左卡）+ 项目经历 timeline（g2 右卡）+ 档案扩展块（`#profileExts`，来源 chip + pending 确认流）。
- **编辑态**：「编辑资料」→ **原位展开编辑卡 `#profileEditor`**（不跳页不遮挡）：昵称（聚焦全选）/ 签名 textarea（60 字计数，空=默认态）/ 标签（删·加·推荐）/ 头像行（预览 + 更换头像 drawer：首字母+8 预设+上传占位）。取消 = 整体还原快照；Esc 取消（弹层优先）。
- **字段结构**（profileField，接 Runtime 的唯一契约）：
```js
{ id:'nickname'|'avatar'|'signature'|'tags'|'tagline'|…,
  label, value, editable, type:'text'|'avatar'|'multiline'|'tags'|'email'… }
```
  展示态 DOM 带 `data-field/data-editable/data-type` 投影。头像 value 语义：`''`=首字母，emoji=预设，未来 `custom:<引用>`=上传。

## 工作空间（列表 + 工作模式）

**列表页 `#/workspaces`**：page-head（自动/固定布局 seg + 创建按钮）→ **工作模式模板区**（`state.wfModes` 编程/学习卡 + 创建模式虚线卡，点击=准备流程后进入）→ ws-grid（12 列，size-l span6 / m·s span3，minimap + 使用次数；卡片可拖排序，拖后自动转固定布局）。

**工作模式 `#/run`（cinema 沉浸态）**：
- **run-head**：返回/emoji/名称/工作中 live 徽章 + 布局 seg（自由|自动整理|聚焦）+ 排列 seg（自动|手动）+ 恢复默认/保存布局 + 时钟。
- **状态栏 `#runStatus`**：当前任务（未设置⇄正在进行：X）· 应用 chips（●运行中/等待打开/已关闭，点击三态演示）· 布局（自动布局⇄手动调整·xx）· 模式 chip（开模板 drawer）· 布局结构入口（drawer 实时推导窗口关系树，重叠>30% 判浮动）。**所有变化走 `refreshRunStatus()` 局部重写**。
- **appbar**：软件标签页（点击置顶窗口并同步 active；点窗口反向同步）；AI 标签 = dock 开关。
- **窗口表现**：见 ui-components.md Workspace Window（拖拽/吸附/编排/保存恢复）。
- **切换模式体验**：prep overlay（恢复应用/恢复布局/同步状态三步点亮）→ 进入 → toast「工作空间已准备完成」；纯视觉 mock。

## 学习系统 `#/learn`

- **结构**：学习目标大卡（`state.learnGoal`：类型 chip + 名称 + 水平/周期 + 修改目标 drawer + AI 重新规划）→ 进行中课程卡（progress + 目标/下一步 + 继续学习）→ 学习路线 timeline（分组 chip + done/cur/todo 状态，cur 加「进行中」badge）。
- **规则**：目标卡是页面锚点；路线节点状态三值（done✓ / cur 高亮 / todo 灰）。

## 生活区域 `#/life`

- **插件槽位规则**：`LIFE_SLOT_DEFS`（7 槽定义：今日使用/天气/消息/音乐…）+ `state.lifeSlots`（顺序数组，on=显示，span=跨列）。页面 = 按 slots 顺序渲染卡片网格；卡右上角来源标注（系统/插件名）；管理抽屉开关槽位；市场虚卡一键添加。
- **规则红线**：槽位是"插件卡片"不是仪表盘小工具——每卡必须有来源语义；今日使用（span2）是系统级槽位与插件同构表达。

## 其他页（简）

- **软件 `#/apps`**：GROUPS 分组网格 + 右键菜单（启动/加工作空间/设置）。
- **项目 `#/project`**：项目卡 + 时间线。
- **设备 `#/device`**：系统状态行 + 连接设备虚卡。
- **插件 `#/plugins`**：插件卡开关 + 开发者模式入口。
- **设置 `#/settings`**：左分类 subnav（外观/工作空间/**AI 与模型**/软件/插件/数据/关于）+ 右 set-body 行式控件；分类切换局部换 `.set-body`（S2 样板）。
