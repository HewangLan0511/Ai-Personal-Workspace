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
    <header class="page-bar">
      <h2>项目管理</h2>
      <div class="page-bar-actions">
        <span class="stage-note">可绑定工作模式、关联学习目标</span>
        <button type="button" @click="openNew">新建项目</button>
      </div>
    </header>

    <p v-if="error" class="hint warn">{{ error }}</p>

    <form v-if="showForm" class="project-form" @submit.prevent="submit">
      <input v-model="form.name" placeholder="项目名称（必填）" />
      <input v-model="form.role" placeholder="角色，如 主要负责人" />
      <input v-model="form.summary" placeholder="一句话简介" />
      <input v-model="form.techStack" placeholder="技术栈（逗号分隔）" />
      <input v-model="form.startDate" placeholder="开始日期，如 2026-09-01" />
      <input v-model="form.endDate" placeholder="结束日期（可选）" />
      <input v-model="form.directory" placeholder="关联目录（可选）" />
      <select v-model="form.status">
        <option value="ongoing">进行中</option>
        <option value="paused">已暂停</option>
        <option value="done">已完成</option>
      </select>
      <select v-model="form.modeName">
        <option value="">不绑定工作模式</option>
        <option v-for="m in modes" :key="m.id" :value="m.name">{{ m.name }}</option>
      </select>
      <select v-model="form.goalId">
        <option value="">不关联学习目标</option>
        <option v-for="g in goals" :key="g.id" :value="g.id">{{ g.title }}</option>
      </select>
      <span class="form-actions">
        <button type="submit" :disabled="busy">{{ editingId === null ? '创建' : '保存' }}</button>
        <button type="button" @click="showForm = false">取消</button>
      </span>
    </form>

    <div v-if="list.length === 0" class="empty-state">
      <p>还没有项目。</p>
      <p class="stage-note">建一个项目并绑定工作模式后，进入该模式时就会显示当前项目。</p>
    </div>

    <div class="project-grid">
      <article v-for="p in list" :key="p.id" class="project-card">
        <header>
          <h3>{{ p.name }}</h3>
          <span class="tag" :class="`tag-${p.status}`">{{ STATUS_LABEL[p.status] }}</span>
        </header>
        <p v-if="p.role || p.summary" class="stage-note">
          <span v-if="p.role">{{ p.role }}</span>
          <span v-if="p.summary"> · {{ p.summary }}</span>
        </p>
        <p v-if="p.techStack.length" class="tech">{{ p.techStack.join(' / ') }}</p>
        <dl class="meta">
          <template v-if="p.modeName"><dt>模式</dt><dd>{{ p.modeName }}</dd></template>
          <template v-if="p.goalTitle"><dt>目标</dt><dd>{{ p.goalTitle }}</dd></template>
          <template v-if="p.directory"><dt>目录</dt><dd>{{ p.directory }}</dd></template>
          <dt>时间</dt>
          <dd>{{ p.startDate || '—' }} ~ {{ p.endDate || '至今' }}</dd>
        </dl>
        <footer class="card-actions">
          <button type="button" :disabled="busy" @click="setStatus(p, 'ongoing')">进行中</button>
          <button type="button" :disabled="busy" @click="setStatus(p, 'paused')">暂停</button>
          <button type="button" :disabled="busy" @click="setStatus(p, 'done')">完成</button>
          <button type="button" @click="openEdit(p)">编辑</button>
          <button type="button" class="danger" @click="remove(p)">删除</button>
        </footer>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-bar-actions,
.form-actions,
.card-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.project-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 12px 0 20px;
  padding: 12px;
  border: 1px dashed var(--pw-border, #e0e0e0);
  border-radius: 8px;
}
.project-form input {
  min-width: 180px;
}
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.project-card {
  border: 1px solid var(--pw-border, #e0e0e0);
  border-radius: 8px;
  padding: 12px;
}
.project-card header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.project-card h3 {
  font-size: 15px;
  margin: 0;
}
.tech {
  font-size: 12px;
  opacity: 0.8;
  margin: 4px 0;
}
.meta {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 2px 8px;
  font-size: 12px;
  margin: 6px 0 10px;
}
.meta dt {
  opacity: 0.6;
}
.meta dd {
  margin: 0;
  word-break: break-all;
}
.tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 10px;
  border: 1px solid currentColor;
}
.tag-ongoing {
  color: #1a73e8;
}
.tag-paused {
  color: #b06000;
}
.tag-done {
  color: #188038;
}
.hint.warn {
  color: #b06000;
}
.danger {
  color: #c5221f;
}
</style>
