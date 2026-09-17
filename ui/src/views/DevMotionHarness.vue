<script setup lang="ts">
/**
 * TECH-01 · Motion/S2 验证固件（dev-only，挂 /dev/motion，不进导航）。
 *
 * 自包含：本地数据、零 API 依赖 —— Test 1（S2 滚动/过滤/重排）的确定性探针。
 * 产品页面的 S2 保障是结构性的（列表稳定 :key、过滤为同容器响应式更新，
 * 见 SoftwareView）—— 本固件把同一纪律放到可机器断言的舞台上实测。
 */
import { computed, onMounted, ref } from 'vue'

interface Row {
  id: number
  label: string
}

const rows = ref<Row[]>(
  Array.from({ length: 200 }, (_, i) => ({ id: i + 1, label: `ROW-${i + 1}` })),
)
const filtered = ref(false)
const scroller = ref<HTMLElement | null>(null)

const visible = computed(() =>
  filtered.value ? rows.value.filter((r) => r.id % 2 === 1) : rows.value,
)

function reorder(): void {
  // 旋转一位：DOM 顺序变化但 key 稳定 —— 检验"重排不 remount、不重放入场"。
  const first = rows.value[0]
  if (first) rows.value = [...rows.value.slice(1), first]
}

onMounted(() => {
  // remount 探针挂载点：CDP 在根元素上写标记，本地操作后断言标记仍在。
  const root = scroller.value?.parentElement
  if (root) (root as HTMLElement & { __dmhMounted?: boolean }).__dmhMounted = true
})
</script>

<template>
  <section class="dmh-root">
    <h3>Motion/S2 验证固件（dev-only）</h3>
    <div ref="scroller" class="dmh-scroller">
      <div class="dmh-toolbar">
        <button type="button" class="dmh-filter" @click="filtered = !filtered">
          {{ filtered ? '取消过滤' : '过滤奇数' }}
        </button>
        <button type="button" class="dmh-reorder" @click="reorder">重排</button>
        <span class="dmh-count">可见 {{ visible.length }} 行</span>
      </div>
      <ul class="dmh-list">
        <li v-for="it in visible" :key="it.id" :data-row-id="it.id">{{ it.label }}</li>
      </ul>
    </div>
  </section>
</template>

<style scoped>
.dmh-root {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dmh-scroller {
  height: 360px;
  overflow-y: auto;
  /* S2 指标纯粹化：关掉浏览器 scroll anchoring（它会在内容收缩时自动调
   * scrollTop 保持视觉稳定，让"scrollTop 是否被重置"失去区分度）。
   * 关掉后 scrollTop 只由滚动容器自身状态决定 —— remount 会归零、
   * 局部更新会原样保留，判据才有意义。 */
  overflow-anchor: none;
  border: 1px solid var(--border);
  border-radius: var(--radius-controls);
  background: var(--surface-1);
}
.dmh-toolbar {
  position: sticky;
  top: 0;
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--border);
}
.dmh-list {
  margin: 0;
  padding: 0 8px;
  list-style: none;
}
.dmh-list li {
  padding: 4px 0;
  border-bottom: 1px solid var(--border-subtle);
  color: var(--text-2);
  font-size: 13px;
}
.dmh-count {
  color: var(--text-3);
  font-size: 12px;
}
</style>
