<script setup lang="ts">
/**
 * 学习成长页（阶段6 · 09 §7）。
 *
 * 三块：
 *  1. 提醒条 —— 长期未更新的目标，提供 继续 / 暂停 / 归档（09 §5）；
 *  2. 目标列表 —— 卡片 + 进度条；
 *  3. 目标详情 —— 竖向时间轴（状态色）+ AI 路线生成（**建议态**，需用户采纳）。
 *
 * 红线 V3 在界面上必须"看得见"：AI 产出的一切都带「AI 建议，待确认」标记，
 * 采纳是**用户点按钮**才发生的动作。
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { configApi } from '@/api/configService'
import {
  GOAL_STATUS_META,
  NODE_STATUS_META,
  learningApi,
  type GoalStatus,
  type LearningGoal,
  type LearningUpdate,
  type NodeDraft,
  type NodeStatus,
  type RoadmapNode,
  type SuggestKind,
  type SuggestResult,
} from '@/api/learningService'
import PwIcon from '@/components/PwIcon.vue'
import { useAiStore } from '@/stores/ai'
import { useLearningStore } from '@/stores/learning'
import { logger } from '@/utils/logger'

const store = useLearningStore()
const ai = useAiStore()

const selectedId = ref<number | null>(null)
const nodes = ref<RoadmapNode[]>([])
const updates = ref<LearningUpdate[]>([])
const nodeBusy = ref(false)

const newGoal = reactive({
  title: '',
  description: '',
  expectedAt: '',
  priority: 'medium' as 'low' | 'medium' | 'high',
})
const showNew = ref(false)
const newTitle = ref('')

// ---- AI 生成（建议态）----
const suggestKind = ref<SuggestKind>('roadmap')
const extra = ref('')
const generating = ref(false)
const suggestion = ref<SuggestResult | null>(null)
const drafts = ref<NodeDraft[]>([])

// ---- 提醒设置 ----
const remindDays = ref(30)
const remindEnabled = ref(true)

const selected = computed(() => store.goals.find((g) => g.id === selectedId.value) ?? null)
const nodeStatuses: NodeStatus[] = ['not_started', 'learning', 'done', 'paused']
const providers = computed(() => ai.providers.filter((p) => p.enabled))
const canGenerate = computed(
  () => !generating.value && !!ai.providerId && providers.value.length > 0,
)

onMounted(async () => {
  await store.init()
  await ai.init()
  remindDays.value = await configApi.get<number>('learning.remind_after_days', 30)
  remindEnabled.value = await configApi.get<boolean>('learning.remind_enabled', true)
  if (store.goals.length > 0 && selectedId.value === null) {
    await select(store.goals[0].id)
  }
})

async function select(id: number): Promise<void> {
  selectedId.value = id
  suggestion.value = null
  drafts.value = []
  try {
    nodes.value = await learningApi.nodes(id)
    updates.value = await learningApi.updates(id, 20)
  } catch (e) {
    logger.warn('learning', `加载路线失败：${String(e)}`)
    nodes.value = []
    updates.value = []
  }
}

async function refresh(): Promise<void> {
  const id = selectedId.value
  await store.reload()
  // 目标可能刚被归档/删除，或列表里已不存在 → 回退到第一个；列表空了就清空详情
  // （不要用 `?? 0` 之类占位：那会拿 id=0 去请求路线，只会得到一条无意义的报错）
  const next =
    id !== null && store.goals.some((x) => x.id === id) ? id : (store.goals[0]?.id ?? null)
  if (next === null) {
    selectedId.value = null
    nodes.value = []
    updates.value = []
    suggestion.value = null
    drafts.value = []
    return
  }
  await select(next)
}

// ---------------------------------------------------------------- 目标

async function submitNew(): Promise<void> {
  if (!newGoal.title.trim()) return
  try {
    const g = await store.addGoal({
      title: newGoal.title.trim(),
      description: newGoal.description.trim() || null,
      expectedAt: newGoal.expectedAt.trim() || null,
      priority: newGoal.priority,
    })
    newGoal.title = ''
    newGoal.description = ''
    newGoal.expectedAt = ''
    showNew.value = false
    await select(g.id)
  } catch (e) {
    logger.warn('learning', `创建目标失败：${String(e)}`)
  }
}

async function setGoalStatus(g: LearningGoal, status: GoalStatus): Promise<void> {
  await store.updateGoal(g.id, { status })
  await refresh()
}

async function removeGoal(g: LearningGoal): Promise<void> {
  if (!window.confirm(`删除学习目标「${g.title}」？其路线与更新记录将不再显示。`)) return
  await store.removeGoal(g.id)
  selectedId.value = null
  await refresh()
}

// ---------------------------------------------------------------- 节点（用户手动）

async function setNodeStatus(n: RoadmapNode, status: NodeStatus): Promise<void> {
  nodeBusy.value = true
  try {
    await learningApi.nodeEdit(n.id, { status })
    nodes.value = await learningApi.nodes(n.goalId)
    updates.value = await learningApi.updates(n.goalId, 20)
    await store.reload()
  } finally {
    nodeBusy.value = false
  }
}

async function renameNode(n: RoadmapNode, title: string): Promise<void> {
  if (!title.trim() || title === n.title) return
  try {
    await learningApi.nodeEdit(n.id, { title: title.trim() })
    nodes.value = await learningApi.nodes(n.goalId)
  } catch (e) {
    logger.warn('learning', `改名失败：${String(e)}`)
  }
}

async function moveNode(n: RoadmapNode, delta: number): Promise<void> {
  nodes.value = await learningApi.nodeMove(n.id, delta)
}

async function removeNode(n: RoadmapNode): Promise<void> {
  if (!window.confirm(`删除节点「${n.title}」？`)) return
  await learningApi.nodeRemove(n.id)
  nodes.value = await learningApi.nodes(n.goalId)
  await store.reload()
}

async function addNode(): Promise<void> {
  const g = selected.value
  if (!g || !newTitle.value.trim()) return
  await learningApi.nodeAdd(g.id, { title: newTitle.value.trim() })
  newTitle.value = ''
  nodes.value = await learningApi.nodes(g.id)
  await store.reload()
}

async function addNote(n: RoadmapNode): Promise<void> {
  const note = window.prompt(`给「${n.title}」加一条备注（写入更新记录）`, n.note ?? '')
  if (note === null) return
  await learningApi.nodeEdit(n.id, { note })
  nodes.value = await learningApi.nodes(n.goalId)
  updates.value = await learningApi.updates(n.goalId, 20)
}

// ---------------------------------------------------------------- AI（只建议）

async function generate(): Promise<void> {
  generating.value = true
  suggestion.value = null
  drafts.value = []
  try {
    const res = await learningApi.suggest({
      goalId: selectedId.value,
      kind: suggestKind.value,
      provider: ai.providerId,
      model: ai.model,
      apiBase: ai.apiBase,
      extra: extra.value,
    })
    suggestion.value = res
    drafts.value = res.nodes.map((n) => ({ ...n }))
  } catch (e) {
    suggestion.value = {
      kind: suggestKind.value,
      advisory: true,
      promptKey: '',
      raw: String(e),
      degraded: true,
      reason: '请求失败',
      nodes: [],
      chunkCount: 0,
      durationMs: 0,
    }
  } finally {
    generating.value = false
  }
}

function draftMove(i: number, delta: number): void {
  const j = i + delta
  if (j < 0 || j >= drafts.value.length) return
  const list = [...drafts.value]
  ;[list[i], list[j]] = [list[j], list[i]]
  drafts.value = list
}

function draftRemove(i: number): void {
  drafts.value = drafts.value.filter((_, idx) => idx !== i)
}

function draftAdd(): void {
  drafts.value = [...drafts.value, { title: '新阶段' }]
}

/** 采纳建议 → **用户动作**，这才是写库的入口（红线 V3）。 */
async function acceptRoadmap(): Promise<void> {
  const g = selected.value
  if (!g) return
  const list = drafts.value.filter((d) => d.title.trim())
  if (list.length === 0) return
  const replace = nodes.value.length > 0
  if (
    replace &&
    !window.confirm(
      `该目标已有 ${nodes.value.length} 个节点。采纳将**替换**现有路线，已标记的进度会重置。确认覆盖？`,
    )
  ) {
    return
  }
  try {
    nodes.value = await learningApi.roadmapConfirm(
      g.id,
      list,
      replace,
      suggestion.value?.raw,
    )
    updates.value = await learningApi.updates(g.id, 20)
    suggestion.value = null
    drafts.value = []
    await store.reload()
  } catch (e) {
    window.alert(`采纳失败：${String(e)}`)
  }
}

