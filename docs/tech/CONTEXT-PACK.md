# CONTEXT-PACK · Personal Workspace（UI 视觉保真收口）· 2026-09-18

> **用途**：把"接着推进需要知道的全部事实"压成一份，供新会话直接接手。
> **配套**：`HANDOFF.md`（项目总入口）· `docs/reviews/LEDGER.md`（进度唯一真相来源）。
> 本文件只写**当前状态 + 下一步 + 约束 + 坑**，不重复历史报告。

---

## 0. 一句话状态

**阶段 0~9 全部通过；V0.1 系列（FINAL / RELEASE）已收口；「UI 视觉保真收口」已完成六大块 ——
设计稿组件层**逐字并入**（374 规则 + 23 keyframes）· 62 枚图标体系从零补齐 · 六页按设计稿重建 ·
壳层「窗口即纸面」双类名桥接 · Run 页整页重建 + cinema 沉浸态 · 右键菜单/行内反馈补齐 ·
**原语层 `pw-*` 别名对齐设计稿取值（第三批）** ·
**button 重置精确复位 + 页面结构归位（第四批：ModelsView / AiView 两页，2026-09-18）**。**
剩余 = **各页内部结构仍用自造类名**（`aiv-*` / `mv-*` / `wiz-*`）而非设计稿类名 —— 第四批已归位
**2/7 页**（models / ai），其余 5 页见 §1.2 第 5 项的有界清单。

- 正式 App = `D:\Personal Workspace\personal-workspace-core.exe`
- 桌面快捷方式 `Personal Workspace.lnk` → 该 exe（已核对）
- 源码唯一 UI = `ui/src/`（**不存在第二套 UI**）
- 路由 = **17 条**（14 产品 + `/models` + `/run` + 2 条 dev 固件）

> ⚠️ **"设计稿 CSS 已并入" ≠ "页面按设计稿渲染"。** 只要还有一层**加载更晚**的近似副本
> （`components/ui/primitives.css` 在 `main.ts` 里排在 `base.css` 之后），最终 computed 值就由它决定。
> 第三批已把原语层改为**消费设计稿 token** 并补了 D1d/D1e 机器守护（§1.4）。

---

## 1. 当前任务：UI 视觉保真收口（唯一在办事项）

### 1.1 已接（有机器证据）

| 项 | 证据 |
|---|---|
| 侧栏 = 原型分组 IA（含 ⚙设置 + 设备行） | DOM 断言：`.nav-foot` / `a[href="/settings"]` / 分组 工作·学习·项目·生活 |
| 首页 = 原型结构（greet + Hero + 最近使用 + home-split + widget 列） | `apps/square` 真实启动；`.greet/.sec/.widget-card` 均带动画 |
| 设置 = 原型 set-layout | `.set-layout` + subnav 外观/工作空间/AI 与模型/数据/关于 |
| **17 条路由全部渲染（14 产品页 + models + run + 2 dev）** | `tools/verify_tech04/05d/06a/06b` 路由基线；`tools/_force_ui_dom.py`（部分 marker 待对齐，见 L-048） |
| 骨架统一 + 动效层 | `tools/_force_motion_check.py`：`.page-skeleton` maxWidth=1120/左对齐/宽度随视口流动；`pwViewIn`/`pwEnterUp`/`transition-duration=0.12s`；`data-motion=off` → 全 0s |
| 顶部壳层 appbar 化 | `tools/_force_appbar_check.py` **14/14**：单条 appbar · 高 46 · mode-bar 覆盖生效 · 动作区右缘对齐 · 窄窗零溢出 · 暗色跟随 token |
| **设计稿组件层逐字并入（FULL）** | `tools/_force_design_check.py` **ALL OK**（67 规则级命中 + 计算级取值 + **0 未解析变量**/132 个 `var()`） |
| **壳层「窗口即纸面」内缩面板** | `App.vue`：`.app-shell.shell` > `.app-titlebar` + `.app-panel.panel` > `NavSide | content(.view) | WidgetCol | AiSidebar`；`--panel-inset` 内缩 + `--r-2xl` 圆角 |
| **壳层双类名桥接 + 四态 chrome 策略** | `tools/_fusion_shell_probe.py` **43/43**（真实 Edge + CDP）：四区双类名、宽度 = token、`data-rs` 滞回四态、拖拽改宽并落 token、蓄力折叠 → `.shell.mini`+64px、双击复位 236、rail 切换、干净会话 700 自动折叠 |
| **Run 页整页按设计稿重建** | `RunView.vue` 按原型 `ROUTES.run` 重排：`run-head → run-status → appbar → stage`；含 8 向缩放handle、`.stage.manual`、`.minimap i.t1..t6`、真实窗口事实写入 `.win-body` |
| **cinema 沉浸态（CSS 之前只有壳、无 JS）** | `useShellLayout.playCinema()`：清 `--i` → `cinema-entering` → `--mt-dur-window` gate 后 `cinema-stabilizing` → stable 后清；`setCinema()` 联动 `syncNavAuto` |
| **右键菜单（此前完全缺失）** | `composables/useContextMenu.ts` + `components/CtxMenu.vue`：视口避让、点外/滚轮/Esc 三条关闭路径、`.out` 退场（`--mt-dur-ctx`）；首页 `.app-square` 已接线 |
| **行内反馈** | `okFlash`/`errShake`（`useListSort.ts` 导出）已用于设置页 API Key；`.set-body.swap-in` 用于设置页分类切换 |
| 正式 exe 内嵌 FULL 版 UI | NSIS 刷新实测见 LEDGER `UI-FUSION-FULL` 段 |

