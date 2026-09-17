<script setup lang="ts">
/**
 * AI 侧栏（08 §5）—— 右侧可收起、宽度可拖拽且持久化。
 *
 * 结构：
 *   顶部 模式切换（咨询/工作助手）+ Provider/模型选择 + 权限提示
 *   中部 对话流（Markdown 轻渲染 + 代码块 + 复制）
 *   底部 输入框（多行 / Ctrl+Enter 发送 / Shift+Enter 换行）
 *
 * workspace 模式额外显示"当前上下文"标签（#开发模式 #项目:xxx）。
 *
 * TECH-03-B §一：宽度拖拽的**唯一授权来源是 Motion Runtime**（`claim('drag')`），
 * 见 `startResize`。视觉与动画与接线前完全一致 —— 本文件不新增任何动效。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import { useCurrentModel } from '@/composables/useCurrentModel'
import { claim, type MotionClaim } from '@/motion'
import { SCOPE_LABEL, SCOPES, useAiStore } from '@/stores/ai'
import type { Scope } from '@/stores/ai'
import { renderMarkdown } from '@/utils/markdown'

const ai = useAiStore()
/** TECH-03-B §四：顶栏"当前模型"的**只读**来源 —— ModelRegistry canonical（不连真实 API）。 */
const { currentModel } = useCurrentModel()

const draft = ref('')
const scrollBox = ref<HTMLElement | null>(null)
const showPermissionPanel = ref(false)
const dragging = ref(false)
/** 拖拽把手元素（Motion claim 挂它上面 —— 与"哪个元素在被拖"语义一致）。 */
const resizerEl = ref<HTMLElement | null>(null)
/** 本轮拖拽持有的 Motion 声明。`null` = 未在拖拽。 */
let dragClaim: MotionClaim | null = null
let dragMove: ((ev: MouseEvent) => void) | null = null

const messages = computed(() => ai.messages)

onMounted(async () => {
  await ai.init()
  await ai.refreshContextTags()
})

/** 新内容到达时滚到底部。 */
watch(
  () => messages.value.map((m) => m.content.length).join(','),
  async () => {
    await nextTick()
    const el = scrollBox.value
    if (el) el.scrollTop = el.scrollHeight
  },
)

function send(): void {
  const text = draft.value
  draft.value = ''
  void ai.send(text)
}

/** Enter 发送 / Shift+Enter 换行（08 §5）。 */
function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (ai.streaming) return
    send()
  }
}

/** 结束拖拽：拆监听 + 释放 Motion 声明（两者必须一起做，否则会留下"幽灵 Primary"）。 */
function endResize(): void {
  if (dragMove) window.removeEventListener('mousemove', dragMove)
  window.removeEventListener('mouseup', endResize)
  dragMove = null
  dragClaim?.release()
  dragClaim = null
  dragging.value = false
}

/**
 * 宽度拖拽（左边缘）。
 *
 * TECH-03-B §一：**Motion Runtime 是拖拽的唯一来源** —— 先向它声明 `claim('drag')`：
 * - 拿不到 Primary（被更高优先级 Motion 占着）→ 本次拖拽不启动（并把声明退掉）；
 * - 拖到一半被顶掉（`onSuperseded`）→ 立即收敛退出，不再改宽度。
 *
 * 本函数**不新增任何动画/过渡**，只是把"谁有权拖"这件事收回 Motion Runtime 决策。
 */
function startResize(e: MouseEvent): void {
  const el = resizerEl.value
  if (!el) return
  endResize() // 防御：上一轮若未正常收尾，先清干净，避免叠出多个声明

  const c = claim(el, 'drag', () => endResize())
  if (!c.isPrimary) {
    c.release()
    return
  }
  dragClaim = c
  dragging.value = true

  const startX = e.clientX
  const startW = ai.width

  dragMove = (ev: MouseEvent): void => {
    // 声明失效（被顶掉）后不得再改宽度 —— 单一来源的另一半
    if (!dragClaim?.isPrimary) return
    // 侧栏在右侧：向左拖 → 变宽
    ai.setWidth(startW + (startX - ev.clientX))
  }
  window.addEventListener('mousemove', dragMove)
  window.addEventListener('mouseup', endResize)
}

onUnmounted(() => {
  endResize()
})

async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    /* 剪贴板不可用时静默失败（非关键路径） */
  }
}

function scopeLabel(s: Scope): string {
  return SCOPE_LABEL[s]
}
</script>

