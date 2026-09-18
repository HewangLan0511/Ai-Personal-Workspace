<script setup lang="ts">
/**
 * UI-FUSION-REAL：设置页按原型 `#/settings` set-layout 重建
 * （左 192px 分类 subnav + 右 set-body 行式控件；分类切换局部换内容）。
 *
 * **全部既有真实绑定原样保留**（阶段5/TECH-05-C 的能力一个不少）：
 * 主题 / 开机自启 / 默认 AI Provider / 数据目录 / 匿名遥测 /
 * AI 凭据（系统凭据库，密钥不回显）/ Model Center 入口（/models?from=settings）。
 * 分类只收真实存在的行：外观 / 工作空间 / AI 与模型 / 数据 / 关于
 * （原型还有"软件/插件"两分类，当前无真实设置行，按"禁止伪造数据"原则不造假）。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { invokeCore } from '@/api/client'
import { toast } from '@/composables/useToast'
import { errShake, okFlash, once } from '@/composables/useListSort'
import {
  applySkin,
  getActiveSkinId,
  getMotionLevel,
  listSkins,
  setMotionLevel,
  usePageEntrance,
  type MotionLevel,
} from '@/motion'
import { useAiStore } from '@/stores/ai'
import { useSettingsStore, type ThemeChoice } from '@/stores/settings'
import { useWidgetStore } from '@/stores/widgets'

const store = useSettingsStore()
const ai = useAiStore()
const widgetStore = useWidgetStore()

/**
 * 页面元素进出场（`data-enter` → `.enter-up` 错峰）。设置页每次进入都播 ——
 * 它承载的是"外观"这类**会立刻看见效果**的设置，入场本身也是效果的一部分。
 */
const rootEl = ref<HTMLElement | null>(null)
usePageEntrance(rootEl, { key: 'settings' })

const lastSaved = computed(() =>
  store.savedAt === 0 ? '' : new Date(store.savedAt).toLocaleTimeString(),
)

// ---- 分类（原型 SET_CATS 形态；切换只换 set-body）----
type SetCat = 'appearance' | 'workspace' | 'ai' | 'data' | 'about'
const CATS: Array<{ id: SetCat; label: string }> = [
  { id: 'appearance', label: '外观' },
  { id: 'workspace', label: '工作空间' },
  { id: 'ai', label: 'AI 与模型' },
  { id: 'data', label: '数据' },
  { id: 'about', label: '关于' },
]
const setCat = ref<SetCat>('appearance')
const setBody = ref<HTMLElement | null>(null)

/**
 * 切换分类（设计稿 `patchSettings`）：**只有内容区动**，导航与页头不动。
 * 内容换完立刻补 `.swap-in`（`nextTick` 是等 Vue 把新内容放进 DOM，
 * 否则动画会在旧内容上播完，用户什么也看不见）。
 */
function pickCat(id: SetCat): void {
  if (setCat.value === id) return
  setCat.value = id
  void nextTick(() => once(setBody.value, 'swap-in'))
}

// ---- AI 配置（阶段5 §2：API Key 只进系统凭据库）----
const keyInput = ref('')
const keyEl = ref<HTMLInputElement | null>(null)
const keyProvider = ref('')
const keyError = ref('')
const savingKey = ref(false)

onMounted(async () => {
  await store.load()
  await ai.init()
  // 默认选中当前 Provider，省去用户再点一次
  keyProvider.value = ai.providerId || 'deepseek'
})

const needsKeyProviders = computed(() => ai.providers.filter((p) => p.needsKey))
const selectedProvider = computed(() =>
  ai.providers.find((p) => p.id === keyProvider.value),
)

async function onThemeChange(value: ThemeChoice) {
  await store.setTheme(value)
  toast.success('已保存')
}

/** 主题三档（设计稿 `theme-seg`：浅色 / 深色 / 跟随系统，顺序与文案原文）。 */
const THEMES: Array<{ v: ThemeChoice; n: string }> = [
  { v: 'light', n: '浅色' },
  { v: 'dark', n: '深色' },
  { v: 'system', n: '跟随系统' },
]