### 1.2 下一批（按此顺序做，勿跳）

1. ✅ 顶部壳层 appbar 化 —— LEDGER `UI-FUSION-APPBAR` 段。
2. ✅ 设计稿组件层逐字并入 + 六页重建 —— LEDGER `UI-FUSION-FULL` 段。
   落地方式：`tools/_fusion_css_import.py`（逐字抽取 + 显式排除表）、
   `tools/_fusion_icon_import.py`（62 图标 → `components/PwIcon.vue`）。
3. ✅ 壳层「窗口即纸面」内缩面板 —— 见 §1.1 与 LEDGER 第二批。
4. ✅ Run 页整页重建 + cinema + 右键菜单 + 行内反馈 —— LEDGER 第二批。
5. ✅ **页面内部结构的类名归位**（大件，**已全部完成**）。
   第四批完成 `page:models` + `fn:modelCardHTML/modelGridHTML`、`page:ai`（见 LEDGER 第四批 §3）；
   **第五批完成剩余 5 页**（详见 `docs/reviews/UI-FUSION-BATCH5.md`）：
   - ✅ **`fn:nowPlaying`（4 类）**：`.nowplaying/.ttl/.art/.ctrl` → **DashboardView** 的 greet 行
     ⚠️ **口径修正**：原登记写的是 LifeView，但设计稿把它放在**首页 greet 行右侧**
     （`ROUTES.home` line 2201），且 `.nowplaying` 带 `@media (max-width:1040px){display:none}` ——
     放进 LifeView 会在窄屏把音乐条整体藏掉（功能回归）。故落 DashboardView，数据仍走
     `lifeApi.mediaNow()` 的真实 SMTC 会话，无会话走 `.nowplaying.idle`（不编造曲目）。
   - ✅ **`fn:openAvatarPicker`（3 类）**：`.avatar-grid/.avatar-pick/.avatar-pick--up` → ProfileView
     （补上原型有、工程漏掉的「上传图片」预留入口；点击如实提示"接入后开放"，不伪造上传）
   - ✅ **`fn:openAddApp` / `page:apps`（4 类）**：`.app-row/.wide/.tm/.hover-only` → SoftwareView
     （网格卡 = `.app-square`；**列表视图由表格换成 `.app-row`**（路径改挂 title）；
     扫描抽屉的搜索框 = `.input.search.wide`；扫描行 = `.app-row` + `.nm`）
   - ✅ **`fn:runPrepSequence`（4 类）**：`.run-prep/.rp-steps/.rp-step/.spinner` → RunView
     ⚠️ 原型是 3×340ms **定时器演示**序列；本工程把三步绑定**真实操作**
     （`refresh()` → `layout.apply()` → `refresh()`），没跑完就不打勾
   - ✅ **`fn:tagEditorHtml`**：`.chip--removable` → PwChip 原语双类名桥接（同时挂 `chip*`）
   - ✅ **`fn:openCustomize`**：`.arrange-row` → DashboardView 组件管理行（`.off` = 已关闭）
   - ✅ **`page:workspaces`（4 类）**：`.ws-card/.hd/.nm/.new-card` → ModeView 列表视图
     （卡体外观交给设计稿 `.ws-card`，本地块按纪律删除；`.actions` 由设计稿做 hover 显隐）
   - ✅ **`page:create`（10 类）**：`.wsteps/.wstep/.wline/.pick-grid/.pick/.em/.tick/.detect/.app-pick/.btn--lg`
     → ModeView 现有向导**内部**实现（不另起平行页）；`.detect` 的"检测到 N 个应用"
     取自 apps store 的真实运行态，没有在跑就是 0
   - ⚠️ **ModeView 拖拽画布 `ed-canvas/ed-dragbox` 参与指针几何计算：不要给其子元素加 transform 动画**
   - ⚠️ 改类名时**保留**验收依赖的钩子（`perf_tech01_22.py` 用 `.mv-modal-mask` + 按钮文案「记录当前环境」；
     `_force_ui_dom.py` 每页 marker 是 OR 列表，见 §2）
   - ⚠️ 本地 scoped 块的权重与设计选择器**同权（0,2,0）**：设计稿已覆盖的版面/外观值必须**删本地块**，
     不要"抄一遍"（见 §2 纪律）
