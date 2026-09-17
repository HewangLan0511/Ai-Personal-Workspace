# Workspace Runtime（TECH-02）

> 日期：2026-09-15 · 状态：**已交付，验收 11/11**
> 工具：`tools/verify_tech02_workspace.py`（Edge headless + CDP，跑在 `ui/dist` 最终产物上）
> 参考 UI（唯一消费者）：`ui/src/views/DevWorkspaceHarness.vue`，挂 `/dev/workspace`（dev-only，不进导航）

## 一、这条层解决什么问题

UI-05-B 的「工作空间状态系统」此前把状态写在页面内部的 mock 对象里 —— **UI 直读 mock**。
后果是数据来源换不掉：将来接真实 Agent / 软件控制层时，得把页面全部重写一遍。

TECH-02 把状态**收进一个内存 store**，UI 只经一个门面取数：

```
改造前：  UI ──直接读──> mock 对象 ──> render
改造后：  UI ──> workspaceRuntime API ──> memory store ──> UI 订阅后 render
```

本轮**只换数据源**，不碰 UI 结构、不控制真实软件、不接管窗口系统。

## 二、三个模块

| 文件 | 职责 | 关键约束 |
|------|------|----------|
| `ui/src/workspace/store.ts` | 内存状态：工作空间 / 应用 / 模板 / 快照 / 窗口事件 | 零数据库、零 core、零动画 |
| `ui/src/workspace/layout.ts` | Layout Snapshot：采集 / 恢复 / 清除 **DOM 几何** | 只碰 DOM，不碰任何窗口 API |
| `ui/src/workspace/runtime.ts` | 对外门面（类型再导出 + 方法集合） | UI 唯一的取数/改数入口 |

`store.ts` **不 import Vue**：运行时是框架无关的，将来 TECH-03 的真实 Agent 要复用同一份状态，
不能要求对方装 Vue。所以本层用显式 `subscribe(fn)`，UI 侧自己接进响应式（固件页里就是 `rev.value += 1`）。

## 三、数据模型（§一）

```ts
WorkspaceRuntime = {
  workspaceId: string
  name: string
  goal: string
  mode: string
  apps: Array<{ appId, name, status: 'running' | 'waiting' | 'closed', windowId?, layoutNode? }>
  layout: { type: 'auto' | 'manual', snapshotId?: string }
}
```

`status` 与标识位的关系由**唯一一处**状态机决定（`applyStatusToDraft`）：

| status | windowId | layoutNode |
|--------|----------|------------|
| `running` | `win-<appId>` | `node-<appId>` |
| `waiting` | `win-<appId>` | 无（尚未落到布局树） |
| `closed` | 无 | 无 |

> 为什么把这个状态机提取成 store 的导出函数：`runtime.ts` 的 prepare 流水线第③步也要改状态。
> 两处各写一遍 = 规则迟早漂移。现在两处共用同一实现。

## 四、结构级防篡改（"UI 不直接访问 mock"不是口头约定）

两条硬机制，都是**结构保证**而不是纪律：

1. **`__SEED_TEMPLATES` 模块私有、绝不导出**。UI 拿不到种子数据本体，
   只能经 `workspaceRuntime.listTemplates()` 取数。
2. **所有读取返回 `deepFreeze(clone(x))`**。UI 拿到的是深克隆 + 冻结的副本：
   改它不影响真身，`push` 会直接抛错。

验收 T1d 实测：`Object.isFrozen(...)` 为真、`push` 抛错、改副本后真身状态不变。
T1a/T1b/T1c 是静态门禁：种子未被导出、全仓 `ui/src` 没有任何文件 import
`workspace/store` 或 `workspace/layout`（除模块自身）、`workspace/runtime` 的消费者只有固件页。

## 五、Layout Snapshot（§三）

模板与工作空间此前是**浅绑定**：模板只记"有哪些应用"，不记"它们摆在哪"，
于是每次进入窗口位置都随机。Layout Snapshot 补上"摆在哪"，让绑定变深。

- 保存字段**只有六个**：`{appId, x, y, width, height, zIndex}`；
- 坐标系 = 窗口矩形相对 **canvas 内容盒左上角** 的偏移（取整）；
- DOM 契约（UI ↔ Runtime 之间唯一的布局接口）：
  ```
  [data-wwr-canvas]                       ← 坐标系原点
    └─ [data-app-id="<appId>"]            ← 应用窗口（绝对定位，left/top 即快照 x/y）
  ```
- 只记 **DOM 几何**，永不接触真实系统窗口、永不落库。

> ⚠️ 与 `workspace.snapshot.last`（PW-INTEGRATION-003 §2 的**系统级窗口**快照、core 落库）
> 是两个不同的东西，名字像但层次完全不同。本快照活在 `store.ts` 的内存 `Map` 里。

### 实测到的坑：几何不能交给 Vue 托管

固件页最初用 `:style="boxStyle(appId)"` 绑定几何。T3 立刻变红：

```
save 后几何 A → 拖拽成 B → loadLayoutSnapshot() → DOM 被 applyLayoutToDom 写回 A
                                              ↓
             store 通知 → Vue re-render → 用镜像里的旧值 B 把 DOM 冲回 B
```

moved=true 但 restored=false —— **restore 静默失效**。
结论：**几何必须命令式写 DOM**（`layout.ts` 的契约本来就是"写 left/top/w/h/zIndex"）。
固件页改为 `paintGeometry()` 命令式落盘 + `adoptDomIntoPositions()`（DOM 赢：把真实 DOM 几何收回镜像），
restore 才真正生效。这条对 TECH-03 的消费者同样成立。

