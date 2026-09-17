# Skin System · 产品规范 v1.0

> 定位：给 Personal Workspace 的动效体系加一层「性格皮肤」。
> **本文档只设计皮肤层，不改任何已有 Motion，不改 Runtime 架构。**
> 上游依据：`motion-system.md` §E4（性格旋钮）/ §F（MotionPack 契约）/ §E5（降级）/ §E7（禁止清单）。
> 代码事实来源：`tokens.css` §MOTION TOKENS 与 `index.html` §1.5（两者镜像同步）。

---

## 0. 不变量（Skin 不得触碰的既有设计）

以下条目是从现有代码与已锁定决策中**原样引用**的，Skin 规范在它们之上做加法，不做修改：

| # | 不变量 | 出处 |
|---|---|---|
| I1 | **Duration 与 Intensity 正交，禁止相乘**。Skin 改幅度不改节奏，或改节奏不改幅度 | D2 |
| I2 | 降级三档 standard / reduced / off 走**变量覆盖**，不用 `!important` 归零动画 | D2 / E5 |
| I3 | 禁止回弹 / 弹性缓动 / 粒子 / 大幅飞入 / **缩放超过 1.02（即低于 0.98）** | E7 |
| I4 | 回退链：Skin preset → Skin token → Default → 无动画；缺项降级不报错 | F2 |
| I5 | 热切换只替换 `:root` 变量集，**不打断正在播放的动画** | F4 |
| I6 | `--mt-cinema-interactive-gate: 240ms` 与 `--mt-dur-dwell: 320ms` 是**可用性参数** | E6 / tokens.css |
| I7 | 组件层禁止 `cubic-bezier(` 与裸时长，只有 token 层可以出现 | F5 |
| I8 | loading 循环（`.skel` / `.spinner`）是功能动画，reduced 下静止、off 下静止 | tokens.css |

**Skin 的本质（一句话）**：把 §E4 的四个旋钮 + 一组节奏预设，做成可导入、可校验、可切换的包。
**它不引入新的动画机制，不新增 intent，不改关键帧。**

---

## 1. Skin 包结构

```
<skin-id>.pwskin                 # 分发单元 = 改后缀的 zip（原型阶段：允许直接选一个 skin.json）
├── skin.json                    # 必需。唯一事实来源，纯声明式（见 §1.1）
├── preview.png                  # 必需。256×160，静态截图，供皮肤选择器展示
└── LICENSE                      # 建议。缺省按「未验证皮肤」处理
```

**v1 明确不存在的文件**：`skin.css`、`skin.js`。
原因见 §2 的校验模型：v1 必须是**纯声明式**才能做完整的静态值域校验；
自由 CSS 无法静态证明它不违反 I1/I3，也无法保证不偷改禁改变量。
`presets` / `keyframes`（F2 契约中的 WAAPI 通道）留给 schemaVersion 2，见 §1.3。

### 1.1 `skin.json` schema（schemaVersion 1）

```jsonc
{
  "schemaVersion": 1,
  "id": "designer.calm",              // 反域名，全局唯一，导入时作为 [data-skin] 的值
  "name": "Calm",                     // 皮肤选择器里显示的名字
  "version": "1.0.0",                 // 皮肤自身版本（semver）
  "author": "…",
  "description": "…",                 // ≤ 60 字，选择器副标题

  "motion": {                         // → §E4 四个性格旋钮（T1 层）
    "intensity": 0.55,                // 必填。0 ~ 1.5
    "drift": 1,                       // 必填。0 | 1
    "scaleOn": 1,                     // 必填。0 | 1
    "blur": 0                         // 必填。0 | 1
  },

  "durations": {                      // 可选。key 白名单见 §3.1（T2 层）
    "hover": 120, "drawer": 200
  },
  "stagger": 12,                      // 可选。0 ~ 60（ms）
  "easing": {                         // 可选。key ∈ out | in | inout | emphasis
    "emphasis": "cubic-bezier(0.3, 0, 0.2, 1)"
  },

  "capabilities": {                   // 可选能力，默认全 false
    "accent": false,                  // 是否携带品牌色覆盖（见 §2 T4）
    "viewTransitions": true           // 本皮肤是否允许走 VT 路径（#18 未落地前无效）
  }
}
```

