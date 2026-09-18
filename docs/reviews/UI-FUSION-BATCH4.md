# UI-FUSION 第四批 · 交付报告（2026-09-18）

> 一句话：修掉两个**看得见的保真缺陷**（按钮多一圈灰边、页面结构类名没归位到设计稿），
> 顺带修掉一个**挡住模型持久化的 core 缺陷**（配置键漏登 `KEYS`）。全部有机器证据。

---

## 1. `core`：`ai.models.registry` 键在 `expected_type`/`default_for` 里，却漏在 `KEYS`

| 项 | 内容 |
|---|---|
| 症状 | `verify_tech06b` **45/48**，C2/C3/C6 红 |
| 真因（先前误判为"release exe 陈旧"） | `ConfigService::set` 报 `未登记的配置键：ai.models.registry` ⇒ 模型清单**写不进去** |
| 为什么既有测试抓不到 | 那两条测试是**正向**的（遍历 `KEYS` → 查 type/default）；漏的那项不在 `KEYS` 里，永远不被遍历 |
| 修复 | ① `KEYS` 补键；② 新增**反向**测试 `every_typed_key_is_in_whitelist`（扫 `include_str!` 自身文本，断言 type/default 段里每个键都在 `KEYS` 内） |
| 结果 | `verify_tech06b` **48/48** · `core` 单测 **6/6** |

**修这条时踩的新坑（值得记）**：新测试最初写成 `SRC.find("pub fn expected_type")`，而
`verify_tech04.py` / `verify_tech05c.py` / `verify_model_registry.py` **三个门禁**都用
`config_rs.split("fn expected_type")[-1]` 截函数体 —— 文件里多一处该字面量，它们就取到
**测试段之后的空区间**，`expected_type` 恒判"未登记"（44→43 / 34→33 / 32→31，**三条全是假红**）。
→ 针改为运行时拼 `format!("fn {}", "expected_type")`，并在注释里写明"不许写回字面量"。

---

## 2. UI：设计稿的 `button` 基础重置被排除 ⇒ 所有"裸 button"类都多一圈灰边

- 设计稿重置：`button{background:none;border:0;padding:0}`
- 工程重置（`base.css` 顶部，唯一生效者）：`background:var(--panel); border:1px solid var(--border); padding:4px 10px`
  —— **它是一个可见盒子**
- 受影响：`.icon-btn`（30×30 应透明）、`.seg button`（分段控件段间冒竖线）、`.tabs button`、
  `.chip button`、`.win-btns button`、`.btn`（设计**无边框**）、**`.pw-btn`（每个按钮都有）**

### 修法：精确复位（**不**改工程重置）

`base.css` 在工程重置之后、设计稿并入段**之前**，新增一段**只列设计稿类名**的复位
（`background:none;border:0`）；`primitives.css` 给 `.pw-btn` 补 `border:0`。

**为什么不动工程重置**：工程期还有大量裸按钮走 `class="primary"` + `button.primary{}`
（ModeView / SoftwareView / LayoutView…），整体改重置会一次性打掉它们的盒子 —— 大面积回归。

**为什么放在并入段之前**：设计稿自己声明了 `background`/`border` 的类（`.btn` 底色、
`.btn--secondary`/`.new-card` 边框）会以"同权重、源序更后"胜出 ⇒ 清单宁多勿漏，**不会反向覆盖设计稿**。

**防复发**：`_force_design_check.py` 新增 **D1f** —— `.pw-btn--icon` / `.icon-btn` / `.seg button` /
`.tabs button` 计算级 `borderWidth === 0`（探针 25 → **26 项**）。

---

## 3. 页面结构类名归位：**2/7 页**完成

