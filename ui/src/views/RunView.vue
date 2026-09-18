<script setup lang="ts">
/**
 * RunView —— 工作模式沉浸页 UI 壳（TECH-07-C Phase C1）
 *
 * ## 原型对照（personal-workspace-ui `#/run`）
 * run-head（返回/emoji/名称/工作中徽章/布局 seg/排列 seg/时钟）
 * + 状态栏（当前任务 / 应用三态 chips / 布局 / 模式）
 * + appbar（软件标签页 + AI 标签）
 * + minimap（真实窗口投影）+ 主工作区域（窗口舞台画布）。
 *
 * ## C2 变更（Observe 接线：只换数据源，不动布局/视觉/token/动画）
 * - 数据消费 adapter 投影事实：RunWindowFacts / RunAppFacts / RunModeFacts
 *   —— core 原始结构（WindowInfo/SlotResult）与 command 名不出 adapter；
 * - 应用 chips / appbar 标签从「应用 #id」变为真实软件名 + runState 三态点
 *   （pw-dot--ok/wait/off 既有原语，零新 token）；
 * - 空态 / 未连接态如实展示（connectivity: connected/degraded/offline），
 *   不删任何 UI 区域、不伪造窗口；
 * - 拖拽 / 摆窗：仍然零（窗口矩形 pointer-events:none，无 drag 事件 → 无
 *   windows_place 路径；窗口控制属 C3）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

// 注意：必须用 `/index` 子路径——裸 `@/workspace/runtime` 会被 TS 解析到
// 同名的门面文件 runtime.ts（TECH-02 冻结域），而不是本 adapter 目录。
// 子路径写法同时保持 verify_tech02 T1c 的 `workspace/runtime` 精确匹配门禁不被误触。
// C7-B：MIN_NORM/SNAP_NORM 从 adapter 导入（单一来源），RunView 不再私有定义魔法数。
import { MIN_NORM, SNAP_NORM, workspaceAdapter } from '@/workspace/runtime/index'
import type { WorkspaceFacts } from '@/workspace/runtime/facts'
import type { PlacementResult } from '@/workspace/runtime/actions'
import type { SnapshotStatus } from '@/workspace/runtime/snapshot'
import type { LayoutApplyOutcome, LayoutSaveOutcome } from '@/workspace/runtime/layout'
import { useAiStore } from '@/stores/ai'
// 落位闪光：设计稿 `flash()` = `.just-swap`（Motion System 既有件，零新增动画）。
// 与列表排序共用同一处实现，避免"第二套闪光"。
import { flash } from '@/composables/useListSort'
// 落位过渡的时长/缓动一律走 Motion token（Skin 与 Guard 才能改档）；
// `motionMs` 读 token 的**当前计算值**，JS 等待窗口与 CSS 永远同一个数。
import { motionMs } from '@/motion'

const router = useRouter()
const ai = useAiStore()

const facts = ref<WorkspaceFacts | null>(null)
const loadError = ref('')
const clock = ref(clockText())
let timer: number | null = null

function clockText(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}

const modeName = computed(() => facts.value?.mode?.running ?? '')
const modeMeta = computed(() => {
  const name = modeName.value
  if (!name || !facts.value) return null
  return facts.value.modes.find((m) => m.name === name) ?? null
})

/** 当前模式拉起的软件投影（appbar 标签 + 状态栏 chips 的数据源，C2）。 */
const modeApps = computed(() => facts.value?.mode.apps ?? [])

/** 模式描述（投影字段；C1 走 modeMeta.description，C2 走聚合投影）。 */
const modeDesc = computed(() => facts.value?.mode.description ?? '')

/** 布局名（当前模式绑定的布局）。 */
const layoutName = computed(() => facts.value?.mode.layout ?? '')

/** 连接态：offline = 事实拉取全失败（如实"未连接"，不伪造数据）。 */
const connectivity = computed(() => facts.value?.connectivity ?? 'offline')

/** 可管理窗口总数（观察口径，来自 windows facts 本身）。 */
const windowCount = computed(() => facts.value?.windows.length ?? 0)

/** runState → 文案（设计稿 APP_STATUS 的同义表，用事实层词汇）。 */const runStateText: Record<string, string> = {
  running: '运行中',
  launching: '启动中',
  failed: '启动失败',
  skipped: '已跳过',
  unknown: '状态未知',
}

/** 主显示器工作区（minimap / 舞台投影的归一化基准）。 */
const work = computed(() => {
  const mons = facts.value?.monitors ?? []
  const primary = mons.find((m) => m.primary) ?? mons[0]
  if (!primary) return null
  return { x: primary.work_x, y: primary.work_y, w: primary.work_w, h: primary.work_h }
})

/**
 * C7-E 卡片归属证据：pid → 软件名。**只认 mode_progress.slots 的登记证据**
 * （slots 是唯一同时带 app/appId/pid 的证据链），无证据不标 —— 禁止按标题/
 * exe 猜归属（与 projection.ts 归属判据同一纪律）。
 */
const pidAppName = computed(() => {
  const m = new Map<number, string>()
  for (const s of facts.value?.progress?.slots ?? []) {
    if (typeof s.pid === 'number' && s.pid > 0) {
      const name = s.app || (s.appId !== null ? `应用 #${s.appId}` : '')
      if (name) m.set(s.pid, name)
    }
  }
  return m
})

/** 真实窗口在工作区内的归一化投影（minimap + 舞台共用一份几何；最小化不投影）。 */
const projections = computed(() => {
  const base = work.value
  const wins = facts.value?.windows ?? []
  if (!base || base.w <= 0 || base.h <= 0) return []
  return wins
    .filter((w) => w.rect && w.state !== 'minimized')
    .map((w) => {
      const r = w.rect!
      const x = Math.max(0, (r.x - base.x) / base.w)
      const y = Math.max(0, (r.y - base.y) / base.h)
      const wRatio = Math.min(1, r.w / base.w)
      const hRatio = Math.min(1, r.h / base.h)
      return {
        hwnd: w.hwnd,
        title: w.title,
        mode: w.belongsToMode,
        state: w.state,
        app: pidAppName.value.get(w.pid) ?? null,
        x,
        y,
        w: wRatio,
        h: hRatio,
      }
    })
    .filter((p) => p.x < 1 && p.y < 1 && p.w > MIN_NORM && p.h > MIN_NORM)
})

/**
 * C7-E 卡片条文案：标题（前缀，保持既有 includes 断言兼容）+ 归属证据
 * `app:<名>`（仅 slots pid 证据，无证据不标）+ 窗口状态（最大化/最小化）
 * + 只读标识（非当前模式窗口）。不引入 drawer、不猜 exe、不伪造"未知"类。
 */
