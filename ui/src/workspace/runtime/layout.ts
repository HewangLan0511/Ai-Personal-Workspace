/**
 * Workspace Runtime Adapter —— Layout Persistence（TECH-07-C5）
 *
 * ## 职责（与 Snapshot 双轨并存，禁止混用）
 * - **Layout = 模板**："这类软件排成什么样" —— 归一化 rect + 软件库名称，
 *   存 `layouts` 表（`db_layout_upsert` 唯一写入口），应用走 core `apply_layout`
 *   （未运行 ⇒ `skipped_not_running`，**绝不启动软件**）；
 * - **Snapshot（C4）= 实例**："那一刻的工作区" —— hwnd/pid/exePath 身份 + 物理像素，
 *   存 config `workspace.snapshot.last`，恢复走受限执行器。
 * 本文件**不读写** `workspace.snapshot.last`，**不保存** hwnd/pid/foreground/snapshotId/runId。
 *
 * ## 身份口径（core 链路事实）
 * core `resolve_pid` 按 **`apps.name` 大小写不敏感匹配** → `running.get(app.id)`，
 * 所以 slot 落库字段是**软件库名称**；本层从受管窗口 pid →（slots ∪ running）→ appId
 * →（apps_list）→ name，与 C4 `buildEvidence` 同一条登记证据链，无 title/位置猜测。
 */

import { appsApi } from '@/api/appsService'
import { layoutApi } from '@/api/layoutService'
import { modeApi } from '@/api/modeService'
import { snapshot as takeFacts, type WorkspaceFacts } from './facts'

// ---------------------------------------------------------------- 类型

export type LayoutSaveStatus = 'saved' | 'offline' | 'no_mode' | 'no_windows' | 'write_failed'

export interface LayoutSaveOutcome {
  status: LayoutSaveStatus
  /** 保存成功的布局名（空 = 未落库）。 */
  name: string | null
  /** 写入的槽位数。 */
  slots: number
  detail: string
}

export type LayoutApplyStatus = 'done' | 'partial' | 'failed' | 'offline' | 'no_layout'

/** core `apply_layout` 的逐槽位结果（如实透传，不加工）。 */
export interface LayoutSlotOutcome {
  app: string
  status: string
  hwnd: number | null
  rect: { x: number; y: number; w: number; h: number } | null
  reason: string | null
}

export interface LayoutApplyOutcome {
  status: LayoutApplyStatus
  /** 被应用的布局名（no_layout 时为 null）。 */
  layout: string | null
  placed: number
  skipped: number
  failed: number
  slots: LayoutSlotOutcome[]
  detail: string
}

interface NormRect {
  x: number
  y: number
  w: number
  h: number
}

// ---------------------------------------------------------------- 内部工具

/** 主显示器工作区（物理像素）。与 C4 snapshot 的 primaryWorkArea 同一口径。 */
function primaryWorkArea(facts: WorkspaceFacts): { x: number; y: number; w: number; h: number } | null {
  const m = facts.monitors.find((x) => x.primary) ?? facts.monitors[0]
  if (!m || m.work_w <= 0 || m.work_h <= 0) return null
  return { x: m.work_x, y: m.work_y, w: m.work_w, h: m.work_h }
}

/**
 * pid → 软件库名称（唯一证据链：slots(pid→appId) ∪ running(appId→pid) → apps_list.name）。
 * 与 C4 `buildEvidence` 同一条登记链；查无证据 ⇒ null（调用方跳过该窗口，不猜）。
 */
async function pidToAppName(): Promise<Map<number, string>> {
  const [apps, running] = await Promise.all([
    appsApi.list().catch(() => []),
    appsApi.running().catch(() => ({}) as Record<string, number>),
  ])
  const nameById = new Map(apps.map((a) => [a.id, a.name]))
  const out = new Map<number, string>()
  // 证据源 1：运行注册表（appId → pid）
  for (const [appId, pid] of Object.entries(running)) {
    const name = nameById.get(Number(appId))
    if (name && Number(pid) > 0) out.set(Number(pid), name)
  }
  return out
}

