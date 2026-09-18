<script setup lang="ts">
/**
 * AI 助手（TECH-05-D §P1-A）。
 *
 * ## 本页此前是什么
 * 一个 366 字节的占位骨架 —— 三行文案（"阶段5 交付：…"）。
 * 真实的对话只发生在右侧 AI 侧栏里，`/ai` 这个导航项点进来什么都没有。
 *
 * ## 本页现在是什么
 * **会话状态壳**：把"会话"这件事变成一个用户可以看见、可以操作的真实状态 ——
 * 历史会话、新建会话、切换、清空、空态/生成中/失败态、双模式与权限边界。
 *
 * ```
 *   本页（AiView.vue）   ← 只做展示与交互，不做任何取数/传输
 *        │  读 stores/ai.ts（会话状态 + 消息 + 状态归约）
 *        │  读 composables/useCurrentModel（当前模型的只读投影）
 *        ▼
 *   ai/assistant/*（解析目标 + 权限边界 + 传输）→ core → sidecar
 * ```
 *
 * ## 三条边界（本页刻意不越）
 * 1. **不拼请求、不发请求**：本页没有 `fetch`、没有 `invokeCore`、没有 `localStorage`。
 *    发送只是 `ai.send(text)` 一句话 —— 参数怎么装配由应用层决定；
 * 2. **不持有当前模型**：本页不存 provider/model 副本，只投影 canonical
 *    （与 AI 侧栏同一个 `useCurrentModel()`、同一个共享 ModelRegistry）；
 * 3. **不读工作台数据**：咨询模式下本页**不会去问** core 要上下文
 *    （应用层的 `previewContext` 在 consult 时直接返回空，连调用都不发生）。
 *    工作助手模式本轮只建立**模式状态与权限边界**，不实现真实数据访问。
 *
 * ## 样式
 * 只用 `pw-*` 共享原语 + base.css 既有类 + 本页局部的 `.aiv-*` 版面类；
 * 外观值全部来自 token，本页不定义任何裸色值、不新增任何动画。
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { useCurrentModel } from '@/composables/useCurrentModel'
import { SCOPE_LABEL, SCOPES, useAiStore } from '@/stores/ai'
import type { AiMode, Scope } from '@/stores/ai'
import { renderMarkdown } from '@/utils/markdown'
import PwButton from '@/components/ui/PwButton.vue'
import PwCard from '@/components/ui/PwCard.vue'
import PwChip from '@/components/ui/PwChip.vue'

const ai = useAiStore()
/** 当前模型：与 AI 侧栏同一个共享 Registry、同一个投影函数（只读）。 */
const { currentModel } = useCurrentModel()

const draft = ref('')
const showPermissionPanel = ref(false)

onMounted(async () => {
  await ai.init()
  await ai.refreshContextTags()
})

// ---------------------------------------------------------------- 读模型（全部是投影）

/** 当前模型（canonical 投影）。**不是**本页的一份 state。 */
const modelView = computed(() => currentModel.value)
/** 给验收脚本直接读的 key：`provider::model`（与模型管理页同一口径）。 */
const currentKey = computed(() => {
  const c = modelView.value.canonical
  return c.model ? `${c.provider}::${c.model}` : ''
})

const mode = computed(() => ai.mode)
const isWorkspace = computed(() => ai.mode === 'workspace')
/** 会话状态来自应用层的唯一归约（unset/empty/idle/loading/error）。 */
const status = computed(() => ai.sessionStatus)
const sessions = computed(() => ai.sessionsInMode)
const messages = computed(() => ai.messages)

/** 咨询模式下**恒为空**（判据在应用层，不在本页）。 */
const permitted = computed<Scope[]>(() =>
  isWorkspace.value ? (SCOPES.filter((s) => ai.enabledScopes[s]) as Scope[]) : [],
)

const emptyHint = computed(() =>
  isWorkspace.value
    ? '我会结合你当前的工作模式与项目给出建议。'
    : '普通对话。我不会读取你的项目、文件或个人信息。',
)