function winBarText(p: {
  title: string
  mode: boolean
  app: string | null
  state: string
}): string {
  const bits: string[] = [p.title || '窗口']
  if (p.app) bits.push(`app:${p.app}`)
  if (p.state === 'maximized') bits.push('最大化')
  else if (p.state === 'minimized') bits.push('最小化')
  if (!p.mode) bits.push('只读')
  return bits.join(' · ')
}

// ================================================================ 设计稿状态投影
// 以下全部是「事实 → 设计稿类名/文案」的投影，零新事实、零 mock。

/** runState → 设计稿 `.rs-dot` 三态（运行中 / 等待打开 / 已关闭）。 */
function rsDotOf(runState: string): string {
  if (runState === 'running') return 'ok'
  if (runState === 'launching') return 'wait'
  return 'off'
}

/** 窗口状态 → 文案（事实层词汇，不新增语义）。 */
const winStateText: Record<string, string> = {
  normal: '正常',
  maximized: '最大化',
  minimized: '最小化',
}
function stateText(s: string): string {
  return winStateText[s] ?? s
}

/** 归一化几何 → 人读百分比（布局结构弹窗用；不引入物理像素换算）。 */
function geoText(p: { x: number; y: number; w: number; h: number }): string {
  return `${Math.round(p.x * 100)}%,${Math.round(p.y * 100)}% · ${Math.round(p.w * 100)}%×${Math.round(p.h * 100)}%`
}

/** 受管（可拖拽）窗口数 —— 决定 `.stage.manual`（设计稿的手柄只在手动排列态出现）。 */
const managedCount = computed(() => projections.value.filter((p) => p.mode).length)
const stageManual = computed(() => managedCount.value > 0)

/** 原型 `initStage()` 的提示条文案（离线态必须如实说"未连接"）。 */
const hintText = computed(() => {
  if (connectivity.value === 'offline') return '未连接 core —— 无法读取真实窗口（不显示任何占位窗口）'
  if (!windowCount.value) return '画布空 —— 进入一个工作模式后，这里会显示它的真实窗口投影'
  return stageManual.value
    ? `手动调整 · 拖标题栏移动，拖边缘或角落调整大小（真实窗口 ${windowCount.value} 个）`
    : `自动布局 · 拖动窗口标题栏即可手动调整（真实窗口 ${windowCount.value} 个）`
})

/**
 * appbar 标签选中（原型 `state.run.tab`）：选中哪个软件，它的窗口进入设计稿
 * `.win.sel` 态（标题栏高亮 + `.win-role` 显示"当前工作窗口"）。
 * 匹配依据是**软件名**——窗口投影只有软件名这一条归属证据（`pidAppName`），
 * 按 appId 匹配会得到一个永远选不中的标签。
 */
const activeTab = ref('')
function selectTab(name: string): void {
  activeTab.value = activeTab.value === name ? '' : name
}
function isSel(p: { app: string | null }): boolean {
  return !!activeTab.value && p.app === activeTab.value
}

/** 布局结构弹窗（原型 run-status 的 `run-struct` 按钮）：内容全部来自窗口事实。 */
const structOpen = ref(false)
/** 设计稿 minimap 色片：按软件名稳定散列到 t1..t6（同一软件恒定同色，零随机）。 */
function tintOf(name: string | null): string {
  if (!name) return 't1'
  let h = 0
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0
  return `t${(h % 6) + 1}`
}

async function refresh(): Promise<void> {
  // C3：交互（拖拽/缩放）进行中跳过轮询覆盖 —— 本地预览是用户意图，事实以 commit 后为准
  if (interaction !== null) return
  try {
    const snap = await workspaceAdapter.snapshot()
    facts.value = snap
    // C3 closure audit：core 不可达时**作废上一次摆位结果** —— 断连后继续展示
    // "✓ 已摆位"就是陈旧成功（= 假成功）；未连接态由 hint 区如实表达。
    if (snap.connectivity === 'offline') placement.value = null
    loadError.value = snap.failures.length ? `部分事实不可用：${snap.failures.join(' / ')}` : ''
  } catch (e) {
    loadError.value = String((e as Error)?.message ?? e)
  }
}

// ================================================================ C3 摆位交互
// 设计（TECH-07-C3 §6/§8/§9）：
// - pointermove 只做**本地预览**（命令式写 style，不进 Vue 响应式、不触发渲染风暴）；
// - commit 边界 = pointerup，一次交互恰好一次 windows_place（无 RPC 风暴）；
// - 坐标换算在 adapter（placeWindow）内：RunView 只产出归一化意图；
// - 成功与否都等 facts 确认（成功 → refresh 对齐事实；失败 → refresh 回滚预览 +
//   保持明确失败状态），绝不把本地几何当成"窗口已移动"。

interface Interaction {
  hwnd: number
  mode: 'move' | 'resize'
  dir: string | null
  /** 归一化起始几何 */
  start: { x: number; y: number; w: number; h: number }
  /** pointer 起点与 stage 几何（CSS px） */
  px: number
  py: number
  stage: { left: number; top: number; w: number; h: number }
  /** 预览目标元素（命令式写 style） */
  el: HTMLElement
  /** 是否真的发生过位移/缩放（设计稿 `drag.moved`：没动过就不闪，避免"点一下也闪"） */
  moved: boolean
}

let interaction: Interaction | null = null
const placement = ref<PlacementResult | null>(null)

function stageEl(): HTMLElement | null {
  return document.querySelector('[data-pw="run-stage"]')
}

// ================================================================ 过程反馈（设计稿 initStage）
// 设计稿的过程反馈**零新增动画**，全部复用既有件：
//   · `.carried`（抬起：shadow-lg + brand-300 描边 + z-index:6）—— 被拖的那个窗口
//   · `.carrying`（其余退后：`.stage.carrying .win:not(.carried){opacity:.72}`）
//   · `.win-size`（缩放中的 W×H HUD，右上角 mono 角标；松手加 `.out` 淡出后移除）
//   · `.just-swap`（落位闪光，`--mt-dur-highlight`）
// 工程差异：设计稿在 mousedown 起手就写 HUD（`hudOf(win).textContent = ...`），
// 本工程同样在起手写一次 —— 这样"按下即见尺寸"，符合需求「按下与释放反馈」。

/** 取（或建）该窗口的尺寸 HUD，并确保它不处于淡出态。 */
function hudOf(win: HTMLElement): HTMLElement {
  let hud = win.querySelector<HTMLElement>('.win-size')
  if (!hud) {
    hud = document.createElement('div')
    hud.className = 'win-size'
    win.appendChild(hud)
  }
  hud.classList.remove('out')
  return hud
}

/** 松手/取消：HUD 淡出后移除（设计稿 `out` 后 220ms remove）。 */
function hideHud(win: HTMLElement): void {
  const hud = win.querySelector<HTMLElement>('.win-size')
  if (!hud) return
  hud.classList.add('out')
  window.setTimeout(() => hud.remove(), 220)
}