6. **不接**：设计稿的开发态页面（`spec`（13 类）/ `skinlab` / `guard` / `showcase`）与其 CSS/keyframes
   （`.spec-*`/`.swatch`/`.demo`/`.comp-*`/`.skinlab*`/`.mt-*`、`sceneIn`/`stageSettle`/`dockIn`…）——
   不进产品导航；已在 `_fusion_css_import.py` 的排除表里显式登记理由。
   另外 `const:WIN_MOCK` 的 `.ind/.w70/.w85/.w40/.w55/.w30`（17 次引用）是原型**mock 窗口骨架条**，
   按纪律换真实数据，**不算缺口**；`tint/tint2` 是 `appIcon()/minimap()` 按应用色号拼的类。

### 1.3 真实缺口口径（严格审计，2026-09-18 第三批）

`tools/_design_coverage.py` 的默认"已接"判据**偏松**：它把"类名字面量出现在 `ui/src` 任意位置"算作已接，
而 `base.css` 含全部设计 CSS ⇒ 几乎所有类名都"已接"。

**两种口径都要看，差值 = "有规则、无消费方"：**

| 口径 | 类种 | 引用次数 | 说明 |
|---|---|---|---|
| 默认（含 CSS：规则级接入） | 237/267 = **88.8%** | 1694/1830 = 92.6% | 设计稿有没有被"接进代码库" |
| **`--strict`（仅 `.vue` 消费方）** | **179/267 = 67.0%** | **1584/1830 = 86.6%** | 页面有没有真的在用它 |
| `--strict` 未接 | 88（生产页 **65** / 开发页 23） | 181（生产页 **129** / 开发页 52） | |

用法：`$PY tools/_design_coverage.py [--strict] [--top N]`
（两种口径写不同的 json：`_design_coverage.json` / `_design_coverage.strict.json`）

**工具新增「缺口 → 原型页面归属」**：把每个缺口类定位到它出现的原型块
（`page:<路由>` / `fn:<函数>` / `const:<数据>`），回答"去哪补"而不是只知道"少了什么"。
归属后可见 **绝大多数"缺口"不是缺口**：`const:WIN_MOCK` 的 `.ind/.w70/…` 是 mock 骨架条、
`page:spec/skinlab/guard/showcase` 是开发态页面、`tint/tint2` 是 `appIcon()` 拼的色号类。
**真正的产品页缺口见 §1.2 第 5 项（有界清单）。**

