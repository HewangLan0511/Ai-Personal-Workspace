<script setup lang="ts">
/**
 * 工作空间状态系统（TECH-05-C §P0-3；参考原型 UI-05-B）。
 *
 * ## 它是什么
 * 把"当前在做什么 / 应用都什么状态 / 布局是自动还是手动 / 用哪个模式 / 有哪些模式模板"
 * 收成一条状态栏 + 一组模板卡，落在**真实工作台首页**（`/dashboard`）。
 *
 * ## 数据只有一个来源：`workspaceRuntime`
 * ```
 *   workspaceRuntime.getCurrent() / getApps() / getLayout()   ← 读
 *   workspaceRuntime.updateStatus()                           ← 写（应用状态）
 *   workspaceRuntime.listTemplates() / saveTemplate() / prepareWorkspace()  ← 模板
 *   workspaceRuntime.snapshot.status()                        ← 恢复可用性（只读）
 *   workspaceRuntime.subscribe()                              ← 变更后局部刷新
 * ```
 * 本组件**不 import** `workspace/store` / `workspace/layout`（绕过门面直接拿内存状态
 * 会让"数据来源可整体替换"这件事失效）。
 *
 * ## 明确不做（P0-3 的禁止项，逐条对应）
 * - 不启动 / 不关闭任何真实软件 —— `updateStatus()` 只改内存里的状态字段；
 * - 不控制系统窗口（不移动、不缩放）—— 本组件零窗口 API；
 * - 不做真实快照恢复 —— `snapshot.status().recovery.executable` **恒为 false**，
 *   界面如实显示"接口就绪 / 执行侧未放开"，不画一个假的"已恢复"。
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'

import PwButton from '@/components/ui/PwButton.vue'
import PwCard from '@/components/ui/PwCard.vue'
import PwChip from '@/components/ui/PwChip.vue'
import { toast } from '@/composables/useToast'
import {
  workspaceRuntime,
  type AppStatus,
  type WorkspaceApp,
  type WorkspaceLayout,
  type WorkspaceRecoveryStatus,
  type WorkspaceRuntime,
  type WorkspaceTemplate,
} from '@/workspace/runtime'

const current = ref<WorkspaceRuntime | null>(null)
const apps = ref<WorkspaceApp[]>([])
const layout = ref<WorkspaceLayout | null>(null)
const templates = ref<WorkspaceTemplate[]>([])
const recovery = ref<WorkspaceRecoveryStatus | null>(null)
const busy = ref(false)

function refresh(): void {
  current.value = workspaceRuntime.getCurrent()
  apps.value = workspaceRuntime.getApps()
  layout.value = workspaceRuntime.getLayout()
  templates.value = workspaceRuntime.listTemplates()
  recovery.value = workspaceRuntime.snapshot.status()
}

let unsubscribe: (() => void) | null = null

onMounted(() => {
  refresh()
  unsubscribe = workspaceRuntime.subscribe(() => {
    refresh()
  })
})

onUnmounted(() => {
  unsubscribe?.()
  unsubscribe = null
})

// ---------------------------------------------------------------- 展示映射

const APP_STATUS: Record<AppStatus, { dot: string; text: string }> = {
  running: { dot: 'ok', text: '运行中' },
  waiting: { dot: 'wait', text: '等待打开' },
  closed: { dot: 'off', text: '已关闭' },
}

/** 点击 chip 循环切换状态（UI-05-B 的"点一下换状态"）。**只改内存状态**。 */
const NEXT_STATUS: Record<AppStatus, AppStatus> = {
  running: 'waiting',
  waiting: 'closed',
  closed: 'running',
}

const goal = computed(() => current.value?.goal ?? '')
const modeName = computed(() => current.value?.mode ?? '')
const layoutText = computed(() => {
  const l = layout.value
  if (!l) return '未设置'
  return l.type === 'manual' ? `手动调整 · ${l.snapshotId ?? ''}` : '自动布局'
})
const appCountText = computed(() => {
  const running = apps.value.filter((a) => a.status === 'running').length
  return `${running}/${apps.value.length} 运行中`
})

function cycleStatus(app: WorkspaceApp): void {
  const next = NEXT_STATUS[app.status]
  const updated = workspaceRuntime.updateStatus(app.appId, next)
  if (!updated) return
  // 如实说明这是状态演示，不是真的开了软件
  toast.info(`${app.name} → ${APP_STATUS[next].text}（仅状态演示，未启动真实软件）`)
}

// ---------------------------------------------------------------- 模板

