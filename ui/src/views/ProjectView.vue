<script setup lang="ts">
/**
 * 项目管理页（阶段6 §6，与学习成长同章节交付）。
 *
 * 两个联动点（指令要求"优先做"）：
 *  - **绑定工作模式** —— 进入该模式时看板/侧栏显示当前项目；
 *  - **关联学习目标** —— 项目完成时可提议把目标一并标记完成（**提议，不是自动做**，红线 V3）。
 */
import { computed, onMounted, reactive, ref } from 'vue'

import { learningApi, projectApi, type Project, type ProjectInput } from '@/api/learningService'
import { modeApi, type WorkMode } from '@/api/modeService'
import PwIcon from '@/components/PwIcon.vue'
import { useLearningStore } from '@/stores/learning'
import { logger } from '@/utils/logger'

const learning = useLearningStore()

const list = ref<Project[]>([])
const modes = ref<WorkMode[]>([])
const editingId = ref<number | null>(null)
const showForm = ref(false)
const error = ref('')
const busy = ref(false)

/**
 * 表单模型。
 *
 * ⚠️ 关联字段用 `''` / `null` 三种含义要分清：
 *   `''`    = 不绑定（提交时转成 null）
 *   数字/名 = 绑定
 * 编辑时若用户把绑定清空，提交 `null` —— core 侧的 `Option<Option<_>>` 才认得出
 * "显式解绑"与"没传"的区别。
 */
const form = reactive({
  name: '',
  role: '',
  summary: '',
  techStack: '',
  startDate: '',
  endDate: '',
  status: 'ongoing' as ProjectInput['status'],
  directory: '',
  modeName: '',
  goalId: '' as '' | number,
})

const goals = computed(() => learning.goals)

onMounted(async () => {
  await learning.init()
  await reload()
  try {
    modes.value = await modeApi.list()
  } catch (e) {
    logger.warn('project', `加载工作模式失败（不影响项目管理）：${String(e)}`)
  }
})

async function reload(): Promise<void> {
  try {
    list.value = await projectApi.list()
    error.value = ''
  } catch (e) {
    error.value = `无法读取项目列表：${String(e)}`
  }
}

function openNew(): void {
  editingId.value = null
  Object.assign(form, {
    name: '',
    role: '',
    summary: '',
    techStack: '',
    startDate: '',
    endDate: '',
    status: 'ongoing',
    directory: '',
    modeName: '',
    goalId: '',
  })
  showForm.value = true
}

function openEdit(p: Project): void {
  editingId.value = p.id
  Object.assign(form, {
    name: p.name,
    role: p.role ?? '',
    summary: p.summary ?? '',
    techStack: p.techStack.join(', '),
    startDate: p.startDate ?? '',
    endDate: p.endDate ?? '',
    status: p.status,
    directory: p.directory ?? '',
    modeName: p.modeName ?? '',
    goalId: p.goalId ?? '',
  })
  showForm.value = true
}

function payload(): ProjectInput {
  return {
    name: form.name.trim(),
    role: form.role.trim() || null,
    summary: form.summary.trim() || null,
    // 逗号/顿号分隔，顺手裁掉空项（用户常写 "Rust, Vue, "）
    techStack: form.techStack
      .split(/[,，、]/)
      .map((s) => s.trim())
      .filter(Boolean),
    startDate: form.startDate.trim() || null,
    endDate: form.endDate.trim() || null,
    status: form.status,
    directory: form.directory.trim() || null,
    modeName: form.modeName || null,
    goalId: form.goalId === '' ? null : Number(form.goalId),
  }
}

async function submit(): Promise<void> {
  if (!form.name.trim()) return
  busy.value = true
  try {
    if (editingId.value === null) {
      await projectApi.add(payload())
    } else {
      await projectApi.update(editingId.value, payload())
    }
    showForm.value = false
    await reload()
  } catch (e) {
    error.value = String(e)
  } finally {
    busy.value = false
  }
}

/** 改状态；项目转 done 且挂着目标时，**询问**用户是否一并完成目标。 */
async function setStatus(p: Project, status: Project['status']): Promise<void> {
  busy.value = true
  try {
    const saved = await projectApi.update(p.id, { status })
    await reload()
    if (saved.linkedGoalDone && saved.goalId) {
      const yes = window.confirm(
        `项目「${saved.name}」已完成。是否把关联的学习目标「${saved.goalTitle ?? ''}」也标记为完成？`,
      )
      if (yes) {
        await learningApi.goalUpdate(saved.goalId, { status: 'done' })
        await learning.reload()
      }
    }
  } catch (e) {
    error.value = String(e)
  } finally {
    busy.value = false
  }
}

async function remove(p: Project): Promise<void> {
  if (!window.confirm(`删除项目「${p.name}」？`)) return
  await projectApi.remove(p.id)
  await reload()
}

const STATUS_LABEL: Record<Project['status'], string> = {
  ongoing: '进行中',
  paused: '已暂停',
  done: '已完成',
}
</script>