// ---- 外观 · 动画（Motion Guard 三档）----
//
// 唯一事实来源是 `motion/guards.ts`（localStorage `pw.motion.level`）——
// 这里只是把它的受控入口摆到设置页。**不再另存一份到 config**：
// 两处存同一个开关，迟早会出现"库里是 off、界面显示完整"的分叉。
const MOTION_TIERS: Array<{ v: MotionLevel; n: string; d: string }> = [
  { v: 'standard', n: '完整', d: '所有场景按 Token 播放' },
  { v: 'reduced', n: '减弱', d: '去掉大位移与明显缩放，保留状态反馈' },
  { v: 'off', n: '关闭', d: '关闭非必要动画，状态本身仍然可见' },
]
const motionLevel = ref<MotionLevel>(getMotionLevel())
const motionNote = computed(
  () => MOTION_TIERS.find((t) => t.v === motionLevel.value)?.d ?? '',
)

function onMotionChange(v: MotionLevel): void {
  if (motionLevel.value === v) return
  setMotionLevel(v)
  motionLevel.value = v
  // 设计稿口径：切换即时生效、不弹确认条（结果肉眼可见 —— 动效立刻就变了）
  toast.success(`动效已切换为「${MOTION_TIERS.find((t) => t.v === v)?.n}」`)
}

// ---- 外观 · 皮肤（Skin Engine）----
//
// 皮肤只改"动多少 / 动多久 / 动得多明显"，不改布局/字号/间距/文字颜色
// （skin-system.md §7.3 对设计师的承诺）。选择落在 localStorage `pw.skin`，
// 由 `motion/skin.ts` 的 `restoreSkin()` 在启动时恢复。
const skins = computed(() =>
  listSkins().map((s) => ({ id: s.id, name: s.id === 'default' ? '默认' : s.name })),
)
const skinId = ref<string | null>(getActiveSkinId())

function onSkinChange(id: string): void {
  const r = applySkin(id)
  if (!r.ok) {
    toast.error(`皮肤切换失败：${r.error ?? id}`)
    return
  }
  skinId.value = id === 'default' ? null : id
  // 设计稿 §8.2：换肤的反馈是"看得见的变化" + 一条 Toast，不做任何全屏过渡
  toast.success(`已切换到「${skins.value.find((s) => s.id === id)?.name ?? id}」`)
}

// ---- 外观 · 首页布局（自动 / 固定）----
//
// 键 `ui.dashboard.layout_locked` 早已登记在 core（不是为这个页面新加的），
// 组件区管理里那几个入口操作的是同一份状态。
const layoutAuto = computed(() => !widgetStore.layoutLocked)

async function onLayoutMode(auto: boolean): Promise<void> {
  if (auto === layoutAuto.value) return
  if (auto) await widgetStore.unlockLayout()
  else await widgetStore.lockLayout()
  toast.success(auto ? '首页布局将按使用频率自动调整' : '首页布局已固定')
}

async function saveAll() {
  await store.savePartial({
    autostart: store.data.autostart,
    defaultProvider: store.data.defaultProvider,
    dataDir: store.data.dataDir,
    privacy: store.data.privacy,
  })
  toast.success('已保存')
}

/** 写入 API Key（立即进系统凭据库，界面只显示掩码）。 */
async function saveKey(): Promise<void> {
  keyError.value = ''
  const secret = keyInput.value.trim()
  if (!secret) {
    keyError.value = '请输入密钥'
    // 设计稿 `errShake(input.closest('.field') || input)`：校验失败时抖字段本身
    errShake(keyEl.value?.closest('.pw-row-item') ?? keyEl.value)
    return
  }
  savingKey.value = true
  try {
    const res = await invokeCore<{ keyMask: string; backend: string }>('ai_set_credential', {
      provider: keyProvider.value,
      secret,
    })
    // 输入框立刻清空 —— 明文不在界面上多留一秒
    keyInput.value = ''
    okFlash(keyEl.value?.closest('.pw-row-item') ?? keyEl.value)
    toast.success(`已保存（${res.keyMask}）`)
    await ai.loadProviders()
  } catch (e) {
    keyError.value = String(e)
    errShake(keyEl.value?.closest('.pw-row-item') ?? keyEl.value)
  } finally {
    savingKey.value = false
  }
}

/** 删除已保存的密钥。 */
async function removeKey(): Promise<void> {
  keyError.value = ''
  try {
    await invokeCore('ai_delete_credential', { provider: keyProvider.value })
    toast.success('已删除')
    await ai.loadProviders()
  } catch (e) {
    keyError.value = String(e)
  }
}