/** 工作助手模式的建议提问（点击**填充输入框**，不是装饰性的死按钮）。 */
const SUGGESTIONS = ['总结今天的工作', '生成项目周报', '找出还没提交的改动'] as const

/**
 * 页面内验收句柄（与 `window.__pwModels` / `window.__pwAiModel` 同源做法）。
 *
 * 暴露的全部是**只读投影**：共享 Registry 本体、当前模式、会话 id 与状态、
 * 权限边界。没有任何写口 —— 脚本拿它证明"本页与侧栏读的是同一个 Registry"、
 * "咨询模式的授权范围恒为空"，而不是靠读代码相信。
 */
declare global {
  interface Window {
    __pwAssistant?: {
      /** 共享 ModelRegistry 本体（验收脚本用 `===` 与模型管理页/侧栏比对）。 */
      registry: unknown
      mode: () => string
      sessionId: () => string
      sessionStatus: () => string
      messageCount: () => number
      grantedScopes: () => string[]
      permission: () => string
      /** 连接错误（与"会话错误"分开；验收脚本据此区分环境问题与会话问题）。 */
      connection: () => string
      current: () => string
    }
  }
}

// registry 取自共享单例（与模型管理页/侧栏同一对象）
const shared = ai.assistant
if (typeof window !== 'undefined') {
  window.__pwAssistant = {
    // 共享 ModelRegistry（对象同一性由验收脚本用 === 直接比对）
    registry: shared.registry,
    mode: () => mode.value,
    sessionId: () => ai.sessionId,
    sessionStatus: () => status.value,
    messageCount: () => messages.value.length,
    grantedScopes: () => permitted.value.slice(),
    permission: () => ai.permissionText,
    connection: () => ai.connectionError,
    current: () => currentKey.value,
  }
}

// ---------------------------------------------------------------- 交互（全部是转发）

function send(): void {
  const text = draft.value
  draft.value = ''
  void ai.send(text)
}

function onKeydown(e: KeyboardEvent): void {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (ai.streaming) return
    send()
  }
}

function setMode(m: AiMode): void {
  ai.setMode(m)
  showPermissionPanel.value = false
  void ai.refreshContextTags()
}

function toggleScope(s: Scope): void {
  ai.setScope(s, !ai.enabledScopes[s])
}

function useSuggestion(text: string): void {
  draft.value = text
}

function scopeLabel(s: Scope): string {
  return SCOPE_LABEL[s]
}

