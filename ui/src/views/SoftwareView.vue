<script setup lang="ts">
/**
 * 软件库（阶段2 / 05 §5 UI 页面）。
 *
 * 功能对照指令：
 *   - 卡片网格（图标 + 名称 + 启动按钮 + 菜单）与列表视图切换
 *   - 分类侧栏 + 搜索框
 *   - 空状态引导
 *   - 添加：① 选择可执行文件（自动补全名称/图标）② 扫描已安装软件（勾选入库）
 *   - 运行中标记（05 §3，5s 轮询同步）
 */
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'

import { NativeOnlyError, type AppItem, type InstalledApp } from '@/api/appsService'
import { toast, type ToastVariant } from '@/composables/useToast'
import { useAppsStore } from '@/stores/apps'

const store = useAppsStore()

/** `iconPath → dataURL`（图标经 core 读出转 base64；webview 不能直接加载本地路径） */
const icons = reactive<Record<string, string>>({})

/**
 * 本页的提示一律走统一 Toast Service（TECH-03-B §二）。
 * `notify` 只是本页的调用约定（省略变体 = `info`）；计时/单条/渲染由 Service 负责。
 */
function notify(msg: string, variant: ToastVariant = 'info'): void {
  toast.show(msg, { variant })
}

async function hydrateIcons() {
  for (const item of store.items) {
    if (item.icon && !icons[item.icon]) {
      const url = await store.loadIcon(item.icon)
      if (url) icons[item.icon] = url
    }
  }
}
watch(() => store.items, hydrateIcons, { immediate: true })

// ---------------------------------------------------------------- 操作

async function onLaunch(item: AppItem) {
  try {
    const res = await store.launch(item.id)
    notify(res.alreadyRunning ? `「${item.name}」已在运行（pid ${res.pid}）` : `已启动「${item.name}」`, 'success')
  } catch (err) {
    notify(err instanceof NativeOnlyError ? err.message : `启动失败：${String(err)}`, 'error')
  }
}

async function onRemove(item: AppItem) {
  if (!window.confirm(`确定要从软件库移除「${item.name}」吗？（不会删除文件本身）`)) return
  try {
    await store.remove(item.id)
    notify(`已移除「${item.name}」`, 'success')
  } catch (err) {
    notify(`移除失败：${String(err)}`, 'error')
  }
}

let searchTimer: number | undefined
function onSearchInput() {
  // 输入防抖：搜索会打到 core（core 做过滤），不适合每次按键都请求
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => void store.setSearch(store.search), 250)
}

// ---------------------------------------------------------------- 添加弹窗

const addOpen = ref(false)
const addTab = ref<'file' | 'scan'>('file')
const form = reactive({ name: '', path: '', args: '', category: '' })
const busy = ref(false)
const scanItems = ref<InstalledApp[]>([])
const picked = reactive<Record<string, boolean>>({})
const scanKeyword = ref('')

function openAdd() {
  addOpen.value = true
  addTab.value = 'scan' // 交互原则（2026-09-13）：扫描本机软件是默认路径
  form.name = ''
  form.path = ''
  form.args = ''
  form.category = ''
}

function closeAdd() {
  addOpen.value = false
  scanItems.value = []
}

async function onPickFile() {
  busy.value = true
  try {
    const input = await store.pickAndProbe()
    if (input) {
      form.name = input.name
      form.path = input.path
      notify(`已选择：${input.name}`, 'success')
    }
  } catch (err) {
    notify(err instanceof NativeOnlyError ? err.message : `选择文件失败：${String(err)}`, 'error')
  } finally {
    busy.value = false
  }
}

async function onScan() {
  busy.value = true
  try {
    scanItems.value = await store.scanInstalled()
    notify(`扫描到 ${scanItems.value.length} 个已安装软件（可启动 ${scanItems.value.filter((x) => x.launchable).length} 个）`, 'success')
  } catch (err) {
    notify(err instanceof NativeOnlyError ? err.message : `扫描失败：${String(err)}`, 'error')
  } finally {
    busy.value = false
  }
}

const visibleScan = computed(() => {
  const kw = scanKeyword.value.trim().toLowerCase()
  const list = kw
    ? scanItems.value.filter((x) => x.name.toLowerCase().includes(kw))
    : scanItems.value
  return list.slice(0, 300)
})

const pickedCount = computed(() => Object.values(picked).filter(Boolean).length)

async function submitFile() {
  if (!form.name.trim() || !form.path.trim()) {
    notify('名称与路径不能为空', 'error')
    return
  }
  busy.value = true
  try {
    await store.add({
      name: form.name.trim(),
      path: form.path.trim(),
      args: form.args,
      icon: null,
      type: form.path.split('.').pop() ?? null,
      category: form.category || null,
    })
    notify(`已添加「${form.name}」`, 'success')
    closeAdd()
  } catch (err) {
    notify(`添加失败：${String(err)}`, 'error')
  } finally {
    busy.value = false
  }
}

