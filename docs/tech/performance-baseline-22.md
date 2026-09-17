# #22 DevTools Performance · Motion System 性能基线

> 日期：2026-09-14 · 状态：**PASS WITH LIMITATION**（14 场景采样完成，0 项 NEEDS FIX）
> 工具：`tools/perf_tech01_22.py`（Edge Headless `--headless=new` + CDP）
> 原始数据：`tools/perf22-results.json`（逐场景全量指标）

## 一、测试环境

| 项 | 值 |
|----|----|
| 浏览器 | Edge headless=new（本机安装版），1440×900 |
| 被测物 | `ui/dist`（vite 生产构建，含 TECH-01 Token/Motion Runtime） |
| 承载 | 本地静态服务（SPA 回退），core 后端**不在场**（数据通道走降级/空态） |
| 指标来源 | CDP `Performance.getMetrics` 增量（Layout/RecalcStyle/Paint/Task/Script/Nodes）+ 页内 `PerformanceObserver('longtask')` + `MutationObserver`（DOM 增删）+ 几何读探针（启发式）+ rAF 帧间隔 |
| 基线档位 | Motion Guard 显式 standard（headless 默认上报 reduced-motion，Guard 正确接住——已另证） |

## 二、逐场景结果（全部真实测量，无估算值）

| 场景 | 动作 | 关键指标（CDP 增量） | Long Task | DOM 增删 | 判定 |
|------|------|---------------------|:---------:|----------|:----:|
| S1 Cinema | 原语全时序 + 4 探针元素 | Layout 3 / Recalc 16 / Task 0.04s | 0 | +5/−1 | **PASS** |
| S2 Page Transition | 真实锚点连续导航 ×4（40ms 间隔） | Layout 11 / Recalc 40 / Task 0.07s | 0 | +16/−8 | **PASS** |
| S3a Drag | AI 侧栏把手 CDP 真实鼠标拖拽 12 步 | Layout 12（=每步 1 次）/ Recalc 26 / Task 0.03s；geoReads=**4**（无 write→read 循环）；宽度 360→480 实证生效 | 0 | 0/0 | **PASS** |
| S3b Reorder | 固件重排 ×10 | Layout 10（=每次 1 次）/ Recalc 21 | 0 | +10/−10 | **PASS** |
| S4 Settings | 主题浅↔深 ×6（真实按钮） | Layout 18 / Recalc 73（≈12/次，全文档重算属主题语义）/ Task 0.11s | 0 | +4/−4 | **PASS** |
| S5 Plugins | 空态打开 + 扫描动作 | Layout 4 / Recalc 20 | 0 | +4/−2 | **PASS WITH LIMITATION**（无后端数据，列表 diff 无法在真实数据上测量） |
| S6a Resize | 真实视口变更 ×6（Emulation） | Layout 9（≈1.5/次，无风暴式重复计算）/ Recalc 23 | 0 | +7/−3 | **PASS** |
| S6b Cinema 中断 | Cinema 中真实 resize 事件 | Layout 0 / converged（trace stable）；layout 重算 1 次（初始布局被取消） | 0 | 0/0 | **PASS WITH LIMITATION**（探针为空布局——真实窗口布局成本待 Workspace Engine 接入后重测） |
| S7 快速连续操作 | 过滤 ×20 + SPA 导航 ×6 | Layout 36 / Recalc 71 / Task 0.11s（26 个动作累计）；DOM +1075/−1053（=200 行列表 diff ×20 + 6 次页面重挂载，语义正常） | 0 | 见前 | **PASS** |
| S8 Toast | 捕获弹窗空名提交 → 真实 notify | Layout 3 / Recalc 19；toast 文案「先给这个模式起个名字」实证出现 | 0 | +4/−2 | **PASS** |
| S9 AI Sidebar | 展开/收起 ×3 | Layout 9 / Recalc 9 | 0 | +6/−6 | **PASS** |
| S10 Guard 档位 | 同一动作集（过滤 ×10）× 三档 | standard 10/19 · reduced 10/19 · off 10/20（Layout/Recalc 几乎一致） | 0 | 各 +520/−520 | **PASS WITH LIMITATION**（见下） |

