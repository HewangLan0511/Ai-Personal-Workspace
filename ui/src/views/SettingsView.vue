<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'

import { invokeCore } from '@/api/client'
import { toast } from '@/composables/useToast'
import { useAiStore } from '@/stores/ai'
import { useSettingsStore } from '@/stores/settings'

const store = useSettingsStore()
const ai = useAiStore()

const lastSaved = computed(() =>
  store.savedAt === 0 ? '' : new Date(store.savedAt).toLocaleTimeString(),
)

// ---- AI 配置（阶段5 §2：API Key 只进系统凭据库）----
const keyInput = ref('')
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

async function onThemeChange(value: 'light' | 'dark') {
  await store.setTheme(value)
  toast.success('已保存')
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
    toast.success(`已保存（${res.keyMask}）`)
    await ai.loadProviders()
  } catch (e) {
    keyError.value = String(e)
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
  <section class="settings-form">
    <h2>设置</h2>

    <div class="settings-row">
      <label>
        主题
        <span class="hint">浅色 / 深色</span>
      </label>
      <div>
        <button
          type="button"
          :class="{ primary: store.data.theme === 'light' }"
          @click="onThemeChange('light')"
        >浅色</button>
        <button
          type="button"
          style="margin-left: 6px;"
          :class="{ primary: store.data.theme === 'dark' }"
          @click="onThemeChange('dark')"
        >深色</button>
      </div>
    </div>

    <div class="settings-row">
      <label>
        开机自启
        <span class="hint">登录时自动运行（Windows 注册表写入）</span>
      </label>
      <input
        type="checkbox"
        :checked="store.data.autostart"
        @change="(e) => (store.data.autostart = (e.target as HTMLInputElement).checked)"
      />
    </div>

    <div class="settings-row">
      <label>
        默认 AI Provider
        <span class="hint">AI 侧栏默认调用的 Provider</span>
      </label>
      <select v-model="store.data.defaultProvider">
        <option value="">（未设置）</option>
        <option v-for="p in ai.providers" :key="p.id" :value="p.id" :disabled="!p.enabled">
          {{ p.label }}{{ p.enabled ? '' : '（未开放）' }}
        </option>
      </select>
    </div>

    <div class="settings-row">
      <label>
        数据目录
        <span class="hint">SQLite 数据库与配置文件位置（修改需重启）</span>
      </label>
      <input
        type="text"
        :value="store.data.dataDir"
        placeholder="%APPDATA%/PersonalWorkspace"
        @input="(e) => (store.data.dataDir = (e.target as HTMLInputElement).value)"
      />
    </div>

    <div class="settings-row">
      <label>
        上传匿名遥测
        <span class="hint">默认关闭，不开此开关无任何数据外传</span>
      </label>
      <input
        type="checkbox"
        :checked="store.data.privacy"
        @change="(e) => (store.data.privacy = (e.target as HTMLInputElement).checked)"
      />
    </div>

    <!-- ============ 模型管理入口（TECH-05-C §P0-1）============ -->
    <h3 class="settings-section">模型管理</h3>
    <div class="settings-row">
      <label>
        模型管理中心
        <span class="hint">连接、测试与切换模型（数据来自 ModelRegistry；密钥仍在本页配置）</span>
      </label>
      <RouterLink to="/models?from=settings">
        <button type="button">打开模型管理</button>
      </RouterLink>
    </div>

    <!-- ============ AI 凭据（阶段5 §2）============ -->
    <h3 class="settings-section">AI 凭据</h3>
    <p class="stage-note ai-cred-note">
      密钥保存在<b>系统凭据库</b>（{{ ai.credentialBackend || '未知' }}），
      数据库里只保存引用名 —— 明文密钥不落盘、不入库、不进版本库。
    </p>

    <div class="settings-row">
      <label>
        Provider
        <span class="hint">选择要配置密钥的供应商</span>
      </label>
      <select v-model="keyProvider" @change="models = []">
        <option v-for="p in needsKeyProviders" :key="p.id" :value="p.id">
          {{ p.label }}{{ p.hasKey ? ` ✓ ${p.keyMask}` : '' }}
        </option>
      </select>
    </div>

    <div v-if="selectedProvider" class="settings-row">
      <label>
        API Key
        <span class="hint">
          {{
            selectedProvider.hasKey
              ? `已配置：${selectedProvider.keyMask}（重新输入可覆盖）`
              : '仅写入系统凭据库，界面只回显掩码'
          }}
        </span>
      </label>
      <div class="ai-key-row">
        <input
          v-model="keyInput"
          type="password"
          placeholder="sk-…"
          autocomplete="off"
          @keydown.enter="saveKey"
        />
        <button type="button" class="primary" :disabled="savingKey" @click="saveKey">保存</button>
        <button v-if="selectedProvider.hasKey" type="button" @click="removeKey">删除</button>
      </div>
    </div>

    <div class="settings-row">
      <label>
        模型
        <span class="hint">可从 Provider 拉取，也可手动填写</span>
      </label>
      <div class="ai-key-row">
        <button type="button" :disabled="loadingModels" @click="fetchModels">
          {{ loadingModels ? '拉取中…' : '拉取模型列表' }}
        </button>
        <span v-if="models.length" class="stage-note">{{ models.length }} 个可用</span>
      </div>
    </div>

    <div v-if="models.length" class="ai-model-list">
      <code v-for="m in models" :key="m" class="ai-model-chip">{{ m }}</code>
    </div>

    <p v-if="keyError" class="ai-key-error">{{ keyError }}</p>

    <div class="settings-row">
      <button type="button" class="primary" @click="saveAll">保存</button>
      <span v-if="lastSaved" class="stage-note">上次保存：{{ lastSaved }}</span>
    </div>
  </section>
</template>