### 1.2 字段 → MotionPack 契约的对应（不改架构，只是声明式子集）

`skin.json` 是 `motion-system.md §F2` 中 `MotionPack` 的**声明式投影**，一一对应：

| skin.json 字段 | MotionPack 字段 | 运行时落点 |
|---|---|---|
| `motion.*` + `durations.*` + `stagger` + `easing.*` | `tokens: Record<string,string>` | 注入 `:root[data-skin="<id>"]` 的 CSS 变量 |
| `presets`（v2 预留） | `presets` | `motion.play(el, intent)` 查表 |
| `keyframes`（v2 预留） | `keyframes` | WAAPI 通道 |
| `capabilities` | `capabilities` | `canUseViewTransitions()` 参与判定 |
| `id` / `name` / `version` / `schemaVersion` | 同名元数据 | 注册表 key / UI 展示 / 迁移判定 |

### 1.3 schemaVersion 演进

- `1`：纯声明式（本文档）。
- `2`（预留）：开放 `presets` / `keyframes`，即完整 F2 契约；届时门禁从"静态值域"升级为"运行时校验 + 剥离"。
- 导入时 `schemaVersion > 当前支持` → **拒绝整个包**并回退当前皮肤（I4），UI 明确提示"皮肤需要更新版本的 Workspace"，绝不半生效。

---

## 2. Skin 能控制哪些视觉变量（四级白名单）

原则：**离"表达"越近越自由，离"可用性"越近越锁死。**

| 层 | 变量 | Skin 权限 | 理由 |
|---|---|---|---|
| **T1 幅度旋钮** | `--mt-intensity` / `--mt-drift` / `--mt-scale-on` / `--mt-blur` | 自由（值域见 §3.3） | §E4 的设计初衷：换性格只动这四个 |
| **T2 节奏** | `--mt-dur-*`（白名单子集，见 §3.1）、`--mt-stagger`、`--mt-ease-{out,in,inout,emphasis}` | 白名单内自由（值域见 §3.3） | "快而克制 / 慢而活泼"靠这层实现 |
| **T3 派生幅度** | `--mt-dist-*`(8) / `--mt-scale-*`(3) / `--mt-fade-*`(3) | **禁改** | 它们是 T1 的**派生值**（`calc(N * intensity * drift)`）。Skin 直接给派生值 = 绕过唯一旋钮，幅度模型失效 |
| **T4 品牌色**（可选能力） | `--brand-50…700` / `--brand-contrast` / `--app-tint-*` + `--app-ink-*` | 仅当 `capabilities.accent = true`；必须**同时给浅色 + 深色两套**，且通过对比度门禁 | 纯装饰。三只内置皮肤都不用它——这本身就验证了 T1/T2 足够表达性格 |

### 2.1 禁改清单（导入校验直接拒绝或忽略）

| 变量 | 为什么禁 |
|---|---|
| `--text-1…4` / `--text-inverse` / `--text-on-brand` | 可读性（4.9:1 以上的既有对比度），皮肤无权破坏 |
| `--space-*` / `--gap-*` / `--pad-*` / `--fs-*` / `--lh-*` | 布局稳定性：改间距/字号必然破版，且与"动效性格"无关 |
| `--r-*` | 圆角参与命中感知与视觉尺寸，动效幅度以它为参照 |
| `--dur-micro/fast/base/slow` | 它们是**旧名映射**（→ `--mt-dur-*`），改它们 = 改两处，必须改 T2 源头 |
| `--mt-dur-dwell` | I6：交互节奏（拖到最小停顿多久折叠），不是装饰 |
| `--mt-cinema-interactive-gate` | I6：240ms 可交互门限，皮肤**不得延长**（用户等待权 > 风格） |
| `--mt-dur-ambient` | 功能循环（loading），与性格无关 |
| 任何 `--shadow-*` / `--scrim` / `--bg-*` / `--surface-*` | v1 范围外；皮肤不是主题系统 |

