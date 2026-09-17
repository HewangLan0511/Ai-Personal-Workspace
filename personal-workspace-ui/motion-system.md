# Personal Workspace · 系统化动效方案（Motion System）

> 版本：**v0.3（已实现 · UI-01）**
> 状态：**代码已落地**（`index.html` + `tokens.css`）。本轮把 §E Token、§B 原则、§C 场景全部写进了原型。
>
> **v0.3 变更**：完成 UI-01 实现层 —— Motion Token 双维度落地、卡片微交互、浮层进出场、
> 拖拽让位（FLIP）、页面切换隔离、Cinema 门限、AI 侧栏、Widget 列、状态动效、Motion Guard 三档、
> 首页首入 Entrance；新增动效规范页与三档对比页。详见 §I 实现清单与 §J 已知缺口。
>
> **v0.2 变更**：锁定 D1（View Transitions 渐进增强）、D2（Intensity 与 Duration 拆成两个独立维度）、
> D3（工作模式 560ms / 240ms 恢复交互）。详见 §0。

---

## 0. 已锁定决策（Decisions）

### D1 · View Transitions：渐进增强，且不得掩盖 S2

**结论：Motion System 不依赖 View Transitions（VT）。**

- VT 是**增强项**，不是依赖项。支持时用 VT，不支持时自动走 CSS/JS fallback，**两者共享同一套 Token**，视觉一致。
- 能力探测：`document.startViewTransition` 存在 + pack 声明 `capabilities.viewTransitions` + 未在 reduced/off 档。
- **前置门限（硬约束）：VT 必须在 S2 修复之后才能引入。**
  原因见 §A3 S2 与 §G 红线 1：VT 默认对整页做 cross-fade，
  如果 `render()` 仍然整页重绘，VT 会把"重绘"包装成一段合法的过渡动画——**问题没消失，只是被藏起来了**，
  而且整页快照会带来额外性能开销。
- 因此实现顺序上，**"局部更新不触发场景动画"是 VT 的入场券**，不是可选项。

### D2 · Intensity 与 Duration 是两个独立维度

**结论：`--mt-intensity` 只控制"动多少"，不控制"动多久"。**

| 维度 | Token | 控制内容 |
|---|---|---|
| **Motion Duration（节奏）** | `--mt-dur-*` | 动多久。独立控制，Skin 通过覆盖 duration token 或 duration preset 调节 |
| **Motion Intensity（幅度）** | `--mt-intensity` | 动多少：translate 距离、scale 幅度、opacity 强度、blur / emphasis 等视觉运动幅度 |

- 默认 `--mt-intensity: 1`。
- **intensity 不作为 duration 的乘数**——禁止出现 `calc(var(--mt-dur-*) * var(--mt-intensity))` 这种写法。
- 未来 Skin 改一个 `--mt-intensity` 就能整体改变动效风格（克制 ↔ 活泼），而节奏保持不变。
- 所有幅度基元（dist / scale / fade / blur）由 intensity 派生，见 §E2。

### D3 · 工作模式：560ms 总体过渡，240ms 恢复交互

**结论：采用 560ms，但 240ms 处即恢复基本交互；不为了压到 360ms 牺牲空间感。**

| 区间 | 内容 | 是否阻塞交互 |
|---|---|---|
| **0–240ms（主体段）** | 工作模式主体状态切换：内容区退场、面板形态、stage 底纹、顶栏/返回入口 | **阻塞，240ms 结束即恢复** |
| **240–560ms（后台段）** | 软件栏、AI 面板、Workspace UI、窗口布局落位与视觉反馈、其他非阻塞动效 | **非阻塞**，可被用户操作打断 |
| **560ms** | 达到稳定状态 | — |

- 若实测性能或体验证明 560ms 过长，**统一压缩到 ≈360ms**（按比例压：主体 160ms / 后台 200ms），
  不要单独砍掉某一段——单独砍会破坏空间感的完整性。
- 后台段必须**可被用户操作打断并立即跳到终态**，不能让点击落空（见 §E6「可交互门限」）。

---

## A. 当前 UI 动画分析

### A1. 已有基础（值得保留的）

| 项 | 现状 | 评价 |
|---|---|---|
| Motion Token 雏形 | `tokens.css` §Motion：`--ease-out` `--ease-inout` + `--dur-micro 120 / fast 160 / base 220 / slow 300` | ✅ 方向对，但**只有 6 行**，没有距离/缩放/延迟/编排维度 |
| 缓动克制 | 只两条曲线，且明文写了「禁止回弹/粒子/大幅飞入/缩放 >1.02」 | ✅ 这条纪律要继承 |
| 组件 hover 过渡 | 约 45 处 `transition:` 基本都引用了 token（micro/fast） | ✅ 一致性不错，是好的底子 |
| 降级开关 | `[data-motion="reduced"]` + `@media (prefers-reduced-motion)` 双重 | ✅ 有意识，⚠️ 手段过粗 |
| 拖拽换位脉冲 | `.just-swap` / `swapFlash`，只动 box-shadow | ✅ 已验证不产生刷新感，可作为「编排型动画」的范式 |

### A2. 现有 keyframes 清单与硬编码时长

| 关键帧 | 用在哪 | 时长 | 问题 |
|---|---|---|---|
| `viewIn` | 页面切换 | `var(--dur-base)` | 走了 token ✅ 但只有入场 |
| `toastIn` | Toast 入场 | `var(--dur-base)` | 走了 token ✅ |
| `fadeIn` | scrim | `var(--dur-fast)` | ✅ |
| `modalIn` | 弹窗入场 | `var(--dur-base)` | ✅ |
| `drawerIn` | 抽屉入场 | `var(--dur-base)` | ✅ |
| `ctxIn` | 右键菜单 | **`120ms` 硬编码** | ❌ 未走 token |
| `swapFlash` | 拖拽换位 | **`460ms` 硬编码** | ❌ 未走 token |
| `skel` | 骨架屏 | **`1.4s` 硬编码** | ❌ 未走 token |
| `spin` | Spinner | **`.7s` 硬编码** | ❌ 未走 token |
| `pulse` | 运行中状态点 | **`2.4s` 硬编码** | ❌ 未走 token |
| `pulse`（AI 相关） | — | — | — |
| Toast **出场** | JS 内联 `opacity/transform 200ms` | **硬编码在 JS 里** | ❌ 最典型的参数散落 |

### A3. 结构性问题（按严重度排序）

**S1 · 只有入场，没有出场。** 抽屉、弹窗、Toast、右键菜单、scrim 全是「打开有动画、关闭瞬间消失」——
`layer.innerHTML = ''` 一抹就没了。这是目前最伤质感的一点，用户能明确感觉到「退场是断的」。

**S2 · 页面切换动画会连坐局部更新。** `.view-enter` 挂在整页 `.page` 上，而 `render()` 是整页重绘，
所以**任何**状态变化（拖拽、开关、切 tab）都会重播一次整页入场 —— 这正是前面修掉的「刷新感」的同一个根。
动效方案必须先解决「谁有权触发场景级动画」，否则加了 View Transitions 只会把问题放大。

> ⚠️ **VT 会掩盖 S2，不是在解决 S2。** VT 的默认行为是对整页做 cross-fade 快照。
> 如果 `render()` 仍然整页重绘，VT 会把"重绘"包装成一段看起来合理的过渡动画——
> 用户不再觉得"闪"，但 DOM 依然被整体重建、滚动位置依然被重置、拖拽依然会被打断。
> **问题从"看得见"变成"看不见"，更难排查。** 所以 D1 把它定为 VT 的入场券。

**S3 · 无出场编排，也就没有"状态变化"的语言。** 卡片新增/删除、工作空间创建/删除、软件启动、
窗口布局恢复目前都是硬切，用户缺少「刚刚发生了什么」的线索。

**S4 · 缺少点击反馈（press）。** 全项目只有 hover，没有 pressed 态。桌面应用里这是很明显的缺失，
点下去没有"触感"。

**S5 · 没有 stagger。** 列表/网格是一整块同时出现，缺少层次；反过来说也没法用它做「依次落位」的沉浸感。

**S6 · 降级策略是"一刀切归零"。** 现在是 `* { animation-duration:.001ms !important }`。
问题有三：① 把 hover 的颜色过渡也杀了，界面变得生硬；② `!important` 让 Skin 无法局部覆盖；
③ 「减弱」和「关闭」是两件事，现在只有一种。

