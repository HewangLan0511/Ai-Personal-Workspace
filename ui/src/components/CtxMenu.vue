<script setup lang="ts">
/**
 * 右键菜单浮层（设计稿 `#ctxMenu`）
 * ================================================================
 *
 * 唯一视觉来源 = `personal-workspace-ui/index.html`：
 *   · 类名与结构逐字对应 `.ctx-menu` / `.ctx-head` / `.ctx-item` / `.ctx-sep` /
 *     `.kbd`，几何与动画全部由 base.css 的 UI-FUSION-FULL 段提供 ——
 *     本文件**零视觉声明**（无 style 块），避免长出第二套菜单视觉；
 *   · `.danger`（危险项）、`[disabled]`（禁用项）、`.kbd`（快捷键）三态同设计稿。
 *
 * 挂在 `body` 上（`Teleport`）—— 设计稿就是 `document.body.appendChild(el)`：
 * `.ctx-menu` 是 `position:fixed` 的浮层，留在页面容器里会被祖先的
 * `overflow` / `transform` 裁掉或改参照系。
 *
 * 关闭路径（设计稿 5058–5061 + 4865）：点外部 / 滚轮 / Esc，外加选中条目后关闭。
 */
import { onBeforeUnmount, onMounted } from 'vue'

import PwIcon from '@/components/PwIcon.vue'
import { closeContextMenu, useContextMenu, type CtxEntry } from '@/composables/useContextMenu'

const ctx = useContextMenu()

function run(it: CtxEntry): void {
  if (it.kind !== 'item' || it.disabled) return
  const fn = it.onSelect
  closeContextMenu()
  fn?.()
}

// ---- 关闭路径 ----
function onMouseDown(e: MouseEvent): void {
  if (!ctx.state.open) return
  const t = e.target as HTMLElement | null
  if (t && t.closest('.ctx-menu')) return
  closeContextMenu()
}
function onWheel(): void {
  if (ctx.state.open) closeContextMenu()
}
function onKey(e: KeyboardEvent): void {
  if (e.key === 'Escape' && ctx.state.open) {
    e.preventDefault()
    closeContextMenu()
  }
}

onMounted(() => {
  document.addEventListener('mousedown', onMouseDown)
  document.addEventListener('wheel', onWheel, { passive: true })
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onMouseDown)
  document.removeEventListener('wheel', onWheel)
  document.removeEventListener('keydown', onKey)
})
</script>

<template>
  <Teleport to="body">
    <div
      v-if="ctx.state.open"
      class="ctx-menu"
      :class="{ out: ctx.state.closing }"
      :style="{ left: `${ctx.state.left}px`, top: `${ctx.state.top}px` }"
      role="menu"
      data-pw="ctx-menu"
    >
      <template v-for="(it, i) in ctx.state.items" :key="i">
        <div v-if="it.kind === 'sep'" class="ctx-sep"></div>
        <div v-else-if="it.kind === 'head'" class="ctx-head">{{ it.head }}</div>
        <button
          v-else
          type="button"
          class="ctx-item"
          :class="{ danger: it.danger }"
          :disabled="it.disabled"
          role="menuitem"
          @click="run(it)"
        >
          <PwIcon v-if="it.icon" :name="it.icon" :size="15" />
          <span>{{ it.label }}</span>
          <span v-if="it.kbd" class="kbd">{{ it.kbd }}</span>
        </button>
      </template>
    </div>
  </Teleport>
</template>