<template>
  <!-- 收起态：一条窄条，点击展开 -->
  <div v-if="ai.collapsed" class="ai-rail" @click="ai.toggleCollapsed()">
    <span class="ai-rail-text">AI</span>
  </div>

  <aside v-else class="ai-sidebar" :style="{ width: `${ai.width}px` }">
    <!-- 拖拽把手 -->
    <div
      ref="resizerEl"
      class="ai-resizer"
      :class="{ active: dragging }"
      @mousedown.prevent="startResize"
      title="拖拽调整宽度"
    ></div>

    <!-- 顶部：模式 + 模型 + 权限 -->
    <header class="ai-head">
      <div class="ai-head-row">
        <div class="ai-modes">
          <button
            :class="{ active: ai.mode === 'consult' }"
            @click="ai.setMode('consult')"
            title="不与任何用户数据关联的普通对话"
          >
            咨询
          </button>
          <button
            :class="{ active: ai.mode === 'workspace' }"
            @click="ai.setMode('workspace')"
            title="可读取当前工作模式与项目信息，给出环境相关建议"
          >
            工作助手
          </button>
        </div>
        <button class="ai-icon-btn" title="收起侧栏" @click="ai.toggleCollapsed()">»</button>
      </div>

      <!-- 当前 AI（2026-09-13 交互重构：默认只显示在用 AI 的名字；切换/模型名收进高级） -->
      <details class="ai-advanced">
        <summary>当前 AI：{{ ai.currentProvider?.label ?? '未配置' }}</summary>
        <div class="ai-head-row">
          <select
            :value="ai.providerId"
            class="ai-select"
            @change="ai.setProvider(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="p in ai.providers" :key="p.id" :value="p.id" :disabled="!p.enabled">
              {{ p.label }}{{ p.enabled ? '' : '（未开放）' }}
            </option>
          </select>

          <input
            v-if="ai.currentProvider?.capabilities.includes('models')"
            v-model="ai.model"
            class="ai-model-input"
            placeholder="模型名"
            @change="ai.setModel(ai.model)"
          />
        </div>
      </details>

      <!-- TECH-03-B §四：只读「当前模型」。事实来源 = ModelRegistry canonical；纯展示，不可点、不可改。 -->
      <div class="ai-canonical" :title="currentModel.title" data-pw-current-model>
        <span class="ai-canonical-key">当前模型</span>
        <span class="ai-canonical-val">{{ currentModel.label }}</span>
        <span v-if="currentModel.badge" class="ai-canonical-badge">{{ currentModel.badge }}</span>
      </div>

      <!-- 权限提示（08 §5：必须在 UI 上显式展示） -->
      <div
        class="ai-perm"
        :class="{ none: ai.mode === 'consult' }"
        @click="showPermissionPanel = !showPermissionPanel"
        :title="ai.mode === 'consult' ? '咨询模式不读取任何用户数据' : '点击查看/调整授权范围'"
      >
        <span class="ai-perm-text">{{ ai.permissionText }}</span>
        <span class="ai-perm-toggle">{{ showPermissionPanel ? '▴' : '▾' }}</span>
      </div>

      <!-- 授权范围调整（仅 workspace 模式有意义） -->
      <div v-if="showPermissionPanel && ai.mode === 'workspace'" class="ai-perm-panel">
        <label v-for="s in SCOPES" :key="s" class="ai-perm-item">
          <input
            type="checkbox"
            :checked="(ai.enabledScopes as Record<string, boolean>)[s]"
            @change="
              ai.setScope(
                s,
                ($event.target as HTMLInputElement).checked,
              )
            "
          />
          <span>{{ scopeLabel(s) }}</span>
        </label>
        <p class="ai-perm-note">关闭的来源不会被发送给模型。</p>
      </div>

      <!-- workspace：当前上下文标签 -->
      <div v-if="ai.mode === 'workspace' && ai.contextTags.length" class="ai-tags">
        <span v-for="t in ai.contextTags" :key="t" class="ai-tag">{{ t }}</span>
      </div>
      <div v-else-if="ai.mode === 'workspace' && !ai.currentProvider" class="ai-tags" />

      <!-- 未配置 key 的引导（08 §7 第一行） -->
      <div v-if="!ai.canSend && ai.currentProvider" class="ai-warn">
        <template v-if="ai.currentProvider.needsKey && !ai.currentProvider.hasKey">
          尚未配置 {{ ai.currentProvider.label }} 的 API Key。
          <router-link to="/settings">去设置</router-link>
        </template>
        <template v-else-if="!ai.currentProvider.enabled">
          {{ ai.currentProvider.note }}
        </template>
      </div>
    </header>

    <!-- 对话流 -->
    <div ref="scrollBox" class="ai-stream">
      <div v-if="!messages.length" class="ai-empty">
        <p class="ai-empty-title">
          {{ ai.mode === 'consult' ? '咨询模式' : '工作助手' }}
        </p>
        <p class="ai-empty-hint">
          {{
            ai.mode === 'consult'
              ? '普通对话。我不会读取你的项目、文件或个人信息。'
              : '我会结合你当前的工作模式与项目给出建议。'
          }}
        </p>
      </div>

      <div v-for="m in messages" :key="m.id" class="ai-msg" :class="m.role">
        <div class="ai-msg-role">{{ m.role === 'user' ? '你' : 'AI' }}</div>
        <div class="ai-msg-body">
          <div v-if="m.content" v-html="renderMarkdown(m.content)"></div>
          <span v-if="m.streaming" class="ai-cursor">▍</span>
          <div v-if="m.error" class="ai-msg-error">{{ m.error }}</div>
        </div>
        <button
          v-if="m.role === 'assistant' && m.content && !m.streaming"
          class="ai-copy"
          title="复制"
          @click="copyText(m.content)"
        >
          复制
        </button>
      </div>
    </div>

    <!-- 输入区 -->
    <footer class="ai-foot">
      <textarea
        v-model="draft"
        class="ai-input"
        rows="2"
        placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
        @keydown="onKeydown"
      ></textarea>
      <div class="ai-foot-actions">
        <button class="ai-clear" title="清空对话" @click="ai.clear()">清空</button>
        <button v-if="ai.streaming" class="ai-stop" @click="ai.cancel()">停止</button>
        <button class="ai-send primary" :disabled="!draft.trim() || ai.streaming" @click="send">
          发送
        </button>
      </div>
    </footer>
  </aside>
</template>
