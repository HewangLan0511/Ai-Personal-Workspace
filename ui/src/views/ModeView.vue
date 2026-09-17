<script setup lang="ts">
/**
 * 工作模式（阶段4 · 06 §5 UI）。
 *
 * 三块：
 *  - **模式卡片 + 一键进入**（F-36/F-37）
 *  - **创建向导**（3 步：基本信息 → 选软件 → 设布局；F-02~F-06）
 *  - **模式编辑器**：网格拖拽画布 + 吸附（F-39；07 §6 也要求过，本阶段补齐）
 *  - **应用进度面板**：步骤清单 + 失败重试（F-38）
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import type { LayoutRecord, SlotResult, WorkMode, WorkModeInput } from '@/api/modeService'
import { modeApi } from '@/api/modeService'
import { toast, type ToastVariant } from '@/composables/useToast'
import { useAppsStore } from '@/stores/apps'

const apps = useAppsStore()

const modes = ref<WorkMode[]>([])
const layouts = ref<LayoutRecord[]>([])
const cur = ref<{ running: string | null; configured: unknown; launchedAppIds: number[] } | null>(null)
const progress = ref<{ active: boolean; state: { phase: string }; slots: SlotResult[]; history?: { phase: string }[] } | null>(null)
const busy = ref(false)
const error = ref('')

const view = ref<'list' | 'wizard' | 'editor'>('list')

/**
 * 本页的提示一律走统一 Toast Service（TECH-03-B §二）。
 * 这里保留 `notify` 只是**本页的调用约定**（省略变体 = `info`），
 * 计时/单条/渲染全部由 Service 负责 —— 本页不再持有 `ref` 与 `setTimeout`。
 */
function notify(msg: string, variant: ToastVariant = 'info'): void {
  toast.show(msg, { variant })
}

async function load() {
  try {
    modes.value = await modeApi.list()
    layouts.value = await modeApi.dbLayouts()
    cur.value = (await modeApi.current()) 
    progress.value = (await modeApi.progress()) 
  } catch (err) {
    error.value = String(err)
  }
}

onMounted(async () => {
  await apps.load()
  await load()
})

// ---------------------------------------------------------------- 一键进入 / 进度

let poll: number | undefined

async function enter(m: WorkMode) {
  busy.value = true
  error.value = ''
  try {
    const out = await modeApi.apply(m.id)
    notify(
      `已进入「${out.modeName}」：启动 ${out.launched} · 复用 ${out.alreadyRunning} · 失败 ${out.failed}` +
        (out.askPending ? '（切换策略待确认）' : ''),
    )
    progress.value = (await modeApi.progress()) 
    cur.value = (await modeApi.current()) 
    // 轮询直到流程结束，让进度面板实时刷新
    if (poll) window.clearInterval(poll)
    poll = window.setInterval(async () => {
      const p = (await modeApi.progress()) as typeof progress.value
      progress.value = p
      if (!p?.active) {
        window.clearInterval(poll)
        poll = undefined
        await load()
      }
    }, 400)
  } catch (err) {
    error.value = String(err)
  } finally {
    busy.value = false
  }
}

async function cancelApply() {
  const r = await modeApi.cancel()
  notify(r.cancelled ? `已请求取消（${r.modeName}）` : (r.reason ?? '当前没有进行中的应用流程'))
}

async function exitMode() {
  const r = await modeApi.exit()
  notify(r.closed.length ? `已退出模式，关闭 ${r.closed.length} 个软件` : '已退出模式', 'success')
  await load()
}

/** 失败项"重试"：重新 apply（幂等 —— 已在运行的软件会跳过，只重试失败项）。 */
async function retry() {
  const running = cur.value?.running
  const m = modes.value.find((x) => x.name === running)
  if (!m) {
    notify('当前没有正在运行的命名模式，请直接点卡片"进入"', 'error')
    return
  }
  await enter(m)
}

onUnmounted(() => {
  if (poll) window.clearInterval(poll)
})

const phaseText: Record<string, string> = {
  idle: '空闲',
  validating: '校验中',
  launching: '启动软件',
  waiting_ready: '等待窗口就绪',
  arranging: '排列窗口',
  opening_files: '打开文件入口',
  loading_ai: '载入 AI',
  done: '完成',
  failed: '失败',
  cancelled: '已取消',
}

