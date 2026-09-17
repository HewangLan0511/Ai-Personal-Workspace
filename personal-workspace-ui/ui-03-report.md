# UI-03 实施报告 · 桌面工作台产品完成度优化

目标：不新增功能，优化已有桌面工作台的完成度。四处优化全部落地于 `index.html`（12 处编辑）。
约束遵守：0 新增 token、0 新增动画体系、全部复用既有 Motion Token 与组件、信息架构未动、S2 纪律已验证。

---

## 1. 工作模式拖动反馈（过程 + 落位）

### 修改前
- 拖动过程：窗口纯几何跟随（left/top 内联赋值），窗口外观与静止时完全相同，唯一反馈是 body 光标变 grabbing——"我在搬这个窗口"没有视觉承载。
- 落位：UI-02 已接 `flash()`（just-swap / --mt-dur-highlight），保留。

### 修改后
- **拖起即"抬起"**：pointerdown 命中 win-bar/win-handle 时给被拖窗口加 `.win.carried`——`box-shadow:var(--shadow-lg)`（既有最大档阴影）+ `border-color:var(--brand-300)` + `z-index:6`，同时 `.stage.carrying` 让其余窗口 `opacity:.72` 退后。**"被搬运的窗口浮在别的窗口之上"的空间关系一眼可读。**
- **松手还原 + 落位脉冲**：`onUp` 摘除两个 class（已在 DOM 层面复位），保留既有 `flash()` 落位高亮。
- **跟手不受影响**：left/top 依然没有过渡（1:1 跟手铁律）；唯一的过渡是 `.win` 既有 box-shadow/border-color 过渡上**补了一项 opacity**（同 `--dur-fast`），只作用于"抬起/放下"这一次状态切换，不跟随指针。

### 动效使用说明
新增 CSS 规则 3 条 + `.win` transition 补 1 项 opacity，全部引用既有 token（`--shadow-lg`/`--brand-300`/`--dur-fast`/`--ease-out`）。**0 新 keyframes、0 新 token、0 跟随动画。** 类名特意避开既有 `.dragging`（首页网格排序在用，防止选择器串扰）。

## 2. AI 入口认知统一

### 修改前（三个入口三个名字）
| 入口 | 名称 | 模式叫法 |
|---|---|---|
| 左侧导航 | 「AI」 | 普通聊天 / 工作空间助手 |
| 右侧全局 dock | 「AI 助手」 | 聊天 / 工作区 |
| 运行模式 ai-fab | 「AI 助手」 | — |

同一个"工作空间模式"在页面叫"工作空间助手"、在 dock 叫"工作区"；页面 tab 又叫"普通聊天"——用户需要自己建立"这三个是同一个东西"的映射。

### 修改后
- **命名归一**：导航项「AI」→「AI 助手」；设置页分类「AI」→「AI 助手」；dock seg「工作区」→「工作空间助手」；页面 tab「普通聊天」→「聊天」。现在所有入口统一为：**入口都叫「AI 助手」，两个模式都叫「聊天 / 工作空间助手」**。
- **定位文案区分**（采纳 review P1-4 建议，功能不动）：
  - AI 页（聚焦会话语义）：聊天 tab 副标「聚焦会话 · 适合多轮讨论与长任务；**随手一问用右侧的 AI 助手**」；工作空间助手 tab 副标「聚焦当前工作空间的深度协作 · 需要你授权访问」。
  - dock 保持"随手问"的轻量姿态，文案未加重。
- 一致性收尾：设置页「当前助手」描述同步、spec 页 mock tab 同步、代码注释同步。

## 3. 工作模式状态感

### 修改前
进入工作模式后：侧栏收起 + 窗口落位动画（既有 cinema 机制），但 run-head 只有「emoji + 名称 + 工作中」，页面没有告诉用户"这是一个工作空间"以及"窗口可以拖"。

### 修改后（纯状态呈现，无动画依赖）
1. **run-head 身份行**：名称旁新增 t-cap「工作空间 · N 个应用」——明确"你在一个工作空间里，这里是它的全部应用"。
2. **stage 常驻提示 chip（.stage-hint）**：舞台底部居中一枚胶囊（surface-1 + border + shadow-xs，pointer-events:none 不挡操作）：
   - 自动布局：「自动布局 · 拖动窗口标题栏即可手动调整」——补上"拖动是可以的"这一认知缺口（此前唯一的发现方式是误拖）；
   - 手动调整：「手动调整 · 拖标题栏移动窗口，右下角改大小」。
   该 chip 同时是第 1 项拖动反馈的引导入口。

