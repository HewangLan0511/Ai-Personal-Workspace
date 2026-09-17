# UI-07 验收报告 · 个人档案编辑体验补全

日期：2026-09-15　范围：`personal-workspace-ui/index.html`（单文件原型，纯内存 mock，无数据库）

---

## 一、修改前后对比

| 位置 | 改前 | 改后 |
|---|---|---|
| 档案页 page-head | 头像「白」+ 静态 `白宇` + 方向副标 + **「编辑」按钮无 data-act（点击无任何反应）** | 同布局，但按钮 `data-act="profile-edit"`；点击进入编辑态 |
| 编辑态 | 不存在 | 原位切换：`昵称` 标签 + input（自动聚焦并全选，预填当前昵称）+ `[保存] [取消]` + 提示行「保存后立即生效 · 按 Esc 也可取消」 |
| 保存 | 不存在 | 写回 `profile.fields[nickname].value` → 展示态即时更新 + **头像首字联动** + toast「个人资料已更新」 |
| 取消 | 不存在 | 丢弃修改回展示态（无 toast、无写回）；Esc 键同样取消 |
| 空值防护 | — | 空昵称保存 → toast「昵称不能为空」并保持编辑态聚焦 |

## 二、新增 / 复用组件

**新增（均为局部小件，无新 CSS、无新 token、无新动画）**
- `state.profile`：`{ editing, fields[] }`，字段结构即 **profileField 预留接口**：
  `{ id, label, value, editable, type }`（本轮 nickname 可编辑驱动 UI，tagline 只读展示，email/org 为预留示例不渲染）
- `profileHeadHtml() / refreshProfileHead()`：展示⇄编辑两态渲染与**局部刷新**（只重写 `#profileHead` + `#profileAvatar` 两个叶子）
- ACTIONS：`profile-edit / profile-save / profile-cancel` + 全局 Esc 拦截（编辑态优先，不走 closeLayer）

**复用**
- `input lg / btn(--primary/--ghost/--sm) / t-label / t-cap / toast()` —— 零新设计语言
- 展示态 DOM 直接携带 `data-field="nickname" data-editable="true" data-type="text"`（tagline 为 `data-editable="false"`）—— profileField 接口在 UI 上的可验证投影，未来数字档案系统（添加字段/自定义卡/AI 建议/动态更新）按同结构扩展

## 三、S2 影响：零整页重绘

- 所有变化走 `refreshProfileHead()`：**只重写 `#profileHead` 的 innerHTML + 头像 textContent**
- e2e 断言：保存前后 `#profileHead` 与「编辑」按钮的 **DOM 节点身份不变**（`===` 同一节点），页面其余部分（AI 建议卡 / 扩展块 / 兴趣技能卡）一概未触碰
- 无 render() 调用、无新增 Motion Token、无新动画

## 四、验收结果（verify_ui07.py 5/5 绿）

| # | 用例 | 结果 |
|---|---|---|
| T1 | 编辑入口：输入框出现 + 自动聚焦全选 + 保留原昵称 + 保存/取消在位 | PASS |
| T2 | 保存：改名「白宇 2.0」→ 展示立即变化 + **壳节点身份不变**（headSame/btnSame=True）+ 头像首字联动 + toast「个人资料已更新」 | PASS |
| T3 | 取消：恢复保存过的原昵称，无新 toast（对比 toastHost 数量，不误伤前序存活 toast） | PASS |
| T3b | Esc 取消：键盘退出编辑态恢复原昵称 | PASS |
| T4 | 扩展结构：profileField 投影可验证（data-* 属性 + editable 语义）且字段数据驱动完整编辑闭环 | PASS |

**全量回归**：语法门禁 PASS（3792 行 script）；既有 12 套 e2e **77/77** 全绿（S2 6 / 折叠 7 / widget-dock 6 / toast 4 / win-front 4 / 04b 6 / 04c 6 / 04cp0 6 / 05p0 7 / 05snap 6 / 05b 9 / 06 10）。

**测试侧备注**：T3 首版用 toast 文本断言「无保存结果」误报 —— T2 的 toast 还在 2.2s 存活期内；改为对比 toastHost 子节点数量（取消不新增 toast）。

## 五、风险登记

1. **mock 数据位置**：`state.profile`（内存，刷新即还原）；真实持久化属后续 Runtime/存储层职责，本轮明确不做。
2. **Runtime 接入口**：
   - 字段读写收敛在 `fieldOf(id)` 与 `profile-save` 一处；接入时把「写回内存」替换为 Runtime 调用即可，UI 骨架与局部刷新路径不动。
   - 失败路径已预留注释：写回失败 → `toast('保存失败，请稍后重试','alert')` 并保持编辑态，本轮未实现真实错误处理。
   - 扩展方向接口：`profile.fields[]` 与档案扩展块（UI-04-B `profileExts`）是两个独立结构 —— 基础字段（结构性）与扩展段落（内容性）未来可按此边界分别接 Runtime。
3. **并发编辑冲突**（多端改昵称）不在原型范围，登记给未来账号系统。

按约定停止，不进入下一阶段。