// ---------------------------------------------------------------- 提醒

async function actOnReminder(goalId: number, status: 'learning' | 'paused' | 'archived'): Promise<void> {
  await store.actOnReminder(goalId, status)
  await refresh()
}

async function saveRemind(): Promise<void> {
  await configApi.put('learning.remind_after_days', Number(remindDays.value))
  await configApi.put('learning.remind_enabled', remindEnabled.value)
  await store.checkReminders()
}
</script>

<template>
  <section class="page page-skeleton">
    <div class="page-head">
      <div class="grow">
        <h2 class="t-page">学习成长</h2>
        <div class="t-cap" style="margin-top: 2px">AI 规划，用户执行，系统提醒 · 正在推进 {{ store.goals.length }} 条主线</div>
      </div>
      <button class="btn btn--secondary btn--sm" type="button" @click="showNew = !showNew">
        <PwIcon :name="showNew ? 'x' : 'plus'" :size="15" />
        {{ showNew ? '取消' : '新建目标' }}
      </button>
    </div>

    <!-- 提醒条（09 §5）：应用内提醒 + 三个动作 -->
    <div v-for="r in store.activeReminders" :key="r.goalId" class="reminder-bar">
      <span class="reminder-text">
        「{{ r.title }}」已 <b>{{ r.idleDays }}</b> 天未更新，是否继续？
      </span>
      <span class="reminder-actions">
        <button class="btn btn--secondary btn--sm" type="button" @click="actOnReminder(r.goalId, 'learning')">继续</button>
        <button class="btn btn--ghost btn--sm" type="button" @click="actOnReminder(r.goalId, 'paused')">暂停</button>
        <button class="btn btn--ghost btn--sm" type="button" @click="actOnReminder(r.goalId, 'archived')">归档</button>
        <button class="btn btn--ghost btn--sm" type="button" @click="store.dismiss(r.goalId)">稍后</button>
      </span>
    </div>

    <details class="remind-settings">
      <summary class="t-sm" style="cursor: pointer; color: var(--text-3)">提醒设置</summary>
      <div class="row" style="gap: var(--space-4); margin-top: var(--space-3)">
        <label class="t-sm">
          长期未更新阈值
          <input v-model.number="remindDays" class="input-inline" type="number" min="0" max="365" /> 天
        </label>
        <label class="t-sm">
          <input v-model="remindEnabled" type="checkbox" />
          启用提醒（关掉后不再打扰）
        </label>
        <button class="btn btn--secondary btn--sm" type="button" @click="saveRemind">保存并立即检查</button>
      </div>
    </details>

    <form v-if="showNew" class="new-goal" @submit.prevent="submitNew">
      <label class="input grow"><input v-model="newGoal.title" placeholder="标题（必填），例如：学习计算机视觉并完成项目" /></label>
      <label class="input grow"><input v-model="newGoal.description" placeholder="描述（可选）" /></label>
      <label class="input" style="width: 200px"><input v-model="newGoal.expectedAt" placeholder="期望完成时间，如 2026-12-31" /></label>
      <select v-model="newGoal.priority" class="select">
        <option value="low">低优先级</option>
        <option value="medium">中优先级</option>
        <option value="high">高优先级</option>
      </select>
      <button class="btn btn--primary btn--sm" type="submit">创建</button>
    </form>

    <p v-if="store.error" class="t-cap" style="color: var(--danger)">{{ store.error }}</p>

    <div v-if="store.goals.length === 0" class="empty">
      <div class="illus"><PwIcon name="target" :size="28" /></div>
      <div class="t-sm">还没有学习目标</div>
      <div class="t-cap">先建一个目标，再用「AI 生成路线」让它拆成可执行阶段。</div>
    </div>

    <!-- 目标列表（设计稿卡片网格形态） -->
    <div class="grid g2 goal-grid">
      <article
        v-for="g in store.goals"
        :key="g.id"
        class="card card--lg card--hoverable goal-card"
        :class="{ selected: g.id === selectedId }"
        @click="select(g.id)"
      >
        <div class="row" style="justify-content: space-between">
          <span class="t-card grow">{{ g.title }}</span>
          <span class="badge" :class="GOAL_STATUS_META[g.status].color === 'ok' ? 'badge--success' : GOAL_STATUS_META[g.status].color === 'warn' ? 'badge--warning' : 'badge--brand'">
            {{ GOAL_STATUS_META[g.status].label }}
          </span>
        </div>
        <p v-if="g.description" class="t-cap">{{ g.description }}</p>
        <div class="row" style="gap: var(--space-3)">
          <span class="progress grow"><i :style="{ width: `${g.progress.percent}%` }" /></span>
          <span class="t-cap mono">{{ g.progress.done }}/{{ g.progress.total }}（{{ g.progress.percent }}%）</span>
        </div>
        <div class="row" style="gap: var(--space-4)">
          <span class="t-cap">优先级 {{ g.priority }}</span>
          <span v-if="g.expectedAt" class="t-cap">期望 {{ g.expectedAt }}</span>
        </div>
      </article>
    </div>

    <!-- 目标详情 -->
    <section v-if="selected" class="goal-detail">
      <header class="detail-bar">
        <h3 class="t-section">{{ selected.title }}</h3>
        <div class="detail-actions">
          <button class="btn btn--primary btn--sm" type="button" @click="setGoalStatus(selected, 'learning')">开始/继续</button>
          <button class="btn btn--secondary btn--sm" type="button" @click="setGoalStatus(selected, 'paused')">暂停</button>
          <button class="btn btn--secondary btn--sm" type="button" @click="setGoalStatus(selected, 'done')">标记完成</button>
          <button class="btn btn--secondary btn--sm" type="button" @click="setGoalStatus(selected, 'archived')">归档</button>
          <button class="btn btn--danger btn--sm" type="button" @click="removeGoal(selected)">删除</button>
        </div>
      </header>

      <!-- 竖向时间轴（09 §7：节点带状态色；视觉 = 设计稿 .timeline / .tl-item / .node） -->
      <div class="timeline">
        <div
          v-for="(n, i) in nodes"
          :key="n.id"
          class="tl-item timeline-node"
          :class="n.status === 'done' ? 'done' : n.status === 'learning' ? 'cur' : 'todo'"
        >
          <span class="node"><PwIcon name="check" :size="10" /></span>
          <div class="node-body">
            <div class="node-head">
              <input
                class="node-title"
                :value="n.title"
                :disabled="nodeBusy"
                @change="renameNode(n, ($event.target as HTMLInputElement).value)"
              />
              <span v-if="n.estimated" class="t-cap">{{ n.estimated }}</span>
              <span
                class="badge"
                :class="NODE_STATUS_META[n.status].color === 'ok' ? 'badge--success' : NODE_STATUS_META[n.status].color === 'warn' ? 'badge--warning' : 'badge--brand'"
              >
                {{ NODE_STATUS_META[n.status].label }}
              </span>
            </div>
            <div class="node-actions">
              <select
                :value="n.status"
                class="select"
                :disabled="nodeBusy"
                @change="setNodeStatus(n, ($event.target as HTMLSelectElement).value as NodeStatus)"
              >
                <option v-for="s in nodeStatuses" :key="s" :value="s">
                  {{ NODE_STATUS_META[s].label }}
                </option>
              </select>
              <button class="btn btn--ghost btn--sm" type="button" :disabled="i === 0" @click="moveNode(n, -1)">上移</button>
              <button class="btn btn--ghost btn--sm" type="button" :disabled="i === nodes.length - 1" @click="moveNode(n, 1)">
                下移
              </button>
              <button class="btn btn--ghost btn--sm" type="button" @click="addNote(n)">备注</button>
              <button class="btn btn--danger btn--sm" type="button" @click="removeNode(n)">删除</button>
            </div>
            <p v-if="n.note" class="node-note">备注：{{ n.note }}</p>
            <p v-if="n.resources.length" class="t-cap">
              资料方向：{{ n.resources.join(' / ') }}
            </p>
          </div>
        </div>
        <div v-if="nodes.length === 0" class="t-cap">还没有路线节点 —— 用下面的「AI 生成路线」或手动添加。</div>
      </div>

      <div class="add-node">
        <label class="input grow"><input v-model="newTitle" placeholder="手动添加一个阶段" @keyup.enter="addNode" /></label>
        <button class="btn btn--secondary btn--sm" type="button" @click="addNode">
          <PwIcon name="plus" :size="14" /> 添加节点
        </button>
      </div>

      <!-- AI 生成（建议态；采纳是用户动作） -->
      <section class="ai-block">
        <header>
          <h4>AI 建议</h4>
          <span class="stage-note">AI 只建议，不改动任何进度数据</span>
        </header>
        <div class="ai-controls">
          <select v-model="suggestKind" class="select">
            <option value="roadmap">生成学习路线</option>
            <option value="optimize">路线优化建议</option>
            <option value="summary">阶段总结草稿</option>
          </select>
          <select v-model="ai.providerId" class="select" :disabled="providers.length === 0">
            <option v-if="providers.length === 0" value="">未配置 Provider</option>
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
          <label class="input grow" style="min-width: 160px"><input v-model="extra" placeholder="补充说明（可选）" /></label>
          <button class="btn btn--primary btn--sm" type="button" :disabled="!canGenerate" @click="generate">
            {{ generating ? '生成中…' : '生成' }}
          </button>
        </div>

        <div v-if="suggestion" class="suggestion">
          <p class="advisory">★ AI 建议，待确认（不会自动写入你的学习计划）</p>

          <!-- 解析失败 → 文本展示 + 手动录入（09 §2 禁止让用户看到 JSON 报错） -->
          <template v-if="suggestion.degraded">
            <p class="t-cap">
              模型这次没有返回可解析的结构，已降级为文本展示。你可以照着内容在下方手动添加节点。
            </p>
            <pre class="raw">{{ suggestion.raw }}</pre>
            <button class="btn btn--secondary btn--sm" type="button" @click="draftAdd">按此内容手动录入节点</button>
          </template>

          <!-- 结构化路线 → 草稿可编辑，采纳才落库 -->
          <template v-else-if="suggestion.kind === 'roadmap' && drafts.length > 0">
            <ul class="drafts">
              <li v-for="(d, i) in drafts" :key="i">
                <label class="input grow"><input v-model="d.title" placeholder="阶段标题" /></label>
                <label class="input" style="width: 110px"><input v-model="d.estimated" placeholder="预估时长" /></label>
                <button class="btn btn--ghost btn--sm" type="button" title="上移" @click="draftMove(i, -1)">↑</button>
                <button class="btn btn--ghost btn--sm" type="button" title="下移" @click="draftMove(i, 1)">↓</button>
                <button class="btn btn--danger btn--sm" type="button" title="删除" @click="draftRemove(i)">×</button>
              </li>
            </ul>
            <div class="draft-actions">
              <button class="btn btn--ghost btn--sm" type="button" @click="draftAdd">加一个</button>
              <button class="btn btn--primary btn--sm" type="button" @click="acceptRoadmap">
                {{ nodes.length > 0 ? '覆盖现有路线并采纳' : '采纳为学习路线' }}
              </button>
            </div>
          </template>

          <template v-else>
            <pre class="raw">{{ suggestion.raw }}</pre>
          </template>
          <p class="stage-note">
            模型：{{ suggestion.promptKey || '—' }} · 片段 {{ suggestion.chunkCount }} · 耗时
            {{ suggestion.durationMs }}ms
          </p>
        </div>
      </section>

      <!-- 更新记录（learning_updates） -->
      <section v-if="updates.length" class="updates">
        <h4 class="t-section">更新记录</h4>
        <ul>
          <li v-for="u in updates" :key="u.id">
            <span class="stage-note">{{ u.createdAt }}</span> {{ u.content }}
          </li>
        </ul>
      </section>
    </section>
  </section>