## 4. 设置页体验（去后台控制台感）

### 修改前
页头副标「普通设置在这里，高级与开发者设置默认收起」——是对**看原型的人**说话的注释语气，不是对**用系统的人**说话的设置页语气；「动效规范：逐个场景查看时长与幅度」是规范文档语言。

### 修改后
- 页头副标：「管理外观、工作空间与数据 · **所有设置只保存在这台电脑上**」——系统设置语气，顺带把"本地优先"这一产品承诺放进设置页（与数据分类的既有文案互证）。
- 「动效规范」描述改为「查看每个界面动作的节奏与幅度，可三档对比」。
- 保留判断：设置页的左分类 + 右行式布局本身已是系统设置形态（macOS 系统设置同构），desc 措辞与"开关/分段控件"的控件语言未动——问题在文案语气，不在结构。

---

## 保留原则
1. **S2 局部 diff 纪律**：未新增任何整页重绘路径；`verify_s2_local_diff.py` 6/6（DOM 节点身份判据）。
2. **拖拽不带过渡**：窗口 left/top 仍无 transition，1:1 跟手；carried/carrying 是 class 状态切换，不跟随指针。
3. **Motion Token 复用**：阴影四档、brand 色阶、`--dur-fast`、`--ease-out`、just-swap/swapFlash 全部既有。
4. **信息架构不动**：无新增页面/路由/导航结构；AI 三入口功能原样，只统一名字与定位语。
5. **命名一致性**：`carried`/`carrying`/`stage-hint` 均为新类名（非 token），特意避开既有 `.dragging` 防串扰。

## 新增 / 删除组件列表
- 新增（均为样式规则 + 模板片段，非新组件体系）：`.win.carried`、`.stage.carrying .win:not(.carried)`、`.stage-hint`（舞台提示胶囊）、run-head 工作空间 meta 行。
- 删除：无（未删任何组件/功能）。
- 修改（纯文案/命名）：导航 AI 项、dock seg、AI 页 tab 与副标、设置页页头与两处描述、spec 页 mock tab。

## 动效使用说明
- 复用：`swapFlash`（落位，UI-02 已接）、`--dur-fast`+`--ease-out`（抬起/放下的状态过渡）、cinema/scene 既有入场。
- 新增：**0 个 keyframes、0 个 token、0 个跟随/复杂窗口管理动画**；`.win` transition 补 opacity 一项是本阶段唯一对既有动效声明的修改。

## 验收结果
| 门禁 | 结果 |
|---|---|
| `node` + `vm.Script` 语法门禁（2469 行 script） | **SYNTAX OK** |
| `verify_s2_local_diff.py`（6 用例，DOM 身份判据） | **6/6 PASS** |
| `verify_collapse_expand.py`（7 用例，真实指针拖拽） | **7/7 PASS** |
| Edge 无头 `--dump-dom` 冒烟：`#/run`、`#/ai`、`#/settings` | 全部渲染成功，新元素（stage-hint / run-head meta / 新文案）均在产物中 |

建议验收时手动确认两点（class 级行为，e2e 未单列用例）：① 工作模式拖窗口时其余窗口变暗、被拖窗口浮起；② 松手后既有落位脉冲仍触发。

**本阶段到此为止，等待验收；不进入下一阶段。**

---

# 增补（同日追加两项）

## 增补 1 · run 模式 appbar AI 标签 = dock 展开⇄折叠开关

- `toggle-dock` 的动画路径抽成 `toggleAiDock(fromRunTab)` 共用函数（rail 按钮 / ai-fab / appbar AI 标签同一种手感）。
- 标签语义 = 切换：已展开且是工作空间助手 → 收起；否则 → 展开 + 定为 workspace 模式。判断键与标签 `on` 态共用同一条件，视觉态永远预测点击结果。

## 增补 2 · 组件区可拖动换位 + dock 切换去掉"刷新视效"

### 组件区拖拽（发现真 bug 并修复）
- **现状核实（CDP 探针）**：`enableSort` 的拖拽接线一直挂着、`draggable="true"` 也在，但真实拖动第一次 `dragover` 就抛
  `insertBefore NotFoundError` 静默失败——container 绑在 `#widgetCol`，而卡片的真实父容器是内层 `.wscroll`，
  `ref`（邻居/添加按钮）不是 container 的子节点。首页网格 container 就是直接父节点所以没事。
