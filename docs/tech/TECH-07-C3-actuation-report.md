# TECH-07-C3 实施报告 —— Workspace Window Actuation（windows_place 真实摆位）

> 日期：2026-09-16 · 状态：**已完成，verify_tech07c3.py 27/27 全绿**
> 视觉基线：UI-06~UI-08 + `docs/ui/UI-FUSION-STANDARD.md` + C1/C2 RunView（视觉零变化）
> 停止点：Actuate（摆位）接通即止，未进入 close/activate/launch 等任何其它窗口控制。

---

## 一、数据流（本阶段达成形态）

```text
用户手势（拖拽 bar / 8 向缩放热区，仅 is-managed 窗口）
        ↓  pointermove = 本地命令式预览（不进 Vue 响应式，零渲染风暴）
        ↓  commit 边界 = pointerup（一次交互恰好一次摆位请求）
RunView.vue  —— 只产出归一化意图 PlacementIntent（0..1，相对主工作区）
        ↓  workspaceAdapter.actions.placeWindow()   ← 唯一入口，边界检查见下
ui/src/workspace/runtime/actions.ts（actuate 段）
  1. 段位 = actuate（否则 ActionBlockedError）
  2. hwnd ∈ lastSnapshot && belongsToMode && manageable（否则 unbound，绝不误操作）
  3. 归一化 → 物理 px（clamp 到工作区内）   ← 坐标换算全部在 adapter
        ↓  layoutApi.place(hwnd, rect)（既有 API，windows_place）
core  POST /api/v1/windows/{hwnd} → window_manager::place（SetWindowPos）
        ↓  refresh() 拉取 facts 确认真实几何（成功对齐 / 失败回滚预览，绝不信本地几何）
RunView 投影更新
```

## 二、变更说明

| 项 | C2（observe） | C3（actuate） |
|---|---|---|
| 段位 | observe（actions 全拒绝） | **actuate**（仅 placeWindow 放行；mode_apply 同步放行属既有命令） |
| 白名单 | +apps_list | +`windows_place`、+`apps_running`（均为既有命令）；禁区收窄并新增 `windows_close`/`apps_terminate` 显式禁区 |
| actions.ts | 无摆位 | **placeWindow**：段位/归属校验 + 归一化→物理换算 + windows_place；返回 placed/unbound/offline/failed 四态，绝不假装成功 |
| 归属判据 | pid ∈ 流水线集合 | 冻结并增强：pid ∈ 流水线 slots ∪ `apps_running` 注册表（按当前模式 launchedAppIds）；仍禁止 title/exe 猜测 |
| RunView.vue | 只读投影（pointer-events:none） | is-managed 窗口：bar 拖拽（cursor:grab）+ 8 向缩放热区；**非归属窗口保持整卡只读**；pointermove 本地预览、pointerup 单次提交；placement chip 如实显示四态结果 |
| core Rust | 零改动 | **零改动**（windows_place 既有能力完全满足，无缺口） |

## 三、真实环境验证证据（D 段，非 mock）

真实 core（临时数据目录）+ Edge headless + `VITE_CORE_BASE=''` 同源代理：

- **D1** core 启动 + `/health` OK（随机端口）
- **D2** 注册软件+模式 → mode_apply 真实拉起 charmap → 流水线登记 pid（归属证据）+ `apps_running` 注册表命中
- **D3** UI 出现 is-managed 投影（拖拽/缩放手势已挂载）
- **D4** **拖拽 → 真实窗口 left/top 变化且方向正确**：before=(18,80) → after=(144,140)，期望≈(126,60)（换算基准=主显示器工作区，与 adapter 同一公式）
- **D5** **se 缩放 → 真实窗口 width/height 增加**：w 572→824、h 536→715，期望≈(+252,+179)
- **D6** 非归属窗口只读：0 缩放手柄、0 grab、UI 层即拒绝（不依赖 core 拒绝兜底）
- **D7** S2：observe→drag→place→observe 全程 run-stage/run-head/appbar/minimap **DOM identity 全保持**
- **D8** 停 core（coreDead 实证）→ UI 显示「未连接」、**0 伪造窗口**、两次采样冻结（轮询未停摆）

## 四、过程中修复的缺陷（验收抓出，全部修于产品代码而非绕过）