</template>

<style scoped>
/* UI-FUSION-FULL：本页只保留设计稿组件层之外的少量页内布局，
 * 视觉原语（card / progress / timeline / badge / button / input）一律走 base.css 里的
 * 设计稿组件层；此处零裸色值，全部走 token。 */

/* 提醒条（09 §5）：状态用 warning 语义色，不写死色值 */
.reminder-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--gap-stack);
  padding: var(--space-3) var(--space-4);
  margin-bottom: var(--gap-card);
  border-left: 3px solid var(--warning);
  background: var(--warning-soft);
  border-radius: var(--r-sm);
}

.reminder-actions,
.detail-actions,
.ai-controls,
.draft-actions {
  display: flex;
  gap: var(--gap-inline);
  align-items: center;
  flex-wrap: wrap;
}

.remind-settings {
  margin: 0 0 var(--gap-card);
}

.remind-settings input[type='number'] {
  width: 64px;
}

/* 新建目标表单：设计稿 field 行形态 */
.new-goal {
  display: flex;
  gap: var(--gap-inline);
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: var(--gap-card);
}

.new-goal .input {
  min-width: 180px;
}

/* 选中态：品牌色描边（token，不写死） */
.goal-card {
  cursor: pointer;
}

.goal-card.selected {
  border-color: var(--brand-500);
  box-shadow: 0 0 0 1px var(--brand-500) inset;
}

