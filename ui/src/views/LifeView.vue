<script setup lang="ts">
/**
 * 生活中心页（阶段8 · 11 §A）。
 *
 * 版式（UI-FUSION-FULL）：按设计稿 `ROUTES.life` 复刻 —— `page-head` +
 * `.life-grid`（每张卡 = 一个插件槽位：卡头「名称 / 来源 / 图标」+ 卡体）。
 * 卡片来源仍是真实数据（天气 API / SMTC 媒体会话 / 社交概览 / 使用时长聚合），
 * 设计稿里的演示卡片（日程 / 待办 / 剪贴板）在真实能力到位前不造假。
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
import PwIcon from '@/components/PwIcon.vue'
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

/** 播放进度（设计稿 .progress.thin 的填充比例；时长缺失时退化为 0） */
const mediaPercent = computed(() => {
  const s = media.value?.session
  if (!s || !s.duration_seconds) return 0
  return Math.max(0, Math.min(100, Math.round((s.position_seconds / s.duration_seconds) * 100)))
})

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
    <!-- page-head：标题 + 副标 + 右侧动作（设计稿 ROUTES.life 同构） -->
    <div class="page-head">
      <div class="grow">
        <h2 class="t-page">生活中心</h2>
        <div class="t-cap" style="margin-top: 2px">
          只展示结果，不展示配置 · 卡片来自插件，来源可追溯
        </div>
      </div>
      <button class="btn btn--secondary btn--sm" type="button" @click="socialConnectOpen = !socialConnectOpen">
        <PwIcon name="filter" :size="15" /> 管理卡片
      </button>
    </div>

    <div class="life-grid">
      <!-- ① 天气（系统卡片，来源：天气插件） -->
      <div class="life-card">
        <div class="row" style="justify-content: space-between">
          <span class="t-cap">天气</span>
          <span class="row" style="gap: var(--space-2)">
            <span class="t-cap" style="color: var(--text-4)">天气插件</span>
            <PwIcon name="cloud" :size="16" />
          </span>
        </div>

        <template v-if="weather && weather.reason !== 'no_city'">
          <div class="row" style="align-items: baseline; gap: var(--space-2)">
            <span class="t-num">{{ weather.current.temperature }}°</span>
            <span class="t-sm c2">{{ weather.current.weather }}</span>
          </div>
          <div class="t-cap">{{ weather.city }} · 数据来源：{{ weather.source }}</div>
          <div class="stack" style="gap: var(--space-2)">
            <div v-for="d in weather.daily" :key="d.date" class="row" style="justify-content: space-between">
              <span class="t-sm c2">{{ d.date }}</span>
              <span class="t-cap">{{ d.weather }} {{ d.min }}~{{ d.max }}°C</span>
            </div>
          </div>
        </template>
        <div v-else class="t-cap">
          {{ weather?.message || '未设置城市（不自动定位）' }}
        </div>

        <p v-if="weatherErr" class="t-cap" style="color: var(--danger)">加载失败：{{ weatherErr }}</p>

        <div class="row" style="gap: var(--space-2)">
          <label class="input" style="flex: 1; min-width: 0">
            <input v-model="cityInput" placeholder="手动输入城市（不自动定位）" @keyup.enter="saveCity" />
          </label>
          <button
            class="btn btn--secondary btn--sm"
            type="button"
            :disabled="weatherBusy || !cityInput.trim()"
            @click="saveCity"
          >
            查询
          </button>
        </div>
      </div>

      <!-- ② 正在播放（插件卡片，来源：音乐插件；只读 SMTC） -->
      <div class="life-card span2">
        <div class="row" style="justify-content: space-between">
          <span class="t-cap">正在播放</span>
          <span class="row" style="gap: var(--space-2)">
            <span class="t-cap" style="color: var(--text-4)">音乐插件</span>
            <PwIcon name="music" :size="16" />
          </span>
        </div>

        <template v-if="media?.session">
          <div class="row" style="gap: var(--space-3); align-items: center">
            <span class="app tint4"><PwIcon name="music" :size="20" /></span>
            <div class="grow" style="min-width: 0">
              <div class="t-sm" style="font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ media.session.title }}
              </div>
              <div class="t-cap">{{ media.session.artist }}</div>
            </div>
            <span class="t-cap mono">{{ media.session.status }}</span>
          </div>
          <div class="progress thin"><i :style="{ width: `${mediaPercent}%` }" /></div>
          <div class="row" style="justify-content: space-between">
            <span class="t-cap mono">{{ fmtSecs(media.session.position_seconds) }}</span>
            <span class="row" style="gap: var(--space-4); color: var(--text-2)">
              <button
                class="icon-btn lg"
                type="button"
                title="上一首"
                :disabled="mediaCtrlBusy"
                @click="control('previous')"
              >
                <PwIcon name="prev" :size="18" />
              </button>
              <button
                class="icon-btn lg"
                type="button"
                :title="media.session.status === 'PLAYING' ? '暂停' : '播放'"
                :disabled="mediaCtrlBusy"
                @click="control(media.session?.status === 'PLAYING' ? 'pause' : 'play')"
              >
                <PwIcon name="play" :size="20" />
              </button>
              <button
                class="icon-btn lg"
                type="button"
                title="下一首"
                :disabled="mediaCtrlBusy"
                @click="control('next')"
              >
                <PwIcon name="next" :size="18" />
              </button>
            </span>
            <span class="t-cap mono">{{ fmtSecs(media.session.duration_seconds) }}</span>
          </div>
        </template>
        <div v-else-if="media && !media.available" class="t-cap">
          {{ media.reason ?? '媒体会话不可用' }}
        </div>
        <div v-else class="t-cap">当前没有播放中的媒体</div>

        <div class="t-cap" style="color: var(--text-4)">只读系统媒体会话（SMTC），不保存播放历史</div>
      </div>

      <!-- ③ 消息概览（插件卡片，来源：消息插件；仅未读计数） -->
      <div class="life-card">
        <div class="row" style="justify-content: space-between">
          <span class="t-cap">消息</span>
          <span class="row" style="gap: var(--space-2)">
            <span class="t-cap" style="color: var(--text-4)">消息插件</span>
            <PwIcon name="message" :size="16" />
          </span>
        </div>

        <div v-if="socialItems.length" class="stack" style="gap: var(--space-2)">
          <div v-for="it in socialItems" :key="it.name" class="row" style="justify-content: space-between">
            <span class="t-sm c2">{{ it.name }}</span>
            <span class="row" style="gap: var(--space-2)">
              <span v-if="it.ok" class="badge" :class="it.unread ? 'badge--danger' : ''">
                {{ it.unread }}
              </span>
              <span v-else class="t-cap">{{ it.summary }}</span>
              <button class="icon-btn sm" type="button" title="移除" @click="removeService(it.name)">
                <PwIcon name="x" :size="14" />
              </button>
            </span>
          </div>
        </div>
        <div v-else class="t-cap">还没有连接的应用。连接后这里会显示未读概览。</div>

        <div class="t-cap" style="color: var(--text-4)">
          {{ socialNote || '仅未读计数，不存任何消息内容' }}
        </div>
      </div>

      <!-- ④ 今日使用（系统卡片；聚合秒数，不记窗口明细） -->
      <div class="life-card span2">
        <div class="row" style="justify-content: space-between">
          <span class="t-cap">今日使用</span>
          <span class="row" style="gap: var(--space-2)">
            <span class="t-cap" style="color: var(--text-4)">系统</span>
            <PwIcon name="clock" :size="16" />
          </span>
        </div>

        <p v-if="usageErr" class="t-cap" style="color: var(--danger)">加载失败：{{ usageErr }}</p>
        <template v-if="usage">
          <div class="row" style="align-items: baseline; gap: var(--space-2)">
            <span class="t-num">{{ Math.floor(usage.totalSeconds / 3600) }}</span>
            <span class="t-sm c2">小时 {{ Math.floor((usage.totalSeconds % 3600) / 60) }} 分钟</span>
          </div>
          <div v-if="usage.ranking.length" class="spark" style="height: 44px">
            <i
              v-for="r in usage.ranking"
              :key="r.app_name"
              :class="{ hi: r.seconds / maxRankSeconds > 0.7 }"
              :style="{ height: `${Math.max(6, Math.round((r.seconds / maxRankSeconds) * 100))}%` }"
              :title="`${r.app_name} · ${fmtDuration(r.seconds)}`"
            />
          </div>
          <div v-else class="t-cap">暂无数据（前台采样默认 30s 一次，稍后再看）。</div>
          <div class="stack" style="gap: var(--space-2)">
            <div v-for="r in usage.ranking.slice(0, 5)" :key="r.app_name" class="row">
              <span class="t-sm c2" style="min-width: 110px">{{ r.app_name }}</span>
              <span class="progress thin grow"><i :style="{ width: `${(r.seconds / maxRankSeconds) * 100}%` }" /></span>
              <span class="t-cap mono">{{ fmtDuration(r.seconds) }}</span>
            </div>
          </div>
        </template>
        <div class="t-cap" style="color: var(--text-4)">只存「按天 + 应用」的聚合秒数，不记录窗口切换明细</div>
      </div>

      <!-- ⑤ 从插件市场添加卡片（设计稿虚卡引导；真实能力：连接应用） -->
      <div class="life-card span2" style="border-style: dashed">
        <div class="row" style="justify-content: space-between">
          <span class="t-sm" style="font-weight: 600">从插件市场添加卡片</span>
          <PwIcon name="plus" :size="16" />
        </div>
        <div class="t-cap">
          已连接 {{ services.length }} 个应用。把社交/邮箱接进来，消息概览与未读提醒会出现在这里。
        </div>
        <button v-if="!socialConnectOpen" class="btn btn--secondary btn--sm" type="button" style="align-self: flex-start" @click="socialConnectOpen = true">
          <PwIcon name="plus" :size="14" /> 连接应用
        </button>

        <div v-if="socialConnectOpen" class="stack" style="gap: var(--space-3)">
          <div class="row" style="gap: var(--space-2)">
            <label class="input" style="flex: 1; min-width: 0">
              <input v-model="newService.name" placeholder="显示名称（如：QQ邮箱）" />
            </label>
            <select v-model="newService.type" class="select">
              <option value="demo">体验用演示源</option>
              <option value="imap">我的邮箱（IMAP）</option>
            </select>
          </div>
          <div v-if="newService.type === 'imap'" class="stack" style="gap: var(--space-2)">
            <div class="row" style="gap: var(--space-2)">
              <label class="input" style="flex: 1; min-width: 0"><input v-model="newService.host" placeholder="IMAP 服务器" /></label>
              <label class="input" style="flex: 1; min-width: 0"><input v-model="newService.user" placeholder="账号" /></label>
              <label class="input" style="width: 96px"><input v-model.number="newService.port" placeholder="993" /></label>
            </div>
            <div class="t-cap">密码在保存后通过系统凭据库单独设置，不进配置文件与数据库。</div>
          </div>
          <div class="row" style="gap: var(--space-2)">
            <button class="btn btn--primary btn--sm" type="button" :disabled="socialBusy || !newService.name.trim()" @click="addService">
              连接
            </button>
            <button class="btn btn--ghost btn--sm" type="button" @click="socialConnectOpen = false">取消</button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
