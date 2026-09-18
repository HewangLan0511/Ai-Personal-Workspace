<script setup lang="ts">
/**
 * 个人档案页（阶段7 · 10 §6；TECH-05-C §P0-2 落地 UI-07/UI-08 的视觉与交互）。
 *
 * 版式：主体信息头（头像 + 昵称 + 方向 + 签名 + 标签）→ 中部左技能树/右项目经历 → 底部成长时间线。
 *
 * ## 两个**独立结构**（刻意不合并）
 * 原型把档案拆成 `state.profile.fields`（基础字段）与 `profileExts`（扩展块）两块，
 * 本页保持同样的划分：
 *   - 基础字段（`profile_basic` 表）：昵称 / 方向 / 签名 / 兴趣标签 / 头像；
 *   - 扩展块（各自独立的表）：技能 / 项目经历 / 成长时间线。
 * 编辑基础字段不会读到、也不会写回扩展块的数据。
 *
 * ## 头像为什么不进数据库（P0-2 的硬约束）
 * `profile_basic` 表**不新增列**。头像是一个"单值偏好"，落在已登记的 config 键
 * `profile.avatar` 上（core/src/db/config.rs 的 KEYS），走既有 get_config / put_config。
 *
 * ## 红线在界面上的体现
 * - 待确认建议条置于页首（10 §5"在档案页顶部显示 N 条待确认的档案变化"），
 *   建议不确认就**不进档案**；支持逐条确认 / 批量确认 / 忽略 / 永久拒绝某类；
 * - 首次使用只引导填 3 个字段（10 §1），不做长表单；
 * - 技能按分类分组、默认折叠（10 §禁止事项：超过 20 项不得堆砌）；
 * - 导出前明确告知导出内容（10 §7 隐私要求）。
 */
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'

import { configApi } from '@/api/configService'
import {
  profileApi,
  type ProjectEntryInput,
  type SkillCategory,
  type SuggestionKind,
  type TimelineInput,
} from '@/api/profileService'
import PwButton from '@/components/ui/PwButton.vue'
import PwCard from '@/components/ui/PwCard.vue'
import PwChip from '@/components/ui/PwChip.vue'
import PwDrawer from '@/components/ui/PwDrawer.vue'
import PwIcon from '@/components/PwIcon.vue'
import { toast } from '@/composables/useToast'
import { usePageEntrance } from '@/motion'
import { useProfileStore } from '@/stores/profile'
import { logger } from '@/utils/logger'

const store = useProfileStore()

/**
 * 页面元素进出场（`data-enter` → `.enter-up` 错峰，同一套 token 与步长公式）。
 * 档案页是列表页（技能/项目/时间线会变），**每次进入都播** —— 只在第一次播
 * 等于之后都看不到（首页保留设计稿的"每会话一次"语义，见 DashboardView）。
 */
const rootEl = ref<HTMLElement | null>(null)
usePageEntrance(rootEl, { key: 'profile' })

// ---- 首次引导 / 基础信息编辑 ----
const onboarding = reactive({ name: '', direction: '', motto: '' })
const editingBasic = ref(false)
/** 编辑卡表单（UI-07/UI-08：昵称 / 方向 / 签名 / 标签）。 */
const basicForm = reactive({ name: '', direction: '', motto: '' })
/** 标签编辑草稿 —— 取消时整体丢弃，不污染已保存的兴趣标签。 */
const tagDraft = ref<string[]>([])
const tagInput = ref('')

// ---- 头像（UI-08）----
/**
 * 头像**不改数据库 schema**（P0-2 明确禁止）：`profile_basic` 表只有
 * name/direction/interests/motto，没有头像列。头像是一个单值偏好，
 * 因此落在已登记的 config 键 `profile.avatar` 上（core/src/db/config.rs），
 * 走既有的 get_config / put_config 通道 —— **不是**假装持久化：
 * core 不可达时 configService 会降级到 localStorage 并记 warn。
 */
const AVATAR_KEY = 'profile.avatar'
const AVATAR_PRESETS = ['💻', '🧠', '✍️', '📊', '🚀', '🎯', '🐱', '🌈']
const SIGNATURE_MAX = 60
/** 已保存的头像（空串 = 用昵称首字母）。 */
const avatar = ref('')
const avatarOpen = ref(false)
/** 抽屉内的草稿（点选即时预览；保存才提交、取消还原）。 */
const avatarDraft = ref('')

/** 推荐标签（与档案标签同一语义，只是"一键加上去"）。 */
const TAG_SUGGESTIONS = ['深度学习', 'PyTorch', 'Rust', '嵌入式', '开源', '写作', '摄影', '阅读']

// ---- 技能 ----
const newSkill = reactive({ name: '', level: 50, category: 'other' as SkillCategory })
const skillBusy = ref(false)

// ---- 项目经历 ----
const newProject = reactive({ name: '', role: '', summary: '', techStack: '', startDate: '' })
const projectBusy = ref(false)