**S7 · Core 直接依赖具体实现。** `cubic-bezier(...)` 和裸 ms 出现在组件样式里，Skin 想换风格只能覆盖
`!important` 或改源码 —— 违反「Core 不依赖具体动画实现」。

**S8 · 工作模式（cinema）进出目前是硬切。** `.shell.cinema .panel` 只改了圆角，且**没有 transition**；
工作模式作为产品的分水岭，进出没有任何仪式感，这是沉浸感最大的浪费点。

**S9 · 窗口布局恢复无动画。** `initStage()` 直接按百分比定位，进入工作界面时窗口是"贴"上去的，
而 Mini Map 明明已经存了完整 layout —— 有数据却不演，很可惜。

---

## B. 动画设计原则

1. **动效是信息的载体，不是装饰。** 每一条动画必须能回答「什么变了 / 变到哪去了 / 我现在能点什么」。
   回答不了任何一个的动画，删掉。
2. **位移只在必要处，且 ≤ 24px。** 界面是"纸面"，纸不会飞。默认用 opacity + 4~8px 微调。
3. **只动 `transform` / `opacity` / `box-shadow` / `border-color`。** 禁止动 `width/height/top/left`
   做交互反馈（布局属性会触发重排，也会让相邻元素跟着抖）。
4. **入场可以慢一点，出场必须快。** 出场快 = 不挡路。建议出场 ≈ 入场的 0.7 倍。
5. **动画绝不改变命中区域。** 起始 scale ≥ .97，禁止从 0 缩放；动画期间元素**保持可点击**，
   只有"正在退场且已无意义"的元素才加 `pointer-events:none`。
6. **总时长预算：交互反馈 ≤ 240ms，场景切换 ≤ 320ms，仪式感（工作模式）≤ 560ms 且不阻塞输入。**
7. **循环动画只允许出现在 loading / 运行中指示，** 且 reduced-motion 下必须降级为静态。
8. **参数不进组件。** 组件只写意图名（`mt-enter-panel`），不写曲线和数字。
9. **可降级三档：`full` / `reduced` / `off`。** reduced 不是"没有"，是"去掉位移与缩放，保留淡入"。
10. **Skin 只调旋钮，不改结构。** 一个 `intensity` 系数就能从"克制"变"活泼"，最理想。

---

## C. 动画场景清单

| # | 场景 | 分类 | 当前 | 优先级 |
|---|---|---|---|---|
| 1 | 页面切换 | 场景级 | 仅入场、且会误触发 | P0 |
| 2 | 卡片出现 / 消失 | 内容级 | 无 | P1 |
| 3 | Hover | 微交互 | 有，散落 | P1（统一） |
| 4 | 点击反馈 Press | 微交互 | **缺失** | P0 |
| 5 | 工作模式进入 | 仪式感 | **硬切** | P0 |
| 6 | 工作模式退出 | 仪式感 | **硬切** | P0 |
| 7 | 软件启动 | 反馈 | 仅 Toast | P1 |
| 8 | 窗口布局恢复 | 编排 | **无** | P0 |
| 9 | AI 助手展开 / 收起 | 面板 | 宽度有、内容硬切 | P1 |
| 10 | Toast / 提示 | 浮层 | 入场有、出场硬编码 | P0 |
| 11 | Loading | 状态 | 有，硬编码 | P2 |
| 12 | 状态变化 | 反馈 | 部分 | P1 |
| 13 | 设置面板 | 面板 | 抽屉有、分类切换无 | P2 |
| 14 | 弹窗 | 浮层 | 入场有、出场无 | P0 |

---

## D. 每个场景的动画建议

> 时长沿用新 token 命名（见 E）：`quick 120 / base 180 / panel 240 / scene 320 / cinematic 420`。
> 「阻塞输入」= 该动画期间用户必须等待；**以下除注明外均不阻塞输入**。

### 1. 页面切换 `scene`

| 段 | 参数 |
|---|---|
| 离场 | opacity 1→0，translateY 0→**-4px**，120ms `--ease-in` |
| 入场 | opacity 0→1，translateY **6px**→0，scale .995→1，240ms `--ease-out` |
| 编排 | 首屏模块 stagger 30ms，最多 4 个 |

**硬约束：只在 `route` 变化时播放。** 局部更新（拖拽、开关、切 tab、开关抽屉）一律不触发。
这与 v1.3.1「拖拽不重渲染」是同一条纪律的两面。

**技术（D1 渐进增强）：**

| 层级 | 条件 | 行为 |
|---|---|---|
| 增强 | 支持 `document.startViewTransition` + pack 允许 + 非 reduced/off | VT 接管，命名 `view-transition-name: pw-scene` |
| 兜底 | 不支持 / 被禁用 | CSS/JS 双段：离场 120ms → 换 DOM → 入场 240ms |
| 降级 | `reduced` | 单段 160ms 淡入，无位移 |
| 降级 | `off` | 瞬时 |

两条路径**共用同一批 Token**（`--mt-scene-*`），不允许出现"VT 版一套参数、fallback 版另一套"。
`motion.playScene()` 内部带守卫：非 route 变更时**拒绝播放**并在 dev 下告警。

### 2. 卡片出现 / 消失 `item`

| 段 | 参数 |
|---|---|
| 出现 | opacity 0→1，translateY 8px→0，scale .98→1，180ms ease-out；同批 stagger 30ms（≤6，超出同批） |
| 消失 | opacity 1→0，scale 1→.98，140ms ease-in；随后用 FLIP 补 240ms 的网格重排 |

删除走 **Toast 可撤销**，不用确认弹窗（符合"不打断"）。

### 3. Hover `hover`

统一到 `--mt-dur-quick 120ms`；位移 ≤ 2px；**禁止缩放 > 1.02**。
卡片 hover 保留现有 `shadow + border + translateY(-2px)`，时长 160ms → 统一到 token。

### 4. 点击反馈 `press` ⭐ 新增

| 段 | 参数 |
|---|---|
| 按下 | scale 1→**0.98**，80ms ease-out |
| 松开 | scale →1，120ms ease-out（**不回弹过头**，禁止 overshoot） |
| 图标按钮 | 额外一次 200ms 的 `brand-50` 背景脉冲（可关） |

桌面应用没有触感，press 是唯一替代。这是性价比最高的一条。

### 5. 工作模式进入 `cinema-in`

**D3 时间轴：总 560ms，240ms 恢复交互。**

```
0ms                    240ms                            560ms
├──── 主体段（阻塞） ────┤──────── 后台段（非阻塞） ────────┤
│ 内容区退场 160ms       │ 软件栏 tab stagger 淡入        │ 稳定态
│ 面板形态 240ms         │ AI 面板滑入                    │
│ stage 点阵淡入 240ms   │ 窗口按 layout 落位（stagger）   │
│ 顶栏 / 返回入口切换     │ 布局视觉反馈脉冲               │
└──────── 240ms 起可交互 ─────────────────────────────────┘
```

| 段 | 时间 | 内容 | 参数 |
|---|---|---|---|
| 主体段 | 0–160ms | 内容区退场 | opacity 1→`--mt-fade-from`，translateY 0→`--mt-dist-1`，`--mt-ease-in` |
| 主体段 | 120–360ms | 面板形态（圆角/内缩）+ stage 点阵底纹淡入 | `--mt-dur-panel`，`--mt-ease-inout` |
| 主体段 | 0–240ms | 顶栏 / 返回入口切换 | `--mt-dur-base` |
| **门限** | **240ms** | **恢复基本交互**（`pointer-events` 全部放开） | — |
| 后台段 | 240–560ms | 软件栏 tab 依次淡入 | stagger 30ms，单条 160ms |
| 后台段 | 240–480ms | AI 面板滑入 | `--mt-dur-panel` |
| 后台段 | 240–560ms | 窗口按 layout 顺序落位 | opacity `--mt-fade-from`→1，scale `--mt-scale-modal`→1，单窗 240ms，stagger 40ms |

**后台段规则**：可被任意用户操作打断，打断时立即 `finish()` 跳到终态，**不得让点击落空**。
顶部「运行中」绿点保留 pulse。落位期间窗口可点，不设 `pointer-events:none`。

### 6. 工作模式退出 `cinema-out`

反向但**更快**（总 ≈ 320ms）：窗口**一起**淡出（不做逐个 stagger，退场要利落）→ 面板回常规 → 内容区淡入。
退出不做仪式，用户要的是"赶紧回到工作台"。同样遵守 240ms 交互门限（退出时 ≈140ms 即可交互）。

