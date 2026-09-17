# UI-08 验收报告 · 个人档案页编辑体验增强

日期：2026-09-15　范围：`personal-workspace-ui/index.html`（单文件原型，纯内存 mock）
前置：UI-07 昵称编辑闭环已验收。本轮在其上扩展头像 / 个性签名 / 标签，**不新开页面、不新增路由**。

---

## 一、修改前后对比

| 位置 | 改前（UI-07） | 改后（UI-08） |
|---|---|---|
| 编辑入口 | 「编辑」→ page-head 内仅昵称原地变输入框 | 「编辑资料」→ **原位展开编辑卡**（`#profileEditor`，card 形态，不遮挡整页）：昵称 + 个性签名 + 标签 + 头像 四区 + 保存/取消 |
| 头像 | 只显示昵称首字，不可改 | **点头像或「更换头像」开 picker drawer**：首字母格 + 8 个预设 emoji 格 + 上传虚线格（仅 UI）；点选即时预览（页头/编辑卡头像叶子同步高亮与换字），保存生效 toast「头像已更新」，取消还原 |
| 个性签名 | 无 | 编辑卡内 textarea（maxlength 60 + 实时计数 n/60）；头部新增签名行；**空值保存 = 恢复默认态**（头部显示占位「还没有个性签名」） |
| 标签 | 兴趣方向 chips 写死在模板里 | 由 `tags` 字段驱动（`#profileTags` 容器）；编辑卡内 chip 删除（×）/ 输入 Enter 或 + 添加 / **推荐标签一键添加**；正常添加静默生效（chips 即时更新），空/重复有 toast 反馈 |
| 昵称 | 原位编辑（UI-07） | 逻辑保留：自动聚焦全选、保存/取消/Esc、即时刷新、空值防护 —— 输入位置移入编辑卡首行 |
| 取消语义 | 只还原昵称 | **进入编辑时对整个 fields 做快照（backup）**，取消整体还原四类字段 |

## 二、新增 / 复用组件

**新增（小件，可数）**
- `state.profile.fields[]` 扩展三个 profileField：`avatar`（type:'avatar'，''=首字母/emoji=预设）、`signature`（type:'multiline'，空=默认态）、`tags`（type:'tags'，字符串数组）；`backup` 快照字段
- `profileEditorHtml() / refreshProfileEditor()`：原位编辑卡（开卡时挂 nickname 聚焦全选、签名计数、标签 Enter 监听）
- `tagEditorHtml() / refreshTagEditor()`：标签编辑区（增删只重写 `#tagEditor`，输入焦点可恢复）
- `openAvatarPicker()`：头像选择 drawer（`avatarPickBase` 独立快照，picker 内取消不影响编辑卡）
- ACTIONS：`profile-tag-del/add/sug`、`avatar-picker/set/save/cancel/upload`；`profile-edit/save/cancel` 升级
- CSS 仅 5 条布局类：`.input textarea`（无边框多行）、`.avatar-grid / .avatar-pick(.on / --up)` —— 复用既有颜色/圆角/时长 token，**0 新 token、0 新动画**

**复用**
- card/card--lg、drawer（头像 picker）、input/textarea、chip（含既有 `.chip--removable` 删除钮样式）、chip--brand、avatar、toast、btn 全家族、ico 图标、badge-emoji 语义

## 三、S2 影响

- 局部刷新收敛为四个叶子：`#profileHead`（头部文字）、`#profileAvatar`、`#profileTags`（兴趣方向 chips）、`#profileEditor`（编辑卡壳节点恒在，内容按编辑态切换）；标签增删只重写 `#tagEditor` 更小一级
- e2e 断言（T1/T8）：编辑开合、保存全程，**头部、编辑按钮、AI 建议卡、扩展块容器、两张经历卡 DOM 节点身份全部不变**（`===`）
- 无 render() 调用；Esc 优先级：弹层（picker）> 编辑卡取消

## 四、验收结果（verify_ui08.py 9/9 绿）

| # | 用例 | 结果 |
|---|---|---|
| T1 | 编辑入口：编辑卡原位展开，昵称聚焦全选、签名 0/60、标签 5+推荐 8、头像行；主体节点身份不变 | PASS |
| T2 | 签名：输入「专注 RGB-T 感知」计数联动 11/60 → 保存后头部签名行即时更新 | PASS |
| T3 | 标签：删除(5→4) → Enter 添加「开源」(5) → 推荐一键添加(6) → 保存后兴趣方向 chips 同步 | PASS |
| T4 | 标签取消：删除后取消 → 还原 6 个，无新 toast | PASS |
| T5 | 头像：picker 10 格 → 选 🚀 即时预览 → 保存生效；重开选 💻 后取消 → 还原 🚀 | PASS |
| T6 | 上传入口：演示反馈「图片上传将在接入后开放」，不实现真实上传 | PASS |
| T7 | 空值异常：昵称空阻止保存并保持编辑态；空标签/重复标签 toast 反馈；正常添加静默生效 | PASS |
| T7b | 签名清空保存 → 头部恢复默认态文案 | PASS |
| T8 | 主体节点身份：头部/编辑按钮/AI 建议卡/扩展块/两张经历卡全程身份不变 | PASS |

**回归**：`verify_ui07.py` 已同步更新（T1 适配编辑卡交互，其余原语义保留）5/5；语法门禁 PASS（3953 行 script）；既有 13 套 e2e **82/82** 全绿（S2 6 / 折叠 7 / widget-dock 6 / toast 4 / win-front 4 / 04b 6 / 04c 6 / 04cp0 6 / 05p0 7 / 05snap 6 / 05b 9 / 06 10 / 07 5）—— AI 页、首页、工作模式、模型管理、Motion 系统均无影响。合计 **91/91**。

## 五、后续接 Runtime 的接口位置

1. **字段读写唯一入口**：`fieldOf(id)` + `profile-save`（写回 nickname/signature/tags）+ `avatar-set/save`（头像）。接入时把「写内存」替换为 Runtime 调用，UI 骨架与局部刷新路径不动。
2. **profileField 结构不变**：`{id, label, value, editable, type}`，新增 type 语义：`'avatar'`（value='' 首字母 / emoji 串 / 未来 `custom:<引用>`）、`'multiline'`（≤60）、`'tags'`（string[]）。UI 只消费字段能力，不绑定 Runtime 实现。
3. **失败路径预留**：`profile-save` 内注释位 —— 写回失败改走 `toast('保存失败，请稍后重试','alert')` 并保持编辑态。
4. **上传**：`avatar-upload` 目前只 toast 演示；接入后在此打开文件选择并把结果写入 avatar.value（`custom:` 形态）。
5. **快照/还原**：`state.profile.backup`（编辑态）与 `avatarPickBase`（picker）两处独立快照，未来可换成 Runtime 事务回滚。

按约定停止，不继续扩展个人档案系统。
