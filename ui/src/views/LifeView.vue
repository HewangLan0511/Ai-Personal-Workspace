<script setup lang="ts">
/**
 * 生活中心页（阶段8 · 11 §A）。
 *
 * 版式：四卡片 —— 天气（A1）/ 音乐（A2）/ 社交概览（A3）/ 健康生活（A4）。
 *
 * 隐私与红线在界面上的体现：
 * - 天气城市**手动设置**（11 §A1"不要默认获取系统定位"），无城市时给设置入口；
 * - 音乐只读 SMTC 当前会话，不存播放历史；
 * - 社交只显示未读数与来源摘要，服务由用户显式添加，配置不含密码（密码走凭据库）；
 * - 使用时长只展示聚合结果（今日总时长 / 排行 / 周趋势）。
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'

import {
  lifeApi,
  type MediaSession,
  type SocialItem,
  type SocialServiceConfig,
  type UsageToday,
  type WeatherInfo,
} from '@/api/lifeService'
import { logger } from '@/utils/logger'

// ---- 天气（A1）----
const cityInput = ref('')
const weather = ref<WeatherInfo | null>(null)
const weatherErr = ref('')
const weatherBusy = ref(false)

async function loadWeather(city?: string) {
  weatherBusy.value = true
  weatherErr.value = ''
  try {
    const w = await lifeApi.weather(city)
    weather.value = w
  } catch (e) {
    weatherErr.value = String(e)
    logger.warn('[life]', 'weather 加载失败：' + String(e))
  } finally {
    weatherBusy.value = false
  }
}

function saveCity() {
  const city = cityInput.value.trim()
  if (!city) return
  void loadWeather(city)
}

// ---- 音乐（A2）----
const media = ref<MediaSession | null>(null)
const mediaCtrlBusy = ref(false)

async function loadMedia() {
  try {
    media.value = await lifeApi.mediaNow()
  } catch (e) {
    logger.warn('[life]', 'media 加载失败：' + String(e))
  }
}

async function control(action: 'play' | 'pause' | 'next' | 'previous') {
  mediaCtrlBusy.value = true
  try {
    await lifeApi.mediaControl(action)
    await loadMedia()
  } catch (e) {
    logger.warn('[life]', 'media control 失败：' + String(e))
  } finally {
    mediaCtrlBusy.value = false
  }
}

const fmtSecs = (s: number) => {
  const m = Math.floor(s / 60)
  const r = Math.floor(s % 60)
  return `${m}:${String(r).padStart(2, '0')}`
}

// ---- 社交概览（A3）----
const socialItems = ref<SocialItem[]>([])
const socialNote = ref('')
const services = ref<SocialServiceConfig[]>([])
const newService = reactive({ name: '', type: 'demo' as 'demo' | 'imap', host: '', port: 993, user: '' })
const socialBusy = ref(false)
/** 交互原则（2026-09-13）：未连接服务时只给「连接应用」入口，配置表单不默认铺开。 */
const socialConnectOpen = ref(false)

async function loadSocial() {
  socialBusy.value = true
  try {
    const [ov, cfg] = await Promise.all([lifeApi.socialOverview(), lifeApi.socialConfigGet()])
    socialItems.value = ov.items
    socialNote.value = ov.note
    services.value = cfg.services
  } catch (e) {
    logger.warn('[life]', 'social 加载失败：' + String(e))
  } finally {
    socialBusy.value = false
  }
}

async function addService() {
  const name = newService.name.trim()
  if (!name) return
  const svc: SocialServiceConfig = { name, type: newService.type }
  if (newService.type === 'imap') {
    svc.host = newService.host.trim()
    svc.port = Number(newService.port) || 993
    svc.user = newService.user.trim()
    svc.credRef = `social.imap.${name}`
  }
  const next = [...services.value.filter((s) => s.name !== name), svc]
  try {
    await lifeApi.socialConfigPut(next)
    newService.name = ''
    await loadSocial()
  } catch (e) {
    logger.warn('[life]', '保存社交配置失败：' + String(e))
  }
}