const statusText: Record<string, string> = {
  launched: '已启动',
  already_running: '已在运行',
  failed: '失败',
  skipped_cancelled: '已取消（跳过）',
}

/** 步骤清单：按流水线顺序展示，标注是否走过（F-38）。 */
const STEP_ORDER = ['validating', 'launching', 'waiting_ready', 'arranging', 'opening_files', 'loading_ai', 'done']
const historyPhases = computed(() => new Set((progress.value?.history ?? []).map((h) => h.phase)))
const currentPhase = computed(() => progress.value?.state?.phase ?? 'idle')

function stepState(step: string): 'done' | 'active' | 'pending' {
  if (historyPhases.value.has(step)) return 'done'
  if (currentPhase.value === step) return 'active'
  return 'pending'
}

// ---------------------------------------------------------------- 从当前环境捕获（2026-09-13 交互重构）

const captureOpen = ref(false)
const captureName = ref('')
const captureBusy = ref(false)
const captureResult = ref<{ layout: string; captured: string[] } | null>(null)

function openCapture() {
  captureOpen.value = true
  captureName.value = ''
  captureResult.value = null
}

async function submitCapture() {
  if (!captureName.value.trim()) {
    notify('先给这个模式起个名字', 'error')
    return
  }
  captureBusy.value = true
  try {
    const r = await modeApi.captureCurrent(captureName.value.trim())
    captureResult.value = { layout: r.layout, captured: r.captured }
    notify(`已记录 ${r.captured.length} 个软件及其窗口布局`, 'success')
    await load()
  } catch (err) {
    notify(`捕获失败：${String(err)}`, 'error')
  } finally {
    captureBusy.value = false
  }
}

function closeCapture() {
  captureOpen.value = false
  if (captureResult.value) view.value = 'list'
}

// ---------------------------------------------------------------- 向导

/** 创建意图预设（三·工作模式 2026-09-13）：选目标 → 预勾选匹配软件，其余默认。 */
const GOALS: { key: string; label: string; hint: string; keywords: string[] }[] = [
  { key: 'dev', label: '项目开发', hint: '编辑器 / 终端 / 浏览器', keywords: ['code', 'idea', 'pycharm', 'terminal', 'cmd', 'powershell', 'wt', 'git', 'bash', 'devenv', 'cursor', 'sublime', 'notepad++'] },
  { key: 'learn', label: '学习', hint: '笔记 / 浏览器 / 阅读器', keywords: ['obsidian', 'notion', 'onenote', 'word', 'sumatra', 'chrome', 'msedge', 'firefox', 'calibre'] },
  { key: 'write', label: '写作', hint: '文档 / 输入法无忧环境', keywords: ['word', 'notepad', 'typora', 'obsidian', 'wps'] },
  { key: 'office', label: '办公', hint: '邮件 / 表格 / 沟通', keywords: ['excel', 'outlook', 'wps', 'wechat', 'dingtalk', 'feishu', 'powerpnt'] },
  { key: 'custom', label: '自定义', hint: '自己勾选软件', keywords: [] },
]

const wiz = reactive({
  step: 0 as 0 | 1 | 2 | 3,
  goal: '',
  name: '',
  description: '',
  apps: [] as string[],
  args: {} as Record<string, string>,
  layout: '',
  targets: [] as { path: string; label: string }[],
  provider: '',
  promptKey: '',
  scopes: 'file:read',
  autoApply: false,
  switchPolicy: 'additive',
})

/** 按目标预勾选：软件名/分类命中关键词即选中；自定义则不预选。 */
function pickGoal(key: string) {
  wiz.goal = key
  const g = GOALS.find((x) => x.key === key)
  if (!g || g.keywords.length === 0) {
    wiz.apps = []
  } else {
    wiz.apps = apps.items
      .filter((a) => {
        const hay = `${a.name} ${a.category ?? ''}`.toLowerCase()
        return g.keywords.some((k) => hay.includes(k))
      })
      .map((a) => a.name)
  }
}

