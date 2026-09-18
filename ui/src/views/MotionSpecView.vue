<script setup lang="ts">
/**
 * 动效规范（Motion Spec）· 设计稿 `ROUTES.showcase` + `ROUTES.guard` 的合并落地
 * ============================================================================
 *
 * ## 入口与定位（设计稿原文）
 *   `ROUTES.showcase` 的页头注释写得很明确：
 *   > "只做展示与切换，不进主导航 —— 主 IA 不动，入口放在设置 · 外观。"
 *   本工程照办：路由 `/motion`，**不进侧边导航**，入口是设置页 · 外观的「动效规范」那一行。
 *
 * ## 内容来源
 *   · `MOTION_SCENES`（12 个场景的 token / 时长 / 一句话说明）—— 设计稿 `const MOTION_SCENES` 逐项。
 *     这些是**动效规范本身**（token 名与时长），不是占位数据。
 *   · 实时演示台 `.mt-stage` / `.mt-box` + `MT_DEMO_CLASS` 映射 —— 设计稿 `mtReplay()` 逐项。
 *   · 三档降级对比 —— 设计稿 `ROUTES.guard` 的三张卡（完整 / 减弱 / 关闭）。
 *     设计稿把它放在另一个路由（`#/guard`），这里有**意合并**成一页：两个页面共用
 *     一个演示台与同一份场景清单，拆成两个路由只会让"看完规范再对比降级"多一次跳转；
 *     三档开关本身也已在设置 · 外观（同一份事实，不重复造第二个入口）。
 *
 * ## 为什么这里可以直接 `getMotionLevel() / setMotionLevel()`
 *   那对函数就是 Motion Guard 的受控入口（`motion/guards.ts` 已注明"未来设置页的受控入口"），
 *   持久化在 localStorage `pw.motion.level`。演示台只是把同一个开关摆到"能立刻看见差别"
 *   的位置 —— 不是第二套档位状态。
 *
 * ## 演示动画全部复用既有类，零新增关键帧
 *   `.mt-box` 上挂的都是 base.css 里已有的类（`mt-press` / `scene-in` / `just-swap` /
 *   `enter-up` …）。重播靠"摘类 → 强制重排 → 挂回"，否则同名动画第二次不会重播。
 */
import { computed, ref } from 'vue'
import { RouterLink } from 'vue-router'

import PwIcon from '@/components/PwIcon.vue'
import { toast } from '@/composables/useToast'
import { getMotionLevel, setMotionLevel, type MotionLevel } from '@/motion'
import { useSettingsStore } from '@/stores/settings'

const settings = useSettingsStore()

// ---------------------------------------------------------------- 场景清单

interface Scene {
  k: string
  n: string
  t: string
  d: string
  s: string
}

/** 设计稿 `const MOTION_SCENES`：逐项照抄（token / 时长 / 说明都是规范正文）。 */
const MOTION_SCENES: Scene[] = [
  { k: 'press', n: '按下 Press', t: '--mt-dur-press', d: '80ms', s: 'scale .985，不回弹、不位移' },
  { k: 'hover', n: '悬停 Hover', t: '--mt-dur-hover', d: '140ms', s: '抬起 1px + 阴影，hover 让位给 drag' },
  { k: 'scene', n: '页面切换', t: '--mt-dur-scene-in', d: '160–220ms', s: '只有内容区参与；快速连点只到最后一页' },
  { k: 'cinema', n: '进入工作空间', t: '--mt-dur-window', d: '560ms / 门限 240ms', s: '窗口几乎同时落位，240ms 后即可交互' },
  { k: 'reorder', n: '拖拽让位 Reorder', t: '--mt-dur-reorder', d: '160ms', s: '邻居滑开让位，动画中不排队' },
  { k: 'drop', n: '落位高亮', t: '--mt-dur-highlight', d: '460ms', s: '只动 box-shadow，不改命中区域' },
  { k: 'toast', n: 'Toast', t: '--mt-dur-toast-in', d: '进 180 / 出 120ms', s: '底部居中，最多 2 条，可点击关闭，超额淡出最旧' },
  { k: 'ctx', n: '右键菜单', t: '--mt-dur-ctx', d: '100ms', s: 'scale .98 + 2px 淡入' },
  { k: 'drawer', n: '抽屉 Drawer', t: '--mt-dur-drawer', d: '240ms', s: '右侧推入 24px，遮罩 140ms' },
  { k: 'modal', n: '弹窗 Modal', t: '--mt-dur-modal', d: '180ms', s: '面板 180ms，scale .98 → 1' },
  { k: 'ai', n: 'AI 侧栏', t: '--mt-dur-ai', d: '260ms', s: '先宽度，120ms 后内容才出现' },
  { k: 'entrance', n: '首屏入场', t: '--mt-dur-entrance', d: '总 400–520ms', s: '只在第一次进入首页播放，之后不再重播' },
]

/** 设计稿 `MT_DEMO_CLASS`：场景 key → 演示类（全部是 base.css 里已有的类）。 */
const MT_DEMO_CLASS: Record<string, string> = {
  press: 'mt-press',
  hover: 'mt-hover',
  scene: 'scene-in',
  cinema: 'mt-cinema',
  reorder: 'mt-slide',
  drop: 'just-swap',
  toast: 'mt-toast',
  ctx: 'mt-ctx',
  drawer: 'mt-drawer',
  modal: 'mt-modal',
  ai: 'mt-ai',
  entrance: 'enter-up',
}

const boxEl = ref<HTMLElement | null>(null)
/** 当前演示的场景名（写在盒子里，让人知道刚才点的是哪一个）。 */
const activeScene = ref('')

