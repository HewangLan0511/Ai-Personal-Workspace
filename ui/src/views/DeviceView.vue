<script setup lang="ts">
/**
 * 设备中心页（阶段8 · 11 §B）。
 *
 * 版式（UI-FUSION-FULL）：按设计稿 `ROUTES.device` 复刻 —— `page-head` +
 * 「设备身份卡（身份行 + `grid g4` 指标）」→「曲线卡」→「列表卡」→「虚线引导卡」。
 * 卡内数据全部取自真实 core（指标快照 / 进程枚举 / 模式健康度）。
 *
 * 红线在界面上的体现：
 * - **结束进程必须二次确认**（红线 V5）：点"结束"先弹确认，API 层还强制 confirm=true 双保险；
 * - 指标历史是内存环形缓冲（5 分钟），不落库（11 §B2 数据轻量化）；
 * - 刷新间隔由 core 配置控制（默认 2s），前端只跟随事件与低频轮询，不做高频轮询。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import {
  deviceApi,
  type MetricsSnapshot,
  type ModeHealth,
  type ProcInfo,
} from '@/api/deviceService'
import { on } from '@/api/eventBridge'
import PwIcon from '@/components/PwIcon.vue'
import { logger } from '@/utils/logger'

const snapshot = ref<MetricsSnapshot | null>(null)
const procs = ref<ProcInfo[]>([])
const health = ref<ModeHealth | null>(null)
const pendingKill = ref<ProcInfo | null>(null)
const killBusy = ref(false)
const killMsg = ref('')
const busy = ref(false)

const memPct = computed(() => {
  const s = snapshot.value?.current
  if (!s || !s.mem_total) return 0
  return Math.round((s.mem_used / s.mem_total) * 100)
})

const cpuPct = computed(() => Math.round(snapshot.value?.current.cpu ?? 0))

const fmtBytes = (b: number) => {
  if (!b) return '0'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = b
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

const diskPct = (free: number, total: number) => (total ? Math.round(((total - free) / total) * 100) : 0)

/** 5 分钟 CPU 曲线（sparkline，直接 SVG 折线） */
const sparkPoints = computed(() => {
  const h = snapshot.value?.history ?? []
  if (h.length < 2) return ''
  return h
    .map((p, i) => `${(i / (h.length - 1)) * 300},${40 - (p.cpu / 100) * 38}`)
    .join(' ')
})

/** 设计稿 .spark 柱状图形态：取最近 24 个采样点（每根柱 = 一次采样） */
const sparkBars = computed(() => {
  const h = snapshot.value?.history ?? []
  if (!h.length) return [] as { cpu: number; ts: number }[]
  const step = Math.max(1, Math.floor(h.length / 24))
  return h.filter((_, i) => i % step === 0).slice(-24)
})