- **修复**：`wireDrag()` / `refreshWidgetCol()` 改绑 `.wscroll`。修复后组件区拖拽完整复用既有可拖动对象动画链：
  拖起 `.dragging`（降透明+阴影+Motion Priority 让 hover 让位）、邻居 FLIP 滑开让位（`--mt-dur-reorder`）、
  落位 `just-swap` 高亮、数据与 DOM 同步、读屏播报。零新动画、零新 token。

### dock 切换"刷新视效"（根因证实 + 修复）
- **根因（探针证实）**：`toggle-dock` / `ai-mode` 处理器调 `render()`，`view.innerHTML` 整体重建——
  设置页重播 `swap-in` 淡入即"刷新视效"。探针显示展开/收起/切模式三次操作 view 首子节点身份全部丢失。
- **修复**：新增 `applyDockLocal(rebuild)`——只同步 `#aiDock` 自身（className / 必要时 innerHTML / 补挂手柄）
  与 run 页两处跟随者（appbar AI 标签选中态、ai-fab 显隐），三个入口（rail / fab / AI 标签）全部改走局部路径，
  内容区 DOM 节点身份不变。附带收益：run 模式里用户手动拖过的窗口位置不再被 dock 切换重置。

### 验收（新增正式脚本 `verify_widget_dock.py`，6/6）
| 用例 | 判据 |
|---|---|
| T1 组件区拖拽 | DOM 顺序 + WIDGETS 数据顺序都变、拖起类挂上、无 handler 异常、无 FLIP 残留 transform |
| T2 故障对照组 | 直接 `render()` 必须抹掉身份标记（证明探针有区分度） |
| T3/T4 设置页收起/展开 dock | view 首子节点身份不变 + dock 状态正确切换 |
| T5 ai 模式切换 | 身份不变 + mode/seg/权限条都真的换到 workspace |
| T6 run AI 标签开关 | 收起→标签灭+fab 现+**被拖窗口 inline 位置保留**；再点→展开+标签亮+fab 消失 |

回归：语法门禁 OK（2504 行）；`verify_s2_local_diff.py` **6/6**；`verify_collapse_expand.py` **7/7**。

### 本增补踩坑记录
- 改 `wireDrag` 时把 `const wc = ...` 一并删掉造成 `ReferenceError`，paint 后半段（mountHandles）静默中断
  ——**语法门禁抓不到，是 verify 脚本的"页面就绪"检查（rsh 手柄缺失）抓到的**。运行时接线类改动必须有 e2e。
- 断言方向错误（假设 dock 初始折叠，实际初始展开）导致 T3/T4 假失败；修正断言前先核对状态机初值。

---

# 增补 3 · Toast 队列规则（用户报 bug + 新规）

## 用户规定
同一时刻最多 2 条；新弹窗进来自动挤掉最旧的；每条要么可点击关掉、要么一小段时间后自动消失；消失要有淡出动画。

## Bug 根因（正是"弹窗滞留不消失"的来源）
1. **共享计时器**：所有 toast 共用一个 `toastTimer`，新弹窗 `clearTimeout` 会**取消旧弹窗的自动消失** → 旧弹窗永久滞留，直到数量 >3 被硬删；
2. 超额处理是 `firstElementChild.remove()` **硬删无淡出**；上限还是 3 不是 2；无点击关闭。

## 修复（`toast()` 重写 + `dismissToast()` 抽取）
- **上限 2**：第 3 条进来的同一帧，对最旧的多余项调用 `dismissToast()`——走既有 `.out` 淡出（`--mt-dur-toast-out`，reduced/off 档自动降级），淡出完成后才从 DOM 移除；
- **可点击关闭**：每条 toast `cursor:pointer` + `title="点击关闭"`，点击走同一套淡出；退场中 `pointer-events:none` 防重复触发；
- **自动消失按条独立**：每条 toast 自己的 2.2s 定时器，弹新窗不再影响旧窗寿命（核心 bug 修复点）；
- 零新增 token / 动画：进出场完全复用既有 `toastIn` / `.out` / `--mt-dur-toast-in/out`。

## 验收：新增正式脚本 `verify_toast.py`（4/4）
| 用例 | 判据 |
|---|---|
| T1 超额挤旧 | toast×3 同帧：存活 2、最旧带 `.out`（淡出中非硬删）、0.4s 后被移除、存活恒 2 |
| T2 点击关闭 | 点击后 `.out` 挂上、随后节点移除 |
| T3 自动消失 | 2.2s 后节点从 DOM 移除 |
| T4 计时器独立 | 甲先弹、1.5s 后弹乙：甲 2.8s 时必已退场（旧实现此用例必红） |

回归：语法门禁 OK（2511 行）；S2 **6/6**；折叠展开 **7/7**；widget/dock **6/6**。
