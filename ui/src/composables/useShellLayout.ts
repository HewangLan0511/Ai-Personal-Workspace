/**
 * 壳层布局引擎（UI-FUSION-FULL）—— 逐值移植设计稿 `personal-workspace-ui/index.html`
 * 的两套机制：
 *
 *   §A 边界拖拽：RESIZE_CONF / 手柄 / 级联挤压 / 滞回折叠 / 蓄力 / 到位脉冲
 *      ← 原型 `enableResize` + `mountHandles` + `applyWidths` + `SQUEEZE_CHAIN`
 *   §B 响应式状态机：data-cw（内容分档）+ data-rs（chrome 策略）
 *      ← 原型 `initRS`（单一 ResizeObserver，rAF 节流，带滞回带，零渲染）
 *
 * ★ 三条**不可绕过**的工程约束（比原型严格，原型没有这些）：
 *   1) 拖拽的唯一授权来源是 Motion Runtime —— `claim(el,'drag')`，与
 *      `components/AiSidebar.vue` 同一口径（TECH-03-B §一）。拿不到 Primary 就不启动；
 *      被更高优先级顶掉就立即收敛（move 侧守卫）。
 *   2) 时长/幅度一律走 `--mt-*` token，不在 TS 里写死毫秒。JS 只在"等动画播完
 *      再改状态"的编排点上读 token（`motionMs`），避免 Guard 归零后 JS 空等。
 *   3) 宽度落库走 `configApi`（与 `stores/nav.ts`、`stores/widgets.ts` 同一条通道），
 *      键登记在 `core/src/db/config.rs`（`ui.shell.nav_w` / `ui.shell.widget_w`）。
 *
 * ★ 与原型的一处**有意**差异：原型的 nav/widget/ai 三档宽度都放在 `state.w`。
 *   本工程的 AI 侧栏宽度已由 `stores/ai.ts` 持久化（历史实现 + 冻结验收），
 *   故 AI 档沿用该 store 作唯一来源；nav/widget 两档由本模块持久化。
 *
 * ★ 本模块是**单例**（`useShellLayout()` 返回同一份状态）。
 *   壳层宽度/档位是全局唯一事实：`App.vue`（挂手柄与 ResizeObserver）、
 *   `WidgetCol.vue`（读 `widgetCollapsed`）、`AiSidebar.vue`（读 `aiWidth`）都要同一份。
 *   若每个组件各调一次各建一份，就会出现"两个 ResizeObserver 抢写 data-rs、
 *   两个宽度变量互相覆盖"。生命周期钩子因此**不在本模块注册**，
 *   由 `App.vue` 显式调 `init()` / `destroy()`（它才是壳层的所有者）。
 */

import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'

import { configApi } from '@/api/configService'
import { claim, motionMs, type MotionClaim } from '@/motion'
import { CINEMA } from '@/motion/config'
import { useAiStore } from '@/stores/ai'
import { useNavStore } from '@/stores/nav'

export type PanelKey = 'nav' | 'widget' | 'ai'
export type AreaKey = PanelKey | 'content'

interface ResizeConf {
  min: number
  max: number
  def: number
  /** +1 = 向右拖变宽（左边界固定的列）；-1 = 向左拖变宽 */
  dir: 1 | -1
  /** 折叠后的宽度 */
  foldW: number
  /** 松手 ≤ 此值即折叠（滞回下阈值） */
  foldAt?: number
  /** 折叠态拖到 ≥ 此值才展开（滞回上阈值，必须 > foldAt） */
  expandAt?: number
}

/** 原型 RESIZE_CONF（逐值） */
export const RESIZE_CONF: Record<PanelKey, ResizeConf> = {
  nav: { min: 160, max: 400, def: 236, dir: 1, foldW: 64, foldAt: 176, expandAt: 200 },
  widget: { min: 200, max: 400, def: 224, dir: -1, foldW: 0 },
  ai: { min: 300, max: 560, def: 360, dir: -1, foldW: 48, foldAt: 316, expandAt: 340 },
}