/** 侧栏标题的时间戳（原型：会话列表右侧显示时间）。 */
function timeLabel(ms: number): string {
  const d = new Date(ms)
  const p = (n: number): string => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}`
}
</script>

<template>
  <section class="aiv" :data-pw-assistant-mode="mode" :data-pw-assistant-status="status">
    <header class="aiv-head page-head">
      <div class="pw-grow">
        <h2 class="pw-t-page">{{ isWorkspace ? '工作空间助手' : 'AI 助手' }}</h2>
        <p class="pw-t-cap">
          {{
            isWorkspace
              ? '聚焦当前工作空间的深度协作 · 需要你授权访问'
              : '聚焦会话 · 适合多轮讨论与长任务；随手一问用右侧的 AI 助手'
          }}
        </p>
      </div>

      <div class="tabs aiv-tabs" style="margin-bottom: 0">
        <button
          type="button"
          :class="{ on: !isWorkspace }"
          :aria-pressed="!isWorkspace"
          data-pw-assistant-tab="consult"
          @click="setMode('consult')"
        >
          聊天
        </button>
        <button
          type="button"
          :class="{ on: isWorkspace }"
          :aria-pressed="isWorkspace"
          data-pw-assistant-tab="workspace"
          @click="setMode('workspace')"
        >
          工作空间助手
        </button>
      </div>

      <!-- 当前模型：只读，来源 = 共享 ModelRegistry 的 canonical；点击进模型管理页 -->
      <RouterLink
        class="aiv-model"
        to="/models?from=ai"
        data-pw-assistant-current
        :data-current-key="currentKey"
        :data-current-provider="modelView.canonical.provider"
        :data-current-model="modelView.canonical.model"
        :data-current-label="modelView.label"
        :title="modelView.title"
      >
        <span class="aiv-model-label">当前模型</span>
        <span class="aiv-model-val">{{ modelView.label }}</span>
        <PwChip v-if="modelView.badge" size="sm" variant="outline">{{ modelView.badge }}</PwChip>
      </RouterLink>
    </header>

    <div class="aiv-grid ai-grid">
      <!-- 左：历史会话（会话状态壳的另一半） -->
      <PwCard class="aiv-sessions ai-sessions">
        <div class="pw-row aiv-sessions-head">
          <span class="pw-t-cap pw-grow">历史会话</span>
          <PwButton
            size="sm"
            variant="ghost"
            title="新建会话"
            data-pw-assistant-new
            @click="ai.newSession()"
          >
            ＋
          </PwButton>
        </div>
        <div class="aiv-session-list ai-session-list" data-pw-assistant-sessions>
          <p v-if="!sessions.length" class="pw-t-cap aiv-sessions-empty">还没有会话</p>
          <button
            v-for="s in sessions"
            :key="s.id"
            type="button"
            class="aiv-session ai-session"
            :class="{ 'is-on': s.id === ai.sessionId, on: s.id === ai.sessionId }"
            :data-session-id="s.id"
            :data-session-active="s.id === ai.sessionId ? '1' : '0'"
            @click="ai.switchSession(s.id)"
          >
            <span class="pw-t-sm aiv-session-title">{{ s.title }}</span>
            <span class="pw-t-cap aiv-session-time">{{ timeLabel(s.updatedAt) }}</span>
          </button>
        </div>
      </PwCard>

      <!-- 右：对话区 -->
      <PwCard size="lg" class="aiv-chat ai-chat">
        <!-- 权限边界：两种模式的显示**必须不同**（08 §5） -->
        <div
          class="aiv-chat-head ai-chat-head"
          :class="{ 'is-ws': isWorkspace }"
          data-pw-assistant-permission
          :data-permission-mode="mode"
          :data-granted-count="String(permitted.length)"
          :data-permission-text="ai.permissionText"
        >
          <span class="pw-dot" :class="isWorkspace ? 'pw-dot--ok' : 'pw-dot--off'"></span>
          <span class="pw-t-cap pw-grow">{{ ai.permissionText }}</span>
          <PwButton
            v-if="isWorkspace"
            size="sm"
            variant="ghost"
            data-pw-assistant-manage-perm
            @click="showPermissionPanel = !showPermissionPanel"
          >
            管理权限
          </PwButton>
        </div>

        <!-- 授权范围（仅工作助手模式有意义） -->
        <div v-if="isWorkspace && showPermissionPanel" class="aiv-perm-panel">
          <label v-for="s in SCOPES" :key="s" class="aiv-perm-item">
            <input
              type="checkbox"
              :checked="ai.enabledScopes[s]"
              :data-scope="s"
              @change="toggleScope(s)"
            />
            <span class="pw-t-sm">{{ scopeLabel(s) }}</span>
          </label>
          <p class="pw-t-cap aiv-perm-note">关闭的来源不会被发送给模型。本轮尚未接入真实数据访问。</p>
        </div>

        <!-- 工作助手模式下的上下文标签（本次带了什么） -->
        <div v-if="isWorkspace && ai.contextTags.length" class="aiv-tags">
          <PwChip v-for="t in ai.contextTags" :key="t" size="sm" variant="outline">{{ t }}</PwChip>
        </div>

        <!-- 对话流 -->
        <div class="aiv-msgs ai-msgs" data-pw-assistant-messages>
          <!-- 空会话态 -->
          <div v-if="status === 'empty' || status === 'unset'" class="empty-state" data-pw-assistant-empty>
            <span class="pw-avatar pw-avatar--lg">✦</span>
            <div class="pw-t-card">{{ isWorkspace ? '工作空间助手' : '咨询模式' }}</div>
            <div class="pw-t-cap aiv-empty-hint">{{ emptyHint }}</div>
            <PwButton v-if="status === 'unset'" variant="primary" size="sm" @click="ai.newSession()">
              新建会话
            </PwButton>
          </div>

          <template v-else>
            <div
              v-for="m in messages"
              :key="m.id"
              class="aiv-msg msg"
              :class="m.role === 'user' ? 'is-me me' : 'is-ai'"
              :data-msg-role="m.role"
              :data-msg-streaming="m.streaming ? '1' : '0'"
              :data-msg-error="m.error ? '1' : '0'"
            >
              <div class="pw-t-cap aiv-msg-role">{{ m.role === 'user' ? '你' : 'AI' }}</div>
              <div class="aiv-msg-body bubble">
                <div v-if="m.content" v-html="renderMarkdown(m.content)"></div>
                <span v-if="m.streaming" class="aiv-cursor">▍</span>
                <div v-if="m.error" class="aiv-msg-error">{{ m.error }}</div>
              </div>
            </div>
          </template>

          <!-- 生成中 -->
          <p v-if="status === 'loading'" class="pw-t-cap aiv-state" data-pw-assistant-loading>
            正在生成…
          </p>
          <!-- 上次失败 -->
          <p v-else-if="status === 'error'" class="pw-t-cap aiv-state" data-pw-assistant-error>
            {{ ai.lastError }}
          </p>
        </div>

        <!-- 工作助手模式的建议提问（点击填充输入框，不是死按钮） -->
        <div v-if="isWorkspace && status !== 'loading'" class="aiv-suggest">
          <PwChip
            v-for="s in SUGGESTIONS"
            :key="s"
            as="button"
            size="sm"
            variant="outline"
            @click="useSuggestion(s)"
          >
            {{ s }}
          </PwChip>
        </div>

        <!-- 输入区 -->
        <div class="aiv-foot">
          <textarea
            v-model="draft"
            class="pw-input aiv-input"
            rows="2"
            :placeholder="isWorkspace ? '问关于这个工作空间的事…' : '随便聊点什么…'"
            data-pw-assistant-draft
            @keydown="onKeydown"
          ></textarea>
          <div class="aiv-foot-actions">
            <PwButton size="sm" variant="ghost" data-pw-assistant-clear @click="ai.clear()">
              清空
            </PwButton>
            <PwButton
              v-if="ai.streaming"
              size="sm"
              variant="ghost"
              data-pw-assistant-stop
              @click="ai.cancel()"
            >
              停止
            </PwButton>
            <PwButton
              variant="primary"
              size="sm"
              :disabled="!draft.trim() || ai.streaming || !ai.canSend"
              data-pw-assistant-send
              @click="send"
            >
              发送
            </PwButton>
          </div>
        </div>

        <!-- 核心服务不可达（环境问题，与会话状态分开显示） -->
        <p v-if="ai.connectionError" class="pw-t-cap aiv-warn" data-pw-assistant-connection>
          {{ ai.connectionError }}
        </p>

        <!-- 未配置 Provider / Key 的引导 -->
        <p v-if="ai.currentProvider && !ai.canSend" class="pw-t-cap aiv-warn">
          <template v-if="ai.currentProvider.needsKey && !ai.currentProvider.hasKey">
            尚未配置 {{ ai.currentProvider.label }} 的 API Key。
            <RouterLink to="/settings">去设置</RouterLink>
          </template>
          <template v-else-if="!ai.currentProvider.enabled">
            {{ ai.currentProvider.note }}
          </template>
        </p>
      </PwCard>
    </div>
  </section>
</template>

<style scoped>
/* ── 版面类与设计稿的对应（双类名桥接 · 第四批）────────────────────────────
   设计稿类名已挂在**同一批元素**上（见模板），故下列版面值**不再本地重复定义**，
   一律由设计稿 CSS 决定（它已并入 base.css）：
     .aiv-tabs         → .tabs          （下划线式 tab：gap:--space-5 / .on::after）
     .aiv-grid         → .ai-grid       （264px 1fr / gap:--gap-section）
     .aiv-sessions     → .ai-sessions   （padding:0 + overflow:hidden）
     .aiv-session-list → .ai-session-list（gap:2px / padding:--space-2）
     .aiv-session      → .ai-session    （内距 / 圆角 / hover / .on 高亮）
     .aiv-chat         → .ai-chat
     .aiv-chat-head    → .ai-chat-head
     .aiv-msgs         → .ai-msgs
   ⚠️ 别再把这些值抄回来：本地块会被编译成 `.x[data-v-*]`，与设计选择器
   **同权重（0,2,0）**，平局靠源序决定 —— 构建后源序不可依赖。
   这与第三批"原语层盖掉设计层"是同一类事故。 */

.aiv {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
  height: 100%;
}

.aiv-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.aiv-model {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--panel);
  color: inherit;
  text-decoration: none;
}

.aiv-model-label {
  color: var(--text-dim);
  font-size: 12px;
}

.aiv-model-val {
  font-size: 13px;
}

/* `.ai-grid` 是纯网格，没有"占满剩余高度"的语义 —— 只补这一条。 */
.aiv-grid {
  flex: 1;
  min-height: 0;
}

/* 内距/overflow 交给 `.ai-sessions`（设计稿是 padding:0 + overflow:hidden）。 */
.aiv-sessions {
  min-height: 0;
}

.aiv-sessions-head {
  justify-content: space-between;
  align-items: center;
  /* 设计稿这一行是 `padding:var(--space-3) var(--space-4) var(--space-2)`
     （因为 `.ai-sessions` 自身 padding 为 0，内距全压在这一行上）。 */
  padding: var(--space-3) var(--space-4) var(--space-2);
}

/* `.ai-session-list` 已给 flex:1/overflow-y:auto/gap/padding；
   只补"允许收缩"—— flex 子项默认 min-height:auto 会顶破容器。 */
.aiv-session-list {
  min-height: 0;
}

.aiv-sessions-empty {
  margin: 0;
}

.aiv-session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.aiv-session-time {
  flex: 0 0 auto;
}

/* `.ai-chat` 已给 display:flex/flex-direction:column/overflow；只补允许收缩。 */
.aiv-chat {
  min-height: 0;
}

.aiv-perm-panel {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 10px 0;
}

.aiv-perm-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.aiv-perm-note {
  width: 100%;
  margin: 0;
}

.aiv-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-top: 8px;
}

/* 内距（`--space-5 0`）与滚动交给设计稿 `.ai-msgs`。
   这里只补"逐条竖排 + 允许收缩"；**不设 gap** —— 设计稿的条间距来自
   `.msg` 自身的 `padding:var(--space-3) var(--space-4)`，再加 gap 就会翻倍。 */
.aiv-msgs {
  min-height: 120px;
  display: flex;
  flex-direction: column;
}

.aiv-empty-hint {
  max-width: 420px;
}

/* 气泡外观（圆角/底色/字号/最大宽）交给设计稿 `.msg .bubble`
   （自己贴右时 `.msg.me .bubble` = brand-50 + 右下角小圆角）。
   本页只保留设计稿没有的东西：**竖排的角色标签**（"你"/"AI"）。 */
.aiv-msg {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-width: 88%;
}

.aiv-msg.is-me {
  align-self: flex-end;
  align-items: flex-end;
}

.aiv-msg-role {
  margin: 0;
}

.aiv-msg-error {
  margin-top: 6px;
  color: var(--danger);
  font-size: 12px;
}

.aiv-cursor {
  opacity: 0.6;
}

.aiv-state {
  margin: 0;
}

.aiv-suggest {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding-bottom: 8px;
}

.aiv-foot {
  border-top: 1px solid var(--border-subtle);
  padding-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.aiv-input {
  resize: vertical;
  font-family: inherit;
}

.aiv-foot-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.aiv-warn {
  margin: 8px 0 0;
}
</style>