// ---- 时间线 ----
const newEvent = reactive({ eventDate: '', title: '', description: '', type: 'learning' })
const eventBusy = ref(false)

// ---- 建议 ----
const selectedSuggestions = ref<number[]>([])
const suggestionBusy = ref(false)

// ---- 导出 ----
const exporting = ref(false)
const exportText = ref('')

const basic = computed(() => store.basic)
const isFirstUse = computed(() => store.loaded && !basic.value.name && !basic.value.motto)
const skills = computed(() => store.data?.skills ?? [])
const confirmedSkills = computed(() => skills.value.filter((s) => s.confirmed))
const projects = computed(() => (store.data?.projects ?? []).filter((p) => p.confirmed))
const timeline = computed(() => (store.data?.timeline ?? []).filter((e) => e.confirmed))
const suggestions = computed(() => store.data?.suggestions ?? [])
const rejectedKinds = computed(() => store.data?.rejectedKinds ?? [])

const KIND_LABEL: Record<SuggestionKind, string> = {
  timeline: '时间线',
  skill: '技能',
  project: '项目经历',
}

/** 技能按分类分组（分类内已按 level 降序）；分组折叠 —— 10 §禁止事项"不堆砌" */
const skillGroups = computed(() => {
  const labels: Record<SkillCategory, string> = {
    lang: '编程语言',
    framework: '框架',
    tool: '工具',
    domain: '领域知识',
    other: '其他',
  }
  const order: SkillCategory[] = ['lang', 'framework', 'tool', 'domain', 'other']
  return order
    .map((cat) => ({
      category: cat,
      label: labels[cat],
      items: confirmedSkills.value.filter((s) => s.category === cat),
    }))
    .filter((g) => g.items.length > 0)
})

/** 时间线按 年-月 分组（timeline_list 已按日期倒序） */
const timelineGroups = computed(() => {
  const groups: { ym: string; items: typeof timeline.value }[] = []
  for (const e of timeline.value) {
    const ym = e.eventDate.slice(0, 7)
    const last = groups[groups.length - 1]
    if (last && last.ym === ym) last.items.push(e)
    else groups.push({ ym, items: [e] })
  }
  return groups
})

const avatarChar = computed(() => avatar.value || (basic.value.name || '用户').charAt(0))
const signatureLeft = computed(() => SIGNATURE_MAX - basicForm.motto.length)

/** Esc 取消编辑（UI-07/UI-08 明确要求）—— 只在编辑态挂监听。 */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Escape' && editingBasic.value) {
    e.stopPropagation()
    cancelEditBasic()
  }
}

onMounted(async () => {
  await store.init()
  if (!isFirstUse.value) {
    Object.assign(onboarding, {
      name: basic.value.name,
      direction: basic.value.direction,
      motto: basic.value.motto,
    })
  }
  // 头像：走既有 config 通道读取（键 profile.avatar）。
  // 读失败保持首字母头像 —— 不阻塞页面，也不假装读到了。
  try {
    const stored = await configApi.get<string>(AVATAR_KEY, '')
    if (typeof stored === 'string') avatar.value = stored
  } catch (e) {
    logger.warn('profile', `读取头像失败（保持首字母头像）：${String(e)}`)
  }
})

onUnmounted(() => {
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
})

// ---------------------------------------------------------------- 基础信息

async function submitOnboarding(): Promise<void> {
  if (!onboarding.name.trim()) return
  try {
    await store.saveBasic({
      name: onboarding.name,
      direction: onboarding.direction,
      motto: onboarding.motto,
      interests: [],
    })
  } catch (e) {
    logger.warn('profile', `保存基础信息失败：${String(e)}`)
  }
}

/** 打开**原位**编辑卡（不新开页面、不遮挡整页 —— UI-07 的形态）。 */
function startEditBasic(): void {
  Object.assign(basicForm, {
    name: basic.value.name,
    direction: basic.value.direction,
    motto: basic.value.motto,
  })
  tagDraft.value = [...basic.value.interests]
  tagInput.value = ''
  editingBasic.value = true
  if (typeof window !== 'undefined') window.addEventListener('keydown', onKeydown)
}

function cancelEditBasic(): void {
  editingBasic.value = false
  tagDraft.value = []
  tagInput.value = ''
  if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
  toast.info('已取消编辑')
}

function addTag(): void {
  const v = tagInput.value.trim()
  if (!v) return
  if (tagDraft.value.includes(v)) {
    toast.info(`标签「${v}」已存在`)
    return
  }
  tagDraft.value.push(v)
  tagInput.value = ''
}

function addSuggestedTag(t: string): void {
  if (!tagDraft.value.includes(t)) tagDraft.value.push(t)
}

function removeTag(index: number): void {
  tagDraft.value.splice(index, 1)
}

/** 还没加进来的推荐标签（点一下即加）。 */
const suggestLeft = computed(() => TAG_SUGGESTIONS.filter((s) => !tagDraft.value.includes(s)))