async function submitScan() {
  const inputs = scanItems.value
    .filter((x) => picked[x.name] && x.path)
    .map((x) => ({
      name: x.name,
      path: x.path,
      args: '',
      icon: null,
      type: 'exe',
      category: null,
    }))
  if (inputs.length === 0) {
    notify('请先勾选要添加的软件', 'error')
    return
  }
  busy.value = true
  try {
    const n = await store.addMany(inputs)
    notify(`已入库 ${n} / ${inputs.length} 个（重复路径会被跳过）`, 'success')
    closeAdd()
  } finally {
    busy.value = false
  }
}

// ---------------------------------------------------------------- 生命周期

let poll: number | undefined

onMounted(async () => {
  await store.load()
  poll = window.setInterval(() => void store.refreshRunning(), 5000) // 05 §3：5s
})

onUnmounted(() => {
  window.clearInterval(poll)
  window.clearTimeout(searchTimer)
})
</script>

<template>
  <section class="software-view">
    <header class="apps-toolbar">
      <input
        v-model="store.search"
        class="app-search"
        type="search"
        placeholder="搜索名称或路径…"
        @input="onSearchInput"
      />
      <select v-model="store.category" class="app-category-select" @change="store.setCategory(store.category)">
        <option value="">全部分类</option>
        <option v-for="c in store.categories" :key="c" :value="c">{{ c }}</option>
      </select>
      <button type="button" class="app-view-toggle" @click="store.view = store.view === 'grid' ? 'list' : 'grid'">
        {{ store.view === 'grid' ? '列表视图' : '网格视图' }}
      </button>
      <button type="button" class="primary" @click="openAdd">添加软件</button>
    </header>

    <div class="apps-body">
      <aside class="apps-side">
        <button
          type="button"
          class="app-category"
          :class="{ active: store.category === '' }"
          @click="store.setCategory('')"
        >
          全部（{{ store.items.length }}）
        </button>
        <button
          v-for="c in store.categories"
          :key="c"
          type="button"
          class="app-category"
          :class="{ active: store.category === c }"
          @click="store.setCategory(c)"
        >
          {{ c }}
        </button>
      </aside>

      <main class="apps-main">
        <p v-if="store.loading" class="apps-hint">加载中…</p>

        <div v-else-if="store.items.length === 0" class="apps-empty">
          <p class="apps-empty-title">还没有添加软件，点这里开始</p>
          <button type="button" class="primary" @click="openAdd">添加第一个软件</button>
        </div>

        <div v-else-if="store.view === 'grid'" class="apps-grid">
          <article
            v-for="item in store.items"
            :key="item.id"
            class="app-card"
            :class="{ running: store.isRunning(item.id) }"
            :data-app-id="item.id"
          >
            <div class="app-icon">
              <img v-if="item.icon && icons[item.icon]" :src="icons[item.icon]" :alt="item.name" />
              <span v-else class="app-icon-fallback">{{ item.name.slice(0, 1) }}</span>
            </div>
            <div class="app-name" :title="item.path">{{ item.name }}</div>
            <div class="app-meta">
              {{ item.category || '未分类' }} · 启动 {{ item.launch_count }} 次
            </div>
            <div class="app-actions">
              <button type="button" class="app-launch" :disabled="store.isRunning(item.id)" @click="onLaunch(item)">
                {{ store.isRunning(item.id) ? '运行中' : '启动' }}
              </button>
              <button type="button" class="app-pin" @click="store.togglePin(item)">
                {{ item.pinned ? '取消置顶' : '置顶' }}
              </button>
              <button type="button" class="app-remove" @click="onRemove(item)">移除</button>
            </div>
          </article>
        </div>

        <table v-else class="apps-table">
          <thead>
            <tr>
              <th>名称</th>
              <th>路径</th>
              <th>类型</th>
              <th>启动次数</th>
              <th>最后使用</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in store.items" :key="item.id" :data-app-id="item.id">
              <td class="app-name">{{ item.name }}</td>
              <td class="app-path" :title="item.path">{{ item.path }}</td>
              <td>{{ item.category || '未分类' }}</td>
              <td>{{ item.launch_count }}</td>
              <td>{{ item.last_used_at || '—' }}</td>
              <td>
                <button type="button" class="app-launch" :disabled="store.isRunning(item.id)" @click="onLaunch(item)">
                  {{ store.isRunning(item.id) ? '运行中' : '启动' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </main>
    </div>

    <!-- 添加软件 -->
    <div v-if="addOpen" class="apps-modal-mask" @click.self="closeAdd">
      <div class="apps-modal">
        <header class="apps-modal-head">
          <strong>添加软件</strong>
          <button type="button" @click="closeAdd">关闭</button>
        </header>

        <nav class="apps-modal-tabs">
          <button type="button" :class="{ active: addTab === 'scan' }" @click="addTab = 'scan'">扫描本机软件（推荐）</button>
          <button type="button" :class="{ active: addTab === 'file' }" @click="addTab = 'file'">从电脑中选择</button>
        </nav>

        <div v-if="addTab === 'file'" class="apps-modal-body">
          <p class="apps-hint">选一个程序文件，名称会自动识别好。</p>
          <button type="button" class="primary" :disabled="busy" @click="onPickFile">从电脑中选择…</button>
          <label>名称<input v-model="form.name" class="app-form-name" type="text" /></label>
          <details class="apps-advanced">
            <summary>高级设置</summary>
            <label>路径<input v-model="form.path" class="app-form-path" type="text" placeholder="可直接粘贴完整路径" /></label>
            <label>启动参数<input v-model="form.args" type="text" placeholder="通常留空" /></label>
            <label>分类
              <select v-model="form.category">
                <option value="">未分类</option>
                <option v-for="c in store.categories" :key="c" :value="c">{{ c }}</option>
              </select>
            </label>
          </details>
          <footer class="apps-modal-foot">
            <button type="button" class="primary app-form-submit" :disabled="busy" @click="submitFile">添加</button>
          </footer>
        </div>

        <div v-else class="apps-modal-body">
          <div class="apps-scan-bar">
            <button type="button" class="primary app-scan-start" :disabled="busy" @click="onScan">开始扫描</button>
            <input v-model="scanKeyword" type="search" placeholder="过滤…" />
            <span class="apps-scan-count">已选 {{ pickedCount }}</span>
          </div>
          <ul v-if="scanItems.length" class="apps-scan-list">
            <li v-for="x in visibleScan" :key="x.name + x.path">
              <label>
                <input v-model="picked[x.name]" type="checkbox" :disabled="!x.path" />
                <span class="apps-scan-name">{{ x.name }}</span>
                <span class="apps-scan-path">{{ x.path || '（无启动路径）' }}</span>
              </label>
            </li>
          </ul>
          <p v-else class="apps-hint">点「开始扫描」列出来自注册表的已安装软件（仅勾选项会入库）。</p>
          <footer class="apps-modal-foot">
            <button type="button" class="primary app-scan-submit" :disabled="busy" @click="submitScan">入库所选</button>
          </footer>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.software-view {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
}

.apps-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.app-search {
  flex: 1;
}

.apps-body {
  display: flex;
  gap: 14px;
  min-height: 0;
  flex: 1;
}

.apps-side {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 120px;
}

.app-category {
  text-align: left;
  background: transparent;
  border-color: transparent;
}

.app-category.active {
  background: var(--accent-weak);
  border-color: var(--accent);
}

.apps-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
}

.apps-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 12px;
}

