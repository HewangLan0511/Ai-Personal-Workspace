<script setup lang="ts">
/**
 * PwIcon · 设计稿图标体系（UI-FUSION-FULL）
 *
 * 唯一来源 = `personal-workspace-ui/index.html` 的 62 个 `<symbol id="i-*">`。
 * 本文件由 `tools/_fusion_icon_import.py` 生成，**请勿手改** —— 改设计稿后重跑脚本。
 *
 * 为什么不用 sprite：真实应用没有全局 sprite 宿主，逐 symbol 组件化可以
 * 保留同名同路径（零视觉偏差），同时按需 tree-shake。
 * 注意：本组件刻意不放在 `components/ui/` —— 那里被验收脚本钉死为 4 个原语。
 */

const ICONS: Record<string, string> = {
  'alert': '<path d="M12 4.6 20.8 19.4H3.2z"/><path d="M12 10.2v3.6M12 16.6h.01"/>',
  'arrow-l': '<path d="M19.6 12h-15M10.6 18l-6-6 6-6"/>',
  'arrow-r': '<path d="M4.4 12h15M13.4 6l6 6-6 6"/>',
  'auto': '<rect x="3.4" y="3.4" width="17.2" height="17.2" rx="2.6"/><path d="M3.4 9.2h17.2M10.4 9.2v11.4"/>',
  'bell': '<path d="M6.6 10.4a5.4 5.4 0 0 1 10.8 0c0 4 1.4 5.4 1.4 5.4H5.2s1.4-1.4 1.4-5.4z"/><path d="M10 18.4a2 2 0 0 0 4 0"/>',
  'blocks': '<rect x="3.4" y="3.4" width="7.2" height="7.2" rx="2"/><rect x="13.4" y="3.4" width="7.2" height="7.2" rx="2"/><rect x="3.4" y="13.4" width="7.2" height="7.2" rx="2"/><path d="M13.4 13.4h7.2v7.2h-7.2zM17 13.4v7.2M13.4 17h7.2"/>',
  'book': '<path d="M12 7C10.6 5.4 8.6 4.6 6 4.6H4.2v13.2H6.4c2.2 0 4.2.9 5.6 2.2 1.4-1.3 3.4-2.2 5.6-2.2h2.2V4.6H18c-2.6 0-4.6.8-6 2.4z"/><path d="M12 7v13"/>',
  'card': '<rect x="3.2" y="5.2" width="17.6" height="13.6" rx="2.4"/><circle cx="9" cy="11" r="2"/><path d="M6 15.6c.6-1.5 1.7-2.2 3-2.2s2.4.7 3 2.2M15 10h4M15 13.6h4"/>',
  'check': '<path d="m5 12.6 4.6 4.6L19 7.2"/>',
  'check-c': '<circle cx="12" cy="12" r="8.4"/><path d="m8.4 12.2 2.4 2.4 4.8-5"/>',
  'chev-d': '<path d="m6 9.6 6 6 6-6"/>',
  'chev-l': '<path d="m14.4 6-6 6 6 6"/>',
  'chev-r': '<path d="m9.6 6 6 6-6 6"/>',
  'clock': '<circle cx="12" cy="12" r="8.4"/><path d="M12 7.4V12l3.2 2"/>',
  'cloud': '<path d="M7.2 18.4h9.4a3.4 3.4 0 0 0 .3-6.8 4.9 4.9 0 0 0-9.4-1.2 3.8 3.8 0 0 0-.3 8z"/>',
  'code': '<path d="m9 8-4 4 4 4M15 8l4 4-4 4"/>',
  'copy': '<rect x="8.6" y="8.6" width="11.8" height="11.8" rx="2.4"/><path d="M5.6 15.6A2 2 0 0 1 3.6 13.6V5.6a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2"/>',
  'cpu': '<rect x="6.6" y="6.6" width="10.8" height="10.8" rx="2"/><path d="M10 3.2v3.4M14 3.2v3.4M10 17.4v3.4M14 17.4v3.4M3.2 10h3.4M3.2 14h3.4M17.4 10h3.4M17.4 14h3.4"/>',
  'doc': '<path d="M6.4 3.6h5l6 6v9.2a1.6 1.6 0 0 1-1.6 1.6H6.4A1.6 1.6 0 0 1 4.8 18.8V5.2a1.6 1.6 0 0 1 1.6-1.6z"/><path d="M11.4 3.6v6h6"/>',
  'download': '<path d="M12 4.4v10.8M7.6 10.8 12 15.2l4.4-4.4M4.6 19.4h14.8"/>',
  'edit': '<path d="M4.6 19.4h3.8L18.8 9a2 2 0 0 0-2.8-2.8L5.6 16.6z"/><path d="m14.6 6.6 2.8 2.8"/>',
  'eye': '<path d="M2.8 12S6.2 6.4 12 6.4 21.2 12 21.2 12 17.8 17.6 12 17.6 2.8 12 2.8 12z"/><circle cx="12" cy="12" r="2.6"/>',
  'filter': '<path d="M4 6.6h16M7 12h10M10 17.4h4"/>',
  'folder': '<path d="M3.6 8A2.4 2.4 0 0 1 6 5.6h2.9l2 2.4h6.7A2.4 2.4 0 0 1 20 10.4v7.2a2.4 2.4 0 0 1-2.4 2.4H6a2.4 2.4 0 0 1-2.4-2.4z"/>',
  'globe': '<circle cx="12" cy="12" r="8.4"/><path d="M3.6 12h16.8M12 3.6c2.4 2.4 3.7 5.4 3.7 8.4s-1.3 6-3.7 8.4c-2.4-2.4-3.7-5.4-3.7-8.4S9.6 6 12 3.6z"/>',
  'grid': '<rect x="3.4" y="3.4" width="7" height="7" rx="2"/><rect x="13.6" y="3.4" width="7" height="7" rx="2"/><rect x="3.4" y="13.6" width="7" height="7" rx="2"/><rect x="13.6" y="13.6" width="7" height="7" rx="2"/>',
  'gridview': '<rect x="3.4" y="3.4" width="7" height="7" rx="2"/><rect x="13.6" y="3.4" width="7" height="7" rx="2"/><rect x="3.4" y="13.6" width="7" height="7" rx="2"/><rect x="13.6" y="13.6" width="7" height="7" rx="2"/>',
  'grip': '<circle cx="9" cy="6.6" r="1.3" fill="currentColor" stroke="none"/><circle cx="15" cy="6.6" r="1.3" fill="currentColor" stroke="none"/><circle cx="9" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="15" cy="12" r="1.3" fill="currentColor" stroke="none"/><circle cx="9" cy="17.4" r="1.3" fill="currentColor" stroke="none"/><circle cx="15" cy="17.4" r="1.3" fill="currentColor" stroke="none"/>',
  'home': '<path d="M4 10.6 12 4.2l8 6.4V19a1.6 1.6 0 0 1-1.6 1.6H15.2v-5.8H8.8v5.8H5.6A1.6 1.6 0 0 1 4 19z"/>',
  'info': '<circle cx="12" cy="12" r="8.4"/><path d="M12 11.2v5M12 8.2h.01"/>',
  'link': '<path d="M10.2 13.8a3.4 3.4 0 0 0 4.8 0l2.8-2.8a3.4 3.4 0 0 0-4.8-4.8l-1 1"/><path d="M13.8 10.2a3.4 3.4 0 0 0-4.8 0l-2.8 2.8a3.4 3.4 0 0 0 4.8 4.8l1-1"/>',
  'listview': '<path d="M3.6 6.6h3.4M3.6 12h3.4M3.6 17.4h3.4M10 6.6h10.4M10 12h10.4M10 17.4h10.4"/>',
  'lock': '<rect x="4.8" y="10.4" width="14.4" height="9.8" rx="2.4"/><path d="M8.2 10.4V8a3.8 3.8 0 0 1 7.6 0v2.4"/>',
  'message': '<path d="M4.2 7A2.4 2.4 0 0 1 6.6 4.6h10.8A2.4 2.4 0 0 1 20 7v6.4a2.4 2.4 0 0 1-2.4 2.4h-7l-4.6 3.2v-3.2h-.4"/>',
  'minus': '<path d="M5.4 12h13.2"/>',
  'monitor': '<rect x="2.6" y="4.2" width="18.8" height="12.6" rx="2.4"/><path d="M9 20.4h6M12 16.8v3.6"/>',
  'more': '<circle cx="5.4" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/><circle cx="18.6" cy="12" r="1.5" fill="currentColor" stroke="none"/>',
  'move': '<path d="M12 3.6v16.8M3.6 12h16.8M12 3.6 9.6 6M12 3.6 14.4 6M12 20.4 9.6 18M12 20.4l2.4-2.4M3.6 12 6 9.6M3.6 12 6 14.4M20.4 12 18 9.6M20.4 12 18 14.4"/>',
  'music': '<path d="M9 17.6V6.4l9.4-2v11.2"/><circle cx="6.4" cy="17.6" r="2.6"/><circle cx="15.8" cy="15.6" r="2.6"/>',
  'next': '<path d="M6 6.4 14.4 12 6 17.6z" fill="currentColor" stroke="none"/><path d="M17.6 5.6v12.8"/>',
  'panel': '<rect x="3.2" y="4.6" width="17.6" height="14.8" rx="2.4"/><path d="M14.8 4.6v14.8"/>',
  'pin': '<path d="M12 21.4s6.4-5.6 6.4-10.2a6.4 6.4 0 0 0-12.8 0C5.6 15.8 12 21.4 12 21.4z"/><circle cx="12" cy="11" r="2.4"/>',
  'play': '<path d="M8 5.4 18.2 12 8 18.6z" fill="currentColor" stroke="none"/>',
  'plus': '<path d="M12 5.2v13.6M5.2 12h13.6"/>',
  'power': '<path d="M12 4v8M7.8 6.6a7 7 0 1 0 8.4 0"/>',
  'prev': '<path d="M18 6.4 9.6 12l8.4 5.6z" fill="currentColor" stroke="none"/><path d="M6.4 5.6v12.8"/>',
  'refresh': '<path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.2"/><path d="M19.4 4.4v5h-5"/>',
  'robot': '<rect x="4" y="8.4" width="16" height="11.2" rx="3"/><path d="M12 4.4v4M8.6 13h.01M15.4 13h.01M9.6 16.2h4.8M3 13v3M21 13v3"/>',
  'save': '<path d="M5.4 4.6h9l4.2 4.2v10.6a1.6 1.6 0 0 1-1.6 1.6H5.4a1.6 1.6 0 0 1-1.6-1.6V6.2a1.6 1.6 0 0 1 1.6-1.6z"/><path d="M8 4.6v4.6h6V4.6M7.8 14.6h8.4v6H7.8z"/>',
  'search': '<circle cx="11" cy="11" r="6.4"/><path d="m15.8 15.8 4.2 4.2"/>',
  'settings': '<circle cx="12" cy="12" r="2.8"/><path d="M19.1 14.6a1.5 1.5 0 0 0 .3 1.7l.1.1a1.9 1.9 0 1 1-2.7 2.7l-.1-.1a1.5 1.5 0 0 0-1.7-.3 1.5 1.5 0 0 0-.9 1.4v.2a1.9 1.9 0 1 1-3.8 0v-.1a1.5 1.5 0 0 0-1-1.4 1.5 1.5 0 0 0-1.7.3l-.1.1a1.9 1.9 0 1 1-2.7-2.7l.1-.1a1.5 1.5 0 0 0 .3-1.7 1.5 1.5 0 0 0-1.4-.9h-.2a1.9 1.9 0 1 1 0-3.8h.1a1.5 1.5 0 0 0 1.4-1 1.5 1.5 0 0 0-.3-1.7l-.1-.1a1.9 1.9 0 1 1 2.7-2.7l.1.1a1.5 1.5 0 0 0 1.7.3h.1a1.5 1.5 0 0 0 .9-1.4v-.2a1.9 1.9 0 1 1 3.8 0v.1a1.5 1.5 0 0 0 .9 1.4 1.5 1.5 0 0 0 1.7-.3l.1-.1a1.9 1.9 0 1 1 2.7 2.7l-.1.1a1.5 1.5 0 0 0-.3 1.7v.1a1.5 1.5 0 0 0 1.4.9h.2a1.9 1.9 0 1 1 0 3.8h-.1a1.5 1.5 0 0 0-1.4.9z"/>',
  'sheet': '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.2"/><path d="M3.6 9.6h16.8M3.6 14.4h16.8M9.6 4.6v14.8M14.8 4.6v14.8"/>',
  'shield': '<path d="M12 3.4l7.4 2.9v5.4c0 4.4-2.9 7.6-7.4 9.3-4.5-1.7-7.4-4.9-7.4-9.3V6.3z"/>',
  'spark-sm': '<path d="M12 4.4 13.3 9 18 10.3 13.3 11.6 12 16.2 10.7 11.6 6 10.3 10.7 9z"/>',
  'sparkle': '<path d="M11 3.4 12.6 8 17.4 9.6 12.6 11.2 11 16 9.4 11.2 4.6 9.6 9.4 8z"/><path d="M18 14.4l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z"/>',
  'square': '<rect x="5.4" y="5.4" width="13.2" height="13.2" rx="2"/>',
  'sun': '<circle cx="12" cy="12" r="4"/><path d="M12 2.6v2M12 19.4v2M2.6 12h2M19.4 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4"/>',
  'target': '<circle cx="12" cy="12" r="8.4"/><circle cx="12" cy="12" r="4.4"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none"/>',
  'trash': '<path d="M4.6 7h14.8M9.4 7V5.2h5.2V7M6.6 7l1 12.4h8.8L17.4 7M10.4 10.4v5.6M13.6 10.4v5.6"/>',
  'user': '<circle cx="12" cy="8.6" r="3.4"/><path d="M5.2 19.8c1-3.3 3.6-4.9 6.8-4.9s5.8 1.6 6.8 4.9"/>',
  'ws': '<path d="M9 6.6V5.4A2.4 2.4 0 0 1 11.4 3h7.2A2.4 2.4 0 0 1 21 5.4v7.2A2.4 2.4 0 0 1 18.6 15h-1.2"/><rect x="3" y="8" width="12" height="13" rx="2.4"/>',
  'x': '<path d="m6.4 6.4 11.2 11.2M17.6 6.4 6.4 17.6"/>',
}

export type PwIconName = keyof typeof ICONS

const props = withDefaults(
  defineProps<{ name: string; size?: number | string; strokeWidth?: number }>(),
  { size: 18, strokeWidth: 1.6 },
)

const px = (v: number | string) => (typeof v === 'number' ? `${v}px` : v)
</script>

<template>
  <svg
    class="pw-ico"
    :style="{ width: px(props.size), height: px(props.size) }"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="props.strokeWidth"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    v-html="ICONS[props.name] || ''"
  />
</template>
