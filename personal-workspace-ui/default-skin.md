# Default Skin · 视觉规范 v1.0（产品官方皮肤）

> 定位：Default Skin 是 Personal Workspace 的**官方外观与手感**，即用户打开应用看到的第一眼。
> 上游：`skin-system.md` v1.0（皮肤层契约）/ `design-system.md` §5（Design Token）/ `tokens.css`（唯一事实来源）。
> 本文不做发明：**所有取值均为 token 基线本身**，Default Skin 的工作是把基线声明为产品，并给出"为什么这组值配得上官方体验"。

---

## 0. 定位与三条边界

1. **Default = Token 基线，零覆盖。** 它不注入任何变量、不替换任何值（skin-system.md §4）。
   本文档是基线的**产品化声明**，不是第二套取值。
2. **不新增任何 token，不设计自由 CSS 皮肤。** 颜色/密度/圆角/阴影全部消费既有 `--*` 变量。
3. **不依赖、不绕过皮肤通道。** Default 的生效方式 = `data-skin` 属性**不存在**。
   即使 Runtime 引入 `--mt-skin-*` 中间层，Default 也不声明其中任何一个变量 ——
   「零覆盖」语义在任何通道实现下都成立（§五 Showcase 中的 `--mt-skin-*` 是**预览沙箱**对通道的演示，不是 Default 的生效方式）。

---

## 一、颜色系统

全部取自 `tokens.css :root`，浅色为默认主题，深色经 `[data-theme="dark"]` 映射（皮肤不参与主题切换）。

### 1.1 主色（低饱和蓝，克制到可大面积使用）

| 角色 | Token | 值 | 用在哪 |
|---|---|---|---|
| Primary | `--brand-500` | `#4A6BDC` | 主按钮、选中态、进度、焦点填充 |
| Primary hover | `--brand-600` | `#3A57C4` | 主按钮悬停（只加深，不变色相） |
| Primary active | `--brand-700` | `#2E45A0` | 按下、深底文字 |
| 主色浅底 | `--brand-50/100` | `#EFF3FD / #DFE7FB` | 选中态底、气泡、强调区块 |
| 聚焦描边 | `--border-focus` | `#6E8BE6` | `:focus-visible` 2px 外描边 |

> 官方理由：饱和度压低的蓝在白卡片上**经得起大面积**（选中列表、进度条、主按钮），换任何更艳的主色都会逼着把使用面积缩小 —— 那才是"开发框架感"的来源。

### 1.2 辅色（两个来源，各有禁区）

| 来源 | Token | 用在哪 | 禁区 |
|---|---|---|---|
| **功能辅色**（语义状态） | `--success / --warning / --danger` + 各自 `-soft` 底 + `-text` 深字（三件套成对） | badge、状态点、错误卡、开关 on 态 | 只出现在小元素；禁止大面积色块 |
| **装饰辅色**（应用图标兜底） | `--app-tint-1…6` + `--app-ink-1…6` | 没有真实图标时的应用方块 | 只作为图标底色存在，不迁移作他用 |

### 1.3 accent 策略

Default **不启用** T4 品牌色覆盖能力（`capabilities.accent: false`）。
「强调」这个角色由主色体系自己完成：`brand-400`（聚焦）→ `brand-500`（行动）→ `brand-700`（按压）。
**没有第二强调色** —— 两个 accent 是"看起来没想清楚"的最快路径。

### 1.4 背景与卡片层级（纸面模型）

```
--bg-app     #EBEDF1   窗口底层（桌面）
└─ --bg-canvas  #F4F5F8   工作台面板（铺在桌面上的纸）
   ├─ --surface-1  #FFFFFF   卡片 / 面板（内容承载）
   │  ├─ --surface-2  #F8F9FB  卡片内分区、侧栏
   │  └─ --surface-3  #F1F3F6  控件底、chip、输入框
   └─ --surface-overlay #FFFFFF  浮层（唯一允许 --shadow-lg 的层）
```