**全局汇总：14 个采样窗口、0 个 Long Task（>50ms 主线程任务）。**

## 三、重点检查结论（§三 逐条）

1. **Long Task**：未出现（含快速连续操作、拖拽、Cinema）。最大单场景 TaskDuration 0.13s/26 动作。
2. **单次交互大量 DOM 重建**：未发现。过滤/重排均为 diff 语义（S7 的 +1075/−1053 与"200 行列表 × 20 次 diff + 6 次导航"的理论量一致）。
3. **Forced layout / layout thrashing**：未发现。拖拽 12 步 geoReads=4（启发式探针），无 write→read 交错循环。
4. **Drag 高频重排**：每步恰好 1 次 Layout——宽度变化必然触发，属必要成本，非病态。
5. **Cinema 多元素并发动画主线程压力**：未检出（Task 0.04s）。⚠️ 本轮 Cinema 探针为空布局原语，真实窗口布局的成本必须在 Workspace Engine 落地后重测（已登记）。
6. **Page Transition 不必要的全页计算**：未发现——每次导航 Recalc ≈10 次、Layout ≈3 次，与离场/入场/新页首帧的必要工作一致；无整页额外重算。
7. **局部 diff 是否真比整页 render 省**：是。同一列表"过滤 diff"（Recalc ≈2/次，S10）对比"导航整页重挂"（Recalc ≈10/次，S2），**diff 路径的样式计算约为整页的 1/5**。
8. **Resize 高频重复计算**：无（6 次真实 resize → 9 次 Layout，含浏览器自身被动布局）。
9. **Motion Off/Reduced 是否降低成本**：**在必要 DOM 工作上没有降低——这是设计使然而非缺陷**（§九：Guard 只关非必要动效，不省必要状态更新的布局/样式计算；三档 Layout/Recalc 一致是正确行为）。可省的部分（transition/动画时长、模糊/位移幅度）在 headless 的 rAF 按需出帧下**无法可靠测量**，见 §四。

## 四、无法可靠测量的指标（如实记录，不伪造）

| 指标 | 原因 | 处置 |
|------|------|------|
| 实际 FPS / 帧间隔分布 | headless 按需出帧（rAF 只在渲染管线需要时跑），帧间隔数据不代表真机渲染 | rafGaps 字段保留但**不作为结论依据** |
| Composite/GPU 层成本 | CDP getMetrics 无合成器计数；Layer 树导出在本工具链不稳定 | 未测量，如实标注 |
| Motion Off 省下的 transition/动画成本 | 同 FPS 原因：off 档 transition-duration=0 的收益发生在渲染管线帧调度层，headless 无恒定帧率可对比 | 未测量 |
| S5 Plugins 真实数据 diff | core 后端不在场，列表为空态 | 待 core 在场后补测 |
| S6b Cinema 真实布局成本 | 探针布局为空操作 | 待 Workspace Engine |

## 五、修复前后数据

无。本轮 **0 项 NEEDS FIX**——所有指标在健康范围，未发现属于当前 Motion/S2 实现的性能问题，因此未做任何架构/实现修改（遵守 §四"不为数字乱改架构"）。

## 六、基线错位声明（诚实记录）

任务基线提到"`motion-system.md` §I 校准 / S2 Settings·Plugins 局部 diff 25/25 / Edge 真实点击验收 6/6"——**本仓库无对应物**（`docs/tech/` 下仅有 motion-runtime.md；tools/ 下无 25/25 与 6/6 脚本）。本轮以仓库实际状态为准执行，不假定那些产物存在。若它们在另一工作区，需先同步入库再对齐口径。

## 七、风险等级

**低**。当前 Motion System 在生产构建 + 真实交互路径下无主线程阻塞、无病态重排、无多余 DOM 工作。唯一结构性提醒：Cinema/Workspace 的真实成本评估依赖未来 Workspace Engine 的真实布局回调，届时**必须重跑本脚本**（S6b 场景已预留）。