### 1.4 原语层别名对齐（第三批已完成，2026-09-18）

**根因**：`primitives.css` 在 `main.ts` 里加载在 `base.css` **之后** ⇒ `pw-*` 原语**覆盖**设计稿同名语义类。
`§1.1` 的"设计稿组件层逐字并入"虽然完成了，**页面实际渲染值仍由原语层决定** —— 这是"设计接了但看起来不一样"的根因。

**实测到的 10 处真实漂移（已全部修掉，改为消费设计稿 token）：**

| 项 | 设计稿 | 原语层（改前） |
|---|---|---|
| `.pw-t-section` 字号 | `--fs-section` **15px** | 16px 字面量 |
| `.pw-t-card` 字号 | `--fs-card` **14px** | 15px 字面量 |
| `.pw-t-*` 行高/字距 | `--lh-*` / `--ls-*` | **全部缺失** |
| `.pw-t-page` 字族/字距 | `--font-display` / `-0.014em` | 无字族 / `-0.01em` |
| `.pw-t-label` | `text-transform: uppercase` | **缺失** |
| `.pw-card` 内距 | `--pad-card` **20px** | `--f-space-4` 16px |
| `.pw-card--lg` 内距 | `--pad-card-lg` **24px** | `--f-space-5` 20px |
| `.pw-card--hoverable:hover` | `--shadow-md` + `translateY(-1px)` | `--shadow-card`，**无位移** |
| `.pw-avatar` 配色 | `--brand-100` / `--brand-700` | `--brand-50` / `--brand-600` |
| `.pw-grid` 间距 | `--gap-card` **20px** | `--f-space-3` 12px |

另有：`.pw-btn` 基类多一条**透明边框**（挤掉 1px 内距）、`.pw-btn--lg` 15px（设计 `--fs-card` 14px）、
`.pw-btn--primary` 用 `#fff` 而非 `--text-on-brand`、`.pw-btn--danger` 用 `--danger` 而非 `--danger-text`、
`.pw-btn--secondary` 缺 `--shadow-xs`、**全部交互件缺 transition**、
`.pw-scrim`/`.pw-drawer` **缺入场动画**且 `z-index` 写死 40/41（设计 `--z-modal`/`--z-drawer`=60）、
`.pw-drawer` 用 `--shadow-floating` 而非 `--shadow-lg`。
**选择器一律未动**（`verify_tech05c` T4f 的"每个 `.pw-*` 必须被消费"因此不受影响）。
`--f-space-*` → `--space-*`、`--radius-controls` → `--r-md`、`--f-radius-3` → `--r-lg`、`--shadow-floating` → `--shadow-lg`。

⚠️ **单独注意**：`.pw-grid--models` 必须**显式** `gap: var(--space-3)`（12px）——
设计稿 `.grid` 是 20px 而 `.model-grid` 是 12px，不给它单独设值就会继承 20px。

**防复发（机器守护）**：
- `_force_design_check.py` **D1d**（`.pw-card` 规则级必须字面含 `padding:var(--pad-card)` 等 + `.pw-card--lg` 计算级实测）
  与 **D1e**（`.pw-t-page`20 / `.pw-t-section`15 / `.pw-t-card`14 / `.pw-t-label` uppercase / `.pw-btn`34px）。
- `verify_tech05c.py` **T4c 修工具缺陷**：原先用**行首锚定**正则收集"已定义变量"，
  而 `tokens.css` 排版标度段是**一行多声明** ⇒ `--lh-*`/`--ls-*` 全家被判"未定义"（假阴性，
  也掩盖了"这些 token 从没被消费"）。已改为剥注释后不锚行首。

### 1.5 改动落点