function openWizard() {
  wiz.step = 1
  wiz.goal = ''
  wiz.name = ''
  wiz.description = ''
  wiz.apps = []
  wiz.args = {}
  wiz.layout = layouts.value[0]?.name ?? ''
  wiz.targets = []
  wiz.provider = ''
  wiz.promptKey = ''
  wiz.scopes = 'file:read'
  wiz.autoApply = false
  wiz.switchPolicy = 'additive'
  view.value = 'wizard'
}

function toggleApp(name: string) {
  const i = wiz.apps.indexOf(name)
  if (i >= 0) wiz.apps.splice(i, 1)
  else wiz.apps.push(name)
}

function addTarget() {
  wiz.targets.push({ path: '', label: '' })
}

async function submitWizard() {
  if (!wiz.name.trim()) {
    notify('请填写模式名', 'error')
    return
  }
  const input: WorkModeInput = {
    name: wiz.name.trim(),
    description: wiz.description || null,
    apps: wiz.apps,
    openTargets: wiz.targets.filter((t) => t.path.trim()).map((t) => ({ path: t.path, label: t.label || null, type: 'folder' })),
    layout: wiz.layout || null,
    aiProfile: wiz.provider
      ? {
          provider: wiz.provider,
          systemPromptKey: wiz.promptKey,
          permissionScope: wiz.scopes.split(',').map((s) => s.trim()).filter(Boolean),
        }
      : null,
    autoApply: wiz.autoApply,
    switchPolicy: wiz.switchPolicy,
  }
  busy.value = true
  try {
    await modeApi.add(input)
    notify(`已创建「${input.name}」`, 'success')
    view.value = 'list'
    await load()
  } catch (err) {
    notify(`创建失败：${String(err)}`, 'error')
  } finally {
    busy.value = false
  }
}

/** 布局槽位（卡片 hover 预览用）。
 *  放在 script 里 —— template 内联 TS 类型断言不被 vue-tsc 接受（会在模板里报 TS1005）。 */
function slotsOf(layoutName: string | null): { app: string }[] {
  if (!layoutName) return []
  const l = layouts.value.find((x) => x.name === layoutName)
  return (l?.slots as { app: string }[] | undefined) ?? []
}

async function duplicate(m: WorkMode) {
  try {
    const d = await modeApi.duplicate(m.id)
    notify(`已复制为「${d.name}」`, 'success')
    await load()
  } catch (err) {
    notify(`复制失败：${String(err)}`, 'error')
  }
}

async function removeMode(m: WorkMode) {
  if (!window.confirm(`删除模式「${m.name}」？（软删除，不影响已安装软件）`)) return
  await modeApi.remove(m.id)
  notify(`已删除「${m.name}」`, 'success')
  await load()
}

// ---------------------------------------------------------------- 拖拽画布（F-39）

const GRID = 4
const canvasRef = ref<HTMLElement | null>(null)
const dragStart = ref<{ gx: number; gy: number } | null>(null)
const dragNow = ref<{ gx: number; gy: number } | null>(null)
const edName = ref('')
const edRegions = ref<{ x: number; y: number; w: number; h: number; app: string }[]>([])

function openEditor() {
  edName.value = ''
  edRegions.value = []
  view.value = 'editor'
}

function cellOf(e: MouseEvent) {
  const el = canvasRef.value
  if (!el) return { gx: 0, gy: 0 }
  const r = el.getBoundingClientRect()
  const gx = Math.floor(((e.clientX - r.left) / r.width) * GRID)
  const gy = Math.floor(((e.clientY - r.top) / r.height) * GRID)
  return { gx: Math.max(0, Math.min(GRID - 1, gx)), gy: Math.max(0, Math.min(GRID - 1, gy)) }
}

