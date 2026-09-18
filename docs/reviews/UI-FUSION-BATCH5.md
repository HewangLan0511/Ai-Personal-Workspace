# UI-FUSION 第五批 · 交付报告（2026-09-18）

> 一句话：把**剩余 5 页**（+ 2 个抽屉/浮层函数）的页面内部结构**类名归位到设计稿**，
> 并且每一处都按纪律处理了"本地块 vs 设计稿选择器同权 (0,2,0)"的冲突 ——
> 不是"加个类名"，是**删掉本地块让设计稿真正生效**。

---

## 1. 本批做完的清单（对应 CONTEXT-PACK §1.2 第 5 条）

| 设计稿来源 | 归位的类 | 落地位置 | 关键处置 |
|---|---|---|---|
| `fn:nowPlaying` | `.nowplaying` `.ttl` `.art` `.bar` `.ctrl` | **DashboardView** greet 行 | ⚠️ 原登记写 LifeView，**口径修正**，理由见 §2 |
| `fn:openAvatarPicker` | `.avatar-grid` `.avatar-pick` `.avatar-pick--up` | ProfileView 头像抽屉 | 补上原型有、工程漏的「上传图片」预留入口 |
| `fn:openAddApp` / `page:apps` | `.app-row` `.app-square` `.nm` `.tm` `.wide` `.hover-only` | SoftwareView | 列表视图**由表格换成 `.app-row`** |
| `fn:runPrepSequence` | `.run-prep` `.rp-steps` `.rp-step` `.spinner` | RunView「恢复默认」流程 | ⚠️ 原型是定时器演示；本工程**绑真实操作** |
| `fn:tagEditorHtml` | `.chip--removable` | `PwChip.vue` 原语 | 双类名桥接（同时挂 `chip*`） |
| `fn:openCustomize` | `.arrange-row`（+ `.off`） | DashboardView 组件管理行 | 本地整行块删除 |
| `page:workspaces` | `.ws-card` `.hd` `.nm` `.actions` `.new-card` | ModeView 列表视图 | 卡体外观整体让给设计稿 |
| `page:create` | `.wsteps` `.wstep` `.wline` `.pick-grid` `.pick` `.em` `.tick` `.detect` `.app-pick` `.btn--lg` | ModeView **现有向导内部** | 不另起平行页（原计划如此） |

---

## 2. 两处值得记录的判断

### 2.1 `nowPlaying` 落 DashboardView，不是 LifeView

CONTEXT-PACK 原先把 `fn:nowPlaying` 登记到 LifeView。核对设计稿后改落 DashboardView：

- 设计稿把它放在**首页 greet 行右侧**（`ROUTES.home` line 2201），不在生活页；
- `.nowplaying` 挂着 `@media (max-width:1040px){display:none}` —— 放进 LifeView 会在窄屏
  **把音乐条整体藏掉**，那是功能回归，不是保真；
- 数据仍走 `lifeApi.mediaNow()` 的真实 SMTC 会话：**没有会话就走 `.nowplaying.idle`**
  （文案「没有正在播放 / 点这里开始」），**不编造曲目**（C1/C6）。

### 2.2 `runPrepSequence` 不抄原型的 3×340ms

原型是三组 `setTimeout` —— 勾是"时间到了"打上去的，与是否真的准备好无关。
本工程反过来：`.rp-step.done` **只认真实操作的完成信号**。

```
① 恢复应用 → refresh()            （拉应用/窗口事实；不自动启动软件）
② 恢复布局 → layout.apply()       （真实应用模式绑定布局）
③ 同步状态 → refresh()            （按 facts 复核，成功与否都以事实为准）
```

没跑这个流程就不显示浮层；某步没跑完就不打勾。

同理，ModeView `.detect` 的"检测到当前正在使用 N 个应用"取自 apps store 的
**真实运行态**（5s 轮询 `running` 表），没有在跑就是 0 —— 不写死数字。

---