/**
 * 保存基础信息。
 *
 * **接的是真实 Profile 能力**（`profileStore.saveBasic` → `profile_basic` 表），
 * 不是本地状态：保存成功后由 core 的 `PROFILE_UPDATED` 事件驱动 `reload()`，
 * 页面显示的值来自数据库而不是表单。
 *
 * 结构上有一件事刻意保持**两个独立结构**（P0-2 要求）：
 *   - 基础字段（本编辑卡 = 原型的 `profile.fields`）→ `profile_basic` 表；
 *   - 扩展块（技能 / 项目 / 时间线 = 原型的 `profileExts`）→ 各自的表。
 *   两者不合并成一个对象，也不互相覆盖。
 */
async function saveBasic(): Promise<void> {
  const name = basicForm.name.trim()
  if (!name) {
    toast.error('昵称不能为空')
    return
  }
  try {
    await store.saveBasic({
      name,
      direction: basicForm.direction.trim(),
      motto: basicForm.motto.trim(),
      interests: [...tagDraft.value],
    })
    editingBasic.value = false
    tagDraft.value = []
    tagInput.value = ''
    if (typeof window !== 'undefined') window.removeEventListener('keydown', onKeydown)
    toast.success('个人资料已更新')
  } catch (e) {
    // 失败保持编辑态（用户不必重敲）—— 与 UI-07 预留的失败路径一致
    logger.warn('profile', `保存基础信息失败：${String(e)}`)
    toast.error('保存失败，请稍后重试')
  }
}

// ---------------------------------------------------------------- 头像（UI-08）

function openAvatarPicker(): void {
  avatarDraft.value = avatar.value
  avatarOpen.value = true
}

function setAvatarDraft(v: string): void {
  avatarDraft.value = v
}

/**
 * 上传图片入口：与设计稿一致，属于**预留入口，尚未接入**。
 * 点选后如实告知「接入后开放」，不伪造上传成功。
 */
function pickAvatarImage(): void {
  toast.info('图片上传为预留入口，接入后开放')
}

/** 保存头像：写已登记的 config 键；失败如实提示，不假装成功。 */
async function saveAvatar(): Promise<void> {
  const next = avatarDraft.value
  try {
    await configApi.put(AVATAR_KEY, next)
    avatar.value = next
    avatarOpen.value = false
    toast.success('头像已更新')
  } catch (e) {
    logger.warn('profile', `保存头像失败：${String(e)}`)
    toast.error('保存头像失败，请稍后重试')
  }
}

// ---------------------------------------------------------------- 技能

async function addSkill(): Promise<void> {
  if (!newSkill.name.trim() || skillBusy.value) return
  skillBusy.value = true
  try {
    await profileApi.skillAdd({ ...newSkill })
    newSkill.name = ''
    await store.reload()
  } catch (e) {
    alert(String(e))
  } finally {
    skillBusy.value = false
  }
}

async function setLevel(id: number, level: number): Promise<void> {
  try {
    await profileApi.skillEdit(id, { level })
    await store.reload()
  } catch (e) {
    logger.warn('profile', `调整技能等级失败：${String(e)}`)
  }
}

async function removeSkill(id: number): Promise<void> {
  if (!confirm('删除这条技能？')) return
  try {
    await profileApi.skillRemove(id)
    await store.reload()
  } catch (e) {
    logger.warn('profile', `删除技能失败：${String(e)}`)
  }
}

// ---------------------------------------------------------------- 项目经历

async function addProject(): Promise<void> {
  if (!newProject.name.trim() || projectBusy.value) return
  projectBusy.value = true
  try {
    const input: ProjectEntryInput = {
      name: newProject.name,
      role: newProject.role || null,
      summary: newProject.summary || null,
      techStack: newProject.techStack
        .split(/[、,，;；\s]+/)
        .map((s) => s.trim())
        .filter(Boolean),
      startDate: newProject.startDate || null,
      status: 'done',
    }
    await profileApi.projectAdd(input)
    Object.assign(newProject, { name: '', role: '', summary: '', techStack: '', startDate: '' })
    await store.reload()
  } catch (e) {
    alert(String(e))
  } finally {
    projectBusy.value = false
  }
}

async function removeProject(id: number): Promise<void> {
  if (!confirm('从档案删除这条项目经历？')) return
  try {
    await profileApi.projectRemove(id)
    await store.reload()
  } catch (e) {
    logger.warn('profile', `删除项目经历失败：${String(e)}`)
  }
}

// ---------------------------------------------------------------- 时间线

async function addEvent(): Promise<void> {
  if (!newEvent.title.trim() || !newEvent.eventDate || eventBusy.value) return
  eventBusy.value = true
  try {
    const input: TimelineInput = {
      eventDate: newEvent.eventDate,
      title: newEvent.title,
      description: newEvent.description || null,
      type: newEvent.type as TimelineInput['type'],
    }
    await profileApi.timelineAdd(input)
    Object.assign(newEvent, { eventDate: '', title: '', description: '', type: 'learning' })
    await store.reload()
  } catch (e) {
    alert(String(e))
  } finally {
    eventBusy.value = false
  }
}

