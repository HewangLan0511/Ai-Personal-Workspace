# TECH-01 · Design Token Runtime + Motion Runtime 技术说明

> 交付日期：2026-09-14 · 状态：✅ 已交付（验收 9/9，见 `tools/verify_tech01.py`）
> 定位：承载 Design System、Motion System D1-D7 与未来 Skin System 的工程底座。
> 本阶段**不包含**任何 UI 重设计、IA 重排、业务逻辑变更。

## 一、总体架构

```text
Product Core
    ↓
Design System（tokens.css：Foundation → Semantic）
    ↓
Default Skin（TECH-01 §五给定的 Default 值）
    ↓
Active Skin（预留：Skin Override 只写 Semantic 层之上）
    ↓
Semantic Tokens → Components → UI
```

```text
Core Motion System（本运行时，安全规则固化）
    ↓
Motion Guard（不可被 Skin 关闭）
    ↓
Skin Motion Profile（预留：easing/intensity/drift/scale/blur 风格覆盖）
    ↓
Component Motion → UI
```

## 二、文件清单

| 文件 | 职责 |
|------|------|
| `ui/src/styles/tokens.css` | Design Token：Foundation（原始材料）→ Semantic（组件唯一消费层）→ Legacy 桥接（`--bg/--panel/--accent...` 指向 Semantic，存量样式零改动兼容）；含暗色主题映射 |
| `ui/src/styles/motion-tokens.css` | Motion Token：duration/easing/intensity/gate 变量 + `data-motion`/`data-perf` 档位映射 + 交互元素 motion 基线 |
| `ui/src/motion/config.ts` | 优先级表（§十一 8 级）、DUR/页面过渡/Cinema 时间轴常量 |
| `ui/src/motion/guards.ts` | Motion Guard（standard/reduced/off，系统偏好+用户覆盖持久化）+ Performance Guard（normal/reduced/emergency），档位经 `data-motion`/`data-perf` 下发 CSS |
| `ui/src/motion/conflict.ts` | Conflict Guard：按元素登记 claim，高优先级让位低优先级（onSuperseded 快速收敛），同一元素只有一个 Primary |
| `ui/src/motion/interrupt.ts` | Interrupt Guard：WAAPI 封装，cancel/finish/最大生命周期（duration+1s 强制收敛，Promise 必收敛） |
| `ui/src/motion/pageTransition.ts` | Page Transition：content-only（out 160ms / in 200ms），世代号 latest-wins，离场页 absolute 浮出 |
| `ui/src/motion/cinema.ts` | Workspace Cinema 原语：§十四时间轴（begin 80 / switch 160 / positioning+gate 240 / stable 560），Interactive Gate promise、resize→取消空间动画→重算布局→快速收敛 |
| `ui/src/motion/viewTransition.ts` | VT 渐进增强：`motionViewTransition()` 唯一入口，`?motion=novt` 强制 fallback，业务代码禁止直调 `document.startViewTransition` |
| `ui/src/motion/runtime.ts` | 门面 + `window.__pwMotion` 调试口（测试用） |
| `ui/src/views/DevMotionHarness.vue` | 验证固件（`/dev/motion`，dev-only，不进导航） |
| `tools/verify_tech01.py` | 验收脚本：Edge headless + CDP 实测 Test 1~8 |

## 三、关键设计决策

1. **Duration 与 Intensity 解耦（§七）**：intensity 只进幅度（translate/scale/blur/opacity），永远不乘 duration。档位切换时 `--mt-dur-quick` 纹丝不动（Test 6 断言）。
2. **Legacy 桥接而非全量改造**：`base.css` 原裸值块整体删除，`--bg/--panel/--text/--shadow` 等旧名在 tokens.css 中桥接到 Semantic 层 —— 存量 796 行样式与全部组件**零改动**即接入 token 体系；新代码禁止使用旧名。
3. **安全规则固化、风格规则参数化（§十八）**：Interactive Gate / Guard 档位 / 冲突优先级 / 中断规则是常量与闭包，Skin 未来只能经 `--mt-*` 变量与 profile 覆盖风格值，无法绕过安全层。
4. **headless 的 reduced-motion**：Edge headless 默认上报 `prefers-reduced-motion: reduce`，Motion Guard 正确自动进 reduced 档 —— 反向证明了系统偏好链路生效。验收脚本显式 `setLevel('standard')` 建立基线并留档初始档位。
5. **S2 指标纯粹化**：固件滚动容器 `overflow-anchor: none` —— 浏览器滚动锚定会在删行时自动调整 scrollTop 掩盖"是否 remount"，关掉后 scrollTop 只由容器状态决定（remount 归零 / 局部更新原样保留）。
6. **页面过渡不依赖 VT**：WAAPI 为基础依赖，VT 纯增强（Test 5 断言整轮导航 `vtCalls === 0`）。