function onDown(e: MouseEvent) {
  dragStart.value = cellOf(e)
  dragNow.value = dragStart.value
}
function onMove(e: MouseEvent) {
  if (!dragStart.value) return
  dragNow.value = cellOf(e)
}
function onUp() {
  const a = dragStart.value
  const b = dragNow.value
  dragStart.value = null
  dragNow.value = null
  if (!a || !b) return
  const x = Math.min(a.gx, b.gx)
  const y = Math.min(a.gy, b.gy)
  const w = Math.abs(a.gx - b.gx) + 1
  const h = Math.abs(a.gy - b.gy) + 1
  // 重叠检查（网格吸附后仍可能重叠 → 拒绝，保持布局语义干净）
  const overlap = edRegions.value.some(
    (r) => x < r.x + r.w && r.x < x + w && y < r.y + r.h && r.y < y + h,
  )
  if (overlap) {
    notify('该区域与已有区域重叠', 'error')
    return
  }
  edRegions.value.push({ x, y, w, h, app: '' })
}

const dragBox = computed(() => {
  const a = dragStart.value
  const b = dragNow.value
  if (!a || !b) return null
  const x = Math.min(a.gx, b.gx)
  const y = Math.min(a.gy, b.gy)
  const w = Math.abs(a.gx - b.gx) + 1
  const h = Math.abs(a.gy - b.gy) + 1
  return { left: `${(x / GRID) * 100}%`, top: `${(y / GRID) * 100}%`, width: `${(w / GRID) * 100}%`, height: `${(h / GRID) * 100}%` }
})

function regionStyle(r: { x: number; y: number; w: number; h: number }) {
  return {
    left: `${(r.x / GRID) * 100}%`,
    top: `${(r.y / GRID) * 100}%`,
    width: `${(r.w / GRID) * 100}%`,
    height: `${(r.h / GRID) * 100}%`,
  }
}

async function saveLayout() {
  if (!edName.value.trim()) {
    notify('请给布局起个名字', 'error')
    return
  }
  if (edRegions.value.length === 0) {
    notify('请先在画布上拖出至少一个区域', 'error')
    return
  }
  if (edRegions.value.some((r) => !r.app)) {
    notify('每个区域都要指定软件', 'error')
    return
  }
  const slots = edRegions.value.map((r, i) => ({
    app: r.app,
    rect: { x: r.x / GRID, y: r.y / GRID, w: r.w / GRID, h: r.h / GRID },
    z: i + 1,
  }))
  busy.value = true
  try {
    // 06 §技术要点：数据库是唯一真相 —— 走 upsert（它内部会导出 JSON）
    await modeApi.dbLayoutUpsert(edName.value.trim(), '自定义布局（编辑器创建）', slots, 0)
    notify(`布局「${edName.value}」已保存（已写库并导出 JSON）`, 'success')
    view.value = 'list'
    await load()
  } catch (err) {
    notify(`保存失败：${String(err)}`, 'error')
  } finally {
    busy.value = false
  }
}

function applyTemplate(kind: 'quad' | 'split-v' | 'split-h' | 'three') {
  const t: Record<string, { x: number; y: number; w: number; h: number; app: string }[]> = {
    quad: [
      { x: 0, y: 0, w: 2, h: 2, app: edRegions.value[0]?.app ?? '' },
      { x: 2, y: 0, w: 2, h: 2, app: edRegions.value[1]?.app ?? '' },
      { x: 0, y: 2, w: 2, h: 2, app: edRegions.value[2]?.app ?? '' },
      { x: 2, y: 2, w: 2, h: 2, app: edRegions.value[3]?.app ?? '' },
    ],
    'split-v': [
      { x: 0, y: 0, w: 2, h: 4, app: edRegions.value[0]?.app ?? '' },
      { x: 2, y: 0, w: 2, h: 4, app: edRegions.value[1]?.app ?? '' },
    ],
    'split-h': [
      { x: 0, y: 0, w: 4, h: 2, app: edRegions.value[0]?.app ?? '' },
      { x: 0, y: 2, w: 4, h: 2, app: edRegions.value[1]?.app ?? '' },
    ],
    three: [
      { x: 0, y: 0, w: 3, h: 4, app: edRegions.value[0]?.app ?? '' },
      { x: 3, y: 0, w: 1, h: 2, app: edRegions.value[1]?.app ?? '' },
      { x: 3, y: 2, w: 1, h: 2, app: edRegions.value[2]?.app ?? '' },
    ],
  }
  edRegions.value = t[kind].map((r) => ({ ...r }))
}
</script>

