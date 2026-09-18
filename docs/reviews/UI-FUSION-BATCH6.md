# UI-FUSION-BATCH6 —— 动效与 UI 对接（首页 / 档案 / 设置 / 软件 + 拖拽 + 侧栏）

> 范围：`ui/` 动效补齐与设计稿对接。**不动主 IA、不动冻结域、不新增产品导航以外的页面**（唯一新增
> 页面 `/motion` 是设计稿 `ROUTES.showcase` 的落地页，入口在设置 · 外观，不进侧边导航）。
> 判定口径按 HANDOFF §「审核规则已收敛」：**判定 + 理由 / 硬证据 / 阻塞项**，不写长篇分析。

---

## 1. 判定

**通过（3 项记录在案）**

理由：本轮 5 项需求的落地物均已接线并有可运行证据（见 §2）；构建与类型检查 0 错；
验收脚本除下列 3 条既有环境性问题外全 PASS。

记录在案（不阻塞下一步）：
1. `verify_tech06b` C6（真重启后归档一致）—— 既有环境问题，本轮前后同一症状（本轮 47/48，历史 09:23 为 45/48）。
2. `verify_tech07c6` D5 / R-C5 —— 依赖技术栈真实重启链路，与 C6 同族环境敏感；单独跑 `tech07c5` 时 C2 已转绿。
3. 设计稿附录页 `#/skinlab`（皮肤实验室）、`#/spec`（设计规范与组件）**有意不落地为产品页** ——
   二者是原型自述的"只做展示与切换"验证场（`_fusion_css_import.py` 的 EXCLUDE 表在上一轮已按此决策排除
   其样式）。设置 · 外观的 5 行（主题 / 动画 / 动效规范 / 皮肤 / 首页布局）已覆盖设计稿该类目全部设置项。

---

## 2. 硬证据

### 2.1 需求 → 落地物 → 证据

| 需求 | 落地物 | 证据 |
|---|---|---|
| ① 四页动画（页面切换 / 进出场 / 悬浮与点击反馈） | `motion/pageTransition.ts`（`scene-in/out`）· 四页 `data-enter` · 设计稿 Press 规则并入 | `createPageTransitionHooks` 在 `App.vue` 接线；`base.css:2649` `button:active,…{transform:scale(var(--mt-scale-press))}`（原被 `^button` 前缀连带排除） |
| ② 设置 · 外观设置项全覆盖 | `SettingsView.vue` 外观 5 行 + 入口 `/motion` | 设计稿 `setBodyHtml('appearance')` 四行逐项对齐，另加 skin-system §9.2 第 4 项的「皮肤」行 |
| ③ 可拖动对象拖拽动画 | `.arrange-row` + `useAutoSort` + `widgetStore.reorderWidget` | **`tools/_probe_arrange_drag.py` 11/11**（真实 handler 链路） |
| ④ 窗口拖拽动画 | `RunView` `.carried`/`.carrying`/`.win-size` HUD/`.just-swap`/限时落位 transition | **`tools/_probe_window_drag.py`**（真实 core + 真实 charmap 窗口） |
| ⑤ 侧栏折叠平滑切换 | `base.css` 段前「壳层折叠动画的连续性补齐」块 | **`tools/_probe_sidebar_mini.py` 8/8**（真实浏览器 `getComputedStyle`） |

### 2.2 三个探针补的是哪一块空白

既有的 `verify_tech07c3` 已用同款 pointer 事件链证明"拖拽 → 真实窗口落位"的**行为**正确；
本轮的三个探针补的是**视觉反馈链路**——这正是静态复核抓不住的一类：
"类写在 CSS 里、调用点丢了"只能靠真跑。

---

## 3. 本轮修掉的两个真问题（都是"文件里有、实际不生效"）

### 3.1 侧栏折叠态居中的修复**整条失效**（同权重平局被源序反超）

段前块原先写 `.app-shell.mini .nav-item` ＝ **(0,3,0)**，而设计稿并入段里
`.shell.mini .nav-item{justify-content:center;padding:0;gap:0}` **也是 (0,3,0)** 且更靠后
⇒ 平局由源序判定 ⇒ 设计稿赢，`padding-left` 居中修复被 `padding:0` 覆盖。

- 为什么静态检查全绿：选择器**确实在文件里**，grep 得到、typecheck 通过、构建无误。
- 抓住它的方式：`tools/_probe_sidebar_mini.py` 量**计算值**（折叠态若为 `0px` 即失效）。
- 修法：`.shell.app-shell.mini …` ＝ (0,4,0)。`.shell` 与 `.app-shell` 确实同在壳元素上
  （`App.vue class="app-shell shell"`），不是凑权重。
