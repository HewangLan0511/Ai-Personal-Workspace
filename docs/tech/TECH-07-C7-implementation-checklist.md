# TECH-07-C7 Implementation Checklist —— Phase 1 只读审计（F3 交互尾巴收敛）

> 日期：2026-09-16 冻结
> 目标（用户指令冻结）：**C7 = F3 交互尾巴收敛** —— Esc 退出当前交互态、窗口交互异常恢复、
> 边界吸附（仅 UI 预览层）、窗口树状态展示补全（只读）。
> 硬约束：不改变 core 能力、不开放 windows_activate、不引入 windows_close、不改变 C6 三链恢复语义、
> 不新增视觉 Token、不改冻结 CSS、不碰 snapshot schema / layout_apply / mode_restore / 多显示器 / 多实例。
> 性质：**Phase 1 = 只读审计，零代码改动。** 停止条件：✅ 本 checklist + ✅ audit-report → 停止等 Phase 2 拍板。

---

## C7-01 Pointer 生命周期审计

### 现状（`RunView.vue` 125~269 行，C3 冻结设计）

```
pointerdown（startDrag / startResize → beginInteraction）
  ├─ 残留防护：上一次交互未收尾则先 cancelInteraction()        ← 已有（166 行）
  ├─ setPointerCapture（try/catch：合成指针失败不拖死交互链）  ← 已有（180-184 行）
  └─ 挂 window 级监听 ×4：pointermove / pointerup / pointercancel / lostpointercapture（185-189 行）

pointermove（onInteractMove）→ previewGeometry → writeGeometry（纯本地 style 写入，零 core 调用）
pointerup（commitInteraction）→ interaction=null → detach → 至多一次 windows_place → refresh
pointercancel / lostpointercapture（cancelInteraction）→ interaction=null → detach → writeGeometry(start) 本地回滚
detachInteraction：4 个监听对称移除（213-218 行）
```

### 闭环判定

| 异常退出路径 | 闭环 | 备注 |
|---|---|---|
| pointercancel | ✅ | cancel：null → detach → 回滚 |
| lostpointercapture | ✅ | 同上；且正常 pointerup 路径 commit 先 detach，cancel 不会二次触发 |
| 上一次交互异常残留 | ✅ | beginInteraction 先 cancel（166 行） |
| **Esc 键退出** | ❌ **不存在** | 全文件无 keydown/Escape 处理 —— 即 F3 要补的主项（见 C7-02） |
| **cancel 路径 facts refresh** | ⚠️ 部分 | commit 路径有 `refresh()`；cancel 路径只有 writeGeometry(start) 本地回滚、**不重采样 facts**。语义上取消未改变任何真实状态，refresh 非必需；但本阶段判据要求"异常退出 → facts refresh 恢复"，Phase 2 可给 cancel 补一次只读 refresh（零 core 风险），登记为可实现项 |

- **禁止项核对**：现有 window 级监听**仅在交互存活期间挂载、detach 对称移除**，非常驻全局监听、非 document hack —— 不违反禁令。Phase 2 的 Esc 若实现，须沿用同模式（交互期间挂 keydown、detach 移除），不得新增常驻全局键监听。

---

## C7-02 Esc 事件链审计

**现状：不存在。** `RunView.vue` 无任何 keydown/Escape 处理（全文件检索零命中）。

Phase 2 设计约束（冻结）：
- Esc 只在 `interaction !== null` 时有意义：清除预览（writeGeometry(start) 回滚）→ cancelInteraction；
- ✅ 清除预览 ✅ 不 commit（不调 placeWindow）✅ 不调用 core ✅ 不改变窗口位置（真实位置从未变过——commit 边界在 pointerup）；
- 非交互态 Esc = 无操作（不抢占全局快捷键）；
- 监听生命周期与 pointer 监听同进同出（attach/detach 对称），禁止常驻。

四条要求在现有 cancelInteraction 语义下**天然满足**——Esc 只需复用 cancel 通路，零新增 core 交互。

---

## C7-03 Window Geometry 边界审计

### 现链路