### 7. 软件启动 `launch`

| 段 | 参数 |
|---|---|
| 被点图标 | scale 1→**1.06**→1，240ms（一次，不循环） |
| 卡片角标 | 出现 spinner（≤150ms 不显示，避免闪） |
| 反馈 | 启动中 → 已启动 → 失败，分别对应 spinner / toast / 错误态 |

**禁止全屏 splash / 遮罩。** 真实实现应接真实进程状态，不要假 timeout。

### 8. 窗口布局恢复 `layout-restore` ⭐ 高价值

进入工作界面且存在已保存布局时：

- 所有窗口 opacity 0→1 + scale .99→1 + translateY 6px→0，单窗 240ms
- 按 `x + y` 排序 stagger **40ms**（从左上往右下铺开）
- 若无保存布局：默认布局同样落位，stagger 缩到 25ms（不抢戏）
- 「保存布局」确认：所有窗口一次 320ms 描边脉冲（复用 `swapFlash` 的机制与参数）

Mini Map 已经存了完整 layout，这个动画等于把数据"演"出来，沉浸感收益最大。

### 9. AI 助手展开 / 收起 `ai-dock`

| 段 | 参数 |
|---|---|
| 展开 | 宽度 48→360，`240ms ease-inout`；**内容延迟 60ms** 淡入 160ms |
| 收起 | 内容先 100ms 淡出 → 再收宽度 240ms（避免内容被挤压变形） |
| 模式切换 | 聊天 ⇄ 工作区：内容横向交叉淡入 160ms；**容器高度固定**，禁止跳动 |

### 10. Toast / 提示 `toast`

| 段 | 参数 |
|---|---|
| 入场 | opacity 0→1 + translateY 10px→0，240ms ease-out（保留现有 `toastIn`，参数 token 化） |
| 出场 | opacity 1→0 + translateY 0→6px，**160ms ease-in**（现状是 JS 内联 200ms → 收回 token） |
| 堆叠 | 新 toast 进场时旧的上移 160ms（现状瞬移） |
| 约束 | 停留 2200ms；最多 3 条，超出最老的先走 |

### 11. Loading `loading`

- 骨架 shimmer 1400ms、spinner 700ms → **全部 token 化**
- **延迟出现：<150ms 不显示 spinner**（防闪烁，这是最容易被忽略但体感最明显的一条）
- 确定型进度：进度条 width transition 200ms，不要无限循环假装在工作
- reduced-motion：shimmer → 静态色块；spinner → 静态图标 + 文字

### 12. 状态变化 `state`

| 变化 | 参数 |
|---|---|
| 开关 toggle | 160ms（现状已有，统一到 token） |
| 状态点 / 徽标 | 颜色 120ms + 一次 scale 脉冲 200ms |
| 数值刷新（如"已使用 3h24m"） | 200ms 交叉淡入；**禁止滚动数字** |
| 错误 | 卡片描边转红 + shake 3px × 2，240ms —— **全项目唯一允许的抖动**，reduced 下改静态描边 |

### 13. 设置面板 `settings`

| 段 | 参数 |
|---|---|
| 分类切换 | 内容 160ms 淡入 + 4px 上移（**不做横向滑动**，左侧目录已足够表达层级）；实现上是真·局部 diff：只换 `.set-body` 的 innerHTML，`.set-body` 节点本身与四个容器都不重建（§I #18） |
| 面板本体 | 右侧滑入 24px，240ms（现有 `drawerIn` 参数化） |
| 高级设置展开 | `grid-template-rows: 0fr → 1fr`，240ms（比 `max-height` hack 干净，且无需测量） |
| 开发者模式 | 新分组 240ms 淡入 + 8px 上移，**不得引起整页跳动**；只重建 `.subnav` 与 `.set-body` 两块 |

### 14. 弹窗 `modal`

| 段 | 参数 |
|---|---|
| 入场 | scrim 淡入 160ms；弹窗 opacity + scale .97→1 + translateY 8px→0，240ms ease-out |
| 出场 | 弹窗 180ms ease-in；scrim 160ms 淡出（**现状全瞬消，要补**） |
| 无障碍 | 打开时焦点进入，关闭时归还来源元素；ESC 关闭 |
| 细节 | 点 scrim 关闭前给 80ms press 反馈 |

---

## E. Motion Token 设计

### E1. 三层结构

```
L0 原子层（数值）      --mt-dur-*  --mt-ease-*  --mt-dist-*  --mt-scale-*  --mt-fade-*
        ↓ 组合
L1 意图层（语义）       --mt-enter-panel-dur / -ease / -dist / -scale   ← Core 只认这一层
        ↓ 实现
L2 呈现层（关键帧）     @keyframes mtEnterPanel { from{ opacity:0; transform:translateY(var(--mt-enter-panel-dist)) } }
```

**Core 组件只允许写 L1 的名字**，不写数字、不写曲线。

### E2. L0 原子（建议值）

> 迁移映射：`micro → quick`、`fast → base`、`base → panel`、`slow → scene`（语义更准，值微调）。

#### E2.1 维度一：Motion Duration（节奏）—— 独立控制

```css
:root{
  /* 时长：从"瞬时"到"仪式"。只决定"动多久"，与 intensity 完全无关 */
  --mt-dur-instant:   80ms;   /* 按下 */
  --mt-dur-quick:    120ms;   /* hover、颜色 */
  --mt-dur-base:     180ms;   /* 小组件进出、开关 */
  --mt-dur-panel:    240ms;   /* 面板、抽屉、侧栏、弹窗 */
  --mt-dur-scene:    320ms;   /* 页面 / 场景切换 */
  --mt-dur-cinematic:420ms;   /* 工作模式：后台段主体 */
  --mt-dur-ambient:  600ms;   /* 仅 loading 循环等非交互，允许被降级为静态 */
}
```

调节节奏的**唯一**途径是覆盖这些 token（或新增 duration preset）。
**禁止** `calc(var(--mt-dur-*) * var(--mt-intensity))` 这类写法。

#### E2.2 维度二：Motion Intensity（幅度）—— 只控制"动多少"

```css
:root{
  --mt-intensity: 1;   /* 默认 1；Skin 改这一个值即可整体换风格 */
  --mt-drift: 1;       /* 位移总开关 0/1 */
  --mt-scale-on: 1;    /* 缩放总开关 0/1 */
  --mt-blur: 0;        /* 毛玻璃伴随，默认关 */

  /* ---- 幅度基元：全部由 intensity 派生 ---- */
  --mt-dist-1: calc(4px  * var(--mt-intensity) * var(--mt-drift));
  --mt-dist-2: calc(8px  * var(--mt-intensity) * var(--mt-drift));
  --mt-dist-3: calc(16px * var(--mt-intensity) * var(--mt-drift));
  --mt-dist-4: calc(24px * var(--mt-intensity) * var(--mt-drift));

  --mt-scale-enter: calc(1 - .020 * var(--mt-intensity) * var(--mt-scale-on));  /* 1 → .98 */
  --mt-scale-modal: calc(1 - .030 * var(--mt-intensity) * var(--mt-scale-on));  /* 1 → .97 */
  --mt-scale-press: calc(1 - .020 * var(--mt-intensity) * var(--mt-scale-on));  /* 1 → .98 */
  --mt-scale-scene: calc(1 - .005 * var(--mt-intensity) * var(--mt-scale-on));  /* 1 → .995 */
  --mt-scale-launch: calc(1 + .060 * var(--mt-intensity) * var(--mt-scale-on)); /* 1 → 1.06 */
  --mt-scale-layout: calc(1 - .010 * var(--mt-intensity) * var(--mt-scale-on)); /* 1 → .99 */

  --mt-fade-from: clamp(0, calc(1 - .95 * var(--mt-intensity)), 1);  /* 1 → .05 */
  --mt-fade-dim:  clamp(0, calc(1 - .60 * var(--mt-intensity)), 1);  /* 1 → .40 */

  --mt-blur-amount: calc(6px * var(--mt-blur) * var(--mt-intensity));
  --mt-shake-x:     calc(3px * var(--mt-intensity));
}
```

| intensity | 观感 | 典型 Skin |
|---|---|---|
| `0.6` | 克制：几乎不位移、淡入很浅 | Calm / 办公向 |
| `1.0` | 标准 | 默认 |
| `1.4` | 活泼：位移与缩放更明显 | Lively / 娱乐向 |