- **卡片层级靠描边不靠阴影**：`--surface-1` + `--border-subtle`(#EDEFF3，几乎不可见) + `--shadow-xs`。
  hover 才升到 `--border` + `--shadow-md`。阴影是层级信号，不是装饰。
- `--bg-sunken` #E9EBF0：凹陷区专用（编排画布、进度槽），禁止当内容底色。

### 1.5 状态颜色（三件套，成对使用）

| 状态 | 主色 | 底 `-soft` | 字 `-text` |
|---|---|---|---|
| 成功 / 已启用 | `#2E9C6E` | `#E7F5EF` | `#1F7351` |
| 待确认 / 警告 | `#C08A1E` | `#FAF2E0` | `#8A6116` |
| 错误 / 危险 | `#CE4A3F` | `#FBECEA` | `#A03329` |

规则（design-system §5.1）：饱和度压到最低；深色主题由 `[data-theme="dark"]` 整组重映射，皮肤不做单点改色。

---

## 二、动效风格定义

### 2.1 三皮肤关系：一根旋钮轴 + 一条官方承诺

```
幅度轴（--mt-intensity）      节奏轴（装饰类 --mt-dur-*）
  Calm   0.55  ●               Calm   装饰 -20~30%，更利落
  Default 1.0  ●  ← 官方        Default 基线（tokens.css 现值）
  Lively 1.35  ●               Lively 装饰 +15~25%，更舒展

  反馈轴（press / hover / drag / ctx / drop / perm）
  ─── 三者差 ≤ ±20% ───  这条是官方承诺：换皮肤不换"跟手"
```

- Calm / Lively 的存在**不是**给 Default 找补，而是证明光谱两端可用；
  Default 居中是选择，不是没设计（skin-system.md §5/§6 的值全部从这套基线推导）。
- **Default 必须作为官方体验**的三个理由：① 1.0 是反馈与装饰的唯一平衡点 —— 处处有反馈、无一处表演；② 这是工作工具，长时间使用的疲劳度权重高于演示惊艳度；③ 560ms 的 Cinema 是仪式感上限，全产品再无第二处超过它。

### 2.2 六种感觉（参数均为 token 现值）

| 场景 | 参数 | 感觉 | 明确不做 |
|---|---|---|---|
| **hover** | `--mt-dur-hover 140ms` · 抬 `--mt-dist-hover 1px` · 阴影 xs→md · 描边 subtle→border | **纸面被指尖轻抬**：1px 足够让人知道"接住了"，140ms 内完成，不抢下一步操作 | 不放大、不变色相、不加发光 |
| **press** | `--mt-dur-press 80ms` · `--mt-scale-press ≈ .985` | **按进纸面 1.5%**：短促、结实、无回弹 —— 桌面应用的"咔哒"感 | 无弹性曲线、无涟漪 |
| **panel 出现** | drawer `240ms` / modal `180ms` · `--mt-dist-panel 24px` · `--mt-fade-from .05` · ease-out | **从桌面滑上来**：位移是主语言，透明度只做辅助（从 .05 起步，几乎不闪） | 不缩放入场、不弹跳落位 |
| **页面切换** | out `80ms` → in `140ms`（总 220ms）· `--mt-dist-page 4px` | **翻页，不是转场**：离场快到几乎无感，入场 4px 上浮 —— 方向感告诉你"内容换了"，仅此而已 | 不滑动整屏、不交叉溶解、无 mask 揭示 |
| **drag reorder** | 邻居让位 `160ms` · drop snap `160ms` · 成功高亮 `460ms` 描边脉冲 | **磁吸归位**：放手那一刻元素"吸"进槽位，邻居提前 160ms 让好位；被拖元素全程跟手零延迟 | 让位不加 FLIP 位移（红线 3）；被拖元素不做任何跟随动画 |
| **workspace cinema** | 窗口落位 `200ms` · 错峰 `16ms` · **240ms 交互门限** · 总 560ms · `--mt-fade-window .7` | **落位即工作**：窗口几乎同时出现（.7 起步，透明但不虚无），240ms 后鼠标点击必定命中；560ms 只是后台收尾，用户感知不到 | 门限不因任何皮肤延长；不播"整个桌面飞入" |

---

## 三、空间与层级

| 维度 | 取值（token） | 产品化理由 |
|---|---|---|
| **卡片密度** | `--pad-card 20 / --pad-card-lg 24` · `--gap-card 20` · `--gap-section 32` | 桌面密度：比移动端松一档。密了像后台系统，松了像演示稿 |
| **圆角** | 控件 `--r-sm/md 6/8` · 卡片 `--r-lg/xl 12/16` · 大容器 `--r-2xl 20` · chip 全圆 | ≤ 20 封顶（design-system §5.3）。圆角与动效幅度共享同一坐标系：18px 圆角配 24px 滑入才不突兀 |
| **阴影** | 4 级：`xs/sm` 静态 · `md` hover · `lg` 仅浮层 | 阴影预算极克制 —— 层级靠描边与底色差表达，阴影只确认"浮起来了" |
| **模糊** | `--mt-blur: 0` | **Default 无毛玻璃**。与「窗口即纸面」语言冲突：纸不透视。毛玻璃是 Lively 的特权（`--mt-blur: 1`） |
| **透明度** | scrim `rgba(20,23,28,.32)` · 入场起点 `--mt-fade-from .05` · 窗口 `--mt-fade-window .7` | 透明度只出现在三处：遮罩、入场第一步、Cinema。内容层永远不透明 |
| **信息层级** | `--text-1(17.4:1) → text-2(7.2) → text-3(4.9) → text-4(3.1，仅占位)` × 九级字号 · 数字 `tabular-nums` | 四级文字 + 九级字号构成全部层级；**不靠颜色深浅以外的方式**（无大写强调、无加粗轰炸）。text-4 不承载信息，只承载"这里可以不读" |

---

## 四、Default Skin 参数表（skin.json）

`schemaVersion 1` 纯声明式。**它同时也是「空参数表」** —— 这正是 Default 的定义：

```jsonc
{
  "schemaVersion": 1,
  "id": "workspace.default",
  "name": "默认",
  "version": "1.0.0",
  "description": "官方外观与手感。Token 基线本身，零覆盖。",

  "motion":   { "intensity": 1, "drift": 1, "scaleOn": 1, "blur": 0 },
  "stagger":  24,
  "easing":   {},            // 空 = 用 tokens.css 的 --mt-ease-* 基线（含 --mt-ease-emphasis）
  "durations": {},           // 空 = 全部 26 个 duration token 用基线值

  "capabilities": { "accent": false, "viewTransitions": true }
}
```

| 设计参数 | 值 | 来源 |
|---|---|---|
| intensity / drift / scaleOn | `1 / 1 / 1` | tokens.css §MOTION TOKENS |
| blur | `0` | 同上（Default 无毛玻璃） |
| stagger | `24ms` | 同上 |
| easing | 基线 4 条（`--mt-ease-out/in/inout/emphasis`） | 同上 |
| durations | 26 个 duration token 全基线；`--mt-dur-dwell 320ms` 与 `--mt-cinema-interactive-gate 240ms` 禁改 | 同上 |
| 颜色 / 密度 / 圆角 / 阴影 | **不在 skin.json 内** —— 它们是主题层与布局层，Default 的"取值"就是 `tokens.css` / `design-system §5` 现值 | 本文 §一/§三 |

> 实现注意（重申 skin-system.md §4）：Default 走**移除 `data-skin` 属性**路径，运行时不注入上表任何值；
> 上表的意义是"把基线登记为官方选择"，以及作为 Calm / Lively 的推导原点。

---

## 五、Showcase：Skin Lab 页面

### 5.1 目的与形态

在动效规范页（`ROUTES.showcase`）新增入口「皮肤实验室」→ `#/skinlab`（**主 IA 不动**）。
一屏之内并排放三块**真实组件**样本 —— 首页 / 设置 / Workspace —— 顶部一个参数沙箱，
切换 Default / Calm / Lively 三档，立即在同一屏感受「Skin + Motion + Layout」的整体效果。

### 5.2 `--mt-skin-*` 预览通道（演示层，非 Runtime 能力）

沙箱只作用于页面内的一个容器，不持久化、不影响全局，等价于 skin-system.md §7.1 步骤④的页内形态：

```css
.skin-sandbox{
  /* 皮肤参数一律经 --mt-skin-* 通道进入；fallback = Default 基线 */
  --mt-intensity: var(--mt-skin-intensity, 1);
  --mt-stagger:   var(--mt-skin-stagger, 24ms);
}
```

| 档位 | `--mt-skin-intensity` | `--mt-skin-stagger` |
|---|---|---|
| Default | 不设置（fallback 1） | 不设置（fallback 24ms） |
| Calm | `.55` | `12ms` |
| Lively | `1.35` | `32ms` |

切档只改**这一个容器**的 inline style（S2：局部更新，不重绘、不触发场景动画、不进 VT）。
节奏维度（durations）不在沙箱演示 —— 沙箱必须诚实：它演示的是幅度轴，
完整节奏差异在皮肤通道实现后于设置·外观生效。

### 5.3 三块样本（全部复用真实组件 class，禁止另造假组件）

1. **首页样本**：Display 问候语（26/34 600）+ 一行 `app-square`（真实 hover 抬升 / press 按压 / 点击有 `launching` 本地 loading + Toast）。
2. **设置样本**：三行 `setRow` —— 主题分段控件（真实切换 `data-theme`）、动画三档（真实 `set-motion`）、开关（真实翻转）。**在样本里改主题，整个应用立即变** —— 这就是"Skin 参与整体效果"的证明。
3. **Workspace 样本**：`--bg-sunken` 底 + 两个静态窗口卡（标题栏 + 骨架行 + 状态点），配软件栏样式；hover 有 `md` 阴影。静态复刻，不接 `initStage()`（避免为演示引入运行路径）。

页头下方附一条**色板带**：主色 / 辅色 / 状态三件套 / 背景四层的真实色块 + token 名 —— 本文 §一的可视化。
底部三个直达按钮：打开真实首页 / 设置 / 工作空间（`data-act="go"`）。

---

## 六、验收标准（"第一眼是完整产品"的操作化定义）

不是"代码通过"，而是下面这张走查表全部为真：

| # | 走查项 | 通过标准 |
|---|---|---|
| V1 | 打开首页 3 秒内 | 问候语 → 工作空间卡 → 次级模块的视觉顺序无需思考；无任何"占位感"元素（空状态按 §7.1 有真内容） |
| V2 | 任意元素 hover | 1px 抬升 + 描边变化在 140ms 内完成；没有一处"hover 了但没反应" |
| V3 | 主按钮按下 | 80ms 内有明确"按进纸面"反馈；松开即回弹到位，无果冻感 |
| V4 | 首页 → 设置 → 返回 | 220ms 翻页感；scrollTop 与焦点符合 S2 纪律；无白屏瞬间 |
| V5 | 进 Workspace | 240ms 后点击任意窗口**必定命中**；560ms 内视觉完全静止 |
| V6 | 拖拽一张卡 | 被拖元素 1:1 跟手；邻居让位；松手磁吸归位 + 一次描边脉冲收尾 |
| V7 | 切深色主题 | 全部层级关系保持（纸面模型在暗色下依然三层分明）；文字对比度不降级 |
| V8 | Skin Lab 切三档 | 同一屏内 Calm 明显更静、Lively 明显更活、**反馈跟手程度三者一致** |
| V9 | 整体气质 | 没有渐变、没有发光、没有回弹、没有超过 1.02 的缩放（E7 红线零违反） |

**一句话**：用户不会想到"皮肤"或"框架"——他只会觉得这个应用**本来就该长这样**。
Default Skin 的成功标准是被忽略。