```
preview rect（本地 previewGeometry，无越界保护）
  → commit（pointerup 一次）
  → adapter placeWindow：clamp(x,0,1) / clamp(y,0,1) / clamp(w,0.02,1) / clamp(h,0.02,1)（独立 clamp）
  → windows_place（core，物理像素）
  → facts refresh 确认（成功对齐 / 失败回滚预览）
```

### 逐项确认

| 项 | 现状 | 判定 |
|---|---|---|
| x+w / y+h 越界 | **可越界**：x 与 w 独立 clamp，联合不保证 x+w ≤ 1（如 x=1, w=0.5 ⇒ x+w=1.5）→ 摆位后窗口部分出工作区。**即 C5-06 登记项，仍未修** | ⚠️ 本阶段可实现项（最小修：adapter 内联合 clamp，或预览层 clamp） |
| MIN size | 预览层 MIN=0.04（归一化），adapter 层 clamp 下限 0.02 —— 实际 commit 的 w≥0.04，adapter 下限不触发；**两层口径分裂（0.04/0.02）**，不破坏 geometry 但建议 Phase 2 统一 | ⚠️ 可实现项（口径统一） |
| 多方向 resize 回弹 | e/s/w/n 数学对称（w=s.w−dx; x=s.x+(s.w−w)），MIN clamp 后 x 跟随，无回弹缺陷；越界场景与 move 同解（commit clamp / facts 确认回滚） | ✅ 无异常 |
| safeRect | 仅 C4 restore 路径使用，不参与拖拽 place 链路（placeWindow 只有 clamp） | ✅ 边界清晰 |

---

## C7-04 吸附设计审计（只设计，不实现）

**冻结原则**：
- 吸附**只允许作用于 preview layer**（previewGeometry 计算内的目标修正）——纯本地、不进 Vue 响应式、每帧仅 style 写入；
- **禁止** pointermove → core windows_place 的实时摆位（commit 边界必须仍是 pointerup 单次提交）；
- 吸附**不改变** commit 语义与 adapter 归一化协议（吸附只是 intent 生成端的辅助）；
- 吸附候选（monitor edge / window edge / grid）**暂不决定** —— Phase 2 拍板后再细化；
- 实现落点唯一：`previewGeometry`（及可能的辅助几何函数），不新增监听、不新增 core 调用、零新 Token（吸附提示线若要可视化，只能复用既有样式变量，Phase 2 再议）。

---

## C7-05 Window Tree 状态来源审计（只读）

### 数据链

```
core WindowInfo（hwnd/title/class_name/pid/visible/minimized/maximized/rect/area —— 无 exePath）
  → projection.mapWindow → RunWindowFacts（hwnd/title/state/belongsToMode/manageable/rect/...）
  → RunView 舞台卡片：is-managed 类（p.mode）+ "非当前模式窗口（只读）"标注；非 managed 卡片无 pointerdown（586 行 p.mode 门控）
```

### 展示能力判定

| 类别 | 现状 |
|---|---|
| managed | ✅ 已展示（is-managed 卡片，可拖拽/缩放） |
| unmanaged | ✅ 已展示（只读标注，不可交互） |
| **unknown** | ⚠️ **无此类别** —— projection 只有 belongsToMode/manageable 两个布尔。**建议不引入第三类**（无证据源，引入=编造事实）；若 Phase 2 需要，唯一诚实口径是"manageable 但不属于当前模式"，仍属 unmanaged 展示范畴 |
| 独立窗口树 drawer | ❌ 不存在（C1 壳未含；现状 = 舞台卡片直接承载全部窗口展示）。"窗口树状态展示补全"两个可选口径：(a) 现有卡片信息补全（state/几何文本，最小增量）；(b) 新增只读 drawer 面板（新 UI 面，需零新 Token 约束下设计）—— **Phase 2 拍板** |
| 新增控制入口 | **禁止**（本阶段只读；不新增任何按钮/命令调用） |

---

## C7-06 C3/C4/C5/C6 回归边界审计