<template>
  <section class="mode-view">
    <!-- ============ 列表 ============ -->
    <template v-if="view === 'list'">
      <header class="mv-toolbar">
        <h3 class="mv-title">工作模式</h3>
        <span v-if="cur?.running" class="mv-running">当前：{{ cur.running }}</span>
        <span v-else-if="typeof cur?.configured === 'string' && cur.configured" class="mv-last">
          上次使用：{{ cur.configured }}
        </span>
        <span class="mv-toolbar-gap"></span>
        <button type="button" class="primary" @click="openCapture">保存当前环境为模式</button>
        <button type="button" @click="openWizard">新建模式</button>
        <button type="button" @click="openEditor">布局编辑器</button>
        <button v-if="cur?.running" type="button" @click="exitMode">退出模式</button>
      </header>

      <p v-if="modes.length === 0" class="mv-hint">
        还没有工作模式。最快的方式：把手头的软件开好、摆好位置，点「保存当前环境为模式」——下次一键回到这个状态。
      </p>

      <p v-if="error" class="mv-error">{{ error }}</p>

      <div class="mv-grid">
        <article v-for="m in modes" :key="m.id" class="mode-card" :class="{ active: cur?.running === m.name }">
          <header class="mode-card__head">
            <span class="mode-card__name">{{ m.name }}</span>
            <span v-if="m.autoApply" class="mode-card__badge">自动</span>
          </header>
          <p class="mode-card__desc">{{ m.description || '—' }}</p>
          <div class="mode-card__meta">
            {{ m.apps.length }} 个软件 · 用过 {{ m.useCount }} 次 · {{ m.layout || '无布局' }}
          </div>
          <!-- hover 预览：软件清单 + 布局缩略（F-36） -->
          <div class="mode-card__preview">
            <div class="mode-card__apps">
              <span v-for="a in m.apps" :key="a" class="mode-card__app">{{ a }}</span>
              <span v-if="m.apps.length === 0" class="mode-card__app mode-card__app--empty">未选软件</span>
            </div>
            <div class="mode-card__slots">
              <span v-for="(s, i) in slotsOf(m.layout)" :key="i" class="mode-card__slot">
                {{ s.app }}
              </span>
            </div>
          </div>
          <footer class="mode-card__actions">
            <button type="button" class="primary mode-enter" :disabled="busy" @click="enter(m)">一键进入</button>
            <button type="button" @click="duplicate(m)">复制</button>
            <button type="button" @click="removeMode(m)">删除</button>
          </footer>
        </article>
      </div>

      <!-- ============ 进度面板（F-38） ============ -->
      <div v-if="progress && (progress.active || progress.slots?.length)" class="mv-progress">
        <header class="mv-progress__head">
          <strong>应用进度</strong>
          <span class="mv-progress__phase">{{ phaseText[currentPhase] || currentPhase }}</span>
          <button v-if="progress.active" type="button" @click="cancelApply">取消</button>
        </header>
        <ol class="mv-steps">
          <li v-for="s in STEP_ORDER" :key="s" :class="`is-${stepState(s)}`">
            <span class="mv-steps__mark">{{ stepState(s) === 'done' ? '✅' : stepState(s) === 'active' ? '⏳' : '⬜' }}</span>
            {{ phaseText[s] }}
          </li>
        </ol>
        <ul class="mv-slots">
          <li v-for="(s, i) in progress.slots" :key="i" :class="`is-${s.status}`">
            <span class="mv-slots__app">{{ s.app }}</span>
            <span class="mv-slots__status">{{ statusText[s.status] || s.status }}</span>
            <span v-if="s.reason" class="mv-slots__reason">{{ s.reason }}</span>
          </li>
        </ul>
        <button v-if="progress.slots?.some((s) => s.status === 'failed')" type="button" class="primary mv-retry" @click="retry">
          重试失败项
        </button>
      </div>
    </template>

    <!-- ============ 从当前环境捕获（弹窗） ============ -->
    <div v-if="captureOpen" class="mv-modal-mask" @click.self="closeCapture">
      <div class="mv-modal">
        <header class="apps-modal-head">
          <strong>保存当前环境为模式</strong>
          <button type="button" @click="captureOpen = false">关闭</button>
        </header>
        <template v-if="!captureResult">
          <p class="mv-hint">把想用的软件都开好、摆好位置，然后给这套环境起个名字。系统会记住开了哪些软件、各自在什么位置。</p>
          <label>模式名称<input v-model="captureName" class="wiz-name" type="text" placeholder="例如：写代码" @keyup.enter="submitCapture" /></label>
          <footer class="apps-modal-foot">
            <button type="button" class="primary" :disabled="captureBusy" @click="submitCapture">
              {{ captureBusy ? '正在记录…' : '记录当前环境' }}
            </button>
          </footer>
        </template>
        <template v-else>
          <p class="mv-ok">已创建模式「{{ captureName.trim() }}」</p>
          <p class="mv-hint">记住了这些软件（布局已保存为 {{ captureResult.layout }}）：</p>
          <div class="mode-card__apps" style="display: flex">
            <span v-for="a in captureResult.captured" :key="a" class="mode-card__app">{{ a }}</span>
          </div>
          <footer class="apps-modal-foot">
            <button type="button" class="primary" @click="closeCapture">完成</button>
          </footer>
        </template>
      </div>
    </div>

    <!-- ============ 向导（2026-09-13 瘦身：目标 → 选软件 → 布局；技术配置收进「高级设置」） ============ -->
    <template v-else-if="view === 'wizard'">
      <header class="mv-toolbar">
        <strong>新建模式</strong>
        <button type="button" @click="view = 'list'">取消</button>
      </header>

      <!-- 第 0 步：选目标 -->
      <div v-if="wiz.step === 0" class="mv-form">
        <p class="mv-hint">这个模式用来做什么？系统会据此帮你挑好软件。</p>
        <div class="wiz-goals">
          <button
            v-for="g in GOALS"
            :key="g.key"
            type="button"
            class="wiz-goal"
            :class="{ active: wiz.goal === g.key }"
            @click="pickGoal(g.key)"
          >
            <span class="wiz-goal__label">{{ g.label }}</span>
            <span class="wiz-goal__hint">{{ g.hint }}</span>
          </button>
        </div>
        <label>模式名称<input v-model="wiz.name" class="wiz-name" type="text" placeholder="例如：深度学习模式" /></label>
        <footer>
          <button type="button" class="primary" :disabled="!wiz.goal || !wiz.name.trim()" @click="wiz.step = 1">下一步</button>
        </footer>
      </div>

      <!-- 第 1 步：确认软件 -->
      <div v-else-if="wiz.step === 1" class="mv-form">
        <p class="mv-hint">已按「{{ GOALS.find((g) => g.key === wiz.goal)?.label }}」帮你勾好了一批，增删几个就好：</p>
        <ul class="wiz-apps">
          <li v-for="a in apps.items" :key="a.id">
            <label>
              <input type="checkbox" :checked="wiz.apps.includes(a.name)" @change="toggleApp(a.name)" />
              <span>{{ a.name }}</span>
              <span v-if="a.category" class="wiz-cat">{{ a.category }}</span>
            </label>
          </li>
        </ul>
        <p v-if="apps.items.length === 0" class="mv-hint">软件库为空 —— 先到「软件」页扫描添加。</p>
        <footer>
          <button type="button" @click="wiz.step = 0">上一步</button>
          <button type="button" class="primary" @click="wiz.step = 2">下一步</button>
        </footer>
      </div>

      <!-- 第 2 步：布局 + 高级 -->
      <div v-else class="mv-form">
        <label>
          窗口布局（可选）
          <select v-model="wiz.layout">
            <option value="">（不设置）</option>
            <option v-for="l in layouts" :key="l.name" :value="l.name">{{ l.name }} — {{ l.description || '' }}</option>
          </select>
        </label>
        <p class="mv-hint">进模式后软件会自动摆到布局位置；也可以之后用「保存当前环境为模式」随时覆盖。</p>

        <details class="wiz-advanced">
          <summary>高级设置</summary>
          <label><input v-model="wiz.autoApply" type="checkbox" /> 应用启动时自动进入此模式</label>
          <label>
            切换策略
            <select v-model="wiz.switchPolicy">
              <option value="additive">保留其他模式的软件</option>
              <option value="exclusive">关闭其他模式拉起的软件</option>
              <option value="ask">每次询问并记住</option>
            </select>
          </label>
          <h4>文件入口（可选）</h4>
          <div v-for="(t, i) in wiz.targets" :key="i" class="wiz-target">
            <input v-model="t.path" type="text" placeholder="目录或文件路径" />
            <input v-model="t.label" type="text" placeholder="标签" />
          </div>
          <button type="button" @click="addTarget">+ 添加入口</button>
          <h4>AI 配置（可选）</h4>
          <label>Provider<input v-model="wiz.provider" type="text" placeholder="如 deepseek" /></label>
          <label>提示词模板 Key<input v-model="wiz.promptKey" type="text" placeholder="如 dev_assistant" /></label>
          <label>权限范围<input v-model="wiz.scopes" type="text" placeholder="file:read,app:launch" /></label>
        </details>

        <footer>
          <button type="button" @click="wiz.step = 1">上一步</button>
          <button type="button" class="primary wiz-submit" :disabled="busy" @click="submitWizard">创建</button>
        </footer>
      </div>
    </template>

    <!-- ============ 布局编辑器（F-39，网格吸附拖拽） ============ -->
    <template v-else>
      <header class="mv-toolbar">
        <strong>布局编辑器</strong>
        <button type="button" @click="applyTemplate('quad')">四分屏</button>
        <button type="button" @click="applyTemplate('split-v')">左右</button>
        <button type="button" @click="applyTemplate('split-h')">上下</button>
        <button type="button" @click="applyTemplate('three')">三分</button>
        <button type="button" @click="edRegions = []">清空</button>
        <button type="button" @click="view = 'list'">返回</button>
      </header>

      <p class="mv-hint">在画布上**按住拖拽**画出区域（自动吸附到 {{ GRID }}×{{ GRID }} 网格），再为每个区域指定软件。</p>

      <div class="ed-body">
        <div
          ref="canvasRef"
          class="ed-canvas"
          @mousedown.prevent="onDown"
          @mousemove="onMove"
          @mouseup="onUp"
          @mouseleave="onUp"
        >
          <div v-for="(r, i) in edRegions" :key="i" class="ed-region" :style="regionStyle(r)">
            <span class="ed-region__idx">区域 {{ i + 1 }}</span>
            <select v-model="r.app" class="ed-region__app" @mousedown.stop>
              <option value="">选择软件…</option>
              <option v-for="a in apps.items" :key="a.id" :value="a.name">{{ a.name }}</option>
            </select>
            <button type="button" class="ed-region__del" @mousedown.stop @click="edRegions.splice(i, 1)">×</button>
          </div>
          <div v-if="dragBox" class="ed-dragbox" :style="dragBox"></div>
        </div>

        <aside class="ed-side">
          <label>布局名<input v-model="edName" class="ed-name" type="text" placeholder="如 my-coding" /></label>
          <p class="mv-hint">保存会**先写数据库再导出 JSON**（06 §技术要点：数据库是唯一真相）。</p>
          <button type="button" class="primary ed-save" :disabled="busy" @click="saveLayout">保存布局</button>
        </aside>
      </div>
    </template>
  </section>