> 校验行为按变量分级：T1/T2 白名单内的 → 应用；白名单外的 → **丢弃并在导入报告中列明**（不拒绝整个包，遵循 I4 的"缺项降级"精神）。
> 唯一例外：`schemaVersion` 不匹配 → 拒绝整包（§1.3）。

---

## 3. Skin 与 Motion Token 的映射

### 3.1 T2 节奏白名单（`durations.*` 的合法 key → 目标变量）

**反馈类**（交互可用性参数，值域收窄到基线 ±20%，见 §3.3）：
`press → --mt-dur-press`、`hover`、`drag`、`ctx`、`drop`、`perm`

**装饰类**（风格参数，值域基线 ±50%）：
`highlight`、`reorder`、`scene-out`、`scene-in`、`window`、`toast-in`、`toast-out`、
`drawer`、`modal-bg`、`modal`、`ai`、`ai-out`、`nav`、`nav-out`、
`entrance`、`entrance-ws`、`entrance-2`

> 这组分类是本规范的产品判断：**反馈时长是可用性参数，装饰时长才是风格参数。**
> 所以 Lively 可以把入场做长，但 hover / press 必须仍然"跟手"。
> `highlight`（落位成功高亮）归装饰类：drop 本身已经完成交互，它只是事后脉冲。
> 不在两份名单里的 duration 一律禁改（`dwell` / `ambient` / `gate`，见 §2.1）。

### 3.2 三条硬规则（校验器照此实现）

1. **不相乘（I1 的校验形式）**：v1 是纯声明式，天然不可能写出 `calc(dur * intensity)`；
   schemaVersion 2 开放 keyframes 后，校验器必须扫描皮肤提供的 keyframe/preset 字符串，
   发现 `--mt-dur-*` 与 intensity/drift/scale-on 出现在同一 `calc()` → **剥离该项并告警**。
2. **派生量唯一来源是 T1**：`durations` / `easing` / `motion` 之外出现的任何 `--mt-dist-*` /
   `--mt-scale-*` / `--mt-fade-*` 键 → 丢弃（T3 禁改）。
3. **easing 白名单 + 形状校验**：`easing.*` 只接受 `cubic-bezier(x1,y1,x2,y2)`，且
   `x1,x2 ∈ [0,1]`（CSS 硬要求），`y1,y2 ∈ [0,1]`（**比 CSS 严**：超出 = 回弹，违反 I3）。

### 3.3 值域（校验器的常量表，含推导）

| 字段 | 允许值 | 推导 |
|---|---|---|
| `motion.intensity` | `[0, 1.5]` | **上限由 I3 卡出**：`--mt-scale-float = 1 − .02 × I` ≥ .97 → I ≤ 1.5。位移侧 `--mt-dist-panel = 24I ≤ 40px` → I ≤ 1.67，不是约束。故 1.5 是硬上限 |
| `motion.drift` / `motion.scaleOn` | `0 \| 1` | §E4 定义为总开关 |
| `motion.blur` | `0 \| 1` | 毛玻璃伴随，默认关 |
| `stagger` | `[0, 60]` ms | 基线 24ms，±50% ≈ 12–36，放宽到 60 给表现型皮肤 |
| `durations.反馈类` | `基线 × [0.8, 1.2]` | 可用性：反馈感知延迟显著变化会改变"跟手"判断 |
| `durations.装饰类` | `基线 × [0.5, 1.5]` | 风格自由，但 1.5× 上限保证 cinema 等总编排（240+320ms）不被拉爆 |
| easing | §3.2 规则 3 | — |

**越界处理**：钳制到边界值，并在导入报告标为「已钳制」（不是拒绝——与"缺项降级"一致的宽容策略）。
唯一整包拒绝条件：`schemaVersion` 不支持 / JSON 不可解析 / 缺 `id` 或 `motion.intensity`。

---

## 4. Default Skin（内置，回退链的底）

> **视觉规范见 `default-skin.md`（v1.0）**：颜色系统 / 三皮肤手感关系 / 六种动效感觉 /
> 空间层级的产品化声明，以及 `#/skinlab` 皮肤实验室（三块真实样本 + `--mt-skin-*` 预览通道）。
> 本节只保留它在皮肤体系中的**结构性定义**。