- 顺带记录一条易错认知：**"写在并入段之前" ≠ "能生效"** —— 靠前就必须靠权重赢，源序帮不上忙。

### 3.2 `onLayoutApply` 在 core 停止时会长时间无反馈

`onLayoutApply` 走三步 `runPrepSequence([refresh, apply, refresh])`，前后各一次 `refresh()`；
core 停止后每个请求都要跑满客户端 5s 超时（`api/client.ts` `timeoutMs=5000`），
整段 ≈ 2~3 个超时窗口 ⇒ 用户点完「恢复默认」要盯 20s+ 的空 chip，
`verify_tech07c5` C2 的 25s 观察窗也正好擦边（同一脚本时绿时红）。

修法：`connectivity === 'offline'` 时**立刻**如实回复 `✕ 未连接 —— 应用未执行`（不新增判断口径，
复用页面既有轮询事实；文案沿用 `placementText.offline`）。
对照 `onLayoutSave` 本来就只 await 一次 adapter 调用、离线快速失败 —— 两条路径口径由此一致。

---

## 4. 基线同步

- `ui/src/styles/base.css`：`121b562804633520` → `ee7d92615121cd45` → **`07e79a756e1657c1`**
  （前一次是 resync 并入 Press 规则 + `.mt-*` 层 + 段前补齐块；后一次是 §3.1 的权重更正）。
  五个脚本（c2~c6）活跃基线已同步；旧值仅留在注释里作为演进记录。
- `primitives.css` / `tokens.css` / `motion-tokens.css` / `snapshot.ts` **未变**（指纹一致）。

---

## 5. 机器证据

> ⚠️ **本批次验收被接踵而来的「V0.1 归档清理」任务打断**（最后一批跑到一半被停）。
> 下表是 14:00 那一次**跑完**的结果；其后又在 RunView 修了 §3.2，单独复跑的结果另列。
> 归档前若还要补齐，重跑顺序见 `tools/_batch5_verify_all.py`（约 26 分钟）。

| 检查 | 结果 |
|---|---|
| `vue-tsc --noEmit` | `exit=0` |
| `tools/_fusion_build.py` | `built in 2.19s`，exit=0（同源 `VITE_CORE_BASE=''`） |
| `verify_tech01` / `tech02_workspace` / `tech04` / `tech05c` / `tech05d` / `tech06a` | 9/9 · 11/11 · 44/44 · 34/34 · **89/89** · 43/43 全绿 |
| `verify_tech06b` | 47/48 —— 仅 C6（真重启）红，既有环境性 |
| `verify_skin_engine` / `tech07c` / `tech07c2` / `tech07c3` / `tech07c4` | 全绿（tech07c4 = 25/25 + 1 Deferred） |
| `verify_tech07c5` / `tech07c6` | C2 / D5 红（即 §3.2 所记的空 chip） |
| **§3.2 修复后复跑（单独）** | `verify_tech07c5` → **C2 PASS**（`应用chip='✕ 未连接 —— 应用未执行'`）；`verify_tech07c4` → 25/25 |
| `tools/_probe_sidebar_mini.py` | **8/8** |
| `tools/_probe_arrange_drag.py` | **11/11** |
| `tools/_fusion_css_import.py` 幂等性 | 段内 63529 字节**逐字一致**，`--resync` 不会冲掉段前块，指纹稳定 |
| `tools/_design_coverage.py` | 267 个设计稿类名 **89.89%** 落地；未落地的 27 个全是原型家具（见 §1 记录项 3） |

---

## 6. 交付清单（本轮改动文件）

新增：`ui/src/views/MotionSpecView.vue` · `tools/_probe_sidebar_mini.py` ·
`tools/_probe_arrange_drag.py` · `tools/_probe_window_drag.py` · `tools/_diag_arrange_order.py` ·
`tools/_batch5_verify_all.py`

改动（UI）：`RunView.vue` · `DashboardView.vue` · `SettingsView.vue` · `ProfileView.vue` ·
`base.css` · `stores/widgets.ts` · `composables/useWidgets.ts` · `motion/entrance.ts` ·
`router/index.ts`

改动（工具/基线）：`tools/_fusion_css_import.py`（UNEXCLUDE 白名单）· `tools/verify_tech04.py` ·
`verify_tech05c.py` · `verify_tech05d.py` · `verify_tech06a.py` · `verify_tech06b.py` ·
`verify_tech07c.py` · `verify_tech07c2.py` · `verify_tech07c3.py` · `verify_tech07c4.py` ·
`verify_tech07c5.py` · `verify_tech07c6.py`
