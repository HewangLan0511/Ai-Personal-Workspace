/**
 * Workspace Runtime Adapter —— 边界常量（TECH-07-C Phase C1）
 *
 * ## 这一层是什么（TECH-07-B 设计 §二的落地骨架）
 * `ui/src/workspace/`（TECH-02 冻结域）与 core 真实事实之间的**受控通道**：
 * - 域规则：workspace 域内（store/layout/snapshot/runtime 门面）零 `@/api`；
 *   本目录（`workspace/runtime/` 子目录）是**唯一**被允许 import `@/api` 的邻接层。
 * - 为什么是子目录：`workspace/runtime.ts`（门面）已存在且被 verify_tech02 T1c
 *   登记消费者集合；本目录以 `workspace/runtime/<file>` 子路径引用，不与门面混淆。
 *
 * ## C3 边界（硬约束，验收 verify_tech07c3 会查）
 * - **facts 只读**：当前模式 / 运行窗口 / 布局 / 显示器 / 进度（C2 投影不变）。
 * - **actions**：windows_place（移动/缩放，C3 放开）+ 非窗口控制的模式动作。
 *   归属规则冻结（C2 §五）：hwnd 必须 ∈ 最新 facts.windows 且 belongsToMode
 *   且 manageable —— 否则 unbound 拒绝，绝不误操作其他窗口。
 * - ❌ 仍不实现：windows_activate/close、layout_apply、恢复（mode_restore/
 *   快照）、apps_launch（FORBIDDEN_COMMANDS，出现即红）。
 * - ❌ 不新增 core 命令：白名单命令全部是已验收的既有命令。
 */

/** adapter 允许调用的 core 命令白名单（全部为既有已验收命令，TECH-07-C C1/C2/C3/C4/C5）。 */
export const ALLOWED_COMMANDS = [
  // facts（读）
  'modes_list',
  'modes_current',
  'mode_progress',
  'layouts_list',
  'monitors_list',
  'windows_list',
  'apps_list', // C2：软件库名称表（launchedAppIds → name 映射），只读
  'apps_running', // C3：运行注册表（appId → pid），归属判据证据源，只读
  'ping', // C4：core 实例身份（pid/started_at），Snapshot `source` 的真实出口，只读
  // actions（写，非窗口控制）
  'mode_apply',
  'mode_cancel',
  'mode_exit',
  // C5：布局持久化（模板语义，双轨并存 —— 见 runtime/layout.ts）
  'db_layout_upsert', // 保存布局（LayoutRepo 唯一写入口；slot 存 apps.name + 归一化 rect，无 hwnd/pid）
  'layout_apply', // 恢复默认 = 应用模式绑定布局（core apply_layout：未运行 skip，不启动软件）
  // actions（写，窗口控制 —— C3 起放开 place：移动/缩放外部窗口）
  'windows_place',
] as const

export type AllowedCommand = (typeof ALLOWED_COMMANDS)[number]

/**
 * 禁止本层出现的命令（C5 起仅 layout_apply / db_layout_upsert 移入白名单，其余仍禁：
 * 激活/查找/矩形读取/恢复/捕获/启动/关闭 —— C5 仍不是控制阶段，出现即红）。
 * verify_tech07c3 用这份清单对 adapter 源码做静态扫描：**出现即红**。
 */
export const FORBIDDEN_COMMANDS = [
  'windows_activate',
  'windows_find',
  'windows_rect',
  'mode_restore',
  'modes_capture_current',
  'apps_launch',
  // C3 明确禁区（§12 安全边界）：只允许 Move / Resize
  'windows_close',
  'apps_terminate',
] as const

/** C3 起的段位（TECH-07-B 设计 §2.4：dryRun → observe → actuate）。 */
export type AdapterMode = 'dryRun' | 'observe' | 'actuate'

/**
 * 当前段位：**C3 = actuate**（窗口控制放开，仅限 windows_place 移动/缩放）。
 * - facts 不变：仍是 C2 的只读投影；
 * - actions 准入：placeWindow 校验段位 + 归属 + manageable；
 * - 演进记录：C1 observe → C2 observe（真实接线）→ C3 actuate（仅 place）
 *   → C4 snapshot（持久化 + 受限恢复）→ C5 layout（模板保存/应用，双轨并存）。
 */
export const ADAPTER_MODE: AdapterMode = 'actuate'