function replay(k: string): void {
  const scene = MOTION_SCENES.find((s) => s.k === k)
  activeScene.value = scene?.n ?? k
  // Toast 场景：设计稿直接弹一条真实 Toast（它本来就是全局浮层，盒子里演不出来）
  if (k === 'toast') {
    toast.show('这是一条 Toast：进 180ms / 出 120ms', { variant: 'success' })
    return
  }
  const box = boxEl.value
  if (!box) return
  box.className = 'mt-box'
  void box.offsetWidth // 强制重排：同名动画才会重播
  box.classList.add(MT_DEMO_CLASS[k] ?? 'mt-hover')
}

// ---------------------------------------------------------------- 三档降级

type Tier = { v: MotionLevel; n: string; d: string }

/** 设计稿 `ROUTES.guard` 的三档说明（原文照抄）。 */
const TIERS: Tier[] = [
  { v: 'standard', n: '完整', d: '默认档。所有场景按 Token 播放：位移、缩放、层级过渡都在。' },
  {
    v: 'reduced',
    n: '减弱',
    d: '去掉大位移、明显缩放与装饰性循环；保留 Focus、State、Progress、Success、Error。适合晕动敏感 / 长时间使用。',
  },
  {
    v: 'off',
    n: '关闭',
    d: '关闭非必要动画。注意：hover / press / 焦点 / 选中这些交互状态本身还在，只是不再"动"过去。',
  },
]

const level = ref<MotionLevel>(getMotionLevel())
const tierName = computed(() => TIERS.find((t) => t.v === level.value)?.n ?? level.value)

function applyTier(v: MotionLevel): void {
  setMotionLevel(v)
  level.value = v
}

// ---------------------------------------------------------------- 皮肤（只读回显）

/**
 * 皮肤选择器在设置 · 外观（skin-system.md §9.2 第 4 项）。本页只**回显**当前皮肤，
 * 不再放第二个选择器 —— 同一件事一份入口。
 */
const skinLabel = computed(() => {
  const t = settings.data.theme
  if (t === 'system') return '主题跟随系统'
  return t === 'dark' ? '深色' : '浅色'
})
</script>

<template>
  <div class="page wide">
    <div class="page-head" data-enter="hero">
      <div class="pw-grow">
        <div class="t-page">动效规范</div>
        <div class="t-cap" style="margin-top: 2px">
          Motion System v0.2 · 时长取 --mt-dur-*，幅度取 --mt-intensity —— 两个独立维度，不相乘
        </div>
      </div>
      <RouterLink to="/settings" class="btn btn--secondary" data-pw="motion-back">
        <PwIcon name="chev-l" :size="14" /> 返回设置
      </RouterLink>
    </div>

    <!-- ===== 实时演示 ===== -->
    <div class="card card--lg" style="margin-bottom: var(--gap-section)" data-enter="ws">
      <div class="t-section" style="margin-bottom: var(--space-3)">实时演示</div>
      <div class="mt-stage">
        <div ref="boxEl" class="mt-box" data-pw="motion-box">
          {{ activeScene || '点右侧「重播」' }}
        </div>
      </div>
      <div class="t-cap" style="margin-top: var(--space-3)">
        当前档位：<b>{{ tierName }}</b>
        —— 切到「关闭」再重播，位移与缩放会归零，但按钮状态本身仍然可见。
        （当前{{ skinLabel }}）
      </div>
    </div>

    <!-- ===== 场景清单 ===== -->
    <div class="t-section" style="margin-bottom: var(--space-3)">场景清单</div>
    <div
      class="card"
      style="padding: 0; overflow: hidden; margin-bottom: var(--gap-section)"
      data-enter="ws"
    >
      <div v-for="s in MOTION_SCENES" :key="s.k" class="mt-row">
        <div class="main">
          <div class="t-sm">{{ s.n }}</div>
          <div class="t-cap">{{ s.s }}</div>
        </div>
        <span class="chip mono">{{ s.t }}</span>
        <span class="t-sm num" style="min-width: 132px; text-align: right">{{ s.d }}</span>
        <button
          type="button"
          class="btn btn--secondary btn--sm"
          :data-pw="`motion-replay-${s.k}`"
          @click="replay(s.k)"
        >
          重播
        </button>
      </div>
    </div>

    <!-- ===== 三档降级对比（设计稿 ROUTES.guard） ===== -->
    <div class="t-section" style="margin-bottom: var(--space-3)">动效降级对比</div>
    <div class="grid g3" style="margin-bottom: var(--gap-section)">
      <div
        v-for="t in TIERS"
        :key="t.v"
        class="card"
        :class="{ sel: level === t.v }"
        :data-pw="`motion-tier-${t.v}`"
        style="padding: var(--space-5); display: flex; flex-direction: column; gap: var(--space-3)"
      >
        <div class="row" style="justify-content: space-between">
          <div class="t-section">{{ t.n }}</div>
          <span v-if="level === t.v" class="chip">当前</span>
        </div>
        <div class="t-cap grow">{{ t.d }}</div>
        <button
          type="button"
          class="btn btn--sm"
          :class="{ 'btn--secondary': level !== t.v }"
          :data-pw="`motion-apply-${t.v}`"
          @click="applyTier(t.v)"
        >
          {{ level === t.v ? '已应用' : '应用这一档' }}
        </button>
      </div>
    </div>

    <RouterLink to="/settings" class="btn btn--ghost btn--sm" data-pw="motion-back-bottom">
      <PwIcon name="chev-l" :size="14" /> 返回设置
    </RouterLink>
  </div>
</template>