- `ui/src/styles/base.css`：
  - **809 行起** = UI-FUSION-REAL 排版标度段（`.app-main h2/h3`、`.page-head`）
  - **850 行起** = UI-FUSION-FORCE 段：①页面骨架 ②动效层 ③壳层收编 ④其余页面根容器
  - **末尾 `UI-FUSION-FULL:BEGIN..END`** = 设计稿组件层（**脚本生成的逐字段，勿手改**；改设计稿后重跑 `tools/_fusion_css_import.py --apply`）
  - **`END` 之后** = `UI-FUSION-FULL · 收口`（接线段：`.pw-ico` / `.card--hoverable:hover` 反馈 / `.spark-line` / 生活页卡片入场）
- **keyframes 只允许放在 `base.css`**（`verify_tech04` T4c / `verify_tech05d` T9b 断言全局仅 base.css；现共 **23 组**）
- **自定义属性只能定义在 `tokens.css` / `motion-tokens.css`**（T4a/T9a 守护）。并入设计稿 CSS 时**必须**保证片段里没有 `--x:` 声明 —— `_fusion_css_import.py` 内置该校验
- 动效时长/幅度**一律走 `--mt-*` token**；设计稿的 `--dur-base/--dur-slow/--ease-inout` 只是**映射别名**
- **图标**：`components/PwIcon.vue`（62 枚，`.pw-ico`）；**不要**放进 `components/ui/`（T9c 钉死 4 个原语）；类名不要用 `.ico`（撞侧栏）

---

## 2. 硬约束（碰之前先看）

| 约束 | 位置 |
|---|---|
| `base.css` hash **`9d86a51bf1883369`** · `tokens.css` **`4741eed584a8b589`** · `motion-tokens.css` **`adee6b0380a7b04d`** · `primitives.css` **`37a8ff2d375f61c4`** | `verify_tech07c2/3/4/5/6.py` 的 frozen 表（**共 4 项 × 5 脚本 = 20 处**，另有 schema/boundary/ModeBar/snapshot，合计 **26 项**）；改样式必须同步这 5 处并在 LEDGER 记账 |
| `ModeBar.vue` `eccb9c10727d3d30`、`boundary.ts` `19dfb41e2df31ccd`、`workspace/snapshot.ts` `604fe010e0d3f980`、`database/schema.sql` `d95ca49cc3285166` | 同上 |
| 冻结域（禁 UI 直连 `@/api`）：`workspace/runtime/*`、`workspace/snapshot.ts`、`RunView.vue` | `verify_tech07c1~c7` |
| `RunView.vue` 禁出现 `@keyframes` / `animation` / `transition`（A4） | `verify_tech07c2` |
| 验收依赖的 DOM（不可删）：`.app-nav` + 全部 href、`.widget-card/.widget-title/.widget-usage/.widget-actions`、各页文案标记、`main` 区、`page-skeleton`、`.mv-modal-mask` + 「记录当前环境」按钮 | `verify_stage1.py`、`verify_tech05c/05d`、`perf_tech01_22.py` |
| `_force_ui_dom.py` 每页 marker 是 **OR 列表**（每页只需命中其一）：`/dashboard` `.home-hero,.hero,.page-head`；`/mode` `.mv-toolbar,.mode-card,.page-head`；`/ai` `.ai-view,.ai-shell,.pw-card`；`/plugins` `.page-head,.card,.tile`；`/device` `.page-head,.card,.metric`；`/models` `.pw-card`；`/settings` `.set-layout` | 改类名时**至少保留一个** |
| 门禁：`python tools/gate.py --stage 9 --build` ⚠️ **实测 FAIL=40 / WARN=116 / PASS=30** —— 40 条全为 A020/A021 且全落在 `tools/_*.py` 批量脚本，产品代码 0 命中；见 LEDGER **L-047**（待裁决）。**"0F/0W" 已失效** | 红线 V1~V8（产品代码仍应 0 命中） |

---

## 3. 命令速查（本项目实测可用）