**关键：改 intensity 只改变幅度，节奏（duration）一点不变。**
这两个维度正交，Skin 可以组合出"慢而克制"或"快而活泼"，互不干扰。

#### E2.3 缓动（不属于以上任一维度，独立）

```css
--mt-ease-out:      cubic-bezier(.22,.61,.36,1);  /* 进入 */
--mt-ease-in:       cubic-bezier(.4,0,1,1);       /* 退出 */
--mt-ease-inout:    cubic-bezier(.4,0,.2,1);      /* 位移 / 布局 */
--mt-ease-emphasis: cubic-bezier(.05,.7,.1,1);    /* 工作模式：更长尾的减速，制造沉浸 */
/* 禁止：spring / bounce / overshoot */
```

#### E2.4 编排基元

```css
--mt-stagger-step: 30ms;
--mt-stagger-max:  6;
--mt-delay-content: 60ms;   /* 容器先动，内容后动 */
--mt-cinema-interactive-gate: 240ms;   /* 仪式感动效的"恢复交互"门限，见 §E6 */
```

### E3. L1 意图（Core 唯一可见的一层）

> 幅度列一律引用 **E2.2 的幅度基元**（已含 intensity 派生），不写死数字。

| 意图名 | dur（节奏） | ease | dist（幅度） | scale（幅度） | fade（幅度） |
|---|---|---|---|---|---|
| `mt-hover` | `--mt-dur-quick` | out | 0 | 1 | 1 |
| `mt-press` | `--mt-dur-instant` | out | 0 | `--mt-scale-press` | 1 |
| `mt-enter-small` | `--mt-dur-base` | out | `--mt-dist-1` | `--mt-scale-enter` | `--mt-fade-from` |
| `mt-enter-panel` | `--mt-dur-panel` | out | `--mt-dist-3` | 1 | `--mt-fade-from` |
| `mt-enter-overlay` | `--mt-dur-panel` | out | `--mt-dist-2` | `--mt-scale-modal` | `--mt-fade-from` |
| `mt-exit-*` | 上表 × **.7** | **in** | 同上 | 同上 | 同上 |
| `mt-scene-in / out` | `--mt-dur-scene` | out / in | `--mt-dist-1` | `--mt-scale-scene` | `--mt-fade-from` |
| `mt-cinema-in / out` | `--mt-dur-cinematic` | emphasis / in | `--mt-dist-2` | `--mt-scale-modal` | `--mt-fade-from` |
| `mt-item-add / remove` | base / base×.7 | out / in | `--mt-dist-2` | `--mt-scale-enter` | `--mt-fade-from` |
| `mt-reorder` | `--mt-dur-panel` | out | 0 | 1 | 1（仅 box-shadow 脉冲） |
| `mt-layout-restore` | `--mt-dur-panel` | out | `--mt-dist-2` | `--mt-scale-layout` | `--mt-fade-from` |
| `mt-launch` | `--mt-dur-base` | out | 0 | `--mt-scale-launch` | 1 |
| `mt-state-change` | `--mt-dur-base` | out | 0 | 1 | `--mt-fade-dim` |
| `mt-error` | `--mt-dur-panel` | inout | `--mt-shake-x` | 1 | 1 |

> 注意：除 `mt-exit-*` 的 0.7 系数与 `mt-cinema` 的分段外，**没有任何意图把 duration 与 intensity 相乘**。

### E4. 性格旋钮（Skin Engine 的关键）

```css
--mt-intensity: 1;             /* ★ 主旋钮：幅度（距离/缩放/透明度/模糊），默认 1 */
--mt-drift: 1;                 /* 位移总开关：0 = 纯淡入 */
--mt-scale-on: 1;              /* 缩放总开关 */
--mt-blur: 0;                  /* 毛玻璃伴随，默认关 */
```

**Skin 只改这几个旋钮就能整体换风格，不必碰任何关键帧，也不必改任何 duration。**

| Skin 想做的事 | 改什么 | 不改什么 |
|---|---|---|
| 整体更克制 / 更活泼 | `--mt-intensity` | duration（节奏不变） |
| 彻底不要位移 | `--mt-drift: 0` | 其余 |
| 只要淡入淡出 | `--mt-drift: 0; --mt-scale-on: 0` | 其余 |
| 整体更快 / 更慢 | 覆盖 `--mt-dur-*`（或提供 duration preset） | intensity（幅度不变） |

> 这就是 D2 拆分带来的好处：**风格（幅度）与节奏（时长）可以独立调**。
> 以前"活泼"必然意味着"更慢更夸张"，现在可以做出"快而克制"或"慢而活泼"。

校验规则：Skin 注册时若发现它把 `--mt-intensity` 用在 duration 上（如自定义 keyframe 里写
`calc(var(--mt-dur-*) * var(--mt-intensity))`），门禁告警并剥离该 preset。

### E5. 降级策略（替换现在的一刀切）

两个维度**分别**降级：幅度走 intensity，节奏走 duration token。

```css
/* reduced：幅度收窄 + 节奏缩短，两件事分开做 */
[data-motion="reduced"]{
  --mt-intensity: .35;         /* 幅度：位移/缩放/淡入都变浅 */
  --mt-drift: 0;               /* 干脆不要位移 */
  --mt-scale-on: 0;
  --mt-stagger-step: 0ms;

  --mt-dur-instant: 60ms;      /* 节奏：duration 维度独立缩短（不是乘 intensity） */
  --mt-dur-quick:   90ms;
  --mt-dur-base:   120ms;
  --mt-dur-panel:  140ms;
  --mt-dur-scene:  160ms;
  --mt-dur-cinematic: 240ms;
}
/* off：全部瞬时 */
[data-motion="off"]{
  --mt-intensity: 0; --mt-drift: 0; --mt-scale-on: 0; --mt-stagger-step: 0ms;
  --mt-dur-instant: 0ms; --mt-dur-quick: 0ms; --mt-dur-base: 0ms;
  --mt-dur-panel: 0ms; --mt-dur-scene: 0ms; --mt-dur-cinematic: 0ms;
}
/* 循环类单独处理：reduced 下直接静态 */
[data-motion="reduced"] .skel,
[data-motion="reduced"] .spinner,
[data-motion="reduced"] .live .dot{ animation:none }
@media (prefers-reduced-motion: reduce){
  :root{ --mt-intensity:.35; --mt-drift:0; --mt-scale-on:0;
         --mt-dur-base:120ms; --mt-dur-panel:140ms; --mt-dur-scene:160ms; --mt-dur-cinematic:240ms }
}
```

> 比 `*{animation-duration:.001ms!important}` 好在三处：保留淡入（仍能表达"什么变了"）、
> 不被 `!important` 锁死（Skin 可覆盖）、三档而不是一档。
> **注意**：reduced 也会走 duration 维度的独立覆盖——这正是 D2 拆分的价值之一，
> 否则"减弱动画"就只能靠压 intensity，结果是"幅度没了但还是很慢"。

### E6. 可交互门限（Interactive Gate）

任何**仪式感 / 长时**动效（当前只有 `mt-cinema-*`，未来可能有全屏引导）必须声明
`--mt-interactive-gate`：到达该时刻**强制恢复交互**，不等动画播完。

```css
--mt-cinema-interactive-gate: 240ms;
```

运行时规则：

1. Gate 到达时，runtime 放开被动画元素的 `pointer-events`，并恢复可聚焦。
2. Gate 之后仍在跑的动画属于**后台段**，必须可被用户操作打断：
   收到任意指针/键盘事件 → `animation.finish()` 立即跳到终态 → 再执行用户操作。
   **绝不能让用户"点了个正在动的按钮但没反应"。**
3. 后台段动画不得改变元素的命中区域（首帧之后即可命中）。

### E7. 禁止清单（写进门禁）

- ❌ 弹簧 / 回弹 / overshoot / 弹性缓动
- ❌ 粒子、光效、3D 翻转、旋转入场
- ❌ 交错超过 6 个、单个 stagger > 40ms
- ❌ 交互反馈 > 240ms、场景 > 320ms（cinematic 除外）
- ❌ 动画 `transform: scale()` 起点 < .97（press 例外，取 `--mt-scale-press`）
- ❌ 组件内出现 `cubic-bezier(` 或裸 `ms` 字面量
- ❌ **`--mt-intensity` 与 `--mt-dur-*` 相乘**（D2 硬约束，违反即剥离 preset）
- ❌ 长时动效未声明 `--mt-interactive-gate`

---

## F. Skin Engine 如何接管动画