/** 拉取模型列表（本地服务常靠它确认是否在运行）。 */
const models = ref<string[]>([])
const loadingModels = ref(false)
async function fetchModels(): Promise<void> {
  loadingModels.value = true
  models.value = []
  try {
    const res = await invokeCore<{ models: string[] }>('ai_list_models', {
      provider: keyProvider.value,
      apiBase: selectedProvider.value?.defaultBase ?? '',
    })
    models.value = res.models ?? []
    if (!models.value.length) {
      toast.info('未取到模型（服务可能未运行，或该 Provider 不提供列表接口）')
    }
  } catch (e) {
    keyError.value = String(e)
  } finally {
    loadingModels.value = false
  }
}
</script>

<template>
  <div ref="rootEl" class="page">
    <!-- 原型 page-head -->
    <div class="page-head" data-enter="hero">
      <div class="pw-grow">
        <div class="pw-t-page">设置</div>
        <div class="pw-t-cap head-cap">管理外观、工作空间与数据 · 所有设置只保存在这台电脑上</div>
      </div>
    </div>

    <!-- 原型 set-layout：左分类 subnav + 右 set-body -->
    <div class="set-layout" data-enter="ws">
      <nav class="subnav">
        <button
          v-for="c in CATS"
          :key="c.id"
          type="button"
          class="nav-item subnav-item"
          :class="{ active: setCat === c.id }"
          @click="pickCat(c.id)"
        >
          <span class="lbl">{{ c.label }}</span>
        </button>
      </nav>

      <div ref="setBody" class="set-body">
        <!-- ======== 外观（设计稿 setBodyHtml('appearance') 的五项逐项落地）======= -->
        <template v-if="setCat === 'appearance'">
          <div class="t-section" style="margin-bottom: var(--space-3)">外观</div>

          <!-- 主题：设计稿是三档分段控件（浅色 / 深色 / 跟随系统），不是两个按钮 -->
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">主题</div>
              <div class="pw-t-cap">
                默认浅色 · 选「跟随系统」后随系统明暗自动切换（当前实际：{{
                  store.resolved === 'dark' ? '深色' : '浅色'
                }}）
              </div>
            </div>
            <div class="seg" data-act="theme-seg" data-pw="set-theme">
              <button
                v-for="t in THEMES"
                :key="t.v"
                type="button"
                :class="{ on: store.data.theme === t.v }"
                :data-v="t.v"
                @click="onThemeChange(t.v)"
              >
                {{ t.n }}
              </button>
            </div>
          </div>

          <!-- 动画：Motion Guard 三档（完整 / 减弱 / 关闭） -->
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">动画</div>
              <div class="pw-t-cap">界面切换与悬浮反馈 · 三档降级 · {{ motionNote }}</div>
            </div>
            <div class="seg" data-act="set-motion" data-pw="set-motion">
              <button
                v-for="t in MOTION_TIERS"
                :key="t.v"
                type="button"
                :class="{ on: motionLevel === t.v }"
                :data-v="t.v"
                @click="onMotionChange(t.v)"
              >
                {{ t.n }}
              </button>
            </div>
          </div>

            <!-- 动效规范：入口在设置 · 外观（设计稿页头原文），不占主导航。
                 设计稿这里是 `<button class="btn">`；工程里直接用真链接 ——
                 `<a>` 里再套 `<button>` 是非法嵌套（交互元素套交互元素），
                 键盘/读屏会给出两个焦点。`.btn` 自带 `display:inline-flex` 全部几何，
                 套在 `<a>` 上取值不变，只补一条下划线复位（见文件尾 scoped 样式）。 -->
            <div class="pw-row-item">
              <div class="pw-row-item__main">
                <div class="pw-row-item__title">动效规范</div>
                <div class="pw-t-cap">查看每个界面动作的节奏与幅度，可三档对比</div>
              </div>
              <RouterLink
                to="/motion"
                class="btn btn--secondary btn--sm set-motion-spec"
                data-pw="set-motion-spec"
              >
                打开 ›
              </RouterLink>
            </div>

          <!-- 皮肤：skin-system.md §9.2 第 4 项 —— 与「动画」并排的那一行 -->
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">皮肤</div>
              <div class="pw-t-cap">
                只改"动多少 / 动多久"，不改布局、字号与文字颜色（不影响可读性）
              </div>
            </div>
            <div class="seg" data-act="set-skin" data-pw="set-skin">
              <button
                v-for="s in skins"
                :key="s.id"
                type="button"
                :class="{ on: (skinId ?? 'default') === s.id }"
                :data-v="s.id"
                @click="onSkinChange(s.id)"
              >
                {{ s.name }}
              </button>
            </div>
          </div>

          <!-- 首页布局：自动（按使用频率）/ 固定 -->
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">首页布局</div>
              <div class="pw-t-cap">模块是否按使用频率变化</div>
            </div>
            <div class="seg" data-act="set-layout" data-pw="set-layout">
              <button type="button" :class="{ on: layoutAuto }" data-v="auto" @click="onLayoutMode(true)">
                自动
              </button>
              <button type="button" :class="{ on: !layoutAuto }" data-v="fixed" @click="onLayoutMode(false)">
                固定
              </button>
            </div>
          </div>
        </template>

        <!-- ======== 工作空间 ======== -->
        <template v-if="setCat === 'workspace'">
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">开机自启</div>
              <div class="pw-t-cap">登录时自动运行（Windows 注册表写入）</div>
            </div>
            <input
              type="checkbox"
              :checked="store.data.autostart"
              @change="(e) => (store.data.autostart = (e.target as HTMLInputElement).checked)"
            />
          </div>
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">布局与模式</div>
              <div class="pw-t-cap">在工作空间页管理布局编辑器与工作模式</div>
            </div>
            <RouterLink to="/mode"><button type="button" class="pw-btn pw-btn--secondary pw-btn--sm">打开</button></RouterLink>
          </div>
        </template>

        <!-- ======== AI 与模型 ======== -->
        <template v-if="setCat === 'ai'">
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">默认 AI Provider</div>
              <div class="pw-t-cap">AI 侧栏默认调用的 Provider</div>
            </div>
            <select v-model="store.data.defaultProvider" class="set-select">
              <option value="">（未设置）</option>
              <option v-for="p in ai.providers" :key="p.id" :value="p.id" :disabled="!p.enabled">
                {{ p.label }}{{ p.enabled ? '' : '（未开放）' }}
              </option>
            </select>
          </div>

          <!-- 模型管理入口（TECH-05-C §P0-1，原型同款行式） -->
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">模型管理中心</div>
              <div class="pw-t-cap">连接、测试与切换模型（数据来自 ModelRegistry；密钥仍在本页配置）</div>
            </div>
            <RouterLink to="/models?from=settings">
              <button type="button" class="pw-btn pw-btn--secondary pw-btn--sm">打开模型管理</button>
            </RouterLink>
          </div>

          <div class="ai-cred-note pw-t-cap">
            密钥保存在<b>系统凭据库</b>（{{ ai.credentialBackend || '未知' }}），
            数据库里只保存引用名 —— 明文密钥不落盘、不入库、不进版本库。
          </div>

          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">Provider</div>
              <div class="pw-t-cap">选择要配置密钥的供应商</div>
            </div>
            <select v-model="keyProvider" class="set-select" @change="models = []">
              <option v-for="p in needsKeyProviders" :key="p.id" :value="p.id">
                {{ p.label }}{{ p.hasKey ? ` ✓ ${p.keyMask}` : '' }}
              </option>
            </select>
          </div>

          <div v-if="selectedProvider" class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">API Key</div>
              <div class="pw-t-cap">
                {{
                  selectedProvider.hasKey
                    ? `已配置：${selectedProvider.keyMask}（重新输入可覆盖）`
                    : '仅写入系统凭据库，界面只回显掩码'
                }}
              </div>
            </div>
            <div class="ai-key-row">
              <input
                ref="keyEl"
                v-model="keyInput"
                type="password"
                placeholder="sk-…"
                autocomplete="off"
                @keydown.enter="saveKey"
              />
              <button type="button" class="pw-btn pw-btn--primary pw-btn--sm" :disabled="savingKey" @click="saveKey">保存</button>
              <button v-if="selectedProvider.hasKey" type="button" class="pw-btn pw-btn--sm" @click="removeKey">删除</button>
            </div>
          </div>

          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">模型</div>
              <div class="pw-t-cap">可从 Provider 拉取，也可手动填写</div>
            </div>
            <div class="ai-key-row">
              <button type="button" class="pw-btn pw-btn--secondary pw-btn--sm" :disabled="loadingModels" @click="fetchModels">
                {{ loadingModels ? '拉取中…' : '拉取模型列表' }}
              </button>
              <span v-if="models.length" class="pw-t-cap">{{ models.length }} 个可用</span>
            </div>
          </div>

          <div v-if="models.length" class="ai-model-list">
            <code v-for="m in models" :key="m" class="ai-model-chip">{{ m }}</code>
          </div>

          <p v-if="keyError" class="ai-key-error">{{ keyError }}</p>

          <div class="pw-row-item">
            <button type="button" class="pw-btn pw-btn--primary" @click="saveAll">保存</button>
            <span v-if="lastSaved" class="pw-t-cap">上次保存：{{ lastSaved }}</span>
          </div>
        </template>

        <!-- ======== 数据 ======== -->
        <template v-if="setCat === 'data'">
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">数据目录</div>
              <div class="pw-t-cap">SQLite 数据库与配置文件位置（修改需重启）</div>
            </div>
            <input
              type="text"
              class="set-input"
              :value="store.data.dataDir"
              placeholder="%APPDATA%/PersonalWorkspace"
              @input="(e) => (store.data.dataDir = (e.target as HTMLInputElement).value)"
            />
          </div>
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">上传匿名遥测</div>
              <div class="pw-t-cap">默认关闭，不开此开关无任何数据外传</div>
            </div>
            <input
              type="checkbox"
              :checked="store.data.privacy"
              @change="(e) => (store.data.privacy = (e.target as HTMLInputElement).checked)"
            />
          </div>
          <div class="pw-row-item">
            <button type="button" class="pw-btn pw-btn--primary" @click="saveAll">保存</button>
            <span v-if="lastSaved" class="pw-t-cap">上次保存：{{ lastSaved }}</span>
          </div>
        </template>

        <!-- ======== 关于 ======== -->
        <template v-if="setCat === 'about'">
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">Personal Workspace</div>
              <div class="pw-t-cap">本地优先的个人工作台 · Windows 桌面版（v0.1 基线）</div>
            </div>
          </div>
          <div class="pw-row-item">
            <div class="pw-row-item__main">
              <div class="pw-row-item__title">数据与隐私</div>
              <div class="pw-t-cap">所有数据只保存在这台电脑上；无账号系统、无云端同步。</div>
            </div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ============ 原型 #/settings 视觉（set-layout / row-item / subnav） ============ */