```bash
PY=C:/Users/baiyu/.workbuddy/binaries/python/versions/3.13.12/python.exe          # 系统 python（无 PIL/win32）
VENV=C:/Users/baiyu/.workbuddy/binaries/python/envs/default/Scripts/python.exe     # 装了 pillow，做截图/实机验证用它
cd "C:\Users\baiyu\Desktop\Personal Workspace"

$PY tools/_fusion_build.py            # vue-tsc + vite build（VITE_CORE_BASE='' 同源，供 C2/C3）
$PY tools/_fusion_regression.py       # TECH-02 + C1~C7 串行（单跑口径）
$PY tools/_fusion_tauri_build.py      # Tauri release（先 touch core/src/main.rs 强制重嵌 dist）
$VENV tools/_force_refresh_install.py # NSIS 静默升级 → 刷新 D:\Personal Workspace
$VENV tools/_force_motion_check.py    # 动效/骨架实测（computed style + Guard 归零）
$VENV tools/_force_appbar_check.py    # 壳层 appbar 实测 14 项
$PY   tools/_fusion_shell_probe.py    # 壳层四区双类名/宽度 token/滞回/拖拽 43 项
$PY   tools/_design_coverage.py       # 静态设计覆盖度审计（口径偏松，见 §1.3）
$VENV tools/_force_design_check.py    # 设计稿组件层实测（规则级 + 计算级 + 0 未解析变量）
$VENV tools/_force_ui_dom.py          # 逐页 DOM 断言（需 core 在场）
$VENV tools/_force_app_click.py "D:\Personal Workspace\personal-workspace-core.exe"  # 实机真实点击（需桌面空闲）
```

**改完源码 ≠ 改完被测物**：验收一律跑在**最终构建产物**上；Tauri 侧改完必须 `touch core/src/main.rs` + 重建。

---

## 4. 环境与坑（血泪）

| 坑 | 规避 |
|---|---|
| Bash 工具 **PATH 为空**（`ls`/`head`/`grep`/`dirname` 全 not found） | 命令前加 `export PATH="/usr/bin:/bin:/c/Windows/System32:$PATH"`；或一律用 **Python subprocess** |
| 从 Bash 里调 `powershell` 被安全策略拦截 | 用 PowerShell 工具，别从 Bash 转 |
| PowerShell 工具 stdout 被吞（exit 0 无输出） | 命令 `> 文件 2>&1`，再用 Python 读 |
| 沙箱代理劫持 `127.0.0.1` 请求（502/超时） | urllib 用 `build_opener(ProxyHandler({}))` |
| WebView2 CDP 端点**只在启动后 ~5 秒存活**；ws 握手**不能带 `Origin`**（403） | 不要指望 CDP 做多页实机验收 |
| 消息级点击（`WM_LBUTTON*`/`PostMessage`）Chromium **不响应** | 只认真实输入 |
| 截图要三条同时成立：进程 DPI 感知 + `ImageGrab.grab(all_screens=True)` + 窗口真在最前；`HWND_TOPMOST` 必须传 `c_void_p(-1)` | 见 `tools/_force_app_click.py` |
| Tauri webview 是主窗口**子窗口**（`WRY_WEBVIEW`→`Chrome_WidgetWin_0/1`→`Chrome_RenderWidgetHostHWND`）；枚举要排除 `ConsoleWindowClass` | 同上 |
| **用户跑独占全屏游戏时**：抓屏全白、抢前台不可能、真实点击会落进游戏 | `_force_app_click.py` 有**落点归属校验**会拒绝执行；此时不要硬来 |
| 同文件多处改动**必须串行 Edit**，改完 grep 复核（并行 Edit 会互相覆盖且每个都报成功） | 铁律，已两次踩 |
| **验收脚本要求的构建方式就是被测条件**：`ui/dist` 必须用 `VITE_CORE_BASE=''`（`tools/_fusion_build.py`）。裸 `npm run build` 会让 c2 的 D 段**假红**（`ui投影={titles:[],bars:[]}`） | 脚本红先核对产物 |
| **重建 DOM 时删掉"看起来多余"的旧类名 = 打掉冻结钩子**（`.run-win__rz*` 被 C3 D5/D6 依赖） | 重构前先 grep 验收脚本用了哪些选择器 |
| **验收脚本跑到一半改 `ui/src`** → 后续脚本 FATAL「`ui/dist` 早于 `ui/src`」 | 批量跑验收期间**冻结源码** |
| 嵌套回归红灯（C4/C5/C6 的 R 段） | 收口口径：**每套独立通过证据即判通过**，不追嵌套连绿；先杀泄漏的 core/Edge 进程再单跑 |
| `ui/dist/assets` 有历史 chunk 残留（`emptyOutDir:false`） | 已知遗留；**副作用**：exe 内嵌整个 dist 目录，故"键名存在"不能单独证明新旧 |
| `_force_motion_check.py` 等 `tools/_*.py` 触发门禁 A020/A021 | 见 LEDGER **L-047**；新写工具用 `Path(__file__).resolve().parents[1]` + 环境变量定位 Edge |
| **Python 重定向到文件时不刷新 stdout**（`verify_tech07c6` 跑 30 分钟日志恒 0 字节） | 判断进度别只看日志；用 `-u` 或临时改 `flush` |
| `beforeBuildCommand` 会重跑 `npm --prefix ui run build` | Tauri 构建后 `ui/dist` 已是**生产构建**（chunk 名与 `_fusion_build.py` 不同） |