> **产品规范已拆出**：包结构 / 变量白名单 / 三只皮肤的具体值 / 导入与校验 / 切换规则 /
> 验收用例，见 **`skin-system.md`（v1.0）**。本节只保留架构契约，两者冲突时以 skin-system.md 为准。

### F1. 依赖倒置：Core 只认意图，不认实现

```
        Core（业务代码）
             │  只调用 motion.play(el, 'panel.open')
             ▼
      MotionRuntime（接口 / 抽象）
             ▲  实现由外部注入
             │
   ┌─────────┴──────────┐
 DefaultMotionPack   SkinMotionPack
   （内置，兜底）      （皮肤自带，可覆盖任意 intent）
```

Core 代码里的**唯一**动效写法：

```js
motion.play(el, 'panel.open');          // 不传任何曲线和数字
motion.exit(el, 'panel.close').then(() => el.remove());
motion.stagger(items, 'item.add', { max: 6 });
```

### F2. 契约（MotionPack）

```ts
interface MotionPack {
  id: string;
  schemaVersion: 1;
  tokens: Record<string, string>;                 // 覆盖 L0/L1 变量，直接挂到 :root
  presets?: Record<IntentName, Preset>;           // 覆盖具体意图
  keyframes?: Record<string, Keyframe[]>;         // 可选：自定义关键帧（WAAPI 用）
  capabilities?: { viewTransitions?: boolean };   // 能力声明
}
type Preset = {
  dur?: string; ease?: string;
  from?: { opacity?: number; transform?: string };
  to?:   { opacity?: number; transform?: string };
};
```

**回退链**：Skin 的 `presets[intent]` → Skin 的 `tokens` → Default pack → 无动画。
缺一个 intent 不报错，只降级（保证皮肤作者写一半也能用）。

### F3. 三条通道，按开销从低到高

| 通道 | 适用 | 说明 |
|---|---|---|
| **CSS 变量 + 语义 class**（默认，80% 场景） | hover / press / enter / exit / toast / 面板 | 零 JS，Skin 换变量即换风格 |
| **WAAPI**（编排场景） | 出场动画、stagger、FLIP、布局恢复 | `el.animate()` + `finished` Promise；封装在 runtime 里，Core 不碰 |
| **View Transitions**（场景切换） | 页面切换 | 能力探测，不支持降级双段 |

### F4. 生命周期规则

- **注册**：`registerMotionPack(pack)`，后注册者覆盖同名 key，不同名 key 继承
- **热切换**：换肤只替换 `:root` 上的变量集 → **正在播放的动画不打断**，自然收敛（避免闪断）
- **版本**：`schemaVersion` 不匹配时 Core 做迁移或拒绝并回退 Default，绝不白屏
- **校验**：注册时跑门禁（E7 禁止清单 + 时长上限 + intensity/duration 不得相乘），不合规的项丢弃并在控制台告警，不影响其余

### F5. Core 侧门禁（保证不反向依赖）

- ESLint / Stylelint 规则：**组件样式与 JS 中禁止出现 `cubic-bezier(`、`animation:` 裸时长、`transition-duration:` 裸时长**
- CI 检查：`grep -r "cubic-bezier" src/` 必须只命中 `motion/` 目录
- 这条是"Core 不依赖具体动画实现"唯一的强制手段，只靠自觉一定会被破

---

## G. 推荐技术实现方式

| 手段 | 用在哪 | 理由 |
|---|---|---|
| **CSS 变量 + 语义 class** | 全部微交互、进出场 | 零 JS 开销，Skin 友好，最优先 |
| **WAAPI `el.animate()`** | 出场动画、stagger、FLIP | 需要 `finished` Promise 做"播完再移除"，CSS 做不到 |
| **View Transitions API**（**可缺省**） | 页面切换（增强） | D1：Motion System 不依赖它；支持才用，不支持自动降级 |
| **FLIP** | 网格重排、插入排序、Mini Map 位置变化 | 唯一能做"布局变化补间"的低成本方案 |
| `grid-template-rows: 0fr→1fr` | 高级设置展开 | 比 `max-height` 干净，不用测高度 |

**明确不用**：动画库（Framer Motion / GSAP 等）——本项目动效规模小、且要被 Skin 接管，
引入库会让"Core 只认意图"这条架构约束失效。

### 性能纪律

- 只动 `transform` / `opacity` / `box-shadow` / `border-color`
- `will-change` **只在动画期间**加（`animationstart` 加 / `animationend` 摘），禁止常驻
- 长任务预算：任意动画帧 < 16ms，动画引发的主线程工作 < 50ms
- 循环动画只允许 loading / 运行中指示

### View Transitions：渐进增强接入法（D1 落地）

```
                 ┌─ 支持 startViewTransition ─┐
路由变更触发 ────┤  且 pack.capabilities 允许  ├──→ VT 路径（::view-transition-old/new）
                 │  且 非 reduced/off          │     仍用 --mt-scene-* token
                 └──────────┬─────────────────┘
                            │ 任一条件不满足
                            ▼
                    CSS/JS fallback：离场 120ms → 换 DOM → 入场 240ms
```

- 开关集中在一处：`motion.canUseViewTransitions()`，业务代码**永远不直接调** `document.startViewTransition`。
- 两条路径共用 `--mt-scene-*` token，视觉参数必须一致（只有"是否被 snapshot"不同）。
- VT 只包**路由切换**这一次 DOM 替换；`render()` 里的局部更新路径不进 VT。
- fallback 不是"次等方案"：它是**默认路径**，VT 只是叠加。fallback 必须长期可测
  （提供 `?motion=novt` 强制走 fallback 的调试开关）。

### 五条"别踩"的红线

1. **View Transitions 只能包路由切换，绝不能包 `render()`** —— 否则重演「拖拽像刷新」的翻车。
2. **VT 之前必须先过 S2 门限**：局部更新不得触发整页重绘与整页入场动画。
   验收方式：滚动到中段 → 触发拖拽/开关 → `scrollTop` 不变且无 `.view-enter` 重播。
   **这条不通过，不允许进入 VT 阶段**（D1）。
3. **换位是"交换 + 继承尺寸"，不要给它加 FLIP 位移动画**，会和内容瞬移打架。
   保持现在的「内容瞬移 + 描边脉冲」。FLIP 只给**插入排序**用。
4. **出场动画不能成为"点不动"的来源**：出场元素立刻 `pointer-events:none` 并从可聚焦列表移除，
   但入场元素从头到尾可点。
5. **长时动效（cinema）必须在 gate 处放开交互**，后台段可被用户操作打断并 `finish()` 跳终态（D3/E6）。

---

## H. 实现顺序

> 原则：**先立规矩再写动画；先补出场再补编排；最后才做 Skin 接口。**
> 前 4 步是纯替换，视觉零变化、风险最低。

| 阶段 | 内容 | 风险 | 产出 |
|---|---|---|---|
| **0. 契约与门禁** | 建 `motion-tokens.css`：**duration 与 intensity 两套独立 token**（D2）+ intent 命名表 + lint（禁 `cubic-bezier`/裸 ms/禁 intensity×duration）+ reduced 三档 | 低 | 规矩先落地，后面不会跑偏 |
| **1. 参数回收** | 把 6 处硬编码（`ctxIn 120ms`、`swapFlash 460ms`、`skel 1.4s`、`spin .7s`、`pulse 2.4s`、Toast 出场 200ms）换成 token | 极低 | 视觉零变化，纯技术债清理 |
| **2. 微交互统一** | hover 全量走 `mt-hover`；**新增 `mt-press`**（`--mt-scale-press` / instant） | 低 | 点击有"触感" |
| **3. 补出场** | 抽屉 / 弹窗 / Toast / 右键 / scrim 全部补出场动画；Toast 堆叠位移 | 中 | 解决 S1，质感提升最明显 |
| **4. 卡片增删** | `item.add / item.remove` + stagger + FLIP 重排 | 中 | 解决 S3 |
| **4.5 ⛩ S2 门限** | **"局部更新不触发场景动画"改造 + 端到端验收**（滚动中段 → 拖拽/开关 → `scrollTop` 不变、无重播）。**不过不许进阶段 5** | 中 | D1 的入场券 |
| **5. 页面切换** | 先落 **CSS/JS fallback 双段**（默认路径），再加 VT 增强；`?motion=novt` 可强制走 fallback | 中 | 解决 S2 |
| **6. AI 侧栏** | 宽度 240ms + 内容延迟 60ms 淡入，收起先淡出内容 | 低 | 解决内容硬切 |
| **7. 工作模式进出** | D3：cinema-in 主体段 0–240ms / 后台段 240–560ms；`--mt-cinema-interactive-gate: 240ms`；后台段可打断 | 中 | 解决 S8，沉浸感主战场 |
| **8. 布局恢复** | 窗口按 layout stagger 40ms 落位 + 保存确认脉冲 | 中 | 解决 S9，把数据"演"出来 |
| **9. 启动 / Loading / 状态** | launch 脉冲、spinner 150ms 延迟出现、错误 shake | 低 | 补齐反馈细节 |
| **10. Skin 接口** | `MotionRuntime` + 示例 Skin：Calm（`intensity .6`，duration 不变）/ Lively（`intensity 1.4`）验证**只改幅度不改节奏** | 中 | 验证 F 章 + D2 |
| **11. 门禁与验收** | 性能（长任务 <50ms / 60fps）、三档降级、gate 处交互已恢复、后台段可打断、reduced 下循环静止 | 低 | 交付前收口 |