const fmtClock = (ts: number) => {
  const d = new Date(ts > 1e12 ? ts : ts * 1000)
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

const oldestTs = computed(() => sparkBars.value[0]?.ts ?? 0)
const newestTs = computed(() => sparkBars.value[sparkBars.value.length - 1]?.ts ?? 0)

async function refreshMetrics() {
  try {
    snapshot.value = await deviceApi.metrics()
  } catch (e) {
    logger.warn('[device]', 'metrics 加载失败：' + String(e))
  }
}

async function refreshProcs() {
  try {
    procs.value = await deviceApi.processes()
  } catch (e) {
    logger.warn('[device]', '进程列表加载失败：' + String(e))
  }
}

async function refreshHealth() {
  try {
    health.value = await deviceApi.modeHealth()
  } catch (e) {
    logger.warn('[device]', '模式健康度加载失败：' + String(e))
  }
}

async function refreshAll() {
  busy.value = true
  try {
    await Promise.all([refreshMetrics(), refreshProcs(), refreshHealth()])
  } finally {
    busy.value = false
  }
}

function askKill(p: ProcInfo) {
  // 红线 V5 第一道：UI 二次确认（第二道在 core API：confirm != true 一律拒绝）
  pendingKill.value = p
}

async function confirmKill() {
  const target = pendingKill.value
  if (!target) return
  killBusy.value = true
  killMsg.value = ''
  try {
    await deviceApi.killProcess(target.pid)
    killMsg.value = `已结束 ${target.name} (pid ${target.pid})`
    pendingKill.value = null
    await refreshProcs()
  } catch (e) {
    killMsg.value = `结束失败：${String(e)}`
  } finally {
    killBusy.value = false
  }
}

const offMetrics = on('DEVICE_METRICS_UPDATED', () => void refreshMetrics())

let timer: number | undefined

onMounted(() => {
  void refreshMetrics()
  void refreshProcs()
  void refreshHealth()
  // 进程列表 5s 轮询（CPU% 差分需要连续请求；远高于 1s 高频线）
  timer = window.setInterval(() => void refreshProcs(), 5000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  offMetrics()
})
</script>

<template>
  <section class="page-skeleton">
    <div class="page-head">
      <div class="grow">
        <h2 class="t-page">设备中心</h2>
        <div class="t-cap" style="margin-top: 2px">
          查看与管理 · 首页只展示状态，这里可以深入查看
        </div>
      </div>
      <button class="btn btn--secondary btn--sm" type="button" :disabled="busy" @click="refreshAll">
        <PwIcon name="refresh" :size="15" /> 刷新
      </button>
    </div>

    <!-- ① 设备身份 + 指标 -->
    <div class="card card--lg" style="margin-bottom: var(--gap-section)">
      <div class="row">
        <span class="app tint6 lg"><PwIcon name="monitor" :size="24" /></span>
        <div class="grow">
          <div class="t-card">本机</div>
          <div class="t-cap">桌面设备 · 指标每 2s 采样 · 历史保留 5 分钟（内存缓冲，不落库）</div>
        </div>
        <span class="badge" :class="snapshot ? 'badge--success' : 'badge--warning'">
          <span class="pw-dot" :class="snapshot ? 'pw-dot--ok' : 'pw-dot--wait'" />
          {{ snapshot ? '在线' : '未连接' }}
        </span>
      </div>

      <div class="grid g4" style="margin-top: var(--space-6); gap: var(--space-5)">
        <div class="metric">
          <span class="k t-cap">CPU</span>
          <span class="v">{{ cpuPct }}%</span>
          <div class="progress thin"><i :style="{ width: `${Math.min(100, cpuPct)}%` }" /></div>
        </div>
        <div class="metric">
          <span class="k t-cap">内存</span>
          <span class="v">{{ fmtBytes(snapshot?.current.mem_used ?? 0) }}</span>
          <div class="progress thin"><i :style="{ width: `${memPct}%` }" /></div>
          <span class="t-cap">共 {{ fmtBytes(snapshot?.current.mem_total ?? 0) }}</span>
        </div>
        <div v-for="d in snapshot?.current.disks ?? []" :key="d.letter" class="metric">
          <span class="k t-cap">磁盘 {{ d.letter }}</span>
          <span class="v">{{ fmtBytes(d.free_bytes) }}</span>
          <div class="progress thin"><i :style="{ width: `${diskPct(d.free_bytes, d.total_bytes)}%` }" /></div>
          <span class="t-cap">可用 / 共 {{ fmtBytes(d.total_bytes) }}</span>
        </div>
      </div>
    </div>

    <!-- ② CPU 曲线（设计稿 .spark 柱状形态，数据为真实采样） -->
    <div class="card card--lg" style="margin-bottom: var(--gap-section)">
      <div class="t-section" style="margin-bottom: var(--space-4)">CPU · 最近采样</div>
      <div v-if="sparkBars.length" class="spark" style="height: 56px">
        <i
          v-for="(p, i) in sparkBars"
          :key="i"
          :class="{ hi: p.cpu > 70 }"
          :style="{ height: `${Math.max(3, Math.round(p.cpu))}%` }"
          :title="`${fmtClock(p.ts)} · ${Math.round(p.cpu)}%`"
        />
      </div>
      <svg v-if="sparkPoints" viewBox="0 0 300 40" class="spark-line" preserveAspectRatio="none">
        <polyline :points="sparkPoints" fill="none" stroke="var(--brand-500)" stroke-width="1.5" />
      </svg>
      <div v-if="sparkBars.length" class="row" style="justify-content: space-between; margin-top: var(--space-2)">
        <span class="t-cap">{{ fmtClock(oldestTs) }}</span>
        <span class="t-cap">{{ fmtClock(newestTs) }} · 最新采样</span>
      </div>
      <div v-else class="t-cap">正在积累历史数据…（默认每 2s 采样一次）</div>
    </div>

    <!-- ③ 运行中的程序（设计稿 row-item 列表形态；结束进程需二次确认） -->
    <div class="card card--lg" style="margin-bottom: var(--gap-section); padding: var(--space-2)">
      <div class="sec-head" style="margin: var(--space-2) var(--space-2) var(--space-3)">
        <div class="t-section grow">运行中的程序</div>
        <span class="t-cap">结束进程是破坏性操作，需要二次确认</span>
      </div>
      <div v-for="p in procs.slice(0, 30)" :key="p.pid" class="row-item">
        <span class="app tint1 xs"><PwIcon name="cpu" :size="13" /></span>
        <div class="main">
          <div class="title">{{ p.name }}</div>
          <div class="t-cap mono">PID {{ p.pid }}</div>
        </div>
        <span class="chip chip--outline mono" style="height: 22px">CPU {{ p.cpu_percent.toFixed(1) }}%</span>
        <span class="t-cap mono" style="min-width: 72px; text-align: right">{{ fmtBytes(p.mem_bytes) }}</span>
        <button class="btn btn--danger btn--sm" type="button" @click="askKill(p)">结束</button>
      </div>
      <div v-if="!procs.length" class="t-cap" style="padding: var(--space-3)">正在枚举进程…</div>
    </div>

    <!-- ④ 模式健康度 -->
    <div class="card card--lg" style="margin-bottom: var(--gap-section); padding: var(--space-2)">
      <div class="sec-head" style="margin: var(--space-2) var(--space-2) var(--space-3)">
        <div class="t-section grow">模式健康度</div>
        <span class="t-cap">按模式查看绑定软件的历史启动次数与今日实际使用时长</span>
      </div>
      <template v-for="m in health?.modes ?? []" :key="m.modeId">
        <div class="row" style="padding: var(--space-3) var(--space-2) 0">
          <span class="t-sm" style="font-weight: 600">{{ m.modeName }}</span>
        </div>
        <div v-for="a in m.apps" :key="a.name" class="row-item">
          <span class="app tint4 xs"><PwIcon name="grid" :size="13" /></span>
          <div class="main">
            <div class="title">{{ a.name }}</div>
            <div class="t-cap">启动 {{ a.launchCount }} 次 · 今日使用 {{ Math.round(a.usedSecondsToday / 60) }} 分钟</div>
          </div>
          <span class="progress thin" style="width: 120px">
            <i :style="{ width: `${Math.min(100, Math.round((a.usedSecondsToday / 3600) * 100))}%` }" />
          </span>
        </div>
      </template>
      <div v-if="!health?.modes.length" class="t-cap" style="padding: var(--space-3)">尚无模式数据。</div>
    </div>

    <!-- ⑤ 连接更多设备（设计稿虚线引导卡） -->
    <div class="card card--dashed" style="display: flex; gap: var(--space-3); align-items: center; padding: var(--space-4)">
      <PwIcon name="link" :size="18" />
      <div class="grow">
        <div class="t-sm" style="font-weight: 600">连接更多设备</div>
        <div class="t-cap" style="margin-top: 2px">手机与平板的连接能力在规划中</div>
      </div>
      <span class="badge">规划中</span>
    </div>

    <!-- 红线 V5：二次确认（设计稿 .scrim + .modal 形态） -->
    <div v-if="pendingKill" class="scrim" @click.self="pendingKill = null">
      <div class="modal" role="dialog" aria-label="确认结束进程">
        <div class="modal-head">
          <div class="t-card grow">确认结束进程</div>
          <button class="icon-btn" type="button" title="关闭" @click="pendingKill = null">
            <PwIcon name="x" :size="18" />
          </button>
        </div>
        <div class="modal-body">
          <p class="t-body">
            确定要结束「<strong>{{ pendingKill.name }}</strong>」（PID {{ pendingKill.pid }}）吗？
          </p>
          <p class="t-cap" style="margin-top: var(--space-2)">未保存的数据可能丢失。此操作不可撤销。</p>
          <p v-if="killMsg" class="t-cap" style="margin-top: var(--space-3)">{{ killMsg }}</p>
        </div>
        <div class="modal-foot">
          <button class="btn btn--secondary" type="button" :disabled="killBusy" @click="pendingKill = null">取消</button>
          <div class="spacer" style="flex: 1" />
          <button class="btn btn--danger" type="button" :disabled="killBusy" @click="confirmKill">
            <PwIcon name="trash" :size="15" /> 确认结束
          </button>
        </div>
      </div>
    </div>
  </section>
</template>