async function applyTemplate(tpl: WorkspaceTemplate): Promise<void> {
  if (busy.value) return
  busy.value = true
  try {
    const report = await workspaceRuntime.prepareWorkspace(tpl.id)
    if (report.ok) toast.success(`已应用模式模板「${tpl.name}」（${report.steps.length} 步）`)
    else toast.error(`应用失败：${report.steps[0]?.detail ?? '未知原因'}`)
  } finally {
    busy.value = false
  }
}

function saveAsTemplate(): void {
  const tpl = workspaceRuntime.saveTemplate()
  if (!tpl) {
    toast.error('还没有工作空间，无法保存为模板')
    return
  }
  toast.success(`已保存模板「${tpl.name}」`)
}

function recoveryText(): string {
  const r = recovery.value
  if (!r) return '未读取'
  if (!r.recovery.available) return r.recovery.reason
  return r.recovery.reason
}
</script>

<template>
  <section class="ws-status" data-pw-workspace-status>
    <!-- 状态栏（UI-05-B：当前任务 / 应用 / 布局 / 模式） -->
    <div class="pw-row pw-row--wrap ws-bar" data-pw-ws-bar>
      <span class="ws-item">
        <span class="pw-t-label">当前任务</span>
        <PwChip v-if="goal" variant="brand" data-pw-ws-goal>{{ goal }}</PwChip>
        <PwChip v-else data-pw-ws-goal>未设置工作目标</PwChip>
      </span>

      <span class="ws-item ws-apps">
        <span class="pw-t-label">应用</span>
        <PwChip
          v-for="a in apps"
          :key="a.appId"
          as="button"
          size="sm"
          :title="'点击切换状态（仅状态演示）'"
          @click="cycleStatus(a)"
        >
          <i class="pw-dot" :class="`pw-dot--${APP_STATUS[a.status].dot}`"></i>
          {{ a.name }}<span class="ws-st">{{ APP_STATUS[a.status].text }}</span>
        </PwChip>
        <span v-if="!apps.length" class="pw-t-cap">没有工作空间</span>
      </span>

      <span class="ws-item">
        <span class="pw-t-label">布局</span>
        <PwChip size="sm" data-pw-ws-layout>{{ layoutText }}</PwChip>
      </span>

      <span class="ws-item">
        <span class="pw-t-label">模式</span>
        <PwChip size="sm" data-pw-ws-mode>{{ modeName || '未设置' }}</PwChip>
      </span>

      <span class="pw-spacer"></span>
      <PwButton size="sm" variant="ghost" @click="saveAsTemplate">保存为模板</PwButton>
    </div>

    <!-- 模式模板（UI-05-B：模板卡 + 应用） -->
    <div class="pw-row ws-sec-head">
      <div class="pw-t-section pw-grow">模式模板</div>
      <span class="pw-t-cap">{{ appCountText }}</span>
    </div>

    <div class="pw-grid ws-grid" data-pw-ws-templates>
      <PwCard v-for="t in templates" :key="t.id" stack class="ws-tpl">
        <div class="pw-t-card">{{ t.name }}</div>
        <div class="pw-t-cap">{{ t.goal || '未设置目标' }}</div>
        <div class="pw-t-cap">
          {{ t.apps.length }} 个应用 · {{ t.layoutSnapshot ? '含布局快照' : '无布局快照' }}
        </div>
        <div class="pw-row">
          <PwButton size="sm" :disabled="busy" @click="applyTemplate(t)">应用</PwButton>
        </div>
      </PwCard>
      <PwCard v-if="!templates.length" variant="ghost" class="ws-empty">
        <span class="pw-t-sm pw-c2">还没有模式模板 —— 先准备一个工作空间，再「保存为模板」。</span>
      </PwCard>
    </div>

    <!-- 恢复可用性（只读；执行侧未放开，如实显示） -->
    <PwCard variant="ghost" class="ws-recovery">
      <span class="pw-t-sm pw-c2" data-pw-ws-recovery>
        恢复能力：{{ recoveryText() }}
      </span>
    </PwCard>
  </section>
</template>

<style scoped>
.ws-status {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
}

.ws-bar {
  gap: 12px;
  padding: 8px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-card);
}

.ws-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.ws-apps {
  flex-wrap: wrap;
}

.ws-st {
  color: var(--text-3);
  margin-left: 4px;
}

.ws-sec-head {
  justify-content: space-between;
  margin-top: 4px;
}

.ws-grid {
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
}

.ws-tpl {
  gap: 4px;
}

.ws-empty {
  grid-column: 1 / -1;
}

.ws-recovery {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
</style>