.app-card {
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  box-shadow: var(--shadow);
}

.app-card.running {
  border-color: var(--ok);
}

.app-icon img {
  width: 48px;
  height: 48px;
}

.app-icon-fallback {
  display: grid;
  place-items: center;
  width: 48px;
  height: 48px;
  border-radius: 8px;
  background: var(--accent-weak);
  color: var(--accent);
  font-size: 22px;
  font-weight: 600;
}

.app-name {
  font-weight: 600;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-meta,
.app-path {
  color: var(--text-dim);
  font-size: 12px;
}

.app-path {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
}

.apps-table {
  width: 100%;
  border-collapse: collapse;
}

.apps-table th,
.apps-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}

.apps-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 60px 0;
  color: var(--text-dim);
}

.apps-empty-title {
  font-size: 15px;
}

.apps-hint {
  color: var(--text-dim);
}

.apps-modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  display: grid;
  place-items: center;
  z-index: 50;
}

.apps-modal {
  width: min(680px, 92vw);
  max-height: 80vh;
  overflow: auto;
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.apps-modal-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.apps-modal-tabs {
  display: flex;
  gap: 6px;
}

.apps-modal-tabs button.active {
  background: var(--accent-weak);
  border-color: var(--accent);
}

.apps-modal-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apps-modal-body label {
  display: flex;
  align-items: center;
  gap: 8px;
}

.apps-modal-body label input,
.apps-modal-body label select {
  flex: 1;
}

.apps-scan-bar {
  display: flex;
  gap: 8px;
  align-items: center;
}

.apps-scan-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 320px;
  overflow: auto;
}

.apps-scan-list label {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 4px 2px;
}

.apps-scan-path {
  color: var(--text-dim);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.apps-modal-foot {
  display: flex;
  justify-content: flex-end;
}

.apps-advanced {
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.apps-advanced summary {
  cursor: pointer;
  color: var(--text-dim);
}

/* `.apps-toast` 已移除：本页提示改由统一 Toast Service 渲染
 *（canonical 声明见 `styles/base.css` 的 `.toast-canonical`，与这里原本的写法逐字一致）。 */
</style>