---

## 5. 未决/记录在案

1. **实机逐页点击验收未做**（环境：用户在全屏游戏 / 其他窗口占满）—— 待桌面空闲重跑 `_force_app_click.py`
2. **窗口标题跟随页面未生效**（`router/index.ts` 的 `afterEach` + `core:window:allow-set-title` 均已编入；实机标题恒为 `Personal Workspace`，原因未定）
3. **C4/C5/C6 嵌套红灯**：产品段全绿，红灯只在 R 段跨套件重跑
4. **发版状态**：`NOT RELEASED`；tag `v0.1` 未覆盖
5. **遗留债**：多显示器支持、`WindowInfo` 无 exePath、dist chunk 残留、Chrome/WebView 孤儿进程（验证后清理）
6. **门禁基线失真（L-047）**：`gate.py --stage 9 --build` = FAIL=40/WARN=116/PASS=30，40 条全为 `tools/_*.py` 的 A020/A021；**需白宇裁决**（A 案＝批量工具改 `__file__`/环境变量推导；B 案＝A020/A021 显式排除 `tools/`）
7. **`ui/src/views` 下无 `WorkspacesView`**：原型的 `workspaces`（我的工作空间）与 `create`（创建工作空间向导）两条路由**在工程侧没有对应页**；工程把「工作空间」映射到了 `/mode`（ModeView）。落地时应在 ModeView 内实现这两套设计稿 DOM（§1.2 第 5 项），**不要**另起一个平行页面造第二套 IA
8. **`tokens.css` 补了两条设计稿自身缺失的定义**（`--space-7:28px` / `--i:0`），已登记 hash —— 详见 LEDGER 第二批

---

## 6. 给新会话的开场白（直接粘）