**定义：Default Skin = 零覆盖。** 它的 tokens 表就是 `tokens.css` §MOTION TOKENS 的现值，
一个不多、一个不少。它不可卸载、不可被删除，`id = "workspace.default"`，不出现在皮肤选择器里
（它是"没有皮肤"的状态，选择器里显示为「默认」一项，选中即移除 `data-skin` 属性）。

```jsonc
{ "schemaVersion": 1, "id": "workspace.default", "name": "默认",
  "motion": { "intensity": 1, "drift": 1, "scaleOn": 1, "blur": 0 },
  "durations": {}, "stagger": 24, "easing": {},
  "capabilities": { "accent": false, "viewTransitions": true } }
```

实现要求：**Default 走"移除 `data-skin` 属性"路径，不注入任何变量**。
这保证皮肤层出任何问题时（注册表损坏、JSON 被手改坏），运行时的恢复动作永远是"回到无皮肤态"，
与 F4「绝不白屏」一致。

---

## 5. Calm Skin（低干扰）

**设计陈述**：所有位移减半、入场更利落、错峰减半；**交互反馈几乎不变**（跟手是可用性，不拿来让风格）；
不使用毛玻璃；曲线整体收直（少一点"表演感"）。

```jsonc
{
  "schemaVersion": 1,
  "id": "workspace.calm",
  "name": "Calm",
  "version": "1.0.0",
  "description": "位移减半、节奏利落，反馈保持跟手。长时间使用不累。",

  "motion":   { "intensity": 0.55, "drift": 1, "scaleOn": 1, "blur": 0 },
  "stagger":  12,

  "easing": {
    "out":      "cubic-bezier(0.3, 0.4, 0.3, 1)",
    "emphasis": "cubic-bezier(0.3, 0, 0.2, 1)"     // 从 .05,.7,.1,1 收直，去表演感
  },

  "durations": {
    "press": 70, "hover": 120, "drag": 80, "ctx": 80, "drop": 130, "highlight": 320, "perm": 120,
    "reorder": 120, "scene-out": 60, "scene-in": 120, "window": 160,
    "toast-in": 140, "toast-out": 100, "drawer": 200, "modal-bg": 120, "modal": 160,
    "ai": 220, "ai-out": 180, "nav": 220, "nav-out": 180,
    "entrance": 160, "entrance-ws": 180, "entrance-2": 140
  },

  "capabilities": { "accent": false, "viewTransitions": true }
}
```

自检：`intensity .55` → `--mt-scale-press = 1 − .015×.55 = .992`（远高于 .97 红线）；
`--mt-dist-page = 2.2px`（基线 4px 的一半）。落在 §3.3 全部值域内。

---

## 6. Lively Skin（高活力）

**设计陈述**：幅度顶到接近安全上限、错峰拉开、毛玻璃伴随打开、入场比基线长；
**反馈时长保持基线** —— 活泼来自"动作更大更明显"，不来自"反馈变迟钝"。

```jsonc
{
  "schemaVersion": 1,
  "id": "workspace.lively",
  "name": "Lively",
  "version": "1.0.0",
  "description": "幅度拉满、错峰明显、毛玻璃伴随。演示与个人设备适用。",

  "motion":   { "intensity": 1.35, "drift": 1, "scaleOn": 1, "blur": 1 },
  "stagger":  32,

  "easing": {
    "emphasis": "cubic-bezier(0.05, 0.7, 0.1, 1)"   // 与基线一致：强调感本来就来自它
  },

  "durations": {
    "press": 80, "hover": 140, "drag": 100, "ctx": 100, "drop": 160, "highlight": 520, "perm": 140,
    "reorder": 180, "scene-out": 80, "scene-in": 160, "window": 220,
    "toast-in": 200, "toast-out": 120, "drawer": 280, "modal-bg": 140, "modal": 200,
    "ai": 300, "ai-out": 220, "nav": 300, "nav-out": 220,
    "entrance": 240, "entrance-ws": 260, "entrance-2": 220
  },

  "capabilities": { "accent": false, "viewTransitions": true }
}
```