<template>
  <section class="page">
    <div class="page-head">
      <div class="grow">
        <h2 class="t-page">项目管理</h2>
        <div class="t-cap" style="margin-top: 2px">可绑定工作模式、关联学习目标 · 共 {{ list.length }} 个项目</div>
      </div>
      <button class="btn btn--secondary btn--sm" type="button" @click="openNew">
        <PwIcon name="plus" :size="15" /> 新建项目
      </button>
    </div>

    <p v-if="error" class="t-cap" style="color: var(--danger)">{{ error }}</p>

    <form v-if="showForm" class="project-form" @submit.prevent="submit">
      <label class="input grow"><input v-model="form.name" placeholder="项目名称（必填）" /></label>
      <label class="input grow"><input v-model="form.role" placeholder="角色，如 主要负责人" /></label>
      <label class="input grow"><input v-model="form.summary" placeholder="一句话简介" /></label>
      <label class="input grow"><input v-model="form.techStack" placeholder="技术栈（逗号分隔）" /></label>
      <label class="input"><input v-model="form.startDate" placeholder="开始日期，如 2026-09-01" /></label>
      <label class="input"><input v-model="form.endDate" placeholder="结束日期（可选）" /></label>
      <label class="input grow"><input v-model="form.directory" placeholder="关联目录（可选）" /></label>
      <select v-model="form.status" class="select">
        <option value="ongoing">进行中</option>
        <option value="paused">已暂停</option>
        <option value="done">已完成</option>
      </select>
      <select v-model="form.modeName" class="select">
        <option value="">不绑定工作模式</option>
        <option v-for="m in modes" :key="m.id" :value="m.name">{{ m.name }}</option>
      </select>
      <select v-model="form.goalId" class="select">
        <option value="">不关联学习目标</option>
        <option v-for="g in goals" :key="g.id" :value="g.id">{{ g.title }}</option>
      </select>
      <span class="form-actions" style="display: flex; gap: var(--space-2)">
        <button class="btn btn--primary btn--sm" type="submit" :disabled="busy">{{ editingId === null ? '创建' : '保存' }}</button>
        <button class="btn btn--ghost btn--sm" type="button" @click="showForm = false">取消</button>
      </span>
    </form>

    <div v-if="list.length === 0" class="empty">
      <div class="illus"><PwIcon name="folder" :size="28" /></div>
      <div class="t-sm">还没有项目</div>
      <div class="t-cap">建一个项目并绑定工作模式后，进入该模式时就会显示当前项目。</div>
    </div>

    <div class="grid g2">
      <article v-for="p in list" :key="p.id" class="card card--lg card--hoverable">
        <div class="row" style="justify-content: space-between">
          <h3 class="t-card grow">{{ p.name }}</h3>
          <span
            class="badge"
            :class="p.status === 'done' ? 'badge--success' : p.status === 'paused' ? 'badge--warning' : 'badge--brand'"
          >
            {{ STATUS_LABEL[p.status] }}
          </span>
        </div>
        <p v-if="p.role || p.summary" class="t-cap">
          <span v-if="p.role">{{ p.role }}</span>
          <span v-if="p.summary"> · {{ p.summary }}</span>
        </p>
        <div v-if="p.techStack.length" class="row" style="flex-wrap: wrap; gap: 6px">
          <span v-for="t in p.techStack" :key="t" class="chip">{{ t }}</span>
        </div>
        <dl class="meta">
          <template v-if="p.modeName"><dt>模式</dt><dd>{{ p.modeName }}</dd></template>
          <template v-if="p.goalTitle"><dt>目标</dt><dd>{{ p.goalTitle }}</dd></template>
          <template v-if="p.directory"><dt>目录</dt><dd>{{ p.directory }}</dd></template>
          <dt>时间</dt>
          <dd>{{ p.startDate || '—' }} ~ {{ p.endDate || '至今' }}</dd>
        </dl>
        <div class="row card-actions" style="gap: var(--space-2); flex-wrap: wrap">
          <button class="btn btn--secondary btn--sm" type="button" :disabled="busy" @click="setStatus(p, 'ongoing')">进行中</button>
          <button class="btn btn--ghost btn--sm" type="button" :disabled="busy" @click="setStatus(p, 'paused')">暂停</button>
          <button class="btn btn--ghost btn--sm" type="button" :disabled="busy" @click="setStatus(p, 'done')">完成</button>
          <button class="btn btn--ghost btn--sm" type="button" @click="openEdit(p)">编辑</button>
          <button class="btn btn--danger btn--sm" type="button" @click="remove(p)">删除</button>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
/* UI-FUSION-FULL：页内布局自带，视觉原语（card / badge / chip / button / input / empty）
 * 一律来自 base.css 的设计稿组件层。此处零裸色值。 */

.project-form {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-inline);
  align-items: center;
  margin: 0 0 var(--gap-card);
  padding: var(--space-4);
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
}

.project-form .input {
  min-width: 180px;
}

.card-actions {
  margin-top: var(--space-4);
}

/* 元信息行（dl 表单化，键值两列） */
.meta {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px var(--gap-inline);
  font-size: var(--fs-caption);
  line-height: var(--lh-caption);
  margin: var(--space-3) 0 var(--space-1);
}

.meta dt {
  color: var(--text-3);
}

.meta dd {
  margin: 0;
  word-break: break-all;
  color: var(--text-2);
}
</style>