1. **commitInteraction 死代码（P0）**：先把 `interaction = null` 再调 `previewGeometry()`（读模块级 interaction）→ 恒返回 null → windows_place 从未执行。修复：`previewGeometry(it)` 改为接收交互对象。
2. **setPointerCapture 中断监听注册（P1）**：对合成/已释放 pointerId 抛 NotFoundError，且 capture 位于 addEventListener 之前 → move/up 监听挂不上。修复：capture 包 try/catch（跟手增强，失败不拖死交互链）。
3. **验证代理丢 Content-Type（P1，tools 层）**：ProxyHandler._proxy 未转发 Content-Type → urllib 默认 form-urlencoded → core axum 415 → HTTPError 被 URLError 分支吞成 502 proxy_down → UI 误判 offline。修复：转发 Content-Type（tools/verify_tech07c2.py，GET 路径不受影响，C2 25/25 回归确认）。
4. **验收期望值算错（tools 层）**：物理位移基准应为**主显示器工作区**（/api/v1/monitors），非窗口自身宽高。

## 五、风险列表

- **R-1 offline 判定较粗**：placeWindow 将所有请求异常归为 offline/failed 二分（按 error.code），415/400 等语义错误与真实断连的区分依赖 core 错误码透传，后续可细化。
- **R-2 无拖拽越界回弹动画**：预览直接 clamp 到工作区内（0 new motion 红线），越界为硬停，无动画反馈——符合视觉纪律，体验后续议。
- **R-3 charmap 最小窗口限制**：charmap 对最小尺寸有约束，极小缩放意图会被 Windows 忽略（core place 成功但 rect 不变）——facts 确认环节会如实回滚预览，不假装成功。
- **R-4 dist 从不清理**：沿用 C2 风险记账（emptyOutDir 建议待办）。

## 六、回归结果

| 套件 | 结果 |
|---|---|
| verify_tech07c.py（C1 基线） | **16/16 PASS** |
| verify_tech07c2.py（C2 基线，A17+R2+D6） | **25/25 PASS** |
| verify_tech07c3.py（本阶段，A17+R2+D8） | **27/27 PASS** |

## 七、交付清单

**新增文件：**
- `tools/verify_tech07c3.py`（验收脚本，27 项）
- `tools/diag_t7c3.py`（D4/D5 聚焦诊断，复用验收基建；保留备查）
- `docs/tech/TECH-07-C3-actuation-report.md`（本报告）

**修改文件：**
- `ui/src/views/RunView.vue`（摆位交互：拖拽/8 向缩放/本地预览/pointerup 单次提交/placement chip/只读隔离样式；视觉全用既有 token，0 新动画）
- `ui/src/workspace/runtime/actions.ts`（placeWindow + PlacementIntent/Result/WorkArea）
- `ui/src/workspace/runtime/facts.ts`（lastSnapshot 缓存 + apps_running 聚合 + offline 判据 6 项）
- `ui/src/workspace/runtime/projection.ts`（resolveModePids = slots ∪ 运行注册表）
- `ui/src/workspace/runtime/boundary.ts`（段位 actuate、白名单 +windows_place/apps_running）
- `ui/src/workspace/runtime/index.ts`（出口补 placeWindow/lastSnapshot/类型）
- `tools/verify_tech07c2.py`（ProxyHandler 转发 Content-Type；禁区清单随 C3 演进）
- `tools/verify_tech07c.py`（FORBIDDEN/ALLOWED 清单随 C3 演进）

**未修改文件：**
- 视觉基线四 CSS（tokens/motion-tokens/primitives/base，hash 冻结判定一致）
- **core 全部 Rust 代码**（windows_place 既有能力满足，零缺口、零新命令）

**事实陈述：**
- 真实 Core 是否参与：**是**（真实进程 + mode_apply 真实拉起窗口）
- 是否证明"控制到了正确窗口"：**是**（D2 归属 pid 登记 → D4/D5 拖拽/缩放仅命中该 pid 窗口，before≠after 且方向/幅度符合请求；D6 证明非归属窗口在 UI 层即无任何手势入口）
- 是否执行窗口关闭/激活/恢复/终止：**否**（禁区清单出现即红，adapter 零路径）
- UI 是否发生视觉变化：**否**（交互热区为透明 hover 线 + cursor 变化，全部既有 token）
- Token/Animation 是否增加：**否/否**（hash 冻结 + 静态扫描）
- C1/C2 是否保持：**是 16/16、25/25**