## 3. "本地块 vs 设计稿"同权冲突的处理（本批的主要工作量）

纪律：组件 `<style scoped>` 编译成 `.x[data-v-*]` = (0,2,0)，与设计稿选择器**同权**，
最终谁生效由源序决定 ⇒ **不能各写一遍**，必须删除本地块让设计稿胜。本批删除/收敛的本地块：

| 文件 | 删除/收敛的本地声明 |
|---|---|
| SoftwareView | `.app-card`（display/排版/gap/padding/radius 全删，只留设计稿没有的板底+边框+投影）、`.app-meta`/`.app-path`（让位给 `.app-square .tm`）、`.apps-scan-list label`（让位给 `.app-row`）、`.apps-table` 整块（表格不再是设计稿语言） |
| ModeView | `.mode-card` 卡体外观整块删除（让位给 `.ws-card`）、`.mode-card__head`/`__name`（让位 `.hd`/`.nm`）、`.mode-card__actions` 只留 `margin-top:auto`（flex/gap + hover 显隐由 `.ws-card .actions` 给）、`.wiz-goals`/`.wiz-goal*`（让位 `.pick-grid`/`.pick`） |
| RunView | 无本地块参与（浮层几何全由设计稿 `.run-prep/.rp-steps/.rp-step` 给） |
| DashboardView | `.greet` 保持；组件管理行让位 `.arrange-row` |

**副作用（有意为之）**：ModeView 卡片的操作按钮现在受 `.ws-card .actions` 控制，
默认隐藏、hover/focus-within 才浮出 —— 这就是设计稿的行为。

---

## 4. base.css 精确复位清单扩容

新增两个"裸 button"设计稿类（理由见第四批 §2，二者都是 `<button>` 形态）：

```css
.avatar-pick,   /* ProfileView 头像格 */
.nowplaying,    /* 首页 greet 行的 idle 态是 <button class="nowplaying idle"> */
```

**未动**工程版 `button{}` 重置本身（`class="primary"` 系列仍靠它活着）。

基线同步：`base.css` `9d86a51bf1883369` → **`121b562804633520`**（c2/c3/c4/c5/c6 五个脚本已更新）。
`primitives.css` 本批未改（`37a8ff2d375f61c4` 不变）。

---

## 5. 机器证据

| 检查 | 结果 |
|---|---|
| `vue-tsc --noEmit` | `exit=0`（本批唯一类型问题：RunView 闭包赋值导致 CFA 判 `never`，已显式收窄修掉） |
| `tools/_fusion_build.py` | `built in 3.12s`，exit=0 |
| `tools/_force_design_check.py` | **ALL OK: True** · 26 → **27 项**（新增 `D1g_fifth_batch_page_bindings`） |
| …实测值 | `.nowplaying` rectH=**46**（设计稿 46px）· `.new-card` rectH=**150**（设计稿 150px） |

`D1g` 是**计算级**守卫：设计稿类必须真的出现在对应页面的 DOM 上 ——
只改 CSS/类名而不改元素（"有规则、无消费方"，CONTEXT-PACK §1.3）会直接红。
选择器刻意选了**恒在**的（`.nowplaying` / `.new-card`），避免数据为空时假红。

---

## 6. 未做 / 遗留

- **未完成**：`verify_tech07c2~c6` 本轮没能重跑（需要 Edge WebView 出沙箱，用户拒绝了权限申请）。
  已知前提：C2–C6 依赖 `ui/dist` 必须是 `_fusion_build.py`（`VITE_CORE_BASE=''` 同源）产物 ——
  本批已按该方式重建 dist。轮到跑时可直接执行。
- **未做**：Tauri release 重打包 + NSIS 刷新（同上，等门禁跑完再做）。
- **登记在案**：SoftwareView 列表视图不再有表格，路径信息改挂行 `title`（鼠标悬停可见）；
  这是跟设计稿对齐的取舍，若后续有"路径排序/导出"需求再单独评估。