/** 原型 CONTENT_MIN：主窗口的最小尊严 */
export const CONTENT_MIN = 680
const AREA_MIN: Record<AreaKey, number> = { nav: 160, widget: 200, ai: 300, content: CONTENT_MIN }
/** 折叠能额外释放的空间：160→64 / 300→48 */
const FOLD_REL: Partial<Record<PanelKey, number>> = { nav: 96, ai: 252 }
/** 链的顺序 = 谁先被挤、谁后被挤（沿挤压方向的物理邻接顺序） */
const SQUEEZE_CHAIN: Record<PanelKey, AreaKey[]> = {
  nav: ['content', 'widget', 'ai'],
  widget: ['content', 'nav'],
  ai: ['widget', 'content', 'nav'],
}

/** 原型 CW_GATE：lg/md/sm/xs 的进入阈值（带 50px 滞回） */
const CW_GATE = [1080, 880, 690, 570]
const CW_NAMES = ['', 'lg', 'md', 'sm', 'xs'] as const
export type CwTier = (typeof CW_NAMES)[number]
const CW_FRESH_MS = 700

/** 原型 RS_GATE：full ⇄ compact ⇄ collapsed ⇄ fallback，每条边界 = [进入, 恢复] */
const RS_NAMES = ['full', 'compact', 'collapsed', 'fallback'] as const
export type RsState = (typeof RS_NAMES)[number]
const RS_GATE: Array<[number, number]> = [
  [1400, 1500],
  [950, 1050],
  [650, 750],
]

const KEY_NAV = 'ui.shell.nav_w'
const KEY_WIDGET = 'ui.shell.widget_w'

/** 手柄选择器（App.vue 用它 ref 挂载；AI 档的手柄由 AiSidebar 自己持有，见其注释） */
export const HANDLE_SEL: Record<PanelKey, string> = {
  nav: '.rsh--nav',
  widget: '.rsh--widget',
  ai: '.rsh--ai',
}

export interface ShellLayout {
  navWidth: () => number
  widgetWidth: () => number
  aiWidth: () => number
  navCollapsed: ComputedRef<boolean>
  widgetCollapsed: Ref<boolean>
  cw: Ref<CwTier>
  rs: Ref<RsState>
  /** 沉浸态（设计稿 `.shell.cinema`）：进入运行页时由路由切换。 */
  cinema: Ref<boolean>
  shellStyle: ComputedRef<Record<string, string>>
  init: () => Promise<void>
  destroy: () => void
  attachShell: (el: HTMLElement | null) => void
  attachHandle: (key: PanelKey, el: HTMLElement | null) => void
  toggleWidget: () => void
  resetWidth: (key: PanelKey) => void
  announce: (msg: string) => void
  /** 原型 `go()`：`.cinema` 提前一拍切换 + 侧栏自动折叠意图同步。 */
  setCinema: (on: boolean) => void
  /** 原型 `playCinema()`：0–240 主体 → 240 GATE → 240–560 后台稳定。 */
  playCinema: () => void
}