async function removeEvent(id: number): Promise<void> {
  if (!confirm('删除这条时间线记录？')) return
  try {
    await profileApi.timelineRemove(id)
    await store.reload()
  } catch (e) {
    logger.warn('profile', `删除时间线失败：${String(e)}`)
  }
}

// ---------------------------------------------------------------- 建议（硬关口）

function togglePick(id: number): void {
  const i = selectedSuggestions.value.indexOf(id)
  if (i >= 0) selectedSuggestions.value.splice(i, 1)
  else selectedSuggestions.value.push(id)
}

async function confirmOne(id: number): Promise<void> {
  if (suggestionBusy.value) return
  suggestionBusy.value = true
  try {
    await store.confirmSuggestions([id])
    selectedSuggestions.value = selectedSuggestions.value.filter((x) => x !== id)
  } catch (e) {
    alert(String(e))
  } finally {
    suggestionBusy.value = false
  }
}

async function confirmSelected(): Promise<void> {
  if (selectedSuggestions.value.length === 0 || suggestionBusy.value) return
  suggestionBusy.value = true
  try {
    await store.confirmSuggestions([...selectedSuggestions.value])
    selectedSuggestions.value = []
  } catch (e) {
    alert(String(e))
  } finally {
    suggestionBusy.value = false
  }
}

async function ignoreOne(id: number): Promise<void> {
  try {
    await store.ignoreSuggestions([id])
    selectedSuggestions.value = selectedSuggestions.value.filter((x) => x !== id)
  } catch (e) {
    logger.warn('profile', `忽略建议失败：${String(e)}`)
  }
}

async function rejectThisKind(kind: SuggestionKind): Promise<void> {
  if (
    !confirm(`永久拒绝全部「${KIND_LABEL[kind]}」类建议？之后这类变化不会再出现在待确认里。`)
  )
    return
  try {
    await store.rejectKind(kind)
  } catch (e) {
    logger.warn('profile', `拒绝建议失败：${String(e)}`)
  }
}

function suggestionDetail(kind: SuggestionKind, payload: Record<string, unknown>): string {
  if (kind === 'skill') return `技能「${payload.name ?? ''}」等级 ${payload.level ?? 0}`
  if (kind === 'project') return `项目「${payload.name ?? ''}」`
  return `${payload.eventDate ?? ''} 「${payload.title ?? ''}」`
}

// ---------------------------------------------------------------- 导出