/** 元素当前像素尺寸（HUD 文案来源，与设计稿 `Math.round(wr.width)` 同口径）。 */
function pxSize(el: HTMLElement): { w: number; h: number } {
  const r = el.getBoundingClientRect()
  return { w: Math.round(r.width), h: Math.round(r.height) }
}

/**
 * 起手反馈：抬起 + 其余退后（拖拽与缩放**共用**同一套，设计稿注释
 * 「过程反馈与拖动统一」）。缩放态额外亮出尺寸 HUD。
 */
function markCarrying(el: HTMLElement, mode: 'move' | 'resize'): void {
  el.classList.add('carried')
  stageEl()?.classList.add('carrying')
  if (mode === 'resize') {
    const s = pxSize(el)
    hudOf(el).textContent = `${s.w} × ${s.h}`
  }
}

/**
 * 落手反馈：撤掉抬起态（含 id 幂等），有真实位移才闪一次。
 * 顺序有意「先撤 carried 再 flash」：flash 走的是 `.just-swap` 的 animation，
 * 与 `.carried` 的 box-shadow 不冲突；先撤可让描边从 brand-300 回到常态再闪光。
 */
function markDropped(el: HTMLElement, moved: boolean): void {
  el.classList.remove('carried')
  stageEl()?.classList.remove('carrying')
  hideHud(el)
  if (moved) flash(el)
}

// ---------------------------------------------------------------- 落位对齐过渡
// 需求「落位对齐或惯性过渡」的实现点：拖动**过程中**几何必须 1:1 跟手
// （设计稿红线「拖动过程从未被干预」），所以过渡不能常驻 —— 只有落位收口的那一小段
// 允许缓动：预览几何 → adapter 夹紧/吸附后的合法几何（或失败/取消时写回起始几何）。
// 采取"限时开启"而不是改 .win 的 CSS：常驻 transition 会让跟手带延迟；
// 限时窗口结束后立刻清掉，下一次拖拽仍是 1:1。
const WINDOW_SETTLE_FALLBACK = 240

let settlingEl: HTMLElement | null = null
let settleTimer: number | null = null

/** 关掉落位过渡窗口（幂等）：几何四条边的 transition 清空，恢复 1:1 跟手。 */
function clearSettle(): void {
  if (settleTimer !== null) {
    window.clearTimeout(settleTimer)
    settleTimer = null
  }
  if (settlingEl) {
    settlingEl.style.transition = ''
    settlingEl = null
  }
}

/**
 * 开启落位过渡窗口：`left/top/width/height` 挂上 `--mt-dur-window` +
 * `--mt-ease-emphasis`（= 设计稿 winIn 同一条强调曲线，零新增时长事实）。
 * off 档无需判档：`[data-motion='off'] *` 的 `transition-duration:0ms !important`
 * 会把它归零，档位唯一来源仍是 Motion Guard。
 */
function settleGeometry(el: HTMLElement): void {
  clearSettle()
  const e = 'var(--mt-dur-window) var(--mt-ease-emphasis)'
  // 必须**照抄**设计稿 `.win` 原有的 box-shadow/border-color/opacity 三条
  // —— inline transition 是整条覆盖而不是追加，漏掉它们会把 `.carried` 抬起/落下的
  // 阴影渐变变成瞬变（"改了动画反而更硬"是这类覆盖最常见的翻车点）。
  const base = 'var(--dur-fast) var(--ease-out)'
  el.style.transition =
    `left ${e}, top ${e}, width ${e}, height ${e},` +
    ` box-shadow ${base}, border-color ${base}, opacity ${base}`
  settlingEl = el
  settleTimer = window.setTimeout(clearSettle, motionMs('--mt-dur-window', WINDOW_SETTLE_FALLBACK) + 60)
}

function beginInteraction(
  ev: PointerEvent,
  hwnd: number,
  mode: 'move' | 'resize',
  dir: string | null,
): void {
  const el = (ev.currentTarget as HTMLElement).closest<HTMLElement>('.run-win')
  const st = stageEl()
  if (!el || !st) return
  const p = projections.value.find((q) => q.hwnd === hwnd)
  if (!p) return
  // 上一次交互若异常残留（没收到 up/cancel），先清理再开始，避免状态叠加
  cancelInteraction()
  const r = st.getBoundingClientRect()
  interaction = {
    hwnd,
    mode,
    dir,
    start: { x: p.x, y: p.y, w: p.w, h: p.h },
    px: ev.clientX,
    py: ev.clientY,
    stage: { left: r.left, top: r.top, w: r.width, h: r.height },
    el,
    moved: false,
  }
  // 起手视觉：抬起 + 其余退后（缩放态另出尺寸 HUD）。光标与设计稿一致
  // （`move` → grabbing；`resize` → 方向光标由 `.rz-*` 的 CSS 给，不重复声明）。
  // 先关掉落位过渡窗口：上一次落位可能还在缓动中，不清掉这次拖拽的第一帧就会「慢半拍」。
  clearSettle()
  markCarrying(el, mode)
  if (mode === 'move') document.body.style.cursor = 'grabbing'
  // 指针捕获只是跟手增强（指针离开元素也能收 move）；对合成/已释放的 pointerId
  // 会抛 NotFoundError —— 捕获失败不能拖死整条交互链（move/up 监听在后面必须挂上）。
  try {
    el.setPointerCapture(ev.pointerId)
  } catch {
    /* 无活动指针（合成事件 / 已释放）——window 级监听仍可完成拖拽 */
  }
  window.addEventListener('pointermove', onInteractMove)
  window.addEventListener('pointerup', commitInteraction)
  // 异常路径（系统取消手势 / 指针捕获丢失）：只清理、不提交，绝不发起摆位
  window.addEventListener('pointercancel', cancelInteraction)
  window.addEventListener('lostpointercapture', cancelInteraction)
  // C7-C Esc 链：交互进行中按 Esc = 用户撤销，与 pointercancel 同一取消语义
  window.addEventListener('keydown', onInteractKey)
}

/**
 * C7-C Esc 取消：交互进行中按 Escape → cancelInteraction（不调用 windows_place、
 * 不产生任何 core 请求、不修改事实层，预览写回起始几何）。仅交互存在时消费该按键。
 */
function onInteractKey(ev: KeyboardEvent): void {
  if (!interaction || ev.key !== 'Escape') return
  ev.preventDefault()
  cancelInteraction()
}

function startDrag(ev: PointerEvent, hwnd: number): void {
  beginInteraction(ev, hwnd, 'move', null)
}

function startResize(ev: PointerEvent, hwnd: number, dir: string): void {
  ev.stopPropagation()
  beginInteraction(ev, hwnd, 'resize', dir)
}

/** 写几何到投影元素（命令式，预览与回滚共用同一处写入）。 */
function writeGeometry(
  el: HTMLElement,
  g: { x: number; y: number; w: number; h: number },
): void {
  el.style.left = `${(g.x * 100).toFixed(2)}%`
  el.style.top = `${(g.y * 100).toFixed(2)}%`
  el.style.width = `${(g.w * 100).toFixed(2)}%`
  el.style.height = `${(g.h * 100).toFixed(2)}%`
}