async function removeService(name: string) {
  try {
    await lifeApi.socialConfigPut(services.value.filter((s) => s.name !== name))
    await loadSocial()
  } catch (e) {
    logger.warn('[life]', '移除社交服务失败：' + String(e))
  }
}

// ---- 健康生活（A4）----
const usage = ref<UsageToday | null>(null)
const usageErr = ref('')

const fmtDuration = (secs: number) => {
  const h = Math.floor(secs / 3600)
  const m = Math.floor((secs % 3600) / 60)
  return h > 0 ? `${h} 小时 ${m} 分` : `${m} 分钟`
}

const maxRankSeconds = computed(() =>
  Math.max(1, ...(usage.value?.ranking ?? []).map((r) => r.seconds)),
)

async function loadUsage() {
  try {
    usage.value = await lifeApi.usageToday()
    usageErr.value = ''
  } catch (e) {
    usageErr.value = String(e)
    logger.warn('[life]', 'usage 加载失败：' + String(e))
  }
}

let timer: number | undefined

onMounted(() => {
  void loadWeather()
  void loadMedia()
  void loadSocial()
  void loadUsage()
  // 天气侧有 30min 缓存，轮询只用于媒体会话/使用时长的轻刷新（2 分钟，远低于高频线）
  timer = window.setInterval(() => {
    void loadMedia()
    void loadUsage()
  }, 120_000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <section class="page-skeleton">
    <h2>生活中心</h2>
    <p class="stage-note">天气 · 音乐 · 社交概览 · 健康生活 —— 全部本地优先，不存聊天内容、不自动定位。</p>

    <div class="life-grid">
      <!-- A1 天气 -->
      <div class="card">
        <h3>天气</h3>
        <div class="row">
          <input v-model="cityInput" placeholder="手动输入城市（不自动定位）" @keyup.enter="saveCity" />
          <button :disabled="weatherBusy || !cityInput.trim()" @click="saveCity">查询</button>
        </div>
        <p v-if="weatherErr" class="muted">加载失败：{{ weatherErr }}</p>
        <template v-if="weather">
          <template v-if="weather.reason === 'no_city'">
            <p class="muted">{{ weather.message }}</p>
          </template>
          <template v-else>
            <p class="big">
              {{ weather.current.temperature }}°C · {{ weather.current.weather }}
              <span class="muted">（{{ weather.city }}）</span>
            </p>
            <p class="muted small">数据来源：{{ weather.source }}</p>
            <ul class="plain">
              <li v-for="d in weather.daily" :key="d.date">
                {{ d.date }} {{ d.weather }} {{ d.min }}~{{ d.max }}°C
              </li>
            </ul>
          </template>
        </template>
      </div>

      <!-- A2 音乐 -->
      <div class="card">
        <h3>正在播放</h3>
        <template v-if="media?.session">
          <p class="big">{{ media.session.title }}</p>
          <p class="muted">{{ media.session.artist }}</p>
          <p class="muted small">
            {{ fmtSecs(media.session.position_seconds) }} / {{ fmtSecs(media.session.duration_seconds) }}
            · {{ media.session.status }}
          </p>
          <div class="row">
            <button :disabled="mediaCtrlBusy" @click="control('previous')">上一首</button>
            <button :disabled="mediaCtrlBusy" @click="control(media.session?.status === 'PLAYING' ? 'pause' : 'play')">
              {{ media.session.status === 'PLAYING' ? '暂停' : '播放' }}
            </button>
            <button :disabled="mediaCtrlBusy" @click="control('next')">下一首</button>
          </div>
        </template>
        <p v-else-if="media && !media.available" class="muted">
          {{ media.reason ?? '媒体会话不可用' }}
        </p>
        <p v-else class="muted">当前没有播放中的媒体</p>
        <p class="muted small">只读系统媒体会话（SMTC），不保存播放历史。</p>
      </div>

      <!-- A3 社交概览（2026-09-13：结果优先，未连接只给「连接应用」，配置收进弹窗） -->
      <div class="card">
        <h3>消息概览</h3>
        <p class="muted small">{{ socialNote || '仅未读计数，不存任何消息内容。' }}</p>
        <template v-if="socialItems.length">
          <ul class="plain">
            <li v-for="it in socialItems" :key="it.name">
              <strong>{{ it.name }}</strong>
              <span v-if="it.ok">未读 {{ it.unread }} · {{ it.summary }}</span>
              <span v-else class="muted">{{ it.summary }}</span>
              <button class="link" @click="removeService(it.name)">移除</button>
            </li>
          </ul>
        </template>
        <template v-else>
          <p class="muted">还没有连接的应用。连接后这里会显示未读概览。</p>
          <button v-if="!socialConnectOpen" @click="socialConnectOpen = true">连接应用</button>
        </template>
        <div v-if="socialConnectOpen" class="connect-box">
          <div class="row">
            <input v-model="newService.name" placeholder="显示名称（如：QQ邮箱）" />
            <select v-model="newService.type">
              <option value="demo">体验用演示源</option>
              <option value="imap">我的邮箱（IMAP）</option>
            </select>
          </div>
          <details v-if="newService.type === 'imap'" class="connect-advanced">
            <summary>邮箱服务器设置</summary>
            <div class="row">
              <input v-model="newService.host" placeholder="IMAP 服务器" />
              <input v-model="newService.user" placeholder="账号" />
              <input v-model.number="newService.port" placeholder="993" />
            </div>
            <p class="muted small">密码在保存后通过系统凭据库单独设置，不进配置文件与数据库。</p>
          </details>
          <div class="row">
            <button :disabled="socialBusy || !newService.name.trim()" @click="addService">连接</button>
            <button @click="socialConnectOpen = false">取消</button>
          </div>
        </div>
      </div>

      <!-- A4 健康生活 -->
      <div class="card">
        <h3>屏幕使用时间</h3>
        <p v-if="usageErr" class="muted">加载失败：{{ usageErr }}</p>
        <template v-if="usage">
          <p class="big">今日 {{ fmtDuration(usage.totalSeconds) }}</p>
          <ul class="plain">
            <li v-for="r in usage.ranking" :key="r.app_name">
              <span class="rank-name">{{ r.app_name }}</span>
              <span class="bar" :style="{ width: `${(r.seconds / maxRankSeconds) * 60}%` }" />
              {{ fmtDuration(r.seconds) }}
            </li>
          </ul>
          <p v-if="!usage.ranking.length" class="muted">暂无数据（前台采样默认 30s 一次，稍后再看）。</p>
        </template>
        <p class="muted small">只存"按天 + 应用"的聚合秒数，不记录窗口切换明细。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.life-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
}
.card {
  border: 1px solid var(--pw-border, #d8d8d8);
  border-radius: 10px;
  padding: 14px 16px;
  background: var(--pw-card, #fff);
}
.big { font-size: 1.3em; margin: 6px 0; }
.muted { color: var(--pw-muted, #888); }
.small { font-size: 0.85em; }
.row { display: flex; gap: 8px; margin: 8px 0; flex-wrap: wrap; }
.row input, .row select { flex: 1; min-width: 90px; }
.plain { list-style: none; padding: 0; margin: 6px 0; }
.plain li { display: flex; align-items: center; gap: 8px; padding: 3px 0; flex-wrap: wrap; }
.rank-name { min-width: 110px; display: inline-block; }
.bar { display: inline-block; height: 10px; background: var(--pw-accent, #4a90d9); border-radius: 5px; }
.connect-box { border: 1px solid var(--pw-border, #d8d8d8); border-radius: 8px; padding: 10px; margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }
.connect-advanced { border: 1px dashed var(--pw-border, #d8d8d8); border-radius: 6px; padding: 6px 10px; }
.connect-advanced summary { cursor: pointer; color: var(--pw-muted, #888); }
.link { background: none; border: none; color: #b00; cursor: pointer; padding: 0 4px; }
button { cursor: pointer; }
</style>