/** 时间戳：YYYYMMDD-HHMMSS（本地时间）。 */
function stamp(d: Date): string {
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

// ---------------------------------------------------------------- 保存（F1）

/**
 * 把当前受管窗口排布保存为布局（模板语义）。
 *
 * - 只取 `belongsToMode && manageable && rect` 的**非最小化**窗口（最小化窗口的几何
 *   不代表排布意图，与 C4-D4 skip 口径一致）；
 * - 归一化基准 = 主屏工作区（与 core `to_pixels` / C3 placeWindow 同一口径）；
 * - z = 枚举序 + 1（升序先摆，与 C4 zIndex 近似口径一致）；maximized 如实保存，
 *   alwaysOnTop 恒 false（facts 无此证据，不编造）；
 * - 受管窗口为 0 ⇒ `no_windows`，**不写库**（C4 空快照不覆盖的同款口径）。
 */
export async function saveLayout(modeName: string): Promise<LayoutSaveOutcome> {
  const fail = (status: LayoutSaveStatus, detail: string): LayoutSaveOutcome => ({
    status,
    name: null,
    slots: 0,
    detail,
  })

  // 1) 新鲜事实 + 连通性（offline ⇒ 不写库）
  let facts: WorkspaceFacts
  try {
    facts = await takeFacts()
  } catch (e) {
    return fail('offline', `事实拉取失败：${String((e as Error)?.message ?? e)}`)
  }
  if (facts.connectivity === 'offline') {
    return fail('offline', 'core 未连接 —— 不保存布局')
  }
  const name = modeName?.trim() || facts.mode.running
  if (!name) return fail('no_mode', '当前不在任何工作模式中')

  // 2) 受管窗口（归属 + 可管理 + 有真实几何）
  const wa = primaryWorkArea(facts)
  if (!wa) return fail('write_failed', '主显示器工作区不可用（monitors facts）')
  const managed = facts.windows.filter(
    (w) => w.belongsToMode && w.manageable && w.rect && w.state !== 'minimized',
  )
  if (!managed.length) return fail('no_windows', '没有可保存的受管窗口（不写空布局）')

  // 3) pid → 软件库名称（登记证据链；无证据窗口跳过，不猜）
  const names = await pidToAppName()
  const slots: Array<{
    app: string
    rect: NormRect
    z: number
    alwaysOnTop: boolean
    maximized: boolean
  }> = []
  let skipped = 0
  for (const w of managed) {
    const appName = names.get(w.pid)
    if (!appName || !w.rect) {
      skipped += 1
      continue
    }
    const r = w.rect
    // 物理像素 → 归一化（0..1，相对主屏工作区）；Number.isFinite 护栏（C4-06 口径）
    const norm: NormRect = {
      x: Number.isFinite((r.x - wa.x) / wa.w) ? (r.x - wa.x) / wa.w : 0,
      y: Number.isFinite((r.y - wa.y) / wa.h) ? (r.y - wa.y) / wa.h : 0,
      w: Number.isFinite(r.w / wa.w) ? r.w / wa.w : 0,
      h: Number.isFinite(r.h / wa.h) ? r.h / wa.h : 0,
    }
    slots.push({
      app: appName,
      rect: norm,
      z: slots.length + 1,
      alwaysOnTop: false, // facts 无此证据，不编造
      maximized: w.state === 'maximized',
    })
  }
  if (!slots.length) {
    return fail('no_windows', `受管窗口均无软件库登记证据（跳过 ${skipped}）—— 不写布局`)
  }

  // 4) 落库（命名策略冻结：run-<模式名>-<时间戳>）
  const layoutName = `run-${name}-${stamp(new Date())}`
  try {
    await modeApi.dbLayoutUpsert(layoutName, `Run 页保存（模式：${name}）`, slots, 0)
  } catch (e) {
    return fail('write_failed', `布局写入失败：${String((e as Error)?.message ?? e)}`)
  }
  return {
    status: 'saved',
    name: layoutName,
    slots: slots.length,
    detail: `已保存 ${slots.length} 个槽位` + (skipped ? `（跳过 ${skipped} 个无登记证据窗口）` : ''),
  }
}

// ---------------------------------------------------------------- 应用（F2）

/**
 * 应用当前模式绑定的布局（「恢复默认」）。
 *
 * - **不是 snapshot restore**：不读 `workspace.snapshot.last`，不做 exePath/hwnd 身份匹配；
 * - 未绑定布局 ⇒ `no_layout`，零摆位；
 * - offline ⇒ 不发起 `layout_apply`（C3 placeWindow 的 fail-closed 同款）；
 * - core `apply_layout` 的 skip/重试/降级语义原样透出 —— 本层**不加工、不补窗口、不激活焦点**。
 */
export async function applyBoundLayout(): Promise<LayoutApplyOutcome> {
  const fail = (status: LayoutApplyStatus, detail: string): LayoutApplyOutcome => ({
    status,
    layout: null,
    placed: 0,
    skipped: 0,
    failed: 0,
    slots: [],
    detail,
  })

  let facts: WorkspaceFacts
  try {
    facts = await takeFacts()
  } catch (e) {
    return fail('offline', `事实拉取失败：${String((e as Error)?.message ?? e)}`)
  }
  if (facts.connectivity === 'offline') return fail('offline', 'core 未连接 —— 不应用布局')

  const layoutName = facts.mode.layout
  if (!layoutName) return fail('no_layout', '当前模式未绑定布局')

  try {
    const out = await layoutApi.apply(layoutName)
    const slots: LayoutSlotOutcome[] = (out.slots ?? []).map((s) => ({
      app: s.app,
      status: s.status,
      hwnd: s.hwnd ?? null,
      rect: s.rect ?? null,
      reason: s.reason ?? null,
    }))
    const placed = out.placed ?? 0
    const skipped = out.skipped ?? 0
    const failed = out.failed ?? 0
    const total = slots.length || placed + skipped + failed
    // 状态映射（如实）：全 placed=done；有失败且零摆位=failed；其余（含全 skip）=partial
    const status: LayoutApplyStatus =
      total > 0 && placed === total ? 'done' : placed === 0 && failed > 0 ? 'failed' : 'partial'
    return {
      status,
      layout: layoutName,
      placed,
      skipped,
      failed,
      slots,
      detail: `布局「${layoutName}」：摆位 ${placed}/${total}，跳过 ${skipped}，失败 ${failed}`,
    }
  } catch (e) {
    // layoutService.apply 在非 Tauri 通道失败时会把底层错误包成 NativeOnlyError ——
    // 对同源验证构建而言那就是"请求没到 core"（离线/代理断），归 offline，绝不伪成功。
    const code = (e as { code?: string })?.code ?? ''
    const isNativeOnly = (e as Error)?.name === 'NativeOnlyError'
    const offline =
      isNativeOnly || code === 'proxy_down' || code === 'network' || code === 'timeout'
    return offline
      ? fail('offline', `core 未连接 —— 应用未执行（${String((e as Error)?.message ?? e)}）`)
      : fail('failed', `布局应用失败：${String((e as Error)?.message ?? e)}`)
  }
}

export const layoutRuntime = {
  saveLayout,
  applyBoundLayout,
}