```
接手 Personal Workspace 的 UI 视觉保真收口。先读这三份，别先改代码：
1) docs/tech/CONTEXT-PACK.md   ← 状态/下一步/约束/坑，全在这一份
2) HANDOFF.md                  ← 项目总入口与环境坑
3) docs/reviews/LEDGER.md      ← 进度唯一真相来源

下一步（见 CONTEXT-PACK §1.2 第 5 项）：
把各页内部结构从**自造类名**归位到**设计稿类名**（真实缺口已按原型页面归属，有界）：
① AiView：aiv-grid/aiv-sessions/aiv-session-list/aiv-session/aiv-chat/aiv-chat-head/aiv-msgs → ai-*
② ModeView：一个页面覆盖原型两条路由 —— list 视图 → page-head/seg/wf-row/wf-mode/ws-grid/ws-card/new-card；
   向导 → wsteps/wstep/wline/pick-grid/pick(+em/t/d)/detect/app-pick（**在 ModeView 内做，不另起平行页**）
③ ModelsView：pw-grid--models/mv-card/mv-card-foot → model-grid/model-card/mc-foot
④ RunView：run-prep/rp-steps/rp-step/spinner（"准备工作空间"浮层）—— **必须绑真实操作**，
   原型的 3×340ms 是演示序列，照抄会违反 C1/C6「不产生伪事实」
⑤ LifeView nowplaying/ttl/art/ctrl · ProfileView avatar-grid/avatar-pick/avatar-pick--up · SoftwareView app-row/tm/hover-only
   —— **全部已完成（第五批）**；其中 nowplaying 改落 DashboardView（理由见 §1.2 第 5 条口径修正）

⚠️ 风险点：ModeView 拖拽画布 ed-canvas/ed-dragbox 参与指针几何 —— 子元素禁止加 transform 动画；
改类名前先 grep 验收脚本用了哪些选择器（perf_tech01_22.py 依赖 .mv-modal-mask + 「记录当前环境」；
_force_ui_dom.py 每页 marker 是 OR 列表）。
⚠️ 改完必须复核 T4f（primitives.css 里每个 .pw-* 都要有消费方）——把某页从 pw-* 换成设计类，
   若该页是某个 pw-* 的唯一消费方，会产生孤儿类导致 tech05c 红灯。

硬约束（见 CONTEXT-PACK §2）：样式改动只能落在 ui/src/styles/base.css（keyframes 只允许在该文件）；
base.css 改后必须同步 verify_tech07c2/3/4/5/6 的 hash 基线（当前 **121b562804633520**，
2026-09-18 第五批把 `.avatar-pick`/`.nowplaying` 两个"裸 button"设计稿类加进精确复位清单），
primitives.css 基线 37a8ff2d375f61c4，并在 LEDGER 记账；动效时长/幅度一律走 --mt-* token。
⚠️ **C2–C6 跑的 `ui/dist` 必须是 `tools/_fusion_build.py`（`VITE_CORE_BASE=''` 同源）构建的**；
   裸 `vite build` 会让 C2 的 D 段整段假红（`ui投影={titles:[],bars:[]}`）—— 已踩过两次。
⚠️ "设计稿 CSS 已并入" ≠ "按设计稿渲染" —— 还有一层 primitives.css 加载在 base.css 之后，
   改任何语义类的取值都要同时核对 .pw-* 别名（D1d/D1e 会抓）。
⚠️ **设计稿的 `button` 基础重置在并入时被整组排除**（工程 base.css 有自己的重置，且它是"可见盒子"）。
   凡假设"裸 button"的设计稿类（.icon-btn / .seg button / .tabs button / .chip button /
   .btn / .win-btns button）都多出一圈灰边 —— base.css 里有一段**只列设计稿类名**的精确复位
   （置于设计稿并入段之前，故设计稿自身的 background/border 仍以源序胜出）；.pw-btn 的
   `border:0` 在 primitives.css。**不要**去改工程版 `button{}` 本身（`class="primary"` 那批裸按钮靠它活着）。
⚠️ 本地 scoped 块编译后是 `.x[data-v-*]`，与设计选择器**同权重（0,2,0）**，平局靠源序 ⇒
   构建后源序不可依赖。凡是设计稿已覆盖的版面/外观值，一律**删掉本地块**让位，不要"抄一遍"。

环境：Bash 工具 PATH 为空 → 命令前 export PATH="/usr/bin:/bin:/c/Windows/System32:$PATH"；
Python 用 C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe；
截图/实机验证用 C:\Users\baiyu\.workbuddy\binaries\python\envs\default\Scripts\python.exe（有 pillow）。
改完源码必须重建产物（Tauri 侧先 touch core/src/main.rs）；同文件多处改动串行 Edit + grep 复核。

每批做完：跑 tools/_fusion_build.py + tools/_force_design_check.py + tools/verify_tech05c.py，
重建 + tools/_force_refresh_install.py 把改动打到桌面快捷方式指向的正式 App，并在 LEDGER 记账。
```

---

*本文件与 `HANDOFF.md`、`LEDGER.md` 三者互不替代：HANDOFF 讲制度与入口，LEDGER 讲进度，本文件讲"此刻怎么接着干"。*