## 四、验收结果（9/9，release 构建 + Edge headless + CDP）

| 测试 | 断言要点 | 结果 |
|------|----------|:----:|
| Test 1 S2 | 过滤 200→100 行 / 重排首行变化（区分度）；scrollTop 150 恒定；`__dmhMounted` 探针存活（未 remount） | ✅ |
| Test 2 Conflict | Hover→Drag 让位、Press→Drag 快速结束、迟到的低优先级不成为 Primary 也不误报让位 | ✅ |
| Test 3 Cinema Gate | gate 实测 245.6ms（目标 240），trace 全相位 | ✅ |
| Test 4 Cinema Resize | 260ms 触发 resize → 262.9ms 已 stable（远早于 560ms 全轴），layout 重算 ≥2 次 | ✅ |
| Test 5 latest-wins | /software→/life→/plugins→/device 连续导航（40ms 间隔），终态 /device、中间页移除、终态 opacity=1、无悬挂动画 | ✅ |
| Test 6 Reduced | intensity 1→0.35、blur→0，`--mt-dur-quick` 不变（解耦证据） | ✅ |
| Test 7 Off | 装饰 transition→0s，`.pw-motion-essential` 豁免保持 1s | ✅ |
| Test 8 novt | 带 `?motion=novt`：vtEnabled=false、同步 fallback、VT 零调用；无参数：VT 真实走通（spy=1） | ✅ |

诚实声明：交互为 CDP 合成事件（el.click / dispatchEvent），非真人鼠标；core 后端不在场，验证的是 Motion Runtime 与 S2 行为，不含业务数据链路。产品页面的 S2 保障另可静态核验（列表稳定 `:key`、过滤为同容器响应式更新）。

## 五、组件接入方式（后续 UI 工作的约定）

- 颜色/圆角/阴影/间距：只引用 Semantic Token（`--surface-1` / `--text-2` / `--radius-card`...），禁止硬编码色值与旧变量名。
- 动画：时长用 `--mt-dur-*`，幅度用 `--mt-intensity/--mt-drift/--mt-scale-on/--mt-blur`；复杂序列走 `@/motion`（animate/claim/pageTransition/cinema），组件不自带动画系统。
- 视图更新：需要 VT 时调用 `motionViewTransition()`，不直调浏览器 API。
- 装饰性动画在 off/emergency 下会被豁免规则清零；必要状态反馈（loading/进度/焦点）加 `.pw-motion-essential` 类豁免。

## §J · #22 DevTools Performance 性能体检（2026-09-14）

**结论：PASS WITH LIMITATION（0 项 NEEDS FIX）** —— 14 个采样场景（Cinema / Page Transition / 拖拽 / 重排 / 主题 / Resize / 快速连续操作 / Toast / AI 侧栏 / 三档 Guard 对比）**0 个 Long Task**，无病态重排、无多余 DOM 重建。完整数据与逐项判定见 **`performance-baseline-22.md`**；采样脚本 `tools/perf_tech01_22.py`，原始数据 `tools/perf22-results.json`。

要点：
- diff 路径（局部过滤）的样式计算约为整页导航重挂的 **1/5**（Recalc 2/次 vs 10/次）——S2 纪律有实测收益。
- Motion Off/Reduced **不减少**必要 DOM/Layout 工作（三档一致）——这是 §九 设计使然：Guard 只关非必要动效，不是性能开关。
- 无法可靠测量（headless 限制，如实记录）：真实 FPS/帧间隔、Composite 成本、Off 档 transition 收益。
- 两条**必须重测**的登记项：S5（core 在场后的 Plugins 真实数据 diff）、S6b（Workspace Engine 真实布局回调后的 Cinema 成本）。

验收脚本说明：`perf_tech01_22.py` 复用 `verify_tech01.py` 的 CDP 客户端与 SPA 静态服务；整页导航（goto）发生在测量窗口之外的 setup 段——CDP 计数器随文档导航重置，跨导航测增量会出负值伪影。
