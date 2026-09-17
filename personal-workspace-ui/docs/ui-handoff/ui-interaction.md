# 交互规格 · Personal Workspace

> 交接文档 4/6。覆盖所有交互形态：点击 / 拖动 / 编辑 / 保存 / 取消 / Toast 反馈 / 状态变化。
> 实现载体：单文件 `index.html`，全部交互走**全局事件委派**（`data-act`）+ 页面级局部刷新函数。

## 1. 点击：统一委派层

- 所有可点元素带 `data-act="动作名"`，可选 `data-v="值"`；全局 `document` 级 click 委派统一分发。
- 两种写法并存（既有约定）：
  1. **按钮自带 act+v**（优先）：`<button data-act="model-switch" data-v="m1">`；
  2. **容器带 act**：点击冒泡到容器，委派层从事件目标就近补 v。
- 页面跳转：`data-act="go" data-r="路由名"`；模型管理入口特殊：`data-act="models-entry" data-v="ai|settings"`（写 `state.modelBack` 记录来源），返回按钮 `data-act="models-back"` 据此回跳。
- **分段控件（seg）**：点击切换激活项后**只调局部刷新函数**，不 render()（例：dock 切换走 `applyDockLocal()`，布局 seg 走 `applyRunLayout()`）。

## 2. 拖动：过程与落位分离

| 拖拽 | 规则 |
|---|---|
| 工作模式窗口拖动 | 全程 1:1 跟手，**绝不能带 transition**（拖拽中 body `.is-resizing` 关过渡）；吸附预览层 `.snap-ghost` 只在拖动中显示（pointer-events:none），**松手才落位**。 |
| 窗口 8 向调整大小 | `.rz-*` 热区，MIN 320×200，拖动中 `.win-size` HUD 实时显示尺寸；松手写入 `customLayout`。 |
| 折叠⇄展开手柄 | 全程 1:1 跟手（inline 宽度夹 `[foldW, expandAt]`）；到阈值 `crest` 脉冲+钉阈值 ~260ms 后重锚续跟；未到阈值松手→惯性滑行（写 inline 宽度，摘壳后才交还变量）；阈值必须滞回，dwell 560ms。 |
| 组件区排序 | `enableSort` 必须绑 `.wscroll` 真实滚动父容器（绑 #widgetCol 会 insertBefore 抛错静默失效）。 |
| 拖拽中的状态同步 | 起手时局部同步 `refreshRunStatus()`（auto→manual），不整页刷新。 |

**测试铁律**：class 生效 ≠ 几何就位（宽度过渡未收敛时按下会抓错位置）。

## 3. 编辑：原位展开，不跳页

编辑一律**原位切换展示态⇄编辑态**，壳节点恒在、只重写内容：

- **档案页**：`#profileEditor` 壳节点恒在；`refreshProfileEditor()` 重写卡内容。昵称 input 自动聚焦全选；签名 textarea maxlength 60 + 实时计数；标签 chip × 删除 / Enter 添加 / 推荐一键加；头像 picker 抽屉（首字母 + 8 emoji + 上传虚线格仅 UI，点选即时预览）。
- **编辑快照**：进入编辑态时 `state.profile.backup` 整体快照，取消时整体还原；头像 picker 用独立快照 `avatarPickBase`。
- **抽屉编辑器**：目标编辑（`openGoalEditor`）、模式创建（`modeDraft`）、模型添加（openModelAdd）等走统一 Layer 抽屉，保存后抽屉关闭 + 局部刷新对应容器。

## 4. 保存 / 取消 / Esc

- **保存**：写入 state → 局部刷新展示（如 `refreshProfileHead()` + 头像首字联动）→ toast 反馈（「个人资料已更新」）。空值防护：toast「昵称不能为空」，不落库。
- **取消**：还原快照 + 退回展示态，无 toast。
- **Esc 优先级链**（全局 keydown 拦截）：**全局弹层（Layer）> 页面编辑卡取消 > 其他**。编辑态下 Esc 等价取消，优先级必须压过 closeLayer 之前注册的行为冲突。
- **静默成功**：部分操作成功无 toast（如 tag 添加），这是有意设计；失败/防护类才弹 toast。

## 5. Toast 反馈

- 底部居中 Toast Host：**最多 2 条**，超额挤掉最旧；独立定时器，2200ms 自动退场；点击可关闭。
- 用途：保存成功、防护提示、状态确认。**不做错误堆栈式通知**，一条一事。
- e2e 注意：断言用 toastHost 子节点数量对比，勿查文本（前序 toast 存活期内必误报）。

## 6. 状态变化：S2 局部 diff（最高纪律）

- 页面内任何状态变化**只重写目标叶子容器**，禁止整页 render()。判据是 **DOM 节点身份**：容器节点保持不变，只有内容子节点被替换。
- 现有局部刷新函数索引（新增状态变化优先复用/扩展，不另起 render）：

| 函数 | 作用域 |
|---|---|
| `refreshRunStatus()` | 工作模式状态栏（goal chip / 应用三态 chip / 布局 / 模式） |
| `refreshProfileHead()` | 档案页头部 + 头像叶子 |
| `refreshProfileEditor()` / `refreshProfileTags()` / `refreshTagEditor()` | 档案编辑卡 / 标签展示 / 标签编辑器 |
| `refreshModelPage()` | 模型管理页（当前模型卡 / 模型卡列表 / 计数） |
| `applyDockLocal()` | dock 开关/模式切换 |
| `applyRunLayout()` | 窗口布局几何（不重写 DOM 结构） |
| `#profileExts` / `#lifeGrid` 容器刷新 | 档案扩展块 / 生活槽位增删 |

- 应用三态（运行中 / 等待打开 / 已关闭）chip 点击循环切换；即时局部重写。
- e2e 注意：局部刷新会重建子节点，旧引用点击落在 detached 节点上到不了委派层，**必须现查现点**。

## 7. 弹层体系（Layer）

- 全局唯一 Layer 容器：scrim + modal / drawer / 右键菜单；统一退场（先 `.out` 动画再清空）。
- 工作模式模板切换的 prep overlay **独立于 Layer**（防 Layer 异步退场定时器误清），复用 `.scrim/.modal/.spinner/fadeIn`。
- 弹层内再次弹层（如模型查看→切换模型 drawer）允许，Esc 逐层退。