/** 移除全部交互监听（move/up/cancel/capture-lost/keydown，与 begin 对称）。 */
function detachInteraction(): void {
  window.removeEventListener('pointermove', onInteractMove)
  window.removeEventListener('pointerup', commitInteraction)
  window.removeEventListener('pointercancel', cancelInteraction)
  window.removeEventListener('lostpointercapture', cancelInteraction)
  window.removeEventListener('keydown', onInteractKey)
}

/** 预览几何计算：pointer delta（CSS px）→ 归一化 delta → 应用于起始几何。 */
const lastMove = { x: 0, y: 0 }

function previewGeometry(it: Interaction): { x: number; y: number; w: number; h: number } {
  const dx = (lastMove.x - it.px) / it.stage.w
  const dy = (lastMove.y - it.py) / it.stage.h
  const s = it.start
  let { x, y, w, h } = s
  if (it.mode === 'move') {
    x = s.x + dx
    y = s.y + dy
  } else {
    const d = it.dir ?? ''
    if (d.includes('e')) w = Math.max(MIN_NORM, s.w + dx)
    if (d.includes('s')) h = Math.max(MIN_NORM, s.h + dy)
    if (d.includes('w')) {
      w = Math.max(MIN_NORM, s.w - dx)
      x = s.x + (s.w - w)
    }
    if (d.includes('n')) {
      h = Math.max(MIN_NORM, s.h - dy)
      y = s.y + (s.h - h)
    }
  }
  // C7-A 预览侧同口径收口（C5-06）：w/h 与 x/y 联合约束 —— 预览不再展示 x+w>1
  // 的越界形态；commit 端 adapter placeWindow 已做同规则联合校验（两端一致）。
  w = Math.min(Math.max(w, MIN_NORM), 1)
  h = Math.min(Math.max(h, MIN_NORM), 1)
  x = Math.min(Math.max(x, 0), 1 - w)
  y = Math.min(Math.max(y, 0), 1 - h)
  // C7-D 吸附：仅作用于本预览层（贴近工作区四缘 ≤ SNAP_NORM 时吸上去）。
  // commit 语义不变：仍单次 windows_place，adapter 收到的是吸附后的合法意图，
  // 不新增任何 core 请求、不改 facts。
  if (Math.abs(x) <= SNAP_NORM) x = 0
  else if (Math.abs(x + w - 1) <= SNAP_NORM) x = 1 - w
  if (Math.abs(y) <= SNAP_NORM) y = 0
  else if (Math.abs(y + h - 1) <= SNAP_NORM) y = 1 - h
  return { x, y, w, h }
}

function onInteractMove(ev: PointerEvent): void {
  const it = interaction
  if (!it) return
  lastMove.x = ev.clientX
  lastMove.y = ev.clientY
  const g = previewGeometry(it)
  if (!g) return
  // 命令式预览（跟手），不经过 Vue 响应式 —— 每帧只有 style 写入
  writeGeometry(it.el, g)
  // 有真实「帧」就算动过（设计稿 `drag.moved = true`）——决定松手是否闪一次。
  // 注意：纯按下不动时也会收到 0 位移的 pointermove，故用位移阈值而不是"收到 move"作判据。
  if (Math.abs(lastMove.x - it.px) > 2 || Math.abs(lastMove.y - it.py) > 2) it.moved = true
  // 尺寸 HUD：由归一化几何 × 舞台像素算出，**不读 getBoundingClientRect**
  // ——写 style 之后再读 rect 会强制同步布局，60fps 下代价明显（设计稿同口径）。
  if (it.mode === 'resize') {
    const w = Math.round(g.w * it.stage.w)
    const h = Math.round(g.h * it.stage.h)
    const hud = it.el.querySelector<HTMLElement>('.win-size')
    if (hud) hud.textContent = `${w} × ${h}`
  }
}

/**
 * 交互取消（pointercancel / lostpointercapture）：清理状态 + 监听，
 * **不发起任何摆位**（取消 ≠ 用户确认），预览写回起始几何。
 */
function cancelInteraction(): void {
  const it = interaction
  interaction = null
  detachInteraction()
  if (!it) return
  document.body.style.cursor = ''
  // 取消（Esc / 系统手势）：预览写回起始几何 —— 撤回不闪（没有任何"落位"发生）
  markDropped(it.el, false)
  // 写回起始几何走落位过渡：视觉上是"滑回去"而不是"跳回去"，与落位同一条曲线
  settleGeometry(it.el)
  writeGeometry(it.el, it.start)
}

async function commitInteraction(): Promise<void> {
  const it = interaction
  interaction = null
  detachInteraction()
  if (!it) return
  const g = previewGeometry(it)
  it.el.style.zIndex = ''
  document.body.style.cursor = ''
  // 落手反馈：抬起态撤掉 + 其余窗口恢复 + 尺寸 HUD 淡出（有真实位移才闪）。
  // 刻意放在 **await 之前**：反馈要跟"松手"这个动作同时发生，不能等 core 回话
  // （IPC 往返可能几十毫秒，滞后就变成"松手后延迟闪"）。
  markDropped(it.el, it.moved)
  if (!g) return
  // 落位过渡窗口：下面写回的几何（夹紧/吸附/失败回写）会滑过去而不是跳过去。
  // 成功且几何与预览一致时这段过渡不产生任何可见变化（值没变就没有过渡）。
  settleGeometry(it.el)
  const work = workAreaPx()
  if (!work) {
    placement.value = { status: 'failed', hwnd: it.hwnd, message: '主显示器工作区不可用' }
    writeGeometry(it.el, it.start)
    await refresh()
    return
  }
  // 归一化意图 → adapter（段位/归属校验 + 物理像素换算 + windows_place）
  const result = await workspaceAdapter.actions.placeWindow(
    { hwnd: it.hwnd, x: g.x, y: g.y, w: g.w, h: g.h },
    work,
  )
  placement.value = result
  // 事实确认：成功 → 等 facts 对齐真实几何；非 placed → 预览只是本地意图，
  // 必须写回起始几何（Vue :style 绑定值未变时不会重绘，否则"请求几何"会
  // 滞留成"已确认几何"）—— 绝不以本地几何为准。
  if (result.status !== 'placed') writeGeometry(it.el, it.start)
  // ⚠️ Vue `:style` 绑定只覆盖 left/top/width/height（不碰 transition），
  // 因此上面这段过渡不会因为 refresh 触发重渲染而被打断；过渡窗口结束后
  // `clearSettle()` 清空 inline transition，几何仍是 Vue 绑定值。
  await refresh()
}