### 每个阶段的验收方式（建议）

- 逐阶段跑 Edge `--dump-dom` 冒烟（本机已验证可用）
- **阶段 4.5（S2 门限）**：端到端脚本断言滚动到中段后触发局部更新 → `scrollTop` 未变、无整页重播
- **阶段 7**：断言 240ms 时目标元素 `pointer-events` 已恢复；在后台段中途点击 → 动画立即跳终态且点击生效
- **阶段 10**：分别加载两个 Skin，断言 duration token 完全未变、只有幅度基元变化
- **阶段 11**：DevTools Performance 录 3 秒，检查无掉帧、无长任务

---

## 决策状态

| # | 决策 | 状态 |
|---|---|---|
| D1 | View Transitions 渐进增强，不依赖；VT 前必须先过 S2 门限 | ✅ 已锁定（v0.2） |
| D2 | Intensity（幅度）与 Duration（节奏）拆成两个独立维度 | ✅ 已锁定（v0.2） |
| D3 | 工作模式 560ms 总体 / 240ms 恢复交互；必要时统一压到 ≈360ms | ✅ 已锁定（v0.2） |

---

## I. 实现清单（UI-01，代码已落地）

落点：`personal-workspace-ui/index.html`（原型）+ `personal-workspace-ui/tokens.css`（Token 规范）。

| # | 场景 | 实现 | 关键做法 |
|---|---|---|---|
| 1 | Motion Token | ✅ | `tokens.css` §MOTION TOKENS 与 `index.html` §1.5 同步：duration / intensity 两套独立变量；旧名 `--dur-*` 做映射，避免两套事实来源 |
| 2 | Motion Guard 三档 | ✅ | 变量覆盖实现，不用 `!important` 归零；`reduced` 去大位移/明显缩放/装饰循环，`off` 只关动画不关交互状态 |
| 3 | 卡片微交互 | ✅ | Press `:active` → `scale(var(--mt-scale-press))` 80ms；Hover 140ms；Selected `.sel` brand-50；`:focus-visible` 2px + 2px offset；**同一元素同一时间只有一个主动效状态** |
| 4 | Motion Priority | ✅ | `dragstart` 给 `body` 加 `is-dragging`，CSS 里 Hover 的 transform/shadow 全部让位；`dragend` 摘掉 |
| 5 | 浮层进出场 | ✅ | Toast 进 180 / 出 120ms；右键菜单 100ms；抽屉 240ms；弹窗遮罩 140 + 面板 180ms；**退场统一走 `closeLayer()`**（先加 `.out` 再清空 `layer`），不再 `innerHTML=''` 硬切 |
| 6 | 拖拽让位 | ✅ | 新增 `flip()`：先量旧位置 → 改 DOM → 从旧位置滑回（120–180ms）；**被拖的那个不参与 FLIP**（它跟着光标）；动画期间 `busy` 置位，不排队 |
| 7 | 页面切换隔离 | ✅ | `render({scene:true})` 只在路由变化时播场景动画；局部更新走 `render()`；`sceneSeq` 让 A→B→C→D 只保留最后一跳 |
| 8 | Workspace Cinema | ✅ | `playCinema()`：0–240ms 主体 → **240ms GATE** → 240–560ms 后台稳定（可打断）；窗口 `--i` 错峰 16ms，几乎同时落位，不排队；窗口 opacity .7→1、translateY 8→0，无飞入 |
| 9 | AI 侧栏 | ✅ | 展开先宽度、内容延迟 120ms；收起先淡出内容 180–240ms 再收；Chat/Workspace 只换内容区；权限条 140ms |
| 10 | Widget 列 | ✅ | 固定 224px；关闭后**保留空间**并显示「+ 添加组件」，不再整列消失导致内容跳动 |
| 11 | 状态动效 | ✅ | 成功 `ok-flash`（只闪描边）；错误 `err-shake` 就近纠正（创建工作空间重名为空时触发）；启动应用本地 loading（`launching`），**不遮罩、不阻塞** |
| 12 | 焦点保持 | ✅ | `paint()` 记下焦点元素「身份」（`data-act`+`data-v`+`data-r`），重建 DOM 后按身份还回去，键盘操作不断 |
| 13 | 首页首入 | ✅ | `data-enter` 标记 Hero / Workspace / Secondary；`playEntrance()` 用**总时长反推步长**，整段稳定 400–520ms；`homeEntered` 保证只播一次 |
| 14 | 动效规范页 | ✅ | `ROUTES.showcase`：12 个场景逐个可重播，标注 Token 与时长；入口在设置 · 外观（主 IA 未动） |
| 15 | 三档对比页 | ✅ | `ROUTES.guard`：Standard / Reduced / Off 一键切换，同一演示台切档后重播对比 |
| 16 | 侧栏折叠 / 组件区隐藏 | ✅ | 进入工作模式自动折叠侧栏并隐藏组件区；`--mt-dur-nav` 260/200ms；`go()` 里**提前一拍**加 `cinema`，否则组件区比侧栏晚 80ms 才开始收，会撞上"右边还在变宽" |
| 17 | 边界拖拽改宽度 | ✅ | 三个侧区（导航 / 组件区 / AI）都有手柄：`hover` 出 2px 主色线，拖动即时跟手，**双击重置，方向键 ±16（Shift ±48）** |
| 18 | S2 真正局部 diff | ✅ | 设置页切分类只换 `.set-body` 一块；`patchSettings(rebuildNav)` / `patchPluginCount()`；四个容器（侧栏 / 组件区 / AI / 内容壳）在操作后**仍是同一 DOM 节点**，已被端到端点击验收证明 |

### 边界拖拽：最关键的一条是"拖的时候不许有过渡"

宽度过渡（`--mt-dur-nav` 200ms）在**自动折叠**时是对的，在**手动拖拽**时是灾难 ——
宽度会"追"着光标做缓动，手感像拉橡皮筋。所以 `pointerdown` 给 `body` 加 `is-resizing`，
用 `transition:none !important` 把宽度过渡整体关掉，松手再恢复。

其余要点：
- 手柄 9px 命中区、1px 可见线，`hover`/`focus-visible` 才变 2px 主色 —— 静止时不打扰。
- `pointermove` 用 rAF 节流，一帧最多改一次宽度。
- **宽度走 CSS 变量**（`--sidebar-w` / `--widget-w` / `--ai-panel-w`）写在 `shell` 上，
  不动组件里的硬编码，三个侧区共用一套逻辑。
- 手柄是容器子节点，而 `paint()` 会重写这三个容器的 `innerHTML` → `mountHandles()` 每次刷完补回去；
  节点是同一个，事件只在创建时绑一次，不会越绑越多。
- **不留"假可拖"**：折叠态（collapsed）、工作模式（cinema）、以及窄屏媒体查询写死宽度时，
  手柄全部 `display:none` —— 能拖却没反应比没有手柄更糟。
  **例外**：mini 态的导航手柄要留着 —— 主动折叠按钮已删，拖边界是唯一的展开途径。

### 宽度阈值：min 按"内容刚好不紧凑"，max 按"主窗口还能让出多少"

