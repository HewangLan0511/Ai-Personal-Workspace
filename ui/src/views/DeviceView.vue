<script setup lang="ts">
/**
 * 设备中心页（阶段8 · 11 §B）。
 *
 * 版式：顶部硬件指标（CPU/内存/磁盘 + 5 分钟曲线）→ 进程管理 → 模式健康度。
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
import { logger } from '@/utils/logger'

const snapshot = ref<MetricsSnapshot | null>(null)
const procs = ref<ProcInfo[]>([])
const health = ref<ModeHealth | null>(null)
const pendingKill = ref<ProcInfo | null>(null)
const killBusy = ref(false)
const killMsg = ref('')

const memPct = computed(() => {
  const s = snapshot.value?.current
  if (!s || !s.mem_total) return 0
  return Math.round((s.mem_used / s.mem_total) * 100)
})

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

/** 5 分钟 CPU 曲线（sparkline，直接 SVG 折线） */
const sparkPoints = computed(() => {
  const h = snapshot.value?.history ?? []
  if (h.length < 2) return ''
  return h
    .map((p, i) => `${(i / (h.length - 1)) * 300},${40 - (p.cpu / 100) * 38}`)
    .join(' ')
})

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
    <h2>设备中心</h2>
    <p class="stage-note">硬件指标（5 分钟内存缓冲，不落库）· 运行程序管理 · 模式健康度。</p>

    <div class="metric-row">
      <div class="metric">
        <span class="label">CPU</span>
        <span class="value">{{ Math.round(snapshot?.current.cpu ?? 0) }}%</span>
      </div>
      <div class="metric">
        <span class="label">内存</span>
        <span class="value">{{ memPct }}%</span>
        <span class="muted small">
          {{ fmtBytes(snapshot?.current.mem_used ?? 0) }} / {{ fmtBytes(snapshot?.current.mem_total ?? 0) }}
        </span>
      </div>
      <div v-for="d in snapshot?.current.disks ?? []" :key="d.letter" class="metric">
        <span class="label">磁盘 {{ d.letter }}</span>
        <span class="muted small">
          空闲 {{ fmtBytes(d.free_bytes) }} / {{ fmtBytes(d.total_bytes) }}
        </span>
      </div>
    </div>

    <div class="card">
      <h3>CPU · 最近 5 分钟</h3>
      <svg viewBox="0 0 300 40" class="spark" preserveAspectRatio="none">
        <polyline :points="sparkPoints" fill="none" stroke="#4a90d9" stroke-width="1.5" />
      </svg>
      <p v-if="!sparkPoints" class="muted">正在积累历史数据…（默认每 2s 采样一次）</p>
    </div>

    <div class="card">
      <h3>运行中的程序</h3>
      <p class="muted small">结束进程是破坏性操作，需要二次确认。</p>
      <table class="proc-table">
        <thead>
          <tr><th>进程</th><th>PID</th><th>CPU</th><th>内存</th><th></th></tr>
        </thead>
        <tbody>
          <tr v-for="p in procs.slice(0, 50)" :key="p.pid">
            <td>{{ p.name }}</td>
            <td>{{ p.pid }}</td>
            <td>{{ p.cpu_percent.toFixed(1) }}%</td>
            <td>{{ fmtBytes(p.mem_bytes) }}</td>
            <td><button class="danger" @click="askKill(p)">结束</button></td>
          </tr>
        </tbody>
      </table>
      <p v-if="!procs.length" class="muted">正在枚举进程…</p>
    </div>

    <div class="card">
      <h3>模式健康度</h3>
      <p class="muted small">按模式查看绑定软件的历史启动次数与今日实际使用时长。</p>
      <div v-for="m in health?.modes ?? []" :key="m.modeId" class="mode-block">
        <strong>{{ m.modeName }}</strong>
        <ul class="plain">
          <li v-for="a in m.apps" :key="a.name">
            {{ a.name }} · 启动 {{ a.launchCount }} 次 · 今日使用 {{ Math.round(a.usedSecondsToday / 60) }} 分钟
          </li>
        </ul>
      </div>
      <p v-if="!health?.modes.length" class="muted">尚无模式数据。</p>
    </div>

    <!-- 红线 V5：二次确认 -->
    <div v-if="pendingKill" class="confirm-mask" @click.self="pendingKill = null">
      <div class="confirm-box">
        <p><strong>确定要结束「{{ pendingKill.name }}」（pid {{ pendingKill.pid }}）吗？</strong></p>
        <p class="muted">未保存的数据可能丢失。此操作不可撤销。</p>
        <div class="row">
          <button :disabled="killBusy" @click="pendingKill = null">取消</button>
          <button class="danger" :disabled="killBusy" @click="confirmKill">确认结束</button>
        </div>
        <p v-if="killMsg" class="muted">{{ killMsg }}</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.metric-row { display: flex; gap: 24px; flex-wrap: wrap; margin: 12px 0; }
.metric { display: flex; flex-direction: column; }
.metric .label { color: var(--pw-muted, #888); font-size: 0.85em; }
.metric .value { font-size: 1.4em; font-weight: 600; }
.card { border: 1px solid var(--pw-border, #d8d8d8); border-radius: 10px; padding: 14px 16px; margin: 12px 0; background: var(--pw-card, #fff); }
.spark { width: 100%; height: 60px; }
.proc-table { width: 100%; border-collapse: collapse; font-size: 0.9em; }
.proc-table th, .proc-table td { text-align: left; padding: 4px 8px; border-bottom: 1px solid var(--pw-border, #eee); }
.mode-block { margin: 8px 0; }
.plain { list-style: none; padding: 0; margin: 4px 0; }
.muted { color: var(--pw-muted, #888); }
.small { font-size: 0.85em; }
.row { display: flex; gap: 8px; }
.danger { color: #b00; border-color: #b00; }
button { cursor: pointer; }
.confirm-mask { position: fixed; inset: 0; background: rgba(0, 0, 0, 0.35); display: flex; align-items: center; justify-content: center; z-index: 50; }
.confirm-box { background: var(--pw-card, #fff); border-radius: 10px; padding: 20px 24px; max-width: 420px; }
</style>
