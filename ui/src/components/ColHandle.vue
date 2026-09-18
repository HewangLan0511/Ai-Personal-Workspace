<script setup lang="ts">
/**
 * 面板边界拖拽手柄（原型 `.rsh`，index.html §"边界拖拽手柄"）。
 *
 * 本组件**只出结构**：`role="separator"` + `tabindex=0` + 拖拽提示文案。
 * 视觉全部来自 `base.css` 的设计稿组件层（`.rsh` / `.rsh--nav` / `.rsh--widget`），
 * 行为（指针拖拽 / 双击重置 / 方向键微调 / 蓄力折叠 / 到位脉冲）由
 * `composables/useShellLayout.ts` 统一接管 —— 与原型一致：
 * 手柄节点是容器的子节点，行为在挂载时按 `.rsh--<key>` 查一次绑上。
 *
 * 为什么留成"纯结构 + 外部挂行为"而不是把逻辑写进组件：
 * 原型的手柄生命周期是"容器重绘后重新补回手柄"（`mountHandles()`），
 * 逻辑若写在组件里，容器重绘会重建组件实例 → 拖拽中的指针捕获丢失。
 */
defineProps<{
  /** 归属面板：nav（侧边栏右缘）/ widget（组件区左缘） */
  panel: 'nav' | 'widget'
  /** 无障碍名，如「侧边栏」 */
  name: string
}>()
</script>

<template>
  <div
    class="rsh"
    :class="`rsh--${panel}`"
    role="separator"
    aria-orientation="vertical"
    :aria-label="`调整${name}宽度`"
    title="拖动调整宽度 · 双击重置 · 方向键微调"
    tabindex="0"
  ></div>
</template>