## 六、模板（§四）

模板**自己拥有** apps 与 layoutSnapshot，字段严格按 `{id, name, goal, apps[], layoutSnapshot}`。

| API | 行为 |
|-----|------|
| `createTemplate({name, goal?, apps?, layoutSnapshot?})` | `apps` 省略 → 取当前工作空间；`layoutSnapshot` 省略 → 现场采一份 DOM 几何快照，传 `null` 表示明确不要 |
| `saveTemplate(name?)` | 把**当前工作空间**（应用 + DOM 几何）存成新模板 |
| `loadTemplate(idOrName)` | 注册其快照并把 layout 绑到当前工作空间 |
| `listTemplates()` / `getTemplate(idOrName)` | 读取（冻结副本） |

内置三个种子模板：`AI 开发`（3 应用）/ `写作`（2）/ `学习`（3），均可按 id 或名称访问。

**全部内存，无数据库**。T2c 用对照组证明：整页 reload 后自定义模板消失、种子模板回来
（`{"n": 3, "customGone": true}`）—— 这是"零持久化"的正/反双向证据，不是靠读代码断言。

## 七、窗口状态同步（§五）

```ts
windowEvent({ windowId, event: 'open' | 'close' | 'focus' })
```

| event | 效果 |
|-------|------|
| `open` | 该应用 → `running`（分配 windowId + layoutNode） |
| `close` | 该应用 → `closed`（清空两个标识 + 释放焦点） |
| `focus` | 状态不变，只改 `focusedWindowId`，并把快照里该应用 zIndex 顶到最上 |

`windowId` 匹配不到任何应用时返回 `null`：事件被记录，但**不改任何状态**
（T4 的对照组，防止"事件路径恒置 running"的假通过）。

**现在只更新 Runtime，不连接任何真实软件。** TECH-03 的真实窗口事件从同一个入口灌进来即可。

## 八、准备流程（§六）

点击模板 → `prepareWorkspace(id)`：**真异步流水线**，四个固定步骤（顺序即契约）：

```
① read-workspace        模板 → 工作空间对象
② read-layout-snapshot  读取布局快照（模板自带 / 已注册）
③ sync-app-status       快照覆盖到的 = running，其余 = waiting
④ commit                一次性提交并通知
→ 进入 run（何时渲染由 UI 决定）
```

两个要点：

- **每步之间 `await`**（默认 0ms，可用 `stepDelayMs` 调大）—— 现在全是内存数据，
  但结构是真异步。将来把①②换成"真实软件启动 / 真实窗口就位"时，调用方一行都不用改。
- **只有一次通知**。第③步若逐个调 `updateAppStatus`，会产生 N 次通知 → UI 侧 N 次 diff，
  正是 S2 要避免的"更新状态引发整页刷新"的反面。所以流水线在**草稿**上改，
  最后 `commitWorkspace` 一次性装上（一次通知 = 一次局部 diff）。

若模板自带快照但尚未注册进 store，第②步会 `putSnapshot` 补登记 ——
否则第③步会把全部应用静默降成 `waiting`，模板与工作空间又变回浅绑定。

`prepareWorkspace` 只保证"数据就位 + layout 指向该快照"；**几何的 DOM 应用由 UI 负责**
（只有 UI 知道窗口何时渲染出来）。

## 九、硬边界（§七 不可越）

- 零数据库（全部内存，刷新即重置）
- 零 core（不 import `@/api/*`，不发 invoke / HTTP）
- 零动画、零 Motion 改动（不 import `@/motion/*`，prepare 也不触发动效）
- 零新 token、零新动效、零页面重构
- 零真实软件启动、零系统窗口控制、零插件连接、零 AI 自动规划 → **TECH-03**

## 十、验收（`tools/verify_tech02_workspace.py`，11/11）

驱动真实构建产物 `ui/dist`（脚本自带门禁：dist 早于 `ui/src` 直接 FATAL，
防"改了源码没构建"），Edge `--headless=new` + CDP，全部走真实页面与真实点击。

| 用例 | 判据（摘要） |
|------|--------------|
| T1a–c | 种子私有未导出；全仓无越权 import；runtime 消费者唯一 |
| T1d | 门面 13 个方法齐全；返回值冻结、写不穿真身 |
| T2a–b | create → 按 id 读回字段完整；新模板可被 prepareWorkspace 使用且四步有序 |
| T2c | **对照组**：reload 后自定义模板消失、种子回来（零持久化双向证据） |
| T3 | save → 真实指针拖拽（几何真的变了）→ restore 回原几何（2px 容差）→ clear 回落 auto |
| T4 | open/close/focus 真改 store **且**真改 DOM badge；未匹配事件不改状态（对照组） |
| T5 | 状态更新前后 canvas 与窗口**节点身份不变** + scrollTop 保持；**对照组**：换模板时节点身份必须变（证明探针有区分度） |
| T6 | 1920 / 1366 左右并排、900 上下堆叠，三档均无横向溢出、窗口几何正常 |

T5 的探针纪律：判据是**节点身份（`===`）**而不是"某个标记还在"——
曾把标记打在容器上导致断言恒真的坑，这里用"换模板会让节点身份变化"作对照组排除掉。

## 十一、下一步（TECH-03，本轮不做）

真实软件启动 / 系统窗口控制 / 插件连接 / AI 自动规划。
接口已经留好：`windowEvent()` 灌真实事件、`prepareWorkspace()` 返回 `Promise` 签名不变、
`subscribe()` 天然适配"后端推状态"。
