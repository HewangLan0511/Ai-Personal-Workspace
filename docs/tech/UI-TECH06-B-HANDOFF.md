# UI-TECH06-B HANDOFF —— 数据绑定位置说明（UI-09）

> 性质：**交接说明，不是设计稿**。本轮（TECH-06-B）UI 层零改动（16 路由 / 16 视图不变，无颜色/布局/动画/组件变更）。
> 本文档只回答一件事：**哪些页面在等真实数据、绑定位置在哪里、数据变真后页面会自然吃到什么。**

---

## 1. 模型页（`/models` → `ui/src/views/ModelsView.vue`）

| 绑定点 | 位置 | 说明 |
|---|---|---|
| 唯一数据口 | `getSharedRegistry()`（`ui/src/ai/model/bridge.ts`） | 全应用同一实例；页面**不得**自建 Registry、不得直接读写归档（验收 T1e 已锁定：页面零归档访问） |
| 清单来源 | `registry.list()` → `ModelListEntry[]` | 本轮起 `hydrate()` 会先从 `ai.models.registry` 归档恢复模型——**刷新/重启后清单不再为空**，页面代码无需任何改动 |
| 当前模型 | `composables/useCurrentModel.ts`（内部 `getSharedRegistry()`） | canonical 恢复逻辑不变；本轮新增「不 dangling」保障（default 指向的模型实体随归档一起恢复） |
| 状态显示 | `registry.list()` 的 `entryStatus` + `ai/model/status.ts` 归约 | 重启后模型一律「未测试」（`unchecked`）——这是**刻意行为**（反假绿），UI 侧请勿"优化"成记住上次连接状态 |
| 归档健康度（暂无消费者） | `registry.getArchiveState()` | 本轮新增的只读查询：`ok / absent / unreadable` + `writeError`。当前页面**未接**；如未来要加"保存失败"弱提示，从这里读，属 UI 变更需走冻结豁免 |

## 2. 个人档案页（`/profile` → `ui/src/views/ProfileView.vue`）

| 绑定点 | 位置 | 说明 |
|---|---|---|
| 唯一数据口 | `stores/profile.ts` → `api/profileService.ts` | 页面不直连 core；本轮**零改动** |
| 真实数据现状 | 审计结论：`profile_basic.name/motto/interests` 已是真实持久化（昵称/签名/标签真实落库），头像走 config 键 `profile.avatar`（只存引用） | 详见 `docs/tech/TECH-06-B-profile-audit.md` §结论 |
| 等待真实数据的残留位 | 若页面仍有 mock 兜底分支，绑定位置就在 `stores/profile.ts` 的加载动作处 | **本轮未做**扩展档案（`profile_ext/profile_fields` 不存在于仓库）；扩展需新设计阶段，绑定位置届时不变（仍走 profileService） |

## 3. AI 助手页（`/ai` → `ui/src/views/AiView.vue`，含 `components/AiSidebar.vue`）

| 绑定点 | 位置 | 说明 |
|---|---|---|
| 唯一数据口 | `ai/assistant/bridge.ts`（`getSharedAssistant()`）→ `ai/assistant/service.ts` | 会话/传输已真实化（`ai_chat`/`ai_cancel`/`ai_preview_context`）；本轮**零改动** |
| 目标模型解析 | `service` 内 `getSharedRegistry()`（canonical 优先） | 与模型页**同源**：归档恢复的模型重启后即可被选中，无需页面感知 |
| 状态基线 | AI store 的 localStorage 键基线不增不减（`ui.ai.collapsed/mode/model/provider/width`，验收 T2a-b 锁定） | 模型清单持久化**没有**借道 store/localStorage |

---

## 冻结确认

本轮按指令执行：改颜色 ❌ / 改布局 ❌ / 新增页面 ❌ / 新增动画 ❌ / 重构组件 ❌ —— 全部未发生。
机器证据：`verify_tech06b.py` T5a（模型页零自定义属性/零裸色值）、T5b（16 路由/16 视图与 TECH-06-A 基线一致）。
