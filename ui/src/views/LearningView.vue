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
  <section class="page">
    <header class="page-bar">
      <h2>学习成长</h2>
      <div class="page-bar-actions">
        <span class="stage-note">AI 规划，用户执行，系统提醒</span>
        <button type="button" @click="showNew = !showNew">
          {{ showNew ? '取消' : '新建目标' }}
        </button>
      </div>
    </header>

    <!-- 提醒条（09 §5）：应用内提醒 + 三个动作 -->
    <div v-for="r in store.activeReminders" :key="r.goalId" class="reminder-bar">
      <span class="reminder-text">
        「{{ r.title }}」已 <b>{{ r.idleDays }}</b> 天未更新，是否继续？
      </span>
      <span class="reminder-actions">
        <button type="button" @click="actOnReminder(r.goalId, 'learning')">继续</button>
        <button type="button" @click="actOnReminder(r.goalId, 'paused')">暂停</button>
        <button type="button" @click="actOnReminder(r.goalId, 'archived')">归档</button>
        <button type="button" class="ghost" @click="store.dismiss(r.goalId)">稍后</button>
      </span>
    </div>

    <details class="remind-settings">
      <summary>提醒设置</summary>
      <label>
        长期未更新阈值
        <input v-model.number="remindDays" type="number" min="0" max="365" /> 天
      </label>
      <label>
        <input v-model="remindEnabled" type="checkbox" />
        启用提醒（关掉后不再打扰）
      </label>
      <button type="button" @click="saveRemind">保存并立即检查</button>
    </details>

    <form v-if="showNew" class="new-goal" @submit.prevent="submitNew">
      <input v-model="newGoal.title" placeholder="标题（必填），例如：学习计算机视觉并完成项目" />
      <input v-model="newGoal.description" placeholder="描述（可选）" />
      <input v-model="newGoal.expectedAt" placeholder="期望完成时间（可选），如 2026-12-31" />
      <select v-model="newGoal.priority">
        <option value="low">低优先级</option>
        <option value="medium">中优先级</option>
        <option value="high">高优先级</option>
      </select>
      <button type="submit">创建</button>
    </form>

    <p v-if="store.error" class="hint warn">{{ store.error }}</p>

    <div v-if="store.goals.length === 0" class="empty-state">
      <p>还没有学习目标。</p>
      <p class="stage-note">先建一个目标，再用「AI 生成路线」让它拆成可执行阶段。</p>
    </div>

    <!-- 目标列表 -->
    <div class="goal-grid">
      <article
        v-for="g in store.goals"
        :key="g.id"
        class="goal-card"
        :class="{ selected: g.id === selectedId }"
        @click="select(g.id)"
      >
        <header>
          <h3>{{ g.title }}</h3>
          <span class="tag" :class="`tag-${GOAL_STATUS_META[g.status].color}`">
            {{ GOAL_STATUS_META[g.status].label }}
          </span>
        </header>
        <p v-if="g.description" class="stage-note">{{ g.description }}</p>
        <div class="progress">
          <div class="progress-bar">
            <div class="progress-fill" :style="{ width: `${g.progress.percent}%` }" />
          </div>
          <span class="progress-text">
            {{ g.progress.done }}/{{ g.progress.total }}（{{ g.progress.percent }}%）
          </span>
        </div>
        <footer class="stage-note">
          <span>优先级 {{ g.priority }}</span>
          <span v-if="g.expectedAt">期望 {{ g.expectedAt }}</span>
        </footer>
      </article>
    </div>

    <!-- 目标详情 -->
    <section v-if="selected" class="goal-detail">
      <header class="detail-bar">
        <h3>{{ selected.title }}</h3>
        <div class="detail-actions">
          <button type="button" @click="setGoalStatus(selected, 'learning')">开始/继续</button>
          <button type="button" @click="setGoalStatus(selected, 'paused')">暂停</button>
          <button type="button" @click="setGoalStatus(selected, 'done')">标记完成</button>
          <button type="button" @click="setGoalStatus(selected, 'archived')">归档</button>
          <button type="button" class="danger" @click="removeGoal(selected)">删除</button>
        </div>
      </header>

      <!-- 竖向时间轴（09 §7：节点带状态色） -->
      <ol class="timeline">
        <li v-for="(n, i) in nodes" :key="n.id" class="timeline-node">
          <span class="dot" :class="`dot-${n.status}`" />
          <div class="node-body">
            <div class="node-head">
              <input
                class="node-title"
                :value="n.title"
                :disabled="nodeBusy"
                @change="renameNode(n, ($event.target as HTMLInputElement).value)"
              />
              <span v-if="n.estimated" class="stage-note">{{ n.estimated }}</span>
              <span class="tag" :class="`tag-${NODE_STATUS_META[n.status].color}`">
                {{ NODE_STATUS_META[n.status].label }}
              </span>
            </div>
            <div class="node-actions">
              <select
                :value="n.status"
                :disabled="nodeBusy"
                @change="setNodeStatus(n, ($event.target as HTMLSelectElement).value as NodeStatus)"
              >
                <option v-for="s in nodeStatuses" :key="s" :value="s">
                  {{ NODE_STATUS_META[s].label }}
                </option>
              </select>
              <button type="button" :disabled="i === 0" @click="moveNode(n, -1)">上移</button>
              <button type="button" :disabled="i === nodes.length - 1" @click="moveNode(n, 1)">
                下移
              </button>
              <button type="button" @click="addNote(n)">备注</button>
              <button type="button" class="danger" @click="removeNode(n)">删除</button>
            </div>
            <p v-if="n.note" class="node-note">备注：{{ n.note }}</p>
            <p v-if="n.resources.length" class="stage-note">
              资料方向：{{ n.resources.join(' / ') }}
            </p>
          </div>
        </li>
        <li v-if="nodes.length === 0" class="stage-note">还没有路线节点 —— 用下面的「AI 生成路线」或手动添加。</li>
      </ol>

      <div class="add-node">
        <input v-model="newTitle" placeholder="手动添加一个阶段" @keyup.enter="addNode" />
        <button type="button" @click="addNode">添加节点</button>
      </div>

      <!-- AI 生成（建议态；采纳是用户动作） -->
      <section class="ai-block">
        <header>
          <h4>AI 建议</h4>
          <span class="stage-note">AI 只建议，不改动任何进度数据</span>
        </header>
        <div class="ai-controls">
          <select v-model="suggestKind">
            <option value="roadmap">生成学习路线</option>
            <option value="optimize">路线优化建议</option>
            <option value="summary">阶段总结草稿</option>
          </select>
          <select v-model="ai.providerId" :disabled="providers.length === 0">
            <option v-if="providers.length === 0" value="">未配置 Provider</option>
            <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.label }}</option>
          </select>
          <input v-model="extra" placeholder="补充说明（可选）" />
          <button type="button" :disabled="!canGenerate" @click="generate">
            {{ generating ? '生成中…' : '生成' }}
          </button>
        </div>

        <div v-if="suggestion" class="suggestion">
          <p class="advisory">★ AI 建议，待确认（不会自动写入你的学习计划）</p>

          <!-- 解析失败 → 文本展示 + 手动录入（09 §2 禁止让用户看到 JSON 报错） -->
          <template v-if="suggestion.degraded">
            <p class="hint">
              模型这次没有返回可解析的结构，已降级为文本展示。你可以照着内容在下方手动添加节点。
            </p>
            <pre class="raw">{{ suggestion.raw }}</pre>
            <button type="button" @click="draftAdd">按此内容手动录入节点</button>
          </template>

          <!-- 结构化路线 → 草稿可编辑，采纳才落库 -->
          <template v-else-if="suggestion.kind === 'roadmap' && drafts.length > 0">
            <ul class="drafts">
              <li v-for="(d, i) in drafts" :key="i">
                <input v-model="d.title" placeholder="阶段标题" />
                <input v-model="d.estimated" placeholder="预估时长" class="narrow" />
                <button type="button" @click="draftMove(i, -1)">↑</button>
                <button type="button" @click="draftMove(i, 1)">↓</button>
                <button type="button" class="danger" @click="draftRemove(i)">×</button>
              </li>
            </ul>
            <div class="draft-actions">
              <button type="button" @click="draftAdd">加一个</button>
              <button type="button" class="primary" @click="acceptRoadmap">
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
        <h4>更新记录</h4>
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
.page-bar,
.detail-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-bar-actions,
.detail-actions,
.reminder-actions,
.ai-controls,
.draft-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.reminder-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  margin-bottom: 8px;
  border-left: 3px solid #f9ab00;
  background: rgba(249, 171, 0, 0.08);
  border-radius: 4px;
}
.remind-settings {
  margin: 8px 0 16px;
  font-size: 13px;
}
.remind-settings label {
  margin-right: 16px;
}
.remind-settings input[type='number'] {
  width: 64px;
}
.new-goal {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 16px;
}
.new-goal input {
  min-width: 180px;
}
.goal-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.goal-card {
  border: 1px solid var(--pw-border, #e0e0e0);
  border-radius: 8px;
  padding: 12px;
  cursor: pointer;
}
.goal-card.selected {
  border-color: #1a73e8;
  box-shadow: 0 0 0 1px #1a73e8 inset;
}
.goal-card header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.goal-card h3 {
  font-size: 15px;
  margin: 0;
}
.progress {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 8px 0 4px;
}
.progress-bar {
  flex: 1;
  height: 6px;
  background: rgba(0, 0, 0, 0.08);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: #188038;
  transition: width 0.2s ease;
}
.progress-text,
.goal-card footer {
  font-size: 12px;
  opacity: 0.75;
}
.goal-card footer {
  display: flex;
  gap: 12px;
}
.goal-detail {
  margin-top: 20px;
  border-top: 1px solid var(--pw-border, #e0e0e0);
  padding-top: 16px;
}
.timeline {
  list-style: none;
  margin: 12px 0;
  padding: 0;
}
.timeline-node {
  position: relative;
  display: flex;
  gap: 12px;
  padding: 0 0 16px 0;
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
.dot-not_started {
  background: #9aa0a6;
}
.dot-learning {
  background: #1a73e8;
}
.dot-done {
  background: #188038;
}
.dot-paused {
  background: #f9ab00;
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
.node-title {
  border: 1px solid transparent;
  background: transparent;
  font-size: 14px;
  font-weight: 600;
  min-width: 200px;
  padding: 2px 4px;
}
.node-title:hover,
.node-title:focus {
  border-color: var(--pw-border, #e0e0e0);
  background: #fff;
}
.node-actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
  flex-wrap: wrap;
}
.node-note {
  margin: 4px 0 0;
  font-size: 13px;
  opacity: 0.85;
}
.tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  border: 1px solid currentColor;
}
.tag-gray {
  color: #5f6368;
}
.tag-blue {
  color: #1a73e8;
}
.tag-green {
  color: #188038;
}
.tag-yellow {
  color: #b06000;
}
.add-node {
  display: flex;
  gap: 8px;
  margin: 8px 0 20px;
}
.ai-block {
  border: 1px dashed var(--pw-border, #e0e0e0);
  border-radius: 8px;
  padding: 12px;
}
.ai-block header {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.ai-block h4 {
  margin: 0 0 8px;
}
.advisory {
  color: #b06000;
  font-size: 12px;
  margin: 8px 0;
}
.raw {
  white-space: pre-wrap;
  background: rgba(0, 0, 0, 0.04);
  padding: 8px;
  border-radius: 4px;
  font-size: 12px;
  max-height: 280px;
  overflow: auto;
}
.drafts {
  list-style: none;
  padding: 0;
  margin: 8px 0;
}
.drafts li {
  display: flex;
  gap: 6px;
  margin-bottom: 6px;
}
.drafts input.narrow {
  width: 90px;
}
.hint.warn {
  color: #b06000;
}
.danger {
  color: #c5221f;
}
.updates ul {
  list-style: none;
  padding: 0;
  font-size: 13px;
}
</style>