| 侧区 | min | max | 折叠阈值 | 依据 |
|---|---|---|---|---|
| 导航侧栏 | 160 | 400 | 松手 ≤176 → 折叠成图标条 | nav-item = 12+18+12+文字(最长"工作空间"≈56)+12 ≈ 110；160 时文字完整且两侧有余量，再窄就要切字 |
| 组件区 | 200 | 400 | — | 组件卡片内部是两列信息（数值 + 说明），200 以下开始互相挤 |
| AI 侧栏 | 300 | 560 | 松手 ≤316 → 收成竖条 | 聊天/工作区分段按钮各需 ~140 + 内边距，300 以下按钮文字要换行 |

**max 不是写死的**：`CONTENT_MIN = 680`（主窗口最小尊严 —— 低于它首页 Hero、
工作空间卡片网格、工作模式舞台都会挤）。实际上限 =
`min(配置上限, 起始宽度 + (当前主窗口宽 − 680))`，在 `pointerdown` 时算一次，
拖的过程中不再重算 —— 否则上限会跟着自己变宽而漂移。

**拖到最小值后停顿 → 直接折叠**（dwell），不必松手、也不取消拖拽选中：
手柄保持激活，用户接着往回拖就能展开，整件事是连续的一条手势。
- 停顿时长 `--mt-dur-dwell: 560ms`（2026-09-14 校准：折叠是有破坏性的状态切换，
  中间态必须能被看见并来得及反悔，320ms 太短）。**这是交互节奏不是装饰动画，
  不随 reduced / off 降级** —— 降级后 dwell 变 0 只会让误触折叠更难受。
- 停顿期间必须给反馈：`.rsh.arming` 让那条线在 560ms 内匀速涨粗（2px→6px + 光环），
  同时把手胶囊常亮。没有这段，用户只会觉得"怎么突然就折叠了"。
- **滞回（hysteresis）是硬要求**：展开阈值必须高于折叠阈值（nav 176/200，ai 316/340，
  中间 24px 稳定区），否则折叠的瞬间又满足展开条件，来回抖。
- **到达阈值：脉冲提示 + 略微停顿（2026-09-14 定稿，磁吸方案已驳回）**：
  折叠态拖边缘全程 **1:1 跟手，展开速率完全由拖拽速度决定，不做任何自动滑行/磁吸**。
  到达 `expandAt` 那一刻：① 边缘脉冲一下（`.rsh.crest`，2→6px 主色 + 光环，560ms）；
  ② 宽度钉在阈值 ~260ms（`crestUntil`）——给用户反应时间"已到完全展开宽度、可以松手"；
  ③ 停顿结束把拖拽基准**重锚**到阈值（`startX` 平移），继续 1:1 跟手且无跳变。
- **未到阈值松手：惯性滑行（2026-09-14 定稿）**：从折叠态出发、外拉超过 foldW+12px、
  未到 `expandAt` 就松手 → 边缘从当前位置、以松手瞬间速度（指数平滑采样）起，
  **ease-out 递减滑行到 expandAt**，时长按 `距离/速度` 推得（180–520ms 钳制），
  到位后摘壳展开 + 边缘脉冲。**滑行必须写 inline 宽度**（.mini/.collapsed 类用自己的
  48/64px 压着宽度变量，写变量等于没写），摘壳后才交还变量（顺序不能反）。
  **只属于"折叠态出发"的拖拽**（`startedFolded`）：展开态拖到折叠区松手、驻留折叠后松手都不滑。
  AI 栏同一套标准。折叠态拖拽全程边界线点亮（`.rsh.pull`）。
- 折叠 ⇄ 展开若换了整块内容（AI 的竖条 ⇄ 面板），重建后手柄会被 `innerHTML` 冲掉 ——
  必须 `mountHandles()` 补回并**续上指针捕获**（`setPointerCapture`），否则拖到一半脱手。
  （AI 的 `rebuildAi()` 整类重写 className，`.snap` 必须在 unfold **之后**挂。）
- 松手兜底：没等到 dwell 就松手，只要落在折叠区里照样折叠。

### 三条边界归谁：一条边界只能调一侧

布局是 `导航 | 主视窗 | 组件区 | AI 侧栏`，中间只有**三条**可拖边界：

| 边界 | 手柄 | 调的是谁 |
|---|---|---|
| 导航 ⇄ 主视窗 | `.rsh--nav`（导航右边缘） | 导航宽度 |
| 主视窗 ⇄ 组件区 | `.rsh--widget`（组件区左边缘） | 组件区宽度 |
| 组件区 ⇄ AI 侧栏 | `.rsh--ai`（AI 左边缘） | AI 宽度 |

最后一条同时也是"组件区右边缘"，但**一条边界只能调整一侧**，所以它归 AI 所有 ——
组件区想要更宽，拖它自己的左边缘。

### 两个"手柄存在但用户看不见"的坑

1. **滚动容器吞掉手柄**：组件区原本自己 `overflow-y:auto`，绝对定位的手柄是它的子元素，
   内容一多就跟着滚出视野。改法：外层改 `overflow:hidden`，滚动交给内层 `.wscroll`，
   手柄挂在外层不再被带走。
2. **1px 的线太隐蔽**：hover 才变色的一条细线，用户根本不会发现这里能拖。
   加 `.rsh::after` —— hover / 聚焦 / 拖拽时淡入一段 26px 的胶囊把手，
   它才是"此处可拖"的主要信号，细线只是位置指示。

### 级联挤压（cascade squeeze）：挤不动了就把压力传下去

只让主视窗让路是不够的 —— 主视窗一到 `CONTENT_MIN` 就整个卡住，明明旁边还有空间。
现在压力会**沿挤压方向传播**：主视窗到底 → 找链上下一个还没到阈值的区域 →
它压到最小值后**折叠它**换出更多空间 → 继续往下传，直到缺口被填平或链上全部到底。

布局 `nav | content | widget | ai`，链按**物理邻接**排（谁先被牺牲）：

| 拖谁 | 挤压链（跳过 content，它是 flex:1 自动吸收的） |
|---|---|
| 导航（右边界，向右拖） | content → widget → ai |
| 组件区（左边界，向左拖） | content → nav |
| AI（左边界，向左拖） | content（自动）→ widget → nav |

要点：
- **上限不再是主视窗的富余**，而是整条链能交出的总和，含折叠能释放的那部分（nav 96 / ai 252）。
- 基准用 `startChainW`（pointerdown 时记一次）—— 每帧重新测量会累积漂移。
- `cascade()` 里同一帧内完成"读 content → 扣下一个区域 → 重新应用"，
  用户只看到最终状态，不会看到 content 先被压瘪又弹回。
- **往回拖自动还原**：记录 `autoFolded`，压力解除后依次展开并还原到起始宽度 —— 手势是连续的一件事。
- 折叠/展开做成 `foldArea(k)` / `unfoldArea(k)` 通用版：级联会折叠**别人**，不只是当前拖的这一个。

### ⚠ 两个级联踩坑（都是"能拖但看起来坏了"）

**A · 同时高亮**：高亮写成 `body.is-resizing .rsh::before`（不限定激活项），
结果所有手柄一起亮 —— 级联折叠掉某栏后，那栏的手柄还在（mini 态本就要留着当展开入口），跟着亮了。
→ 凡是"当前激活项"的高亮，选择器必须带 `.on` / `.active`，不能只写类名。

**B · 拖拽态残留**（更严重，直接表现为"再也选不中"）：
```
dwell 折叠 AI → .ai-dock.collapsed .rsh--ai{display:none}
  → 手柄消失 → 指针捕获丢失 → pointerup 收不到 → end() 不执行
  → body.is-resizing 残留 → 其余手柄被 pointer-events:none 全部锁死
```
三处修复，缺一不可：
1. `body.is-resizing .rsh.on{display:block!important}` —— 正在拖的那根永不被隐藏。
2. `pointerup` / `pointercancel` **同时挂到 window** —— 手柄被隐藏或移出 DOM 后，
   事件再也送不到它身上，只有 window 兜得住。
3. `rebuildAi()` 只切 class、不写 `innerHTML`（rail 与 panel 本来就在 DOM 里，
   由 CSS 控制谁显示），从源头避免捕获丢失。

> 通用规则：**任何依赖 pointer capture 的拖拽都必须有 window 级兜底收尾**，
> 否则一次意外隐藏就让整个交互卡死。

### 触摸设备（平板 / 触屏）

鼠标语境下的两个默认假设在触摸端**全部失效**，必须单独处理（`@media (hover: none)`）：

| 假设 | 鼠标端成立 | 触摸端后果 |
|---|---|---|
| 手柄 hover 才显形 | ✅ 克制不打扰 | ❌ 没有 hover = 永远不显形 |
| 命中区 9px 够用 | ✅ 指针精确 | ❌ 手指点不中 |