| 判据 | 与 C7 实施的关系 |
|---|---|
| c2 A2a：placeWindow 恰好 1 处调用 | Esc/吸附**不得**新增 placeWindow 调用点（Esc 复用 cancel 通路天然满足） |
| c2 A2b：RunView 禁 actions.applyMode/cancelApply/exitMode | 不受影响（C7 不碰 mode 动作） |
| c2 A3/A4/A5 + c6 S4：零新 token/动画/hex/无新样式文件 | 吸附提示线等任何可视化只能消费既有变量；否则红 |
| c2 D4：DOM identity（stage/appbar/mini/head 四锚） | Esc/吸附不重建 DOM；窗口树补全若加面板需保 identity |
| c6 S6：C3/C4/C5 交互状态全集（按钮/chip/disabled） | 不删不改；若补全展示需新增 data-pw 须同步登记 |
| c6 S3：hash 基线 8 项 | **RunView.vue 不在 hash 冻结内**（可改）；boundary/ModeBar/冻结域/CSS/schema 不可动 |
| c5 R：全量回归 | C7 实施后全链重跑（串行纪律） |

**禁止事项核对（本阶段全部未触碰）**：windows_activate 白名单化 ✗ / windows_close ✗ / mode_restore 改造 ✗ / snapshot schema ✗ / layout_apply 修改 ✗ / 多显示器 ✗ / 多实例归属 ✗ / 新增视觉 Token ✗ / 修改冻结 CSS ✗。

---

## 停止声明

Phase 1 只读审计完成：零代码改动，冻结域 hash 不变。审计发现与可实现/禁止项清单见
`docs/tech/TECH-07-C7-audit-report.md`。**立即停止，等待 Phase 2 拍板。**


---

## Phase 2 执行段（2026-09-16 冻结，依据用户拍板）

### 冻结决策

| 项 | 决策 |
|---|---|
| C7-A 越界修复 | **纳入**。所有 move/resize 方向统一经过 adapter placeWindow 的**最终联合 geometry 校验**（intent 各分量独立 clamp 保持 C3 契约 → 整窗完整落在工作区内，含舍入收口）。预览端 previewGeometry 做**同口径联合 clamp**（预览不展示越界形态，与 commit 两端一致）——不拦截 commit 本身：pointermove 零 core 调用、pointerup 仍单次 commit |
| C7-B MIN 统一 | **统一到 adapter 常量**：`MIN_NORM = 0.02`（actions.ts 唯一定义并 export，RunView import 消费）。理由：adapter 是 place 契约方，C3/C4 place contract 零变更；消灭 RunView 私有 magic number（预览 0.04 与 projections 过滤 0.02 一并收口） |
| C7-C Esc 链 | **纳入**。交互期挂 window keydown(Escape) → cancelInteraction（与 pointer 监听同进同出）；硬约束：不调 windows_place、零 core 请求、不改事实层 |
| C7-D 吸附 | **monitor edge snap**（仅 previewGeometry + commit 预览同源）；阈值 `SNAP_NORM = 0.02`（adapter 唯一定义）。不做 window edge / grid snap |
| C7-E 窗口树 | **口径 a：现有卡片补全**（bar 文本追加：当前模式/只读 标识、`app:<name>`（仅 progress slots 证据存在时——禁止无来源标注）、已最大化/已最小化）。不新增 drawer、不标记 unknown、不猜 exe |
| C7-F 验证 | 新增 `tools/verify_tech07c7.py`：S 静态 + R 全量回归（C1~C6 + TECH-02 + 契约）+ D 真实（Esc 零摆位 / edge snap / 四角 resize / 交互恢复 / 卡片补全证据） |

### 变更白名单（Phase 2）

`ui/src/views/RunView.vue` · `ui/src/workspace/runtime/actions.ts`（geometry/clamp + 常量）·
`ui/src/workspace/runtime/index.ts`（仅常量 re-export）· `tools/verify_tech07c7.py` · 文档/日志。
**其余全部禁改**（core / schema / 冻结域 / CSS / 既有 verify 脚本 / 三链语义）。

### Baseline hash（实施前记录，2026-09-16 22:5x 复核）

snapshot.ts `604fe010e0d3f980` · tokens `f329f50bddd31d59` · motion `e5e44af4aa807d38` ·
primitives `2de660ce01c2c7d5` · base `46d26e1bc27716a7` · schema `d95ca49cc3285166` ·
boundary `19dfb41e2df31ccd` · ModeBar `eccb9c10727d3d30` —— **8/8 与 C6 收口一致，实施中前 6 项 + boundary/ModeBar 均不得变化**。