自检：`intensity 1.35`（< 1.5 上限）→ `--mt-scale-press = .9798`（≥ .97 ✓）、
`--mt-scale-float = .973`（≥ .97 ✓，**这就是 1.5 上限的由来，Lively 1.35 留了余量**）、
`--mt-dist-panel = 32.4px`（< 40 ✓）、`--mt-fade-from = 0`（入场从全透明开始 —— Lively 的已知特征，
reduced 档会把它拉回 `.47`）。全部落在 §3.3 值域内。

---

## 7. 外部设计师导入规范

### 7.1 导入流程（五步，每步可判定）

```
选择文件 → ①解析 → ②schema 校验 → ③值域/门禁校验 → ④沙箱预览 → 用户确认 → ⑤持久化生效
                └─ 任何一步失败：回到当前皮肤，绝不半生效
```

| 步 | 规则 | 失败行为 |
|---|---|---|
| ① 解析 | JSON 可解析、`schemaVersion` 受支持、`id` 非空且不与内置 `workspace.*` 冲突 | **整包拒绝**，错误码 `E_PARSE` / `E_SCHEMA` / `E_ID` |
| ② schema | 必填：`motion.intensity`；类型：数值/布尔/白名单 key | 未知 key **忽略并记录**（向前兼容） |
| ③ 值域 | §3.3 常量表；T3/禁改清单 §2.1 | **逐项钳制/丢弃并记录**，不拒绝整包 |
| ④ 预览 | 变量挂 `data-skin-preview`（临时属性），**不持久化**；预览面板同时展示三档降级下的效果 | 用户取消 → 摘掉属性即恢复 |
| ⑤ 生效 | 写 `localStorage("pw.skin")`，挂 `data-skin="<id>"`，Toast 确认 | 写失败 → Toast 报错，保持预览态 |

### 7.2 导入报告（产品硬要求，不是可选项）

导入面板必须展示一张**逐项结果表**，每个字段一行：`字段 / 传入值 / 生效值 / 状态`
（状态 ∈ 应用 · 已钳制 · 已忽略 · 已丢弃）。这是 F4「不合规项丢弃并告警，不影响其余」的 UI 化——
**没有这张表，"静默钳制"就变成了静默篡改设计师意图。**

未签名 / 非内置皮肤在选择器中标注「未验证」，可随时一键回默认。

### 7.3 设计师视角的承诺（写进导入面板文案）

> 皮肤只能改变"动多少、动多久、动得多明显"，**不能**改变布局、字号、间距、文字颜色，
> 也不能延长"可以开始操作"的等待时间。所以任何皮肤都装不坏你的工作区。

---

## 8. Skin 切换动画规则

### 8.1 切换 = 变量替换，不是一次"动画"

- 实现：换 `data-skin` 属性 → 该皮肤变量集生效 → **不触发场景动画、不重建 DOM、不进 VT**（S2 纪律）。
- 正在播放的动画：**不重播、不闪断**，按新参数自然收敛（I5）。CSS 的机制保证这一点：
  使用 `var(--mt-*)` 的属性在变量替换后按新计算值继续；transition 元素平滑滑到新幅度，keyframes 动画不中断。
- 长动画（cinema 正在播）同样收敛，不重启。

### 8.2 反馈：靠"看得见的变化"，不靠"切皮动画"

- **Toast 确认**：`已切换到「Lively」皮肤`（与 `set-motion` 的既有反馈同型，入口在设置·外观）。
- **即时可感**：若切换发生在 showcase / guard 页，自动重播一次当前演示（复用 `mtReplay`），
  让用户当场看到差别；其他页面不做任何额外动画 —— 下一次自然发生的动效就是反馈。
- **禁止**：全屏闪白 / 交叉淡变 / "皮肤应用中"遮罩。换肤是**局部变量更新**，把它做成全屏过渡违反 S2。

### 8.3 与降级三档的叠加（正交开关，降级永远赢）