修法：触摸端把命中区加宽到 **24px**，把手**常驻半透明**（`.55`），拖拽时转实心。
`touch-action:none` 保证垂直滑动不会把手势抢去滚页面。

### 断点会把手柄收掉（窄屏 / 竖屏平板上"没有拖拽"是正常的）

| 手柄 | 隐藏断点 | 原因 |
|---|---|---|
| 组件区 | < 1300px | 该断点下组件区整个被响应式规则收起，边界不存在 |
| AI 侧栏 | < 1180px | 同上，AI 收成 48px 竖条 |
| 导航 | < 1100px | 侧栏被强制 mini（64px），媒体查询写死宽度，拖了也不动 |

**一条边界只能调整一侧**，所以留着也只能是"假可拖"。
实测影响：iPad 12.9" 横屏（1366px）三条都能拖；11" 横屏（1180px）只剩导航；竖屏（≤1024px）全无。
→ 这是空间不够时的有意让位，不是缺陷；若要在平板上也能调组件区/AI，需要单独下调断点。

### 主侧栏折叠：三条状态优先级

| 状态 | 含义 | 行为 |
|---|---|---|
| `navMini` | 用户手动折叠 | 最高优先级，跨路由保持 |
| `navAutoMini` | 进入工作模式自动折叠 | 退出工作模式即失效 |
| `navRunExpanded` | 用户在工作模式里手动展开过 | 本次会话内不再自动收，退出后重置 |

**时序**：`go('run')` 里提前一拍折叠 —— 侧栏在场景离场的 80ms 内就开始收（200ms 收完），
窗口 120ms 才开始落位，因此不会出现「窗口滑进来的同时地面还在变宽」。
侧栏 200ms 收完落在 Cinema 主体段内，240ms GATE 时布局已定。

**纪律**：`applyNavMini()` 只改侧栏自己的 class 与按钮文案，**不重建内容区** ——
否则在"新建工作空间"页折叠侧栏会丢输入。

**工作模式下的组件区**：两个语义不同，别混为一谈 ——

| 场景 | 表现 | 规则 |
|---|---|---|
| 用户手动关闭组件区 | **保留 224px**，显示「+ 添加组件」 | `.widget-col.collapsed` |
| 进入工作模式 | **彻底让位，宽度归 0** | `.shell.cinema .widget-col` |

后者用 `visibility` 延迟到收起结束才切 `hidden`（`visibility 0s linear var(--mt-dur-nav-out)`），
否则键盘 Tab 会跑进一个已经看不见的区域。
时序上 `cinema` class 与侧栏**同一拍**加上（`go()` 里提前 toggle），不再等场景离场结束 ——
否则组件区比侧栏晚 80ms 才开始收，窗口 120ms 落位时会撞上"右边还在变宽"。

### 门禁结果

- 静态门禁（`node` + `vm.Script`）：**1 个 script 块，语法通过；接线断言 25/25 通过**
- Edge 无头 `--dump-dom` 冒烟：**home / showcase / guard / settings / run 五个路由全部渲染成功**
- **端到端点击验收**（`verify_s2_local_diff.py`，Edge 无头 + CDP）：**6/6 通过**，见下节

### S2 局部 diff：判据是"节点身份"，不是"看起来没动"

`render()`（局部刷新）本身**不播场景动画、也保 `scrollTop`**，所以它在肉眼上很像"没重绘"。
真正能区分"局部更新"和"整块重建"的只有一件事：**DOM 节点还是不是同一个**。

验收脚本 `verify_s2_local_diff.py` 的做法与两条纪律：

1. **必须标记子节点，不能标记容器。** `paint()` 重写的是 `#sidebar` / `#widgetCol` / `#aiDock` 的
   `innerHTML` —— 容器元素**永远**活着。标在容器上的"存活"断言是**零区分度**的假通过。
   （本脚本第一版就踩了这个坑，被 T1 抓出来。）
2. **反面断言必须有对照组（T1）。** 先直接调一次 `render()`（旧路径），断言子节点标记**被抹掉**；
   对照组成立之后，T2–T6 的"标记存活"才有意义。
   否则"标记还在"完全可能只是探针坏了。

| # | 用例 | 判据 |
|---|---|---|
| T1 | 控制组：走旧路径 `render()` | 侧栏子节点标记**必须消失**（`sameNode=false`）——证明探针看得见重绘 |
| T2 | 设置页切分类 | 侧栏/组件区/AI 子节点存活 **且** 内容壳存活 **且** 内容子节点确被换掉 **且** `hash` 不变 |
| T3 | 开发者模式 | 导航新增 `dev` 项、切到 dev 分类，侧栏子节点仍存活 |
| T4 | 动效档位点「减弱」 | `data-motion=reduced` 且 `state.motion=reduced` 且只有「减弱」处于 on |
| T5 | 首页布局点「固定」 | `state.layoutMode=fixed`，只有「固定」处于 on，侧栏存活 |
| T6 | 插件页切开关 | 页头「启用中 N 个」数字变化 + 开关翻转 + **开关仍是同一个 DOM 节点** |

**T6 的 `sameSwitchNode` 是这套里最强的判据**：走 `render()` 的话这个开关节点会被换掉，
而局部更新只改它的 class —— 同一个断言在"功能坏掉"时会变红。

### 顺手修掉的一个真 bug：分段控件的值取不到

文件里 `data-act` 有两种写法：① 按钮自己带（`ai-mode` / `layout` / `run-mode`）；
② **容器带 `data-act`、按钮只带 `data-v`**（`set-motion` / `set-layout`）。
写法②下 `closest('[data-act]')` 命中的是**容器**，`d.v` 恒为 `undefined` ——
于是「减弱 / 关闭」和「固定」点了等于没点，且分段控件会丢掉选中态。

修法在**委派层**统一补值（`document.addEventListener('click', ...)`）：把"被点按钮"的 `data-v`
并进 payload，handler 只管读 `d.v`。T4 / T5 就是这两个的回归断言。

---

## J. 已知缺口（下一步才做，本轮刻意不碰）

1. **View Transitions 仍为 0 行** —— 但它等的那个门限**本轮已经补齐**：
   设置页（`set-cat` / `toggle-dev` / `set-motion` / `set-layout`）与插件页（`plugin-sw`）
   现在都是真正的局部 DOM diff，不再整块 `paint()` 重建（§I #18，T2–T6 已证）。
   → VT 现在具备入场条件，**但本轮仍未引入**：引入前应先确认这些局部更新是否本来就该配有过渡。
2. **Skin Engine 未接管** —— 但产品规范已完成：`skin-system.md`（包结构 / 四级变量白名单 /
   Default·Calm·Lively 具体值 / 导入校验与逐项报告 / 切换规则 / 8 条验收用例）。
   遗留一个必须随实现落地的层叠契约：降级块的变量声明需加 `!important`，否则
   `:root[data-skin]`（0,2,0）会压过 `[data-motion="off"]`（0,1,0）导致 off 失效（skin-system.md §9.1）。
3. **`enableSort` 的 move 模式是 DOM 局部换位**（不重绘），但 swap 模式下相邻格子的尺寸继承走白名单 `swapSize`，
   若将来新增布局属性需同步白名单。
4. **Toast 堆叠**：目前最多 3 条，超出直接丢弃最旧一条；规格里的「堆叠位移」未做。
5. 性能验收（长任务 <50ms / 60fps）未跑 DevTools Performance，只做了渲染冒烟。

### 仍会整页重绘的动作（已登记，未扩散处理）

`render()` 不做场景动画、也保 `scrollTop`，所以下面这些的违规程度是「整块重建」而非「场景重播」
（代价：焦点丢失、hover 态重置、手柄重新挂载）。**本轮只处理了"设置类动作"，其余刻意留在原地**
以免一次改动面过大：

- `run-mode` / `save-layout`（工作空间运行页）—— 会连带 `initStage()` 重建舞台
- `ai-tab` / `pick-model`（AI 侧栏页签与模型）
- `toggle-play`（生活 · 播放状态）
- `create` 流程（`pick-type` / `toggle-app` / `suggest` / `create-next`）—— 属结构性变更，
  整绘本身可接受，必要时再收窄到内容区
- 自定义抽屉（`widget-sw` / `section-sw` / `col-sw`）—— 本就要同步刷新抽屉背后的页面
- `uninstall-plugin` —— 列表结构变化，整绘可接受
