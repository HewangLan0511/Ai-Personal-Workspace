# UI-06 验收报告 · 模型管理中心

日期：2026-09-15　范围：`personal-workspace-ui/index.html`（单文件原型，纯内存 mock）
前置：TECH-03-A Model Registry Runtime 已完成 —— 本批**只做 UI**，不改 Runtime、不新增模型逻辑，等待接线。

---

## 一、页面设计

**「模型管理」独立页（`#/models`），不进主导航** —— 入口收敛为两处，都不抢 AI 助手：
1. 设置 → 「AI 与模型」分类（原「AI 助手」更名）→ 「当前模型」select / 「模型管理 · 打开」
2. AI 助手页 page-head 的 `当前模型：GPT-5 ▼` chip（原 pick-model 循环器改造，点击跳转）

**页面结构**（工作台风格，非后台管理页）：
```
page-head：← 返回（回到跳转来源页）｜ 模型管理 ｜ 副标：连接、测试与切换，技术细节都替你收好了 ｜ + 添加模型
├─ 当前模型卡（card--lg）：模型名 + 状态 chip + Provider chip + 延迟 chip(演示) + [切换模型]
├─ 我的模型 · N 个模型
├─ model-grid 卡片（auto-fill ≥272px）：名称/Provider 展示名/●状态/延迟 + 查看·设为默认·测试连接·删除
├─ 底部虚线「添加模型」入口（空态时隐藏，空态卡内自带添加按钮）
└─ 空态：✦ 还没有添加模型 / 连接一个AI模型，让工作台拥有自己的智能 / + 添加模型
```

**Provider 展示（原则 4）**：`providerLabel()` 统一映射 —— api→用户填的 Provider 名（OpenAI/API），local→`本地模型`，agent→`个人Agent`。e2e 断言全文（渲染文本）无 registry/canonical/adapter。

## 二、交互流程

1. **切换模型**：顶部「切换模型」或卡上「设为默认」→ drawer 列出全部模型（当前 chip + 状态）→ 点选 → toast「已切换到 X」→ **局部 diff**：只重写 `#curModelCard` / `#modelGrid` / `#modelCount` 内容，页面壳节点身份不变（e2e 断言 DOM identity）
2. **添加模型**：+ 添加模型 → drawer 第一步三类型卡（API 🌐 / 本地 💻 / Agent 🤖，复用 create 向导的 `.pick-grid`）→ 按类型出字段：API=Provider/Endpoint/Key；本地=地址/模型名称；Agent=名称/通讯方式(HTTP/WebSocket chip) → 添加 → 卡片即时出现 + toast；类型可随时用 chip 切换或「重新选择」
2.5. **返回来源记忆**（用户修正补充）：所有入口统一走 `models-entry`（data-v=来源：ai|settings），`state.modelBack` 记录来源页；返回按钮 `models-back` 据此回跳 —— AI 助手页进来回 AI 助手页，设置进来回设置；直链进入默认回设置。回跳后来源重置为 settings。
3. **测试连接**：卡片/查看 drawer 内点击 → 延迟 `38ms · 演示` chip + 未配置→已连接，toast 注明演示数据
4. **查看**：只读 drawer 列出该类型配置项（Key 只显示「已保存/未配置」，不回显明文）
5. **删除**：直接删除 + toast；若删的是当前模型 → 自动落到第一个剩余模型；全部删空 → 空态

## 三、组件复用说明

| 复用 | 用途 |
|---|---|
| `card / card--lg / card--ghost` | 当前模型卡 / 模型卡 / 空态与说明 |
| `drawer（scrim+aside+head/body/foot）` | 切换 / 查看 / 添加 三抽屉 |
| `chip / chip--brand / mono` | 状态、Provider、延迟、「当前」标 |
| `.rs-dot.ok/.off`（UI-05-B 状态点） | ● 已连接 / ● 本地运行 / ○ 未配置 |
| `toast()` | 全部操作反馈 |
| `pick-grid / pick`（create 向导） | 添加模型类型选择 |
| `input/field/btn(--primary/--secondary/--danger/--sm)/seg/row-item/t-*` 排版 | 表单与层级 |
| `.new-card` | 底部虚线添加入口 |

**新增 CSS 仅 4 条**（`.model-grid/.model-card/.mc-foot` 布局类），零新颜色/字号/圆角 token，**零新动画**（drawer/scrim 沿用既有 token 动效）。

**数据结构**：`state.models[] = {id, name, ptype: api|local|agent, provider/addr+mname/agent+channel, status: connected|local|unset, latency, note}` + `state.currentModel`。旧 `state.aiModel` 与 `MODELS` 循环数组删除（e2e 无引用，已 grep 确认）。

## 四、验收结果（verify_ui06.py 10/10 绿）

| # | 用例 | 结果 |
|---|---|---|
| T1 | 页面可访问：当前模型卡 + 3 卡 + 添加入口，渲染文本无技术词泄漏 | PASS |
| T2 | 切换模型：drawer 选择 → 局部更新，**页面壳节点身份不变**（S2）+ toast + 当前 chip 转移 | PASS |
| T3 | 测试连接：延迟 chip（演示）+ 未配置→已连接 | PASS |
| T4 | 设为默认：当前 chip 转移 + 顶部当前模型同步 | PASS |
| T5 | 添加流程：3 类型选择 → 本地模型字段 → 保存即时出现（局部） | PASS |
| T6 | 删除：卡片移除，数量回落 | PASS |
| T7 | 空状态：引导文案 + 顶部「未设置模型」+ 底部入口隐藏、空态内保留添加 | PASS |
| T8 | AI 页入口：`当前模型：X ▼` 展示 + 点击跳转 → **返回按钮回到 AI 助手页（来源记忆，`back=#/ai`）** | PASS |
| T9 | 设置入口：AI 与模型分类 → 打开模型管理 → **返回回设置（`back=#/settings`）** | PASS |
| T10 | 响应式 1920/1366/900 无横向溢出 | PASS |

**全量回归**：语法门禁 PASS（3731 行 script）；既有 11 套 e2e **67/67** 全绿（含设置页/AI 页改动复验）。合计 **77/77**。

**测试侧踩坑记录**（产品代码无恙）：①技术词泄漏误报 —— 断言用了 `textContent`，把我自己写在 `<script>` 里的注释也算进去了，换 `innerText` 只取渲染文本；②T7 删空后入口未隐藏 —— `forEach` 点删到 detached 节点（refreshModelPage 每次重建 grid），改循环现查现点。

## 五、风险与下一步

1. **状态/延迟全是演示值**：`status/latency` 字段结构与 TECH-03 Runtime 对接点已收敛在 `MODEL_STATUS` 映射与 `model-test` 一处，接线时替换即可，UI 骨架不动。
2. **Key 只做掩码展示**：drawer 不回显明文；真实接入时注意 Runtime 侧也不应下发明文。
3. **删除无二次确认**：原型阶段保持轻量；接入真实配置后建议加 confirm modal。
4. 模型页未加入导航 IA、未做 workspace 内嵌 —— 按需求维持独立页 + 双入口。

按约定交付：页面设计 ✅ / 交互流程 ✅ / 组件复用 ✅ / 验收 ✅。不实现真实模型连接，等待 TECH-03 Runtime 接线。