</template>

<style scoped>
.mode-view {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: 100%;
  overflow: auto;
}

.mv-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mv-title {
  margin: 0;
}

.mv-running {
  color: var(--ok);
  font-weight: 600;
}

.mv-last {
  color: var(--text-dim);
}

.mv-hint {
  color: var(--text-dim);
  font-size: 13px;
}

.mv-error {
  color: var(--danger);
}

.mv-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.mode-card {
  position: relative;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-shadow: var(--shadow);
}

.mode-card.active {
  border-color: var(--ok);
}

.mode-card__head {
  display: flex;
  align-items: center;
  gap: 6px;
}

.mode-card__name {
  font-weight: 600;
  font-size: 15px;
}

.mode-card__badge {
  font-size: 11px;
  background: var(--accent-weak);
  color: var(--accent);
  border-radius: 4px;
  padding: 1px 5px;
}

.mode-card__desc {
  margin: 0;
  color: var(--text-dim);
  font-size: 12px;
  min-height: 16px;
}

.mode-card__meta {
  font-size: 12px;
  color: var(--text-dim);
}

.mode-card__preview {
  display: none;
  gap: 6px;
  flex-wrap: wrap;
}

.mode-card:hover .mode-card__preview {
  display: flex;
}

.mode-card__app,
.mode-card__slot {
  font-size: 11px;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 1px 5px;
  color: var(--text-dim);
}