function createShellLayout(): ShellLayout {
  const ai = useAiStore()
  const nav = useNavStore()

  const navW = ref(RESIZE_CONF.nav.def)
  const widgetW = ref(RESIZE_CONF.widget.def)
  /** 侧栏折叠沿用 nav store（`ui.nav.collapsed`，既有持久化键）作唯一来源 */
  const navCollapsed = computed(() => nav.collapsed)
  const widgetCollapsed = ref(false)
  const cw = ref<CwTier>('')
  const rs = ref<RsState>('full')
  const cinema = ref(false)

  let shellEl: HTMLElement | null = null
  const bound = new Map<PanelKey, { el: HTMLElement; teardown: () => void }>()
  /** 用户手动折过导航后，不再被 rs 自动档位覆盖（原型用 state.rsMini 表达同一件事） */
  let manualNav = false
  /**
   * 原型 `state.navAutoMini` / `state.navRunExpanded`：
   * 进入工作模式自动折叠侧栏；用户在工作模式里手动展开过，本次就不再自动收。
   * 与 `manualNav`（用户手动折的常态意图）是两件事，互不覆盖。
   */
  let navAutoMini = false
  let navRunExpanded = false
  let ro: ResizeObserver | null = null
  let rsIdx = 0
  let freshUntil = 0
  let rafId = 0
  let cinemaGateT = 0
  let cinemaStableT = 0

  const shellStyle = computed<Record<string, string>>(() => ({
    '--sidebar-w': `${navW.value}px`,
    '--widget-w': `${widgetW.value}px`,
    '--ai-panel-w': `${ai.width}px`,
  }))

  const navWidth = (): number => navW.value
  const widgetWidth = (): number => widgetW.value
  const aiWidth = (): number => ai.width

  function getWidth(key: PanelKey): number {
    return key === 'nav' ? navW.value : key === 'widget' ? widgetW.value : ai.width
  }

  function setWidth(key: PanelKey, v: number): void {
    const c = RESIZE_CONF[key]
    const next = Math.max(c.min, Math.min(c.max, Math.round(v)))
    if (key === 'nav') navW.value = next
    else if (key === 'widget') widgetW.value = next
    else ai.setWidth(next)
  }

  function isFolded(key: PanelKey): boolean {
    if (key === 'nav') return navCollapsed.value
    if (key === 'widget') return widgetCollapsed.value
    return ai.collapsed
  }

  function nameOf(key: PanelKey): string {
    return key === 'nav' ? '侧边栏' : key === 'widget' ? '组件区' : 'AI 侧栏'
  }

  function fold(key: PanelKey, silent = false): void {
    if (key === 'nav') void nav.setCollapsed(true)
    else if (key === 'widget') widgetCollapsed.value = true
    else ai.setCollapsed(true)
    if (!silent) announce(key === 'widget' ? '组件区已收起' : `${nameOf(key)}已折叠`)
  }

  function unfold(key: PanelKey): void {
    // 工作模式里用户手动展开过侧栏 → 本次会话不再自动收（原型 navRunExpanded）
    if (key === 'nav' && cinema.value) navRunExpanded = true
    if (key === 'nav') void nav.setCollapsed(false)
    else if (key === 'widget') widgetCollapsed.value = false
    else ai.setCollapsed(false)
  }

  /** 原型 announce：只进 aria-live，不弹任何可见提示（拖拽结果肉眼可见，弹条就是噪音） */
  function announce(msg: string): void {
    const r = document.getElementById('pw-live-region')
    if (!r) return
    r.textContent = ''
    window.setTimeout(() => {
      r.textContent = msg
    }, 30)
  }

  /**
   * 原型 areaW：拿区域实测宽度。
   * 选择器用 `.app-*`（工程钩子，永远存在）；`ai-dock` 是 AI 档的唯一根
   * —— 收起态不再是另一个"rail 元素"，而是同一个根加 `.collapsed`。
   */
  function areaWidth(k: AreaKey): number {
    if (!shellEl) return 0
    const el =
      k === 'nav'
        ? shellEl.querySelector('.app-nav')
        : k === 'widget'
          ? shellEl.querySelector('.app-widget')
          : k === 'ai'
            ? shellEl.querySelector('.ai-dock')
            : shellEl.querySelector('.app-content')
    return el ? el.getBoundingClientRect().width : 0
  }

  /**
   * 级联挤压：某个区域被拖宽 → 先挤主视窗；主视窗到底仍不够 → 压力沿挤压方向传给
   * 下一个区域；该区域到底后再折叠它换空间。返回实际让出的空间。
   */
  function squeeze(key: PanelKey, want: number): number {
    let deficit = want
    for (const k of SQUEEZE_CHAIN[key]) {
      if (deficit <= 0) break
      const cur = areaWidth(k)
      const floor = k === 'content' ? AREA_MIN.content : isFolded(k) ? RESIZE_CONF[k].foldW : AREA_MIN[k]
      const slack = Math.max(0, cur - floor)
      const take = Math.min(slack, deficit)
      deficit -= take
      if (take > 0 && k !== 'content') setWidth(k, getWidth(k) - take)
      if (deficit <= 0) break
      // 已把该区域挤到底、缺口还在 → 折叠它换空间（不可折叠的 content 直接继续传压）
      if (k !== 'content' && !isFolded(k) && FOLD_REL[k]) {
        const rel = Math.min(FOLD_REL[k] ?? 0, deficit)
        deficit -= rel
        fold(k, true)
      }
    }
    return want - deficit
  }

  /** 原型 enableResize：指针拖拽 + 滞回折叠 + 蓄力 + 到位脉冲 */
  function setupHandle(key: PanelKey, h: HTMLElement): () => void {
    const c = RESIZE_CONF[key]
    let startX = 0
    let startW = 0
    let on = false
    let pid: number | null = null
    let armT = 0
    let crestT = 0
    let claimRef: MotionClaim | null = null

    function move(ev: PointerEvent): void {
      if (!on) return
      // 声明失效（被更高优先级顶掉）后不得再改宽度 —— 单一来源的另一半
      if (!claimRef?.isPrimary) return
      const raw = startW + (ev.clientX - startX) * c.dir

      // 折叠态：连续拉出。阈值判定必须用未夹紧的 raw，否则被 min 夹住会跳变
      if (isFolded(key)) {
        if (c.expandAt == null || raw < c.expandAt) return
        unfold(key)
        startW = c.foldW
        startX = ev.clientX
        return
      }

      const next = Math.max(c.min, Math.min(c.max, raw))

      /* 蓄力：拖到最小值以下不立刻折叠，先在 dwell 时长里把线涨粗，满了才折叠。
         没有这段反馈，用户只会觉得"怎么突然就折叠了"。 */
      if (c.foldAt != null && next <= c.min) {
        h.classList.add('arming')
        window.clearTimeout(armT)
        armT = window.setTimeout(() => {
          if (!on) return
          h.classList.remove('arming')
          fold(key)
        }, motionMs('--mt-dur-dwell', 560))
      } else {
        h.classList.remove('arming')
        window.clearTimeout(armT)
      }

      let final = next
      const grow = next - getWidth(key)
      if (grow > 0) final = getWidth(key) + squeeze(key, grow)
      setWidth(key, final)
      /* 原型 refill：拖拽中若节点被重建，补回指针捕获，否则拖到一半就脱手 */
      if (pid != null) {
        try {
          h.setPointerCapture(pid)
        } catch {
          /* 捕获不可用不致命：window 监听仍在，pointerup 依然能收尾 */
        }
      }
    }

    function end(): void {
      if (!on) return
      on = false
      window.clearTimeout(armT)
      h.classList.remove('arming')
      h.classList.remove('on')
      document.body.classList.remove('is-resizing')
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', end)
      window.removeEventListener('pointercancel', end)
      // 到位：边缘脉冲一下（与"拉满展开"同一反馈）
      if (!isFolded(key)) {
        h.classList.add('crest')
        window.clearTimeout(crestT)
        crestT = window.setTimeout(() => h.classList.remove('crest'), 560)
        announce(`${nameOf(key)}宽度 ${Math.round(getWidth(key))} 像素`)
      }
      claimRef?.release()
      claimRef = null
      pid = null
    }

    function down(ev: PointerEvent): void {
      if (ev.button !== 0) return
      ev.preventDefault()
      // Motion Runtime 是拖拽的唯一授权来源
      const cl = claim(h, 'drag', () => end())
      if (!cl.isPrimary) {
        cl.release()
        return
      }
      claimRef = cl
      on = true
      pid = ev.pointerId
      startX = ev.clientX
      startW = isFolded(key) ? c.foldW : getWidth(key)
      h.classList.add('on')
      document.body.classList.add('is-resizing')
      try {
        h.setPointerCapture(pid)
      } catch {
        /* 不支持指针捕获的环境退化为 window 监听（下方已挂） */
      }
      window.addEventListener('pointermove', move)
      window.addEventListener('pointerup', end)
      window.addEventListener('pointercancel', end)
    }

    function onDblClick(): void {
      resetWidth(key)
    }

    function onKey(ev: KeyboardEvent): void {
      if (ev.key !== 'ArrowLeft' && ev.key !== 'ArrowRight') return
      ev.preventDefault()
      // 折叠态下方向键先展开，否则"调宽"没有意义（宽度被 foldW 钉着）
      if (isFolded(key)) {
        unfold(key)
        announce(`${nameOf(key)}已展开`)
        return
      }
      const step = (ev.shiftKey ? 48 : 16) * (ev.key === 'ArrowRight' ? 1 : -1) * c.dir
      setWidth(key, getWidth(key) + step)
      announce(`${nameOf(key)}宽度 ${Math.round(getWidth(key))} 像素`)
    }

    h.addEventListener('pointerdown', down)
    h.addEventListener('dblclick', onDblClick)
    h.addEventListener('keydown', onKey)
    return () => {
      h.removeEventListener('pointerdown', down)
      h.removeEventListener('dblclick', onDblClick)
      h.removeEventListener('keydown', onKey)
      window.clearTimeout(armT)
      window.clearTimeout(crestT)
      end()
    }
  }

  function attachHandle(key: PanelKey, el: HTMLElement | null): void {
    const cur = bound.get(key)
    if (cur && cur.el === el) return
    if (cur) {
      cur.teardown()
      bound.delete(key)
    }
    if (!el) return
    bound.set(key, { el, teardown: setupHandle(key, el) })
  }

  function resetWidth(key: PanelKey): void {
    setWidth(key, RESIZE_CONF[key].def)
    if (isFolded(key)) unfold(key)
    announce(`${nameOf(key)}宽度已重置`)
  }

  function toggleWidget(): void {
    widgetCollapsed.value = !widgetCollapsed.value
    announce(widgetCollapsed.value ? '组件区已收起' : '组件区已展开')
  }

  // ---------------- §B 响应式状态机（原型 initRS） ----------------

  function rsStateOf(w: number, cur: number): number {
    for (let k = 0; k < RS_GATE.length; k++) {
      const [down, up] = RS_GATE[k]
      if (cur === k && w < down) return rsStateOf(w, k + 1)
      if (cur === k + 1 && w >= up) return rsStateOf(w, k)
    }
    return cur
  }

  function cwTierOf(w: number, cur: string, fresh: boolean): CwTier {
    let k = Math.max(0, (CW_NAMES as readonly string[]).indexOf(cur))
    while (k > 0 && w > CW_GATE[k - 1] + (fresh ? 0 : 50)) k--
    while (k < CW_GATE.length - 1 && w < CW_GATE[k]) k++
    return CW_NAMES[k]
  }

  /** 原型 applyNavMini：mini = 自动折叠意图 ∨ 窗口档位折叠。 */
  function applyNavMini(): void {
    const mini = navAutoMini || rsIdx >= 2
    if (!manualNav && navCollapsed.value !== mini) void nav.setCollapsed(mini)
  }

  /** 原型 syncNavAuto：退出即清"已手动展开"标记；进入即按需自动折叠。 */
  function syncNavAuto(isRun: boolean): void {
    if (!isRun) navRunExpanded = false
    navAutoMini = isRun && !navRunExpanded
    applyNavMini()
  }

  /**
   * 原型 `go()`：`.cinema` **提前一拍**切换（不等场景离场结束），否则组件区比侧栏
   * 晚 80ms 才开始收，窗口 120ms 落位时会撞上"右边还在变宽"。
   */
  function setCinema(on: boolean): void {
    cinema.value = on
    syncNavAuto(on)
  }

  /**
   * 原型 `playCinema()`：0–240 主体 → 240 GATE → 240–560 后台稳定。
   * 门限与稳定时长取自设计稿自己的时间轴常量（`CINEMA.gate` / `CINEMA.stable`），
   * 不在 TS 里另写一份毫秒；`reduced/off` 时 `--mt-dur-window` 归零即直接到位。
   */
  function playCinema(): void {
    if (!shellEl) return
    if (motionMs('--mt-dur-window', 200) < 20) return
    shellEl.querySelectorAll('.stage .win').forEach((w, i) => {
      ;(w as HTMLElement).style.setProperty('--i', String(i))
    })
    shellEl.classList.add('cinema-entering')
    window.clearTimeout(cinemaGateT)
    window.clearTimeout(cinemaStableT)
    cinemaGateT = window.setTimeout(() => {
      shellEl?.classList.remove('cinema-entering')
      shellEl?.classList.add('cinema-stabilizing')
    }, CINEMA.gate)
    cinemaStableT = window.setTimeout(() => {
      shellEl?.classList.remove('cinema-stabilizing')
    }, CINEMA.stable)
  }

  function applyRs(): void {
    if (!shellEl) return
    const nextIdx = rsStateOf(window.innerWidth, rsIdx)
    const nextName = RS_NAMES[nextIdx]
    if (rsIdx !== nextIdx) {
      rsIdx = nextIdx
      rs.value = nextName
      freshUntil = performance.now() + CW_FRESH_MS
    }
    const view = shellEl.querySelector('.app-main') as HTMLElement | null
    const w = view ? view.clientWidth : window.innerWidth
    const t = cwTierOf(w, cw.value, performance.now() < freshUntil)
    if (cw.value !== t) cw.value = t
    /* 用户正在拖侧区宽度时不做自动折叠（防打架）；拖完 RO 自然收敛 */
    if (document.body.classList.contains('is-resizing')) return
    applyNavMini()
  }

  function attachShell(el: HTMLElement | null): void {
    shellEl = el
    ro?.disconnect()
    ro = null
    if (!el || typeof ResizeObserver === 'undefined') return
    ro = new ResizeObserver(() => {
      if (rafId) return
      rafId = requestAnimationFrame(() => {
        rafId = 0
        applyRs()
      })
    })
    ro.observe(el)
    applyRs()
  }

  // 宽度落库：串行写，避免"后发先至"用旧值覆盖新值（与 stores/widgets.ts 同一条理由）
  let writeQueue: Promise<void> = Promise.resolve()
  function persist(key: string, v: number): void {
    writeQueue = writeQueue.then(
      () => configApi.put(key, v),
      () => configApi.put(key, v),
    )
  }

  async function init(): Promise<void> {
    const [n, w] = await Promise.all([
      configApi.get<number>(KEY_NAV, RESIZE_CONF.nav.def),
      configApi.get<number>(KEY_WIDGET, RESIZE_CONF.widget.def),
    ])
    if (typeof n === 'number' && Number.isFinite(n)) {
      navW.value = Math.max(RESIZE_CONF.nav.min, Math.min(RESIZE_CONF.nav.max, n))
    }
    if (typeof w === 'number' && Number.isFinite(w)) {
      widgetW.value = Math.max(RESIZE_CONF.widget.min, Math.min(RESIZE_CONF.widget.max, w))
    }
  }

  function destroy(): void {
    if (rafId) cancelAnimationFrame(rafId)
    window.clearTimeout(cinemaGateT)
    window.clearTimeout(cinemaStableT)
    rafId = 0
    ro?.disconnect()
    ro = null
    shellEl = null
    for (const b of bound.values()) b.teardown()
    bound.clear()
  }

  watch(navW, (v) => persist(KEY_NAV, v))
  watch(widgetW, (v) => persist(KEY_WIDGET, v))
  // 用户手动折过导航 → 之后的窗口档位不再自动改它（原型 state.rsMini 的等价物）。
  // 工作模式的自动折叠不算"用户意图"，必须排除，否则退出运行页后侧栏展不开。
  watch(navCollapsed, (v, ov) => {
    if (navAutoMini) return
    if (ov !== undefined && v && rsIdx < 2) manualNav = true
  })

  return {
    navWidth,
    widgetWidth,
    aiWidth,
    navCollapsed,
    widgetCollapsed,
    cw,
    rs,
    cinema,
    shellStyle,
    init,
    destroy,
    attachShell,
    attachHandle,
    toggleWidget,
    resetWidth,
    announce,
    setCinema,
    playCinema,
  }
}

/**
 * 单例访问器。
 *
 * 壳层状态必须全局唯一：`App.vue` / `WidgetCol.vue` / `AiSidebar.vue` 三处都要读同一份
 * （宽度、data-cw、data-rs、组件区折叠）。每个组件各建一份会出现"两个 ResizeObserver
 * 抢写同一个属性、两个宽度变量互相覆盖"的隐性竞态。
 * 生命周期（`init` / `destroy`）由壳层所有者 `App.vue` 显式驱动。
 */
let singleton: ShellLayout | null = null

export function useShellLayout(): ShellLayout {
  if (!singleton) singleton = createShellLayout()
  return singleton
}