.page {
  max-width: var(--content-max);
  padding: var(--pad-page-t) var(--pad-page-x) var(--f-space-9);
}

.page-head {
  display: flex;
  align-items: flex-end;
  gap: var(--f-space-4);
  margin-bottom: var(--f-space-6);
}

.head-cap {
  margin-top: 2px;
}

.set-layout {
  display: grid;
  grid-template-columns: 192px 1fr;
  gap: var(--f-space-8);
  align-items: start;
}

.subnav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

/* 原型：设置分类复用 .nav-item 形态（含 active 左竖条视觉） */
.subnav-item {
  position: relative;
  width: 100%;
  height: 34px;
  display: flex;
  align-items: center;
  gap: var(--f-space-3);
  padding: 0 var(--f-space-3);
  border: none;
  background: transparent;
  border-radius: var(--r-md);
  color: var(--text-2);
  font-size: var(--fs-body-sm);
  font-weight: var(--fw-medium);
  text-align: left;
  cursor: pointer;
  transition:
    background var(--dur-micro) var(--ease-out),
    color var(--dur-micro) var(--ease-out);
}

.subnav-item:hover {
  background: var(--surface-3);
  color: var(--text-1);
}

.subnav-item.active {
  background: var(--surface-1);
  color: var(--text-1);
  font-weight: var(--fw-semi);
  box-shadow: var(--shadow-xs);
}

.subnav-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  width: 3px;
  height: 16px;
  border-radius: 0 3px 3px 0;
  background: var(--brand-500);
}

.set-body {
  min-width: 0;
}

.set-body > * + * {
  margin-top: 2px;
}

.set-select,
.set-input {
  max-width: 260px;
}

.set-body .ai-cred-note {
  margin: var(--f-space-3) 0;
}

.set-body .ai-key-row,
.set-body .ai-model-list,
.set-body .ai-key-error {
  margin-top: var(--f-space-2);
}

@media (max-width: 1100px) {
  .set-layout {
    grid-template-columns: 1fr;
  }

  .subnav {
    flex-direction: row;
    flex-wrap: wrap;
    margin-bottom: var(--f-space-4);
  }

  .subnav-item {
    width: auto;
  }
}

/* 「动效规范」入口用真链接（`<a>`）承载设计稿的 `.btn`：`.btn` 已给全部盒模型，
   只缺 `<a>` 默认的下划线 —— 工程的基础重置没有全局清它（见 NavSide 同样的处理）。 */
.set-motion-spec {
  text-decoration: none;
}
</style>