/** 主显示器工作区（物理像素，adapter 坐标换算的输入）。 */
function workAreaPx(): { x: number; y: number; w: number; h: number } | null {
  const mons = facts.value?.monitors ?? []
  const primary = mons.find((m) => m.primary) ?? mons[0]
  if (!primary) return null
  return { x: primary.work_x, y: primary.work_y, w: primary.work_w, h: primary.work_h }
}

// ================================================================ C5 布局（最小暴露）
// 「保存布局」= 受管窗口排布 → db_layout_upsert（模板语义，slot 只存 apps.name + 归一化 rect）；
// 「恢复默认」= 模式绑定布局 → layout_apply（core skip 语义原样透出：未运行跳过、不自动启动、
// 不激活焦点）。与 C4 快照双轨并存：本组入口不读写 workspace.snapshot.last。
// 视觉零新增：复用 pw-btn/pw-chip，无新 token / 动画 / 硬编码色。
const layoutBusy = ref(false)
const layoutChip = ref('')
const layoutDetail = ref('')

// ---- 准备工作空间浮层（原型 `fn:runPrepSequence`：.run-prep/.rp-steps/.rp-step/.spinner）----
//
// ⚠️ 红线差异（C1/C6 不产生伪事实）：原型是 `340ms × 3` 定时器驱动的**演示**序列 ——
// 勾是"时间到了"打上去的，跟有没有真的准备好无关。本工程反过来：**每一步的勾只认
// 真实操作的完成信号**，没跑完就不打勾、没跑这个流程就不显示浮层。
// 三步对应的真实操作：
//   ① 恢复应用 → `refresh()` 拉取应用/窗口事实（不自动启动软件，见 layout.apply 的 skip 语义）
//   ② 恢复布局 → `layout.apply()` 真实应用模式绑定布局
//   ③ 同步状态 → 再 `refresh()` 按 facts 复核（成功与否都以事实为准）
const PREP_STEPS = ['恢复应用', '恢复布局', '同步状态'] as const
const prepOpen = ref(false)
const prepDone = ref<boolean[]>([false, false, false])

async function runPrepSequence(phases: Array<() => Promise<void>>): Promise<void> {
  prepDone.value = phases.map(() => false)
  prepOpen.value = true
  try {
    for (let i = 0; i < phases.length; i++) {
      await phases[i]()
      prepDone.value[i] = true
    }
  } finally {
    prepOpen.value = false
  }
}

async function onLayoutSave(): Promise<void> {
  if (layoutBusy.value) return
  layoutBusy.value = true
  layoutChip.value = ''
  layoutDetail.value = ''
  try {
    const out: LayoutSaveOutcome = await workspaceAdapter.layout.save(modeName.value || '')
    if (out.status === 'saved') {
      layoutChip.value = `✓ 布局已保存 · ${out.name ?? ''}`
      layoutDetail.value = out.detail
    } else {
      layoutChip.value = '✕ 保存失败'
      layoutDetail.value = out.detail
    }
  } catch (e) {
    layoutChip.value = '✕ 保存失败'
    layoutDetail.value = String((e as Error)?.message ?? e)
  } finally {
    layoutBusy.value = false
    void refresh()
  }
}

async function onLayoutApply(): Promise<void> {
  if (layoutBusy.value) return
  layoutBusy.value = true
  layoutChip.value = ''
  layoutDetail.value = ''
  // 已判定未连接 → 立刻如实回复，**不进** `runPrepSequence`。
  //
  // 为什么（实测，不是推测）：那三步里前后各一次 `refresh()`，而 core 停止后每个 HTTP 请求
  // 都要跑满客户端的 5s 超时（`api/client.ts` 的 `timeoutMs`），整段 ≈ 2~3 个超时窗口。
  // 用户点完「恢复默认」要盯着 20s+ 的空 chip（外加挂着的 prep 覆盖层）才知道结果，
  // 验收的 25s 观察窗也正好擦边 → 同一个脚本时绿时红。
  // 这一步不新增任何判断口径：用的就是页面已有的轮询事实 `connectivity`，
  // 文案沿用 `placementText.offline`（同一句"core 未连接"，不另造第二份措辞）。
  if (connectivity.value === 'offline') {
    layoutChip.value = '✕ 未连接 —— 应用未执行'
    layoutDetail.value = placementText.offline
    layoutBusy.value = false
    return
  }
  let out: LayoutApplyOutcome | null = null
  try {
    // 三步都走真实操作（顺序/含义见 `runPrepSequence` 处注释）：不复制原型的定时器序列
    await runPrepSequence([
      async () => {
        await refresh()
      },
      async () => {
        out = await workspaceAdapter.layout.apply()
      },
      async () => {
        await refresh()
      },
    ])
    // 闭包里赋值 ⇒ TS 的 CFA 会把它判成 `null`；显式收窄一次，别让类型系统误报
    const applied = out as LayoutApplyOutcome | null
    if (!applied) {
      layoutChip.value = '✕ 应用失败'
      layoutDetail.value = '布局应用未返回结果'
      return
    }
    const total = applied.placed + applied.skipped + applied.failed
    switch (applied.status) {
      case 'done':
        layoutChip.value = `✓ 布局已应用 ${applied.placed} 个窗口`
        break
      case 'partial': {
        const skips = applied.slots
          .filter((s) => s.status.startsWith('skipped'))
          .map((s) => `${s.app}:${s.status === 'skipped_not_running' ? '未运行' : '无窗口'}`)
        layoutChip.value = `◐ 布局部分应用 ${applied.placed}/${total} · 跳过 ${applied.skipped}${
          skips.length ? `（${skips.join('、')}）` : ''
        }`
        break
      }
      case 'offline':
        layoutChip.value = '✕ 未连接 —— 应用未执行'
        break
      case 'no_layout':
        layoutChip.value = '未绑定布局'
        break
      default:
        layoutChip.value = '✕ 应用失败'
    }
    layoutDetail.value = applied.detail
  } catch (e) {
    layoutChip.value = '✕ 应用失败'
    layoutDetail.value = String((e as Error)?.message ?? e)
  } finally {
    layoutBusy.value = false
    void refresh()
  }
}

// ================================================================ C4 快照（最小暴露）
// 只做状态投影：两个既有按钮 + 一个既有 chip；结果文案如实映射 adapter 的
// 状态与 skip 原因（不把失败压成一句"恢复失败"）。视觉零新增（复用 pw-btn/pw-chip）。
const snapBusy = ref(false)
const snapStatus = ref<SnapshotStatus | null>(null)
const snapResult = ref('')

const snapshotText = computed(() => {
  const r = snapResult.value
  if (r) return r
  const s = snapStatus.value
  if (!s) return '快照：未知'
  if (!s.has) return '快照：无'
  if (!s.valid) return '快照：已损坏（保留原值）'
  return `快照：${s.managed} 个窗口 · ${s.sameRun ? '同一运行期' : '跨重启'}`
})

async function refreshSnapStatus(): Promise<void> {
  try {
    snapStatus.value = await workspaceAdapter.windowSnapshot.status()
  } catch {
    snapStatus.value = null
  }
}

