<script setup lang="ts">
/**
 * Toast 宿主（TECH-03-B §二）—— **全应用唯一的提示渲染者**。
 *
 * 挂在 `App.vue` 根（`app-shell` 之外），所以：
 * - 任何页面/组件调 `toast.*()` 都能显示，不需要各自摆一份 `<p class="...-toast">`；
 * - 切路由不会把提示连根拔掉。
 *
 * 外观 = 接线前 `ModeView`/`SoftwareView` 的固定底部居中 toast（类在 `base.css` 的
 * `.toast-canonical`，声明逐字搬过来）。本轮 `variant` 只落 `data-variant`，不参与着色。
 */
import { currentToast } from '@/composables/useToast'
</script>

<template>
  <!-- 用 `<p>` 与接线前的 `.mv-toast` / `.apps-toast` 元素类型一致（UA 默认 margin 相同 → 像素级不变） -->
  <p
    v-if="currentToast"
    class="toast-canonical"
    data-pw-toast
    :data-variant="currentToast.variant"
    role="status"
    aria-live="polite"
  >
    {{ currentToast.message }}
  </p>
</template>