.mode-card__app--empty {
  color: var(--danger);
}

.mode-card__actions {
  display: flex;
  gap: 6px;
  margin-top: auto;
}

.mode-enter {
  flex: 1;
}

.mv-progress {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.mv-progress__head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mv-progress__phase {
  color: var(--accent);
}

.mv-steps {
  display: flex;
  gap: 14px;
  list-style: none;
  margin: 0;
  padding: 0;
  flex-wrap: wrap;
  font-size: 12px;
}

.mv-steps .is-pending {
  color: var(--text-dim);
}

.mv-steps .is-active {
  font-weight: 600;
}

.mv-slots {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.mv-slots li {
  display: flex;
  gap: 8px;
  font-size: 12px;
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: 4px;
}

.mv-slots li.is-failed {
  border-color: var(--danger);
}

.mv-slots__status {
  color: var(--text-dim);
}

.mv-slots__reason {
  color: var(--danger);
}

.mv-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 620px;
}

.mv-form label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.mv-form label input[type='text'],
.mv-form label select {
  flex: 1;
}

.mv-form footer {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.wiz-apps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 300px;
  overflow: auto;
}

.wiz-apps label {
  display: flex;
  gap: 8px;
  align-items: center;
}

.wiz-args {
  flex: 1;
}

.wiz-target {
  display: flex;
  gap: 6px;
}

.wiz-target input {
  flex: 1;
}

.ed-body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.ed-canvas {
  position: relative;
  width: 520px;
  height: 300px;
  background: var(--bg);
  border: 1px dashed var(--border);
  border-radius: 8px;
  cursor: crosshair;
  /* 网格线（视觉提示吸附格） */
  background-image: linear-gradient(to right, var(--border) 1px, transparent 1px),
    linear-gradient(to bottom, var(--border) 1px, transparent 1px);
  background-size: 25% 25%;
}

.ed-region {
  position: absolute;
  box-sizing: border-box;
  border: 1px solid var(--accent);
  background: var(--accent-weak);
  border-radius: 4px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  overflow: hidden;
}

.ed-region__idx {
  font-size: 11px;
  font-weight: 600;
}

.ed-region__app {
  font-size: 11px;
}

.ed-region__del {
  position: absolute;
  top: 2px;
  right: 2px;
  padding: 0 5px;
  line-height: 16px;
}

.ed-dragbox {
  position: absolute;
  border: 1px dashed var(--accent);
  background: var(--accent-weak);
  opacity: 0.6;
  pointer-events: none;
}

.ed-side {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 220px;
}

.ed-name {
  flex: 1;
}

/* `.mv-toast` 已移除：本页提示改由统一 Toast Service 渲染
 *（canonical 声明见 `styles/base.css` 的 `.toast-canonical`，与这里原本的写法逐字一致）。 */

/* ---- 2026-09-13 交互重构：捕获弹窗 / 目标选择 / 高级折叠 ---- */

.mv-toolbar-gap {
  flex: 1;
}

.mv-ok {
  color: var(--ok);
  font-weight: 600;
}

.mv-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: grid;
  place-items: center;
  z-index: 50;
}

.mv-modal {
  width: min(560px, 92vw);
  max-height: 80vh;
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.wiz-goals {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: 8px;
}

.wiz-goal {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  padding: 10px 12px;
  text-align: left;
}

.wiz-goal.active {
  background: var(--accent-weak);
  border-color: var(--accent);
}

.wiz-goal__label {
  font-weight: 600;
}

.wiz-goal__hint {
  font-size: 12px;
  color: var(--text-dim);
}

.wiz-cat {
  color: var(--text-dim);
  font-size: 12px;
}

.wiz-advanced {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.wiz-advanced summary {
  cursor: pointer;
  color: var(--text-dim);
}
</style>