async function onSnapshotSave(): Promise<void> {
  snapBusy.value = true
  snapResult.value = ''
  try {
    const out = await workspaceAdapter.windowSnapshot.capture()
    snapResult.value =
      out.status === 'saved'
        ? `快照：已保存 ${out.managed} 个窗口`
        : `快照：未保存（${out.status}）`
    await refreshSnapStatus()
  } catch (e) {
    snapResult.value = `快照：保存失败（${String((e as Error)?.message ?? e)}）`
  } finally {
    snapBusy.value = false
    void refresh()
  }
}

async function onSnapshotRestore(): Promise<void> {
  snapBusy.value = true
  snapResult.value = ''
  try {
    const out = await workspaceAdapter.windowSnapshot.restore()
    const detail = out.skipped.length
      ? ` · 跳过 ${out.skipped.length}：${out.skipped.map((s) => s.reason).join('/')}`
      : ''
    // 如实暴露匹配层（同运行期走 hwnd+pid；跨重启走 exePath 唯一候选）—— 不把"换了匹配依据"藏起来
    const layer =
      out.layer === 'same-run' ? '同运行期' : out.layer === 'cross-restart' ? '跨重启' : '未执行'
    snapResult.value = `快照：已恢复 ${out.restored.length} 个窗口（${layer}）${detail}`
    await refreshSnapStatus()
  } catch (e) {
    snapResult.value = `快照：恢复失败（${String((e as Error)?.message ?? e)}）`
  } finally {
    snapBusy.value = false
    void refresh()
  }
}

const placementText: Record<string, string> = {
  placed: '✓ 已摆位（等 facts 确认）',
  unbound: '未绑定当前工作模式 —— 拒绝摆位',
  offline: 'core 未连接 —— 摆位未执行',
  failed: '摆位失败',
}

/** C3 缩放方向（8 向）。左/上侧缩放在 previewGeometry 中同步移动 left/top。 */
const dirs = ['n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw'] as const

function openAi(): void {
  // AI 侧栏入口（原型：appbar 的 AI 标签 = dock 开关）。走既有 store 动作。
  if (ai.collapsed) ai.toggleCollapsed()
}

onMounted(() => {
  void refresh()
  void refreshSnapStatus()
  timer = window.setInterval(() => {
    clock.value = clockText()
    void refresh()
  }, 2000)
})
onBeforeUnmount(() => {
  if (timer !== null) window.clearInterval(timer)
  // 用 cancelInteraction 而不是裸 detachInteraction：它同时清掉拖拽的**视觉残留**
  // （.carried/.carrying 类、尺寸 HUD）与 `document.body` 上的 grabbing 光标 ——
  // 组件在拖拽中途被卸载时，裸 detach 会把 grabbing 光标永久留在整个应用上。
  cancelInteraction()
  clearSettle()
})
</script>

