/**
 * Workspace Runtime Adapter —— 统一出口（TECH-07-C Phase C1/C2）
 *
 * ```text
 * RunView / 未来页面 ──> workspaceAdapter.*（本文件）──> @/api services ──> core 既有命令
 *                                    │
 *                                    └─ boundary.ts：白名单 / 禁令 / 段位开关
 *                                       projection.ts：core DTO → UI 投影（C2）
 * ```
 *
 * 消费规则：
 * - **页面不得绕过 adapter 直接 import `@/api`**（verify_tech07c/07c2/07c3 静态扫 /run 视图）；
 * - adapter 不写 `workspace` 冻结域（store/layout），也不 import 它们（verify_tech02 T1b 不破）；
 * - C3 = actuate 段：facts 全开（真实读取 + 投影），窗口控制放开 **windows_place**
 *   （仅移动/缩放归属当前工作模式的窗口，unbound 拒绝）；
 * - 类型出口：RunView 只 import 本文件 + facts.ts 的投影类型。
 */

export * from './boundary'
export * as projection from './projection'
export * as facts from './facts'
export * as actions from './actions'
// C7-B/C7-D：geometry 常量单一来源（RunView 预览消费，禁止私设第二份）
export { MIN_NORM, SNAP_NORM } from './actions'

import * as facts from './facts'
import * as actions from './actions'
import * as snapshotRuntime from './snapshot'
import * as layoutRuntime from './layout'
import { ADAPTER_MODE, type AdapterMode } from './boundary'

export const workspaceAdapter = {
  /** 段位（C1/C2 固定 observe）。 */
  mode: (): AdapterMode => ADAPTER_MODE,
  /** 一次只读事实快照（真实窗口投影 / 当前模式聚合 / 布局 / 显示器 / 连接态）。 */
  snapshot: facts.snapshot,
  facts: {
    /** 系统真实可管理窗口（投影；pids = 模式流水线 pid 集合，用于归属判据）。 */
    windows: facts.windows,
    modeProgress: facts.modeProgress,
    layouts: facts.layouts,
    monitors: facts.monitors,
    modes: facts.modes,
    /** 软件库（C2：launchedAppIds → name 映射用）。 */
    apps: facts.apps,
  },
  actions: {
    applyMode: actions.applyMode,
    cancelApply: actions.cancelApply,
    exitMode: actions.exitMode,
    /** C3：移动/缩放归属当前工作模式的真实窗口（windows_place；unbound 拒绝）。 */
    placeWindow: actions.placeWindow,
    /** C3：最近一次 facts 快照（RunView 拖拽换算与归属展示用，只读）。 */
    lastSnapshot: facts.lastSnapshot,
  },
  /**
   * C4：Workspace Window Snapshot（历史状态，**不是** live facts）。
   * 捕获 / 恢复 / 状态查询全部经 Core 既有命令，持久化落点 = Core config
   * `workspace.snapshot.last`；UI 不得直接写 SQLite，也不得用 localStorage 冒充。
   */
  windowSnapshot: {
    capture: snapshotRuntime.captureSnapshot,
    restore: snapshotRuntime.restoreSnapshot,
    status: snapshotRuntime.getSnapshotStatus,
    currentRunId: snapshotRuntime.currentRunId,
  },
  /**
   * C5：Workspace Layout Persistence（模板语义，与 snapshot 双轨并存）。
   * 保存 = 受管窗口排布 → `db_layout_upsert`（slot 存 apps.name + 归一化 rect，无 hwnd/pid）；
   * 应用 = 模式绑定布局 → `layout_apply`（core skip 语义原样透出，不启动软件）。
   * 本组入口**不读写** `workspace.snapshot.last`。
   */
  layout: {
    save: layoutRuntime.saveLayout,
    apply: layoutRuntime.applyBoundLayout,
  },
}

export type { PlacementIntent, PlacementResult, PlacementStatus } from './actions'
export type {
  CaptureOutcome,
  CaptureStatus,
  RestoreItem,
  RestoreOutcome,
  RestoreSkip,
  RestoreSkipReason,
  SnapshotStatus,
} from './snapshot'
export type {
  LayoutApplyOutcome,
  LayoutApplyStatus,
  LayoutSaveOutcome,
  LayoutSaveStatus,
  LayoutSlotOutcome,
} from './layout'

export type WorkspaceAdapter = typeof workspaceAdapter