/* 目标详情 */
.goal-detail {
  margin-top: var(--gap-section);
}

.detail-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--gap-stack);
  flex-wrap: wrap;
  margin-bottom: var(--gap-card);
}

/* 路线编辑器内层（.timeline / .tl-item / .node 的视觉来自设计稿组件层） */
.timeline-node {
  align-items: flex-start;
}

.node-head {
  display: flex;
  align-items: center;
  gap: var(--gap-inline);
  flex-wrap: wrap;
}

.node-body {
  flex: 1;
  min-width: 0;
}

.node-title {
  border: 1px solid transparent;
  background: transparent;
  font-size: var(--fs-card);
  font-weight: var(--fw-semi);
  min-width: 200px;
  padding: 2px 4px;
  border-radius: var(--r-xs);
  color: var(--text-1);
}

.node-title:hover,
.node-title:focus {
  border-color: var(--border);
  background: var(--surface-1);
}

.node-actions {
  display: flex;
  gap: 6px;
  margin-top: var(--space-1);
  flex-wrap: wrap;
}

.node-note {
  margin: var(--space-1) 0 0;
  font-size: var(--fs-body-sm);
  color: var(--text-2);
}

.add-node {
  display: flex;
  gap: var(--gap-inline);
  margin: var(--space-2) 0 var(--gap-card);
}

/* AI 建议块：虚线引导卡形态 */
.ai-block {
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
  padding: var(--space-4);
  margin-top: var(--gap-card);
}

.ai-block h4 {
  margin: 0 0 var(--space-2);
  font-size: var(--fs-section);
  line-height: var(--lh-section);
  font-weight: var(--fw-semi);
}

.advisory {
  color: var(--warning-text);
  font-size: var(--fs-caption);
  margin: var(--space-2) 0;
}

.suggestion {
  margin-top: var(--gap-card);
}

.raw {
  white-space: pre-wrap;
  background: var(--surface-3);
  padding: var(--space-2);
  border-radius: var(--r-xs);
  font-family: var(--font-mono);
  font-size: var(--fs-caption);
  max-height: 280px;
  overflow: auto;
}

.drafts {
  list-style: none;
  padding: 0;
  margin: var(--space-2) 0;
}

.drafts li {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}

.drafts input.narrow {
  width: 90px;
}

.updates ul {
  list-style: none;
  padding: 0;
  font-size: var(--fs-body-sm);
}
</style>