<template>
  <!-- 原型 `ROUTES.run`（`personal-workspace-ui` line 2794–2833）DOM 逐字对应：
       run-head → run-status → appbar → stage（+ ai-fab）。
       双类名：设计类（.run-head/.run-status/.appbar/.stage/.stage-grid/.win/.win-bar/
       .win-body/.win-role/.win-handle/.rz/.stage-hint/.ai-fab/.badge-emoji/.live/.seg/
       .minimap）承载几何（唯一来源 = base.css UI-FUSION-FULL 段）；工程钩子类
       （run-*）与 `data-pw` 供冻结验收脚本定位。
       图标按设计稿 `ico()` 的 24×24 path 内联（A6d 禁止 RunView import 组件）。 -->
  <div class="run-wrap" style="display:flex;flex-direction:column;height:100%;min-height:0">
    <!-- ===== run-head：返回 / 徽章 / 名称 / 工作中 / 布局 seg / 排列 seg / 恢复默认 / 保存布局 / 时钟 ===== -->
    <header class="run-head" data-pw="run-head">
      <button class="icon-btn lg" data-pw="run-back" title="返回" @click="router.back()">
        <svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19.6 12h-15M10.6 18l-6-6 6-6" /></svg>
      </button>
      <span v-if="modeMeta?.icon" class="badge-emoji" style="width:30px;height:30px;font-size:16px">{{ modeMeta.icon }}</span>
      <span class="nm">{{ modeName || '工作模式' }}</span>
      <span v-if="modeName" class="live" data-pw="run-live"><span class="dot"></span>工作中</span>
      <span v-else class="chip chip--outline" data-pw="run-live">未在模式中</span>
      <div class="spacer"></div>
      <!-- 布局 / 排列 seg：窗口控制尚未放开（C1 纪律：不提供假交互），样式与设计稿一致 -->
      <div class="seg" role="group" aria-label="布局模式" data-pw="run-layout-seg">
        <button class="on" disabled title="自由布局（窗口布局控制未放开）">自由</button>
        <button disabled title="自动整理（窗口布局控制未放开）">自动整理</button>
        <button disabled title="聚焦布局（窗口布局控制未放开）">聚焦</button>
      </div>
      <div class="seg" role="group" aria-label="排列模式" data-pw="run-arrange-seg">
        <button :class="{ on: !stageManual }" disabled title="自动排列（窗口布局控制未放开）">自动排列</button>
        <button :class="{ on: stageManual }" disabled title="手动调整（窗口布局控制未放开）">手动调整</button>
      </div>
      <button
        class="btn btn--ghost"
        data-pw="run-layout-apply"
        :disabled="layoutBusy"
        title="应用当前模式绑定的布局（未运行的软件跳过，不自动启动）"
        @click="onLayoutApply()"
      >恢复默认</button>
      <button
        class="btn btn--secondary"
        data-pw="run-layout-save"
        :disabled="layoutBusy"
        title="把当前受管窗口排布保存为布局（run-<模式名>-<时间戳>）"
        @click="onLayoutSave()"
      >保存布局</button>
      <span class="t-cap num" data-pw="run-clock" style="margin-left:var(--space-2)">{{ clock }}</span>
    </header>

    <!-- ===== run-status：当前任务 / 应用三态 / 布局 / 模式 + 右侧工程 chips ===== -->
    <div class="run-status" data-pw="run-status">
      <span class="rs-item">
        <span class="rs-k">当前任务</span>
        <span class="chip chip--brand" style="height:24px" data-pw="run-goal">
          <svg class="ico" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="8.4" /><circle cx="12" cy="12" r="4.4" /><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" /></svg>
          {{ modeDesc || '未设置工作目标' }}
        </span>
      </span>
      <span class="rs-item rs-apps">
        <span class="rs-k">应用</span>
        <template v-if="modeApps.length">
          <span
            v-for="a in modeApps"
            :key="a.appId ?? a.name"
            class="chip rs-app"
            data-pw="run-app-chip"
            :title="runStateText[a.runState] ?? a.runState"
          >
            <i class="rs-dot" :class="rsDotOf(a.runState)"></i>{{ a.name }}<span class="rs-st">{{ runStateText[a.runState] ?? a.runState }}</span>
            <span v-if="a.windowCount > 0" class="run-chip__count">×{{ a.windowCount }}</span>
          </span>
        </template>
        <span v-else class="chip chip--outline" style="height:24px">还没有应用在运行</span>
      </span>
      <span class="rs-item">
        <span class="rs-k">布局</span>
        <span class="chip" style="height:24px" data-pw="run-layout-name-chip">{{ layoutName || '未绑定' }}</span>
      </span>
      <span class="rs-item">
        <span class="rs-k">模式</span>
        <span class="chip" style="height:24px" data-pw="run-mode-chip">{{ modeName || '自定义' }}</span>
      </span>
      <span class="grow" style="flex:1"></span>
      <!-- 布局结构（设计稿 run-struct）：内容全部来自窗口事实 -->
      <button class="btn btn--ghost btn--sm" data-pw="run-struct" title="查看当前窗口关系" @click="structOpen = true">
        <svg class="ico" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.6 6.6h3.4M3.6 12h3.4M3.6 17.4h3.4M10 6.6h10.4M10 12h10.4M10 17.4h10.4" /></svg>
        布局结构
      </button>
      <!-- C5 布局结果（保存/应用共用一个 chip；detail 走 title，不压扁失败原因） -->
      <span v-if="layoutChip" class="chip" data-pw="run-layout-chip" :title="layoutDetail">{{ layoutChip }}</span>
      <!-- C4 快照（最小暴露：复用既有 btn / chip，零新视觉语言） -->
      <span class="chip" data-pw="run-snap-chip">{{ snapshotText }}</span>
      <button class="btn btn--ghost btn--sm" data-pw="run-snap-save" :disabled="snapBusy" @click="onSnapshotSave()">保存当前状态</button>
      <button class="btn btn--ghost btn--sm" data-pw="run-snap-restore" :disabled="snapBusy" @click="onSnapshotRestore()">恢复上次状态</button>
      <!-- C3 摆位结果（§9 失败语义：placed/unbound/offline/failed，绝不假装成功） -->
      <span v-if="placement" class="chip" data-pw="run-placement" :title="placement.message ?? ''">
        <i class="rs-dot" :class="placement.status === 'placed' ? 'ok' : 'off'"></i>{{ placementText[placement.status] ?? placement.status }}
      </span>
      <span v-if="loadError" class="run-status__warn" data-pw="run-degraded" :title="loadError">{{ loadError }}</span>
    </div>

    <!-- ===== appbar：软件标签页 + AI 入口（设计稿在 stage 之上，不是页脚） ===== -->
    <div class="appbar" data-pw="run-appbar">
      <template v-if="modeApps.length">
        <button
          v-for="a in modeApps"
          :key="a.appId ?? a.name"
          class="apptab"
          :class="{ on: activeTab === a.name }"
          data-pw="run-app-tab"
          :title="`${runStateText[a.runState] ?? a.runState} · 点击高亮该软件的窗口`"
          @click="selectTab(a.name)"
        >
          <i class="rs-dot" :class="rsDotOf(a.runState)"></i><span>{{ a.name }}</span>
        </button>
      </template>
      <span v-else class="apptab" style="opacity:.5;pointer-events:none" data-pw="run-app-tab">软件标签页</span>
      <button class="apptab" :class="{ on: !ai.collapsed }" data-pw="run-ai-tab" title="AI 助手" @click="openAi()">
        <svg class="ico" viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 3.4 12.6 8 17.4 9.6 12.6 11.2 11 16 9.4 11.2 4.6 9.6 9.4 8z" /><path d="M18 14.4l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z" /></svg>
        <span>AI</span>
      </button>
      <div class="spacer"></div>
      <button class="icon-btn sm" disabled title="添加应用到本次会话（未放开）">
        <svg class="ico" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5.2v13.6M5.2 12h13.6" /></svg>
      </button>
    </div>

    <!-- ===== stage：窗口舞台（真实窗口投影；归属当前模式的窗口可拖拽/缩放 → windows_place） ===== -->
    <div class="stage" :class="{ manual: stageManual }" data-pw="run-stage">
      <div class="stage-grid">
        <div
          v-for="p in projections"
          :key="p.hwnd"
          class="win run-win"
          :class="{ 'is-managed': p.mode, sel: isSel(p) }"
          :style="{ left: `${(p.x * 100).toFixed(2)}%`, top: `${(p.y * 100).toFixed(2)}%`, width: `${(p.w * 100).toFixed(2)}%`, height: `${(p.h * 100).toFixed(2)}%` }"
          :title="p.mode ? `${p.title} · 当前模式（可拖拽/缩放）` : `${p.title} · 非当前模式窗口（只读）`"
        >
          <!-- 双类名：`win-bar` 给设计稿几何（含 `cursor:grab`），`run-win__bar` 是冻结脚本钩子；
               `is-grab` 同时是设计稿语义与 TECH-07-C3 D6 的"归属窗口可拖"判据。 -->
          <div
            class="win-bar run-win__bar"
            :class="{ 'is-grab': p.mode }"
            @pointerdown="p.mode && startDrag($event, p.hwnd)"
          >
            <span class="nm">{{ winBarText(p) }}</span>
            <span class="win-role"></span>
            <span class="grip">
              <svg class="ico" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="6.6" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="6.6" r="1.3" fill="currentColor" stroke="none" /><circle cx="9" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="9" cy="17.4" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="17.4" r="1.3" fill="currentColor" stroke="none" /></svg>
            </span>
          </div>
          <!-- 原型 `.win-body` 内是 mock 文案；本工程放**真实**窗口事实（标题/软件/状态/几何） -->
          <div class="win-body">
            <div class="wb-row"><span class="wb-k">窗口</span><span class="wb-v">{{ p.title || '未命名窗口' }}</span></div>
            <div class="wb-row"><span class="wb-k">软件</span><span class="wb-v">{{ p.app || '未登记归属' }}</span></div>
            <div class="wb-row"><span class="wb-k">状态</span><span class="wb-v">{{ stateText(p.state) }}</span></div>
            <div class="wb-row"><span class="wb-k">几何</span><span class="wb-v">{{ geoText(p) }}</span></div>
          </div>
          <!-- C3 缩放手势：8 向热区（只对归属窗口渲染）；左/上侧缩放会同步移动 left/top。
               双类名：`rz rz-<dir>` 是设计稿几何的来源，`run-win__rz*` 是冻结验收脚本的定位钩子
               （TECH-07-C3 D5/D6 用 `.run-win__rz--se` / `.run-win__rz` 取元素）—— 缺一不可。 -->
          <template v-if="p.mode">
            <span
              v-for="d in dirs"
              :key="d"
              class="rz run-win__rz"
              :class="[`rz-${d}`, `run-win__rz--${d}`]"
              :title="`缩放 · ${d}`"
              @pointerdown="startResize($event, p.hwnd, d)"
            ></span>
          </template>
          <div class="win-handle">
            <svg class="ico" viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="9" cy="6.6" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="6.6" r="1.3" fill="currentColor" stroke="none" /><circle cx="9" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="12" r="1.3" fill="currentColor" stroke="none" /><circle cx="9" cy="17.4" r="1.3" fill="currentColor" stroke="none" /><circle cx="15" cy="17.4" r="1.3" fill="currentColor" stroke="none" /></svg>
          </div>
        </div>
      </div>

      <p class="stage-hint run-stage__hint">
        <svg class="ico" viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3.6v16.8M3.6 12h16.8M12 3.6 9.6 6M12 3.6 14.4 6M12 20.4 9.6 18M12 20.4l2.4-2.4M3.6 12 6 9.6M3.6 12 6 14.4M20.4 12 18 9.6M20.4 12 18 14.4" /></svg>
        <span>{{ hintText }}</span>
      </p>

      <!-- 窗口排布缩略图（设计稿 `.minimap` 语言 + `<i class="t*">` 色片；工程侧新增的常驻件，见文件头） -->
      <div class="minimap run-minimap" data-pw="run-minimap" aria-label="窗口排布缩略图">
        <i
          v-for="p in projections"
          :key="p.hwnd"
          :class="tintOf(p.app)"
          :style="{ left: `${(p.x * 100).toFixed(2)}%`, top: `${(p.y * 100).toFixed(2)}%`, width: `${(p.w * 100).toFixed(2)}%`, height: `${(p.h * 100).toFixed(2)}%` }"
        ></i>
      </div>

      <!-- 设计稿 `.ai-fab`：AI 侧栏收起时的沉浸态入口 -->
      <button v-if="ai.collapsed" class="ai-fab" data-pw="run-ai-fab" @click="openAi()">
        <svg class="ico" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 3.4 12.6 8 17.4 9.6 12.6 11.2 11 16 9.4 11.2 4.6 9.6 9.4 8z" /><path d="M18 14.4l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z" /></svg>
        AI 助手
      </button>
    </div>

    <!-- ===== 布局结构弹窗（设计稿 run-struct）：真实窗口关系，无 mock ===== -->
    <template v-if="structOpen">
      <div class="scrim" data-pw="run-struct-scrim" @click="structOpen = false"></div>
      <div class="modal" role="dialog" aria-label="当前窗口关系" data-pw="run-struct-modal">
        <div class="modal-head">
          <div class="t-card">当前窗口关系</div>
          <div class="t-cap" style="margin-top:4px">
            {{
              connectivity === 'offline'
                ? '未连接 core —— 无窗口事实'
                : `真实窗口 ${windowCount} 个 · 受管 ${managedCount} 个 · 模式 ${modeName || '自定义'}`
            }}
          </div>
        </div>
        <div class="modal-body">
          <div v-for="p in projections" :key="p.hwnd" class="struct-row">
            <i class="rs-dot" :class="p.mode ? 'ok' : 'off'"></i>
            <span class="t-card struct-title">{{ p.title || '未命名窗口' }}</span>
            <span class="t-cap">软件 {{ p.app || '未登记' }} · {{ stateText(p.state) }} · {{ geoText(p) }} · {{ p.mode ? '当前模式' : '只读' }}</span>
          </div>
          <div v-if="!projections.length" class="t-cap">没有可显示的窗口</div>
        </div>
        <div class="modal-foot">
          <button class="btn btn--secondary" @click="structOpen = false">关闭</button>
        </div>
      </div>
    </template>

    <!-- ===== 准备工作空间浮层（原型 `fn:runPrepSequence`）：`.run-prep/.rp-steps/.rp-step/.spinner`
         几何与文案照抄设计稿；**打勾只认真实操作的完成信号**（不是定时器），见脚本区注释。 -->
    <template v-if="prepOpen">
      <div class="scrim" data-pw="run-prep-scrim"></div>
      <div class="modal run-prep" role="dialog" aria-label="准备工作空间" data-pw="run-prep">
        <span class="spinner" style="width: 22px; height: 22px; border-width: 2px"></span>
        <div class="t-card">正在准备工作空间...</div>
        <div class="rp-steps">
          <div
            v-for="(s, i) in PREP_STEPS"
            :key="s"
            class="rp-step"
            :class="{ done: prepDone[i] }"
            :data-pw="`run-prep-step-${i}`"
          >
            <svg
              class="ico"
              viewBox="0 0 24 24"
              width="14"
              height="14"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
              aria-hidden="true"
            >
              <template v-if="i === 2">
                <circle cx="12" cy="12" r="8.4" />
                <path d="m8.4 12.2 2.4 2.4 4.8-5" />
              </template>
              <template v-else>
                <path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.2" />
                <path d="M19.4 4.4v5h-5" />
              </template>
            </svg>
            <span>{{ s }}</span>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* 设计稿未覆盖的少量工程钩子：零动画声明、零裸色值、零新 token。
   能被设计规则命中的一律**不在这里重写**（几何唯一来源 = base.css）——
   下面每一条都注明「设计稿没有对应规则」的理由，避免变成第二套视觉。 */