- Skin 与 `data-motion` 是两个独立开关：**先按皮肤生效，降级在其上再覆盖**。
- 用户在 reduced/off 时选了 Lively：skin 照常记住（刷新后仍恢复该选择），但**实际幅度/节奏以降级为准**。
- 预览与皮肤选择器必须**如实反映这一点**：reduced/off 档位下展示"你的皮肤在当前降级档位下的真实效果"，
  不展示"如果切回完整档会怎样"的幻想预览。

---

## 9. 实现交接（给技术 Agent）

### 9.1 唯一允许触碰 `tokens.css` 的改动：层叠契约

**发现的真实冲突**：皮肤变量若挂 `:root[data-skin="x"]`（特异性 0,2,0），会**压过**现有的
`[data-motion="off"]`（0,1,0）降级块 —— `off` 失效，皮肤用户再也无法真正关掉动画。
靠源码顺序保证降级赢是脆弱的（注入点一变就翻车）。

**契约**：降级块与 `prefers-reduced-motion` 块中的**自定义属性声明**追加 `!important`：

```css
[data-motion="reduced"]{ --mt-intensity: .35 !important; --mt-drift: 0 !important; /* …其余变量同 */ }
[data-motion="off"]{ --mt-intensity: 0 !important; /* … */ }
```

> 说明：这不是 I2 禁止的那种「`!important` 归零动画」——归零的对象是**变量声明的优先级**，
> 动画本身仍由变量驱动（reduced 档仍有 .35 幅度的动画在播）。它只是把"降级层 > 风格层"从
> 靠顺序变成靠声明，skin 注入点从此可以随便放。

### 9.2 落地清单

| # | 事项 | 落点 |
|---|---|---|
| 1 | `applySkin(id)` / `canUseVT()` 已有能力合并 | `index.html`（新增 `motion` 命名空间或独立 `skin.js` 段） |
| 2 | 三只内置皮肤（§4–6 的 JSON 常量） | `index.html` 顶部常量区（原型） |
| 3 | 校验器（§3.2 / §3.3 常量表 + §2.1 禁改清单） | 独立纯函数 `validateSkin(json) → {ok, items[]}` |
| 4 | 皮肤选择器 UI（设置·外观，新增一行「皮肤」，与「动画」三档并排） | `setBodyHtml('appearance')` |
| 5 | 导入面板 + 逐项结果表（§7.2） | 复用现有 drawer / layer 体系 |
| 6 | 持久化 | `localStorage("pw.skin")`，启动时恢复 |
| 7 | `data-skin` / `data-skin-preview` 挂 `documentElement` | 同 `data-theme` / `data-motion` 的既有挂法 |

### 9.3 验收用例（可直接翻译成 `verify_skin_*.py`）

| # | 用例 | 判据 |
|---|---|---|
| S1 | 应用 Calm | `getComputedStyle(root).getPropertyValue('--mt-intensity') === '0.55'`；hover 卡片实测 `translateY = 0.55px` |
| S2 | **降级压过皮肤** | `data-motion="off"` + Lively → computed `--mt-intensity === '0'`（9.1 契约的回归点） |
| S3 | 越界钳制 | `intensity: 3` → 报告标「已钳制」，生效值 `1.5` |
| S4 | v2 字段前瞻 | 含 `presets` 的包 → 报告标「已忽略」，其余字段正常生效，**不拒绝整包** |
| S5 | 切换不打断播放 | showcase 重播进行到一半时切皮肤 → 动画不闪断、不重播（对照：DOM 重建会重播） |
| S6 | 持久化 | 切 Calm → 刷新 → 仍为 Calm；选「默认」→ 刷新 → `data-skin` 属性不存在 |
| S7 | 红线自检 | Lively 下 `--mt-scale-press ≥ .97` 且 `--mt-scale-float ≥ .97` |
| S8 | 选择器如实反映降级 | off 档下预览面板展示的是降级后的真实效果，文案不承诺"切回完整档的效果" |

### 9.4 明确不在本规范范围

- `presets` / `keyframes` / WAAPI 通道 / intent 化改造（schemaVersion 2）
- 主题级换色（T5 已留口子，但三只内置皮肤不使用，属独立立项）
- 移动端 / 触摸（PC-only 硬约束）