| 页 | 挂上的设计稿类 | 同时让出的本地块 |
|---|---|---|
| **ModelsView** | `.model-grid` / `.model-card` / `.mc-foot` / `.new-card` | `.mv-add-row` 只留"满宽 + 禁用态"，形态交 `.new-card`（竖排/居中/`min-height:150px`/虚线，**原来是个横排 pill**）；删 `.mv-card-foot` 本地块 |
| **AiView** | `.tabs` / `.ai-grid` / `.ai-sessions` / `.ai-session-list` / `.ai-session`(+`.on`) / `.ai-chat` / `.ai-chat-head` / `.ai-msgs` / `.msg` / `.bubble`(+`.me`) | 上列类的本地版面与外观声明全部删除；tab 由 `pw-btn` 对 → 设计稿下划线式 `.tabs` |

**顺带对齐的真实偏离**（AiView）：`.ai-grid` `240px minmax(0,1fr)/gap:12px` → 设计 `264px 1fr/gap:--gap-section`；
`.ai-sessions` 内距 `12px` → `0`（内压到表头行）；`.ai-session` 内距/圆角/`.on` 高亮 → 设计值
（`brand-50`/`brand-700`，原来是 `border`+`surface-hover`）；消息气泡 → 设计 `.msg .bubble`
（`--r-lg`/`surface-2`；自己贴右 `brand-50` + 右下小圆角，原来是 `--surface-overlay`）。

**纪律（本批最值钱的一条）**：组件本地 `<style scoped>` 编译后是 `.x[data-v-*]`，与设计选择器
**同权重（0,2,0）**，平局靠**源序**决定 —— 而打包后源序**不可依赖**。
→ 设计稿已覆盖的版面/外观值必须**删掉本地块**让位，"在本地把设计值抄一遍"是**假安全**。

---

## 4. 验证证据（全部本次实跑）

| 门禁 | 结果 |
|---|---|
| `verify_tech06b` | **48/48**（修前 45/48） |
| `verify_model_registry` | **32/32** |
| `verify_tech04` / `05c` / `05d` / `06a` | **44/44** · **34/34** · **89/89** · **43/43** |
| `verify_tech07c2` / `c3` / `c4` / `c5` / `c6` | **25/25** · **27/27** · **25/25**(+1 Deferred) · **24/24** · **27/27**（均 exit=0） |
| `_force_design_check` | **ALL OK: True** — **26 项**（含新 D1f）、`rules 72/72`、`unresolved vars: []` |
| `core` 单测 `db::config` | **6/6** |

**冻结基线（5 个脚本已同步 + LEDGER 记账）**：
`base.css db5244f71716e677 → 9d86a51bf1883369` ·
`primitives.css 014cff0446e63ef6 → 37a8ff2d375f61c4`

**产物**：Tauri release 重建 exit=0 → NSIS 刷新正式位
`D:\Personal Workspace\personal-workspace-core.exe` **12,382,208 → 14,647,808 B**（`refreshed: true`）。

---

## 5. 剩余（有界，下一步）

| 归属 | 设计稿类 | 落点 |
|---|---|---|
| `page:workspaces` + `fn:wsCard` | `.wf-row .wf-mode .wf-mode--new .ws-card .hd .new-card` | ModeView `list` 视图 |
| `page:create` | `.wsteps .wstep .wline .pick-grid .pick .em .tick .detect .app-pick .btn--lg` | ModeView 向导（**不另起平行页**） |
| `fn:runPrepSequence` | `.run-prep .rp-steps .rp-step .spinner` | RunView ⚠️ **必须绑真实操作**（`snapBusy`/`layoutBusy`/`refresh`），不得照抄 3×340ms 演示序列 |
| `fn:nowPlaying` | `.nowplaying .ttl .art .ctrl` | LifeView |
| `fn:openAvatarPicker` | `.avatar-grid .avatar-pick .avatar-pick--up` | ProfileView |
| `fn:tagEditorHtml` / `fn:openCustomize` | `.chip--removable` / `.arrange-row` | 设置页 / 首页 |
| `fn:openAddApp` | `.app-row .wide .tm .hover-only` | SoftwareView |

⚠️ 改类名前先 grep 验收脚本用到的选择器（保留 `data-pw-*` / `.mv-modal-mask` / 按钮文案等钩子）；
ModeView 拖拽画布 `ed-canvas/ed-dragbox` 参与指针几何计算，**不要给其子元素加 transform 动画**。