/* 非当前模式窗口整卡只读（设计稿没有"只读窗口"这个概念，工程侧新增） */
.run-win:not(.is-managed) {
  pointer-events: none;
}

/* 布局结构弹窗的行（设计稿 modal 里没有这一件，沿用 token 拼装） */
.struct-row {
  display: flex;
  align-items: baseline;
  gap: var(--space-2);
  padding: var(--space-2) 0;
  border-bottom: 1px solid var(--border-subtle);
}
.struct-row:last-child {
  border-bottom: 0;
}
.struct-title {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 窗口事实行（替代原型 .win-body 里的 mock 文案） */
.wb-row {
  display: flex;
  gap: var(--space-2);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  min-width: 0;
}
.wb-k {
  flex: 0 0 auto;
  color: var(--text-4);
}
.wb-v {
  flex: 1 1 auto;
  min-width: 0;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 负载告警（设计稿无对应件：原型的状态栏是纯 mock，没有失败态） */
.run-status__warn {
  color: var(--warning);
  font-size: var(--fs-caption);
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 软件 chip 的窗口计数后缀（C2 新增事实，设计稿的 rs-st 只承载三态文案） */
.run-chip__count {
  margin-left: 2px;
  color: var(--text-3);
  font-size: var(--fs-caption);
}

/* 舞台右下角的常驻缩略图：设计稿的 .minimap 无固有尺寸（它总被父容器撑满），
   运行页需要一个固定的角标尺寸，故只在这里定尺寸，视觉语言仍走 .minimap */
.run-minimap {
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: 168px;
  height: 94px;
}
</style>