async function doExport(): Promise<void> {
  if (exporting.value) return
  exporting.value = true
  try {
    exportText.value = await profileApi.exportMarkdown()
    const blob = new Blob([exportText.value], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = '个人档案.md'
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    alert(String(e))
  } finally {
    exporting.value = false
  }
}

const TYPE_LABEL: Record<string, string> = {
  learning: '学习',
  project: '项目',
  skill: '技能',
  cert: '证书',
}
</script>

<template>
  <section ref="rootEl" class="page">
    <header class="page-head profile-head" data-enter="hero">
      <div class="pw-grow">
        <div class="pw-row profile-head-title">
          <h2 class="pw-t-page">个人数字档案</h2>
          <span class="pw-t-cap">我是谁，我正在成为谁</span>
        </div>
        <div class="pw-row pw-row--top profile-id">
          <button
            type="button"
            class="pw-avatar pw-avatar--lg profile-avatar"
            data-pw-avatar
            :title="avatar ? '点击更换头像' : '点击选择头像'"
            @click="openAvatarPicker"
          >
            {{ avatarChar }}
          </button>
          <div class="pw-grow">
            <div class="profile-nick" data-pw-name>{{ basic.name || '未命名' }}</div>
            <p class="pw-t-cap profile-sub" data-pw-direction>
              {{ basic.direction || '还没有填写方向' }}
            </p>
            <p v-if="basic.motto" class="pw-t-sm profile-motto" data-pw-motto>
              「{{ basic.motto }}」
            </p>
            <div v-if="basic.interests.length" class="pw-row pw-row--wrap profile-tags" data-pw-tags>
              <PwChip v-for="t in basic.interests" :key="t" size="sm" variant="brand">{{ t }}</PwChip>
            </div>
          </div>
        </div>
      </div>
      <div class="page-bar-actions">
        <PwButton variant="secondary" @click="startEditBasic">编辑资料</PwButton>
        <PwButton variant="secondary" :disabled="exporting" @click="doExport">
          {{ exporting ? '导出中…' : '导出 Markdown' }}
        </PwButton>
      </div>
    </header>

    <!-- 首次使用引导：只问 3 个字段（10 §1） -->
    <form v-if="isFirstUse" class="onboarding" @submit.prevent="submitOnboarding">
      <h3>先认识一下 —— 只需要 3 个字段</h3>
      <input v-model="onboarding.name" placeholder="怎么称呼你（必填）" />
      <input v-model="onboarding.direction" placeholder="你在往哪个方向走（可选）" />
      <input v-model="onboarding.motto" placeholder="一句话签名（可选）" />
      <button type="submit" :disabled="!onboarding.name.trim()">开始记录</button>
    </form>

    <!-- 待确认建议（10 §5 硬关口） -->
    <div v-if="suggestions.length > 0" class="suggestion-panel" data-enter="sec">
      <header class="suggestion-head">
        <span><b>{{ suggestions.length }}</b> 条待确认的档案变化 —— 确认后才会写入档案</span>
        <button
          type="button"
          :disabled="selectedSuggestions.length === 0 || suggestionBusy"
          @click="confirmSelected"
        >
          批量确认（{{ selectedSuggestions.length }}）
        </button>
      </header>
      <ul class="suggestion-list">
        <li
          v-for="s in suggestions"
          :key="s.id"
          class="suggestion-item"
          :class="{ picked: selectedSuggestions.includes(s.id) }"
        >
          <label class="pick">
            <input
              type="checkbox"
              :checked="selectedSuggestions.includes(s.id)"
              @change="togglePick(s.id)"
            />
          </label>
          <div class="suggestion-body">
            <span class="kind-badge">建议加入{{ KIND_LABEL[s.kind] ?? s.kind }}</span>
            <b>{{ s.title }}</b>
            <span class="detail">{{ suggestionDetail(s.kind, s.payload) }}</span>
          </div>
          <span class="suggestion-actions">
            <button type="button" :disabled="suggestionBusy" @click="confirmOne(s.id)">确认</button>
            <button type="button" class="ghost" @click="ignoreOne(s.id)">忽略</button>
            <button
              type="button"
              class="ghost"
              :title="`永久拒绝全部「${KIND_LABEL[s.kind]}」类建议`"
              @click="rejectThisKind(s.kind)"
            >
              永久拒绝此类
            </button>
          </span>
        </li>
      </ul>
      <p v-if="rejectedKinds.length > 0" class="rejected-note">
        已永久拒绝：{{ rejectedKinds.map((k) => KIND_LABEL[k] ?? k).join('、') }} 类建议
      </p>
    </div>

    <!-- 原位编辑卡（UI-07/UI-08）：不新开页面、不遮挡整页；Esc 取消、保存后立即生效。
         基础字段（昵称/方向/签名/标签）与下面的扩展块（技能/项目/时间线）**是两个独立结构**，
         编辑这里不会触碰扩展块的数据。 -->
    <PwCard v-if="editingBasic" class="profile-editor" data-pw-profile-editor>
      <div class="pw-row">
        <div class="pw-t-section pw-grow">编辑资料</div>
        <span class="pw-t-cap">Esc 取消 · 保存后立即生效</span>
      </div>

      <div class="pw-stack profile-editor-body">
        <div class="pw-field">
          <label>昵称</label>
          <div class="pw-input pw-input--lg profile-w-sm">
            <input v-model="basicForm.name" placeholder="怎么称呼你（必填）" />
          </div>
        </div>

        <div class="pw-field">
          <label>方向</label>
          <div class="pw-input pw-input--lg profile-w-sm">
            <input v-model="basicForm.direction" placeholder="你在往哪个方向走（可留空）" />
          </div>
        </div>

        <div class="pw-field">
          <label>个性签名 · {{ signatureLeft }}/{{ SIGNATURE_MAX }}</label>
          <div class="pw-input pw-input--multi profile-w-md">
            <textarea
              v-model="basicForm.motto"
              :maxlength="SIGNATURE_MAX"
              rows="2"
              placeholder="写一句介绍自己（可留空）"
            ></textarea>
          </div>
          <span class="pw-t-cap">留空恢复默认状态</span>
        </div>

        <div class="pw-field">
          <label>兴趣标签</label>
          <div class="pw-row pw-row--wrap">
            <PwChip
              v-for="(t, i) in tagDraft"
              :key="t"
              variant="brand"
              removable
              @remove="removeTag(i)"
            >
              {{ t }}
            </PwChip>
            <span class="pw-chip chip profile-tag-input">
              <input
                v-model="tagInput"
                placeholder="添加标签"
                @keydown.enter.prevent="addTag"
              />
              <button type="button" class="pw-chip__x" title="添加标签" @click="addTag">＋</button>
            </span>
          </div>
          <div v-if="suggestLeft.length" class="pw-row pw-row--wrap profile-sug">
            <span class="pw-t-cap">推荐</span>
            <PwChip
              v-for="s in suggestLeft"
              :key="s"
              as="button"
              size="sm"
              :title="`添加标签 ${s}`"
              @click="addSuggestedTag(s)"
            >
              ＋ {{ s }}
            </PwChip>
          </div>
        </div>

        <div class="pw-field">
          <label>头像</label>
          <div class="pw-row pw-row--wrap">
            <span class="pw-avatar pw-avatar--lg">{{ avatarChar }}</span>
            <PwButton size="sm" variant="secondary" @click="openAvatarPicker">更换头像</PwButton>
            <span class="pw-t-cap">
              {{ avatar ? '预设头像 · 点头像也可随时更换' : '首字母头像 · 点「更换头像」选择' }}
            </span>
          </div>
        </div>
      </div>

      <div class="pw-row profile-editor-foot">
        <span class="pw-spacer"></span>
        <PwButton variant="ghost" @click="cancelEditBasic">取消</PwButton>
        <PwButton variant="primary" @click="saveBasic">保存</PwButton>
      </div>
    </PwCard>

    <!-- 中部：技能树 | 项目经历 -->
    <div class="middle" data-enter="ws">
      <section class="profile-panel">
        <header class="profile-panel-head">
          <h3>技能树</h3>
        </header>
        <details v-for="g in skillGroups" :key="g.category" class="skill-group" open>
          <summary>{{ g.label }}（{{ g.items.length }}）</summary>
          <ul class="skill-list">
            <li v-for="s in g.items" :key="s.id" class="skill-row">
              <span
                class="skill-name"
                :title="`来源：${s.source === 'user' ? '手动填写' : 'AI 建议已确认'}`"
              >
                {{ s.name }}
              </span>
              <span class="bar">
                <span class="bar-fill" :style="{ width: s.level + '%' }"></span>
              </span>
              <input
                class="level-input"
                type="number"
                min="0"
                max="100"
                :value="s.level"
                @change="setLevel(s.id, Number(($event.target as HTMLInputElement).value))"
              />
              <button type="button" class="ghost tiny" @click="removeSkill(s.id)">删</button>
            </li>
          </ul>
        </details>
        <p v-if="skillGroups.length === 0" class="empty">还没有技能，手动加一条或等系统建议。</p>
        <form class="add-form" @submit.prevent="addSkill">
          <input v-model="newSkill.name" placeholder="技能名（必填）" />
          <input v-model.number="newSkill.level" type="number" min="0" max="100" title="等级 0~100" />
          <select v-model="newSkill.category">
            <option value="lang">编程语言</option>
            <option value="framework">框架</option>
            <option value="tool">工具</option>
            <option value="domain">领域知识</option>
            <option value="other">其他</option>
          </select>
          <button type="submit" :disabled="skillBusy">添加技能</button>
        </form>
      </section>

      <section class="profile-panel">
        <header class="profile-panel-head">
          <h3>项目经历</h3>
        </header>
        <ul class="project-list">
          <li v-for="p in projects" :key="p.id" class="project-row">
            <div class="project-main">
              <b>{{ p.name }}</b>
              <span v-if="p.role" class="muted"> · {{ p.role }}</span>
              <span class="muted period">
                {{ p.startDate || '' }}{{ p.endDate ? ' ~ ' + p.endDate : p.startDate ? ' ~' : '' }}
              </span>
              <p v-if="p.summary" class="muted">{{ p.summary }}</p>
              <p v-if="p.techStack.length" class="muted">技术栈：{{ p.techStack.join('、') }}</p>
            </div>
            <button type="button" class="ghost tiny" @click="removeProject(p.id)">删</button>
          </li>
        </ul>
        <p v-if="projects.length === 0" class="empty">
          还没有项目经历 —— 在「项目管理」里完成一个项目会生成待确认建议。
        </p>
        <details class="add-details">
          <summary>手动添加</summary>
          <form class="add-form column" @submit.prevent="addProject">
            <input v-model="newProject.name" placeholder="项目名（必填）" />
            <input v-model="newProject.role" placeholder="角色（可选）" />
            <input v-model="newProject.summary" placeholder="简介（可选）" />
            <input v-model="newProject.techStack" placeholder="技术栈（顿号分隔，可选）" />
            <input v-model="newProject.startDate" placeholder="开始日期（可选，如 2026-01-01）" />
            <button type="submit" :disabled="projectBusy">添加</button>
          </form>
        </details>
      </section>
    </div>

    <!-- 底部：成长时间线（10 §4） -->
    <section class="profile-panel" data-enter="sec">
      <header class="profile-panel-head">
        <h3>成长时间线</h3>
      </header>
      <div class="tl-groups">
        <div v-for="g in timelineGroups" :key="g.ym" class="tl-group">
          <h4>{{ g.ym }}</h4>
          <ul class="timeline">
            <li v-for="e in g.items" :key="e.id" class="timeline-node">
              <span class="dot" :class="'dot-' + e.type"></span>
              <div class="node-body">
                <div class="node-head">
                  <b>{{ e.title }}</b>
                  <span class="type-badge">{{ TYPE_LABEL[e.type] ?? e.type }}</span>
                  <span class="muted">{{ e.eventDate }}</span>
                  <button type="button" class="ghost tiny" @click="removeEvent(e.id)">删</button>
                </div>
                <p v-if="e.description" class="muted">{{ e.description }}</p>
              </div>
            </li>
          </ul>
        </div>
      </div>
      <p v-if="timelineGroups.length === 0" class="empty">
        还没有记录 —— 学习目标完成、项目完成都会生成待确认的时间线条目。
      </p>
      <details class="add-details">
        <summary>手动添加</summary>
        <form class="add-form" @submit.prevent="addEvent">
          <input v-model="newEvent.eventDate" type="date" />
          <input v-model="newEvent.title" placeholder="事件标题（必填）" />
          <input v-model="newEvent.description" placeholder="说明（可选）" />
          <select v-model="newEvent.type">
            <option value="learning">学习</option>
            <option value="project">项目</option>
            <option value="skill">技能</option>
            <option value="cert">证书</option>
          </select>
          <button type="submit" :disabled="eventBusy">添加</button>
        </form>
      </details>
    </section>

    <!-- 导出预览（导出内容明确告知 —— 10 §7） -->
    <details v-if="exportText" class="export-preview">
      <summary>查看刚导出的 Markdown 内容（仅含已确认条目）</summary>
      <pre>{{ exportText }}</pre>
    </details>

    <p v-if="store.error" class="error-note">{{ store.error }}</p>

    <!-- 头像选择（UI-08）：首字母 / 预设 emoji；点选即时预览，保存才写 config -->
    <PwDrawer
      :open="avatarOpen"
      title="选择头像"
      aria-label="选择头像"
      @close="avatarOpen = false"
    >
      <p class="pw-t-cap profile-hint">选一个喜欢的，或继续用名字首字母。</p>
      <!-- 双类名桥接：`avatar-grid`/`avatar-pick` 是设计稿类（取值的唯一来源，base.css），
           `pw-grid--avatars`/`pw-avatar-pick` 是原语层别名 —— 两者取值等价，
           但别名层还补了设计稿 `.avatar-pick` 没写的 `padding:0`（设计稿的按钮重置
           本来就带 padding:0，本工程的按钮重置带了内边距，必须在这里复位）。
           保留别名类也是 verify_tech05c T4f「原语层无孤儿类」的消费方。 -->
      <div class="avatar-grid pw-grid--avatars">
        <button
          type="button"
          class="avatar-pick pw-avatar-pick avatar-pick--initial"
          :class="{ on: avatarDraft === '' }"
          title="首字母头像"
          @click="setAvatarDraft('')"
        >
          {{ (basic.name || '用户').charAt(0) }}
        </button>
        <button
          v-for="e in AVATAR_PRESETS"
          :key="e"
          type="button"
          class="avatar-pick pw-avatar-pick"
          :class="{ on: avatarDraft === e }"
          @click="setAvatarDraft(e)"
        >
          {{ e }}
        </button>
        <button
          type="button"
          class="avatar-pick pw-avatar-pick avatar-pick--up"
          data-pw-avatar-upload
          title="上传图片（接入后开放）"
          @click="pickAvatarImage"
        >
          <PwIcon name="download" :size="16" />
          <span>上传图片</span>
        </button>
      </div>
      <PwCard variant="ghost" class="profile-avatar-note">
        <span class="pw-t-sm pw-c2">
          头像保存为配置项 profile.avatar（没有改数据库结构）；图片上传为预留入口，接入后开放。
        </span>
      </PwCard>
      <template #foot>
        <PwButton variant="secondary" @click="avatarOpen = false">取消</PwButton>
        <span class="pw-spacer"></span>
        <PwButton variant="primary" @click="saveAvatar">保存</PwButton>
      </template>
    </PwDrawer>
  </section>
</template>

<style scoped>
.onboarding {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: 420px;
  padding: 16px;
  border: 1px dashed var(--pw-border, #e0e0e0);
  border-radius: 8px;
  margin-bottom: 16px;
}
.onboarding h3 {
  margin: 0;
  font-size: 15px;
}

/* ---- 待确认建议 ---- */
.suggestion-panel {
  border-left: 3px solid #1a73e8;
  background: rgba(26, 115, 232, 0.06);
  border-radius: 4px;
  padding: 10px 12px;
  margin-bottom: 16px;
}
.suggestion-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.suggestion-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.suggestion-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px;
  background: var(--pw-surface, #fff);
  border: 1px solid var(--pw-border, #e0e0e0);
  border-radius: 6px;
}
.suggestion-item.picked {
  border-color: #1a73e8;
}
.suggestion-body {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  min-width: 0;
}
.kind-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(26, 115, 232, 0.12);
  color: #1a73e8;
  flex: 0 0 auto;
}
.suggestion-body .detail {
  font-size: 12px;
  opacity: 0.75;
}
.suggestion-actions {
  display: flex;
  gap: 6px;
  flex: 0 0 auto;
}
.rejected-note {
  margin: 8px 0 0;
  font-size: 12px;
  opacity: 0.65;
}

/* ---- 档案头部（UI-07：头像 + 昵称 + 方向 + 签名 + 标签） ---- */
.profile-head {
  display: flex;
  align-items: flex-start;
  gap: 16px;
}

.profile-head-title {
  gap: 8px;
  margin-bottom: 12px;
}

.profile-id {
  gap: 14px;
}

.profile-avatar {
  border: none;
  padding: 0;
  cursor: pointer;
}

.profile-nick {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-1);
}

.profile-sub {
  margin: 2px 0 0;
}

.profile-motto {
  margin: 6px 0 0;
  font-style: italic;
  color: var(--text-2);
}

.profile-tags {
  margin-top: 8px;
  gap: 6px;
}

/* ---- 原位编辑卡（UI-07/UI-08） ---- */
.profile-editor {
  border-color: var(--brand-500);
}

.profile-editor-body {
  margin-top: 16px;
}

.profile-editor-foot {
  justify-content: flex-end;
  margin-top: 16px;
}

.profile-w-sm {
  max-width: 360px;
}

.profile-w-md {
  max-width: 520px;
}

.profile-tag-input {
  gap: 4px;
  padding-right: var(--f-space-1);
}

/* 标签输入框是裸 input：需覆盖 base.css 的全局 input 外观 */
.profile-tag-input input {
  width: 72px;
  font-size: 12px;
  border: 0;
  background: none;
  outline: 0;
  padding: 0;
  border-radius: 0;
  color: var(--text-1);
}

.profile-sug {
  gap: 6px;
  margin-top: 6px;
}

.profile-hint {
  margin: 0 0 8px;
}

/* 首字母格：设计稿 `openAvatarPicker` 里是行内样式（18px / 600 / brand-700），
   这里落成作用域类，避免行内样式绕开设计稿层。 */
.avatar-pick--initial {
  font-size: 18px;
  font-weight: 600;
  color: var(--brand-700);
}

.profile-avatar-note {
  margin-top: 16px;
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

/* ---- 中部两栏 ---- */
.middle {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 900px) {
  .middle {
    grid-template-columns: 1fr;
  }
}
.profile-panel {
  border: 1px solid var(--pw-border, #e0e0e0);
  border-radius: 8px;
  padding: 12px;
}
.profile-panel-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.profile-panel-head h3 {
  margin: 0;
  font-size: 15px;
}
.skill-group {
  margin-bottom: 6px;
}
.skill-group summary {
  cursor: pointer;
  font-size: 13px;
  opacity: 0.85;
}
.skill-list {
  list-style: none;
  margin: 6px 0;
  padding: 0 4px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.skill-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.skill-name {
  width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.bar {
  flex: 1;
  height: 8px;
  background: rgba(0, 0, 0, 0.08);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  display: block;
  height: 100%;
  background: #1a73e8;
  transition: width 0.2s ease;
}
.level-input {
  width: 56px;
}
.project-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.project-row {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid var(--pw-border, #e0e0e0);
  padding-bottom: 8px;
}
.project-row:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.project-main p {
  margin: 2px 0 0;
  font-size: 12px;
}
.period {
  font-size: 12px;
}
.muted {
  opacity: 0.7;
}
.empty {
  font-size: 13px;
  opacity: 0.6;
}
.add-form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}
.add-form input,
.add-form select {
  min-width: 0;
}
.add-form.column {
  flex-direction: column;
}
.add-details {
  margin-top: 10px;
}
.add-details summary {
  cursor: pointer;
  font-size: 13px;
  opacity: 0.8;
}

/* ---- 时间线 ---- */
.tl-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.tl-group h4 {
  margin: 0 0 6px;
  font-size: 13px;
  opacity: 0.8;
}
.timeline {
  list-style: none;
  margin: 0;
  padding: 0;
}
.timeline-node {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 0 0 14px 0;
}
.timeline-node::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 14px;
  bottom: 0;
  width: 1px;
  background: var(--pw-border, #e0e0e0);
}
.timeline-node:last-child::before {
  display: none;
}
.dot {
  width: 11px;
  height: 11px;
  border-radius: 50%;
  margin-top: 4px;
  flex: 0 0 auto;
  z-index: 1;
}
.dot-learning {
  background: #1a73e8;
}
.dot-project {
  background: #188038;
}
.dot-skill {
  background: #f9ab00;
}
.dot-cert {
  background: #9334e6;
}
.node-body {
  flex: 1;
}
.node-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.type-badge {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.06);
}

/* ---- 导出 ---- */
.export-preview pre {
  max-height: 320px;
  overflow: auto;
  font-size: 12px;
  background: rgba(0, 0, 0, 0.04);
  padding: 10px;
  border-radius: 6px;
  white-space: pre-wrap;
}
.error-note {
  color: #d93025;
  font-size: 13px;
}
button.ghost {
  opacity: 0.75;
}
button.tiny {
  font-size: 12px;
  padding: 1px 6px;
}
</style>
