<script setup lang="ts">
/**
 * AI 侧栏（原型 `.ai-dock` + `aiDockHtml()`；业务契约见 08 §5）
 * ==========================================================
 *
 * 结构 = 设计稿 `aiDockHtml()`：
 * ```
 * <aside class="ai-dock" [.collapsed] [.force-open]>
 *   <div class="dock-rail">                       ← 收起态：48px 竖条
 *     <button class="rail-btn">sparkle</button>
 *     <span class="rail-label">AI 助手</span>
 *     <span class="rail-mode">ws|message</span>
 *   </div>
 *   <div class="dock-panel">                      ← 展开态：var(--ai-panel-w)
 *     <div class="rsh rsh--ai"></div>             ← 左缘拖拽手柄
 *     <div class="ai-head">…</div>
 *     <div class="ai-stream / .msg>.bubble">…</div>
 *     <div class="ai-suggest">…</div>
 *     <div class="ai-input">…</div>
 *   </div>
 * </aside>
 * ```
 *
 * ★ 与旧结构的**结构性**差异：收起态不再是"另一个根元素 `.ai-rail`"，
 *   而是同一个 `.ai-dock` 加 `.collapsed`（`.dock-panel` 隐藏、`.dock-rail` 显示）。
 *   这样设计稿的范围规则（`.shell[data-rs="collapsed"] .ai-dock .dock-rail{display:flex}`、
 *   `.shell[data-cw="sm"] .ai-dock …`）才能落到真实节点上；旧写法下那些规则全部落空。
 *
 * ★ 本文件**不含任何样式块**（除末尾几条纯布局的 scoped 规则，零动效）：
 *   `.ai-dock` / `.dock-panel` / `.dock-rail` / `.rail-*` / `.ai-head` / `.ai-perm` /
 *   `.msg` / `.bubble` / `.seg` / `.input` / `.ai-input` 的视觉全部来自
 *   `styles/base.css`（含 UI-FUSION-FULL 段的设计稿规则）。
 *   原因不只是"单一来源"：TECH-03-B §一 T1d 冻结了本文件
 *   —— 文件里不得出现 transition / animation / keyframes 这类字样，
 *   动效只能由 CSS 层承担（`dockIn` / `dockOut` / `dockSwap`）。
 *
 * TECH-03-B §一：宽度拖拽的**唯一授权来源是 Motion Runtime**（`claim('drag')`），
 * 见 `startResize`。三个成对要素（拿不到 Primary 即退 / move 侧守卫 / endResize 必 release）
 * 与 T1a–T1c 的冻结断言一一对应，**不可拆分改写**。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'

import PwIcon from '@/components/PwIcon.vue'
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
/** 设计稿 `rail-mode.on`：工作区模式亮起（聊天模式是默认灰） */
const isWorkspace = computed(() => ai.mode === 'workspace')

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
  <!-- 单根 `.ai-dock`：收起/展开是同一个节点上的 `.collapsed`（设计稿口径） -->
  <aside
    class="ai-dock"
    :class="{ collapsed: ai.collapsed }"
    aria-label="AI 助手"
  >
    <!-- 收起态（48px 竖条）：设计稿 `.dock-rail` -->
    <div class="dock-rail">
      <button class="rail-btn" title="展开 AI 助手" @click="ai.toggleCollapsed()">
        <PwIcon name="sparkle" :size="18" />
      </button>
      <span class="rail-label">AI 助手</span>
      <span
        class="rail-mode"
        :class="{ on: isWorkspace }"
        :title="isWorkspace ? '工作区模式' : '聊天模式'"
      >
        <PwIcon :name="isWorkspace ? 'ws' : 'message'" :size="12" />
      </span>
    </div>

    <!-- 展开态：设计稿 `.dock-panel` -->
    <div class="dock-panel">
      <!-- 拖拽把手（设计稿 `.rsh--ai`）：ref 与 mousedown 必须绑在同一元素（T1c） -->
      <div
        ref="resizerEl"
        class="rsh rsh--ai"
        :class="{ on: dragging }"
        role="separator"
        aria-orientation="vertical"
        aria-label="调整 AI 侧栏宽度"
        title="拖拽调整宽度"
        tabindex="0"
        @mousedown.prevent="startResize"
      ></div>

      <!-- 顶部：标题 + 模式（.seg，设计稿原文）+ 模型 + 权限 -->
      <header class="ai-head">
        <div class="row ai-head-title">
          <div class="row ai-head-brand">
            <span class="ai-head-mark"><PwIcon name="sparkle" :size="18" /></span>
            <span class="t-card">AI 助手</span>
          </div>
          <button class="icon-btn sm" title="收起侧栏" @click="ai.toggleCollapsed()">
            <PwIcon name="chev-r" :size="16" />
          </button>
        </div>

        <!-- 模式切换（设计稿 `.seg`：聊天 / 工作空间助手） -->
        <div class="seg ai-modes" role="tablist">
          <button
            :class="{ on: ai.mode === 'consult' }"
            title="不与任何用户数据关联的普通对话"
            @click="ai.setMode('consult')"
          >
            <PwIcon name="message" :size="14" /> 聊天
          </button>
          <button
            :class="{ on: ai.mode === 'workspace' }"
            title="可读取当前工作模式与项目信息，给出环境相关建议"
            @click="ai.setMode('workspace')"
          >
            <PwIcon name="ws" :size="14" /> 工作空间助手
          </button>
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

        <!-- 权限提示（08 §5：必须在 UI 上显式展示）。设计稿：workspace 用 .ai-perm（success 底），
             consult 用 .ai-perm.plain（中性底）。 -->
        <div
          class="ai-perm"
          :class="{ plain: ai.mode === 'consult' }"
          @click="showPermissionPanel = !showPermissionPanel"
          :title="ai.mode === 'consult' ? '咨询模式不读取任何用户数据' : '点击查看/调整授权范围'"
        >
          <span v-if="ai.mode !== 'consult'" class="dot"></span>
          <PwIcon v-else name="lock" :size="14" />
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

      <!-- 对话流（设计稿 `.msg > .bubble`：自己贴右、AI 贴左） -->
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
          <!-- 建议条（设计稿 `.ai-suggest` + `.chip--outline`） -->
          <div class="ai-suggest">
            <button
              v-for="s in ai.mode === 'consult'
                ? ['列一下今天要做的事', '帮我写一段文案']
                : ['总结今天的工作', '找出未提交的改动']"
              :key="s"
              class="chip chip--outline"
            >
              {{ s }}
            </button>
          </div>
        </div>

        <div v-for="m in messages" :key="m.id" class="msg" :class="{ me: m.role === 'user' }">
          <div class="bubble">
            <div v-if="m.content" v-html="renderMarkdown(m.content)"></div>
            <span v-if="m.streaming" class="ai-cursor">▍</span>
            <div v-if="m.error" class="ai-msg-error">{{ m.error }}</div>
            <div
              v-if="m.role === 'assistant' && m.content && !m.streaming"
              class="ai-msg-actions"
            >
              <button class="ai-copy" title="复制" @click="copyText(m.content)">复制</button>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区（设计稿 `.ai-input` + `.input`） -->
      <footer class="ai-input">
        <label class="input ai-input-box">
          <textarea
            v-model="draft"
            rows="2"
            placeholder="输入消息…（Enter 发送，Shift+Enter 换行）"
            @keydown="onKeydown"
          ></textarea>
          <button
            class="icon-btn sm ai-send-icon"
            :disabled="!draft.trim() || ai.streaming"
            title="发送"
            @click="send"
          >
            <PwIcon name="arrow-r" :size="16" />
          </button>
        </label>
        <div class="ai-foot-actions">
          <button class="ai-clear" title="清空对话" @click="ai.clear()">清空</button>
          <button v-if="ai.streaming" class="ai-stop" @click="ai.cancel()">停止</button>
        </div>
      </footer>
    </div>
  </aside>
</template>

<style scoped>
/* ⚠️ 本文件受 TECH-03-B §一 T1d 冻结：不得出现 transition / animation / keyframes 字样。
 * 因此这里**只放纯布局**（无任何动效声明）—— 动效全部由 styles/base.css 承担。 */

.ai-head-title {
  justify-content: space-between;
}

.ai-head-brand {
  gap: var(--space-2);
}

.ai-head-mark {
  color: var(--brand-600);
}

.ai-modes {
  width: 100%;
}

.ai-modes button {
  flex: 1;
  justify-content: center;
}

.ai-msg-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
  margin-top: 2px;
}

.ai-input-box {
  align-items: flex-end;
  height: auto;
  min-height: 40px;
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
}

.ai-send-icon {
  flex: 0 0 auto;
  color: var(--brand-600);
}

.ai-foot-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-2);
}
</style>
