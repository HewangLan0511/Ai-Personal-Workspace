<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { useSettingsStore } from '@/stores/settings'

const store = useSettingsStore()
onMounted(() => store.load())

const message = ref('')

const providers = ['openai', 'deepseek', 'ollama', 'lmstudio', 'web', 'user_agent']

const lastSaved = computed(() =>
  store.savedAt === 0 ? '' : new Date(store.savedAt).toLocaleTimeString(),
)

async function onThemeChange(value: 'light' | 'dark') {
  await store.setTheme(value)
  message.value = '已保存'
  setTimeout(() => (message.value = ''), 1500)
}

async function saveAll() {
  await store.savePartial({
    autostart: store.data.autostart,
    defaultProvider: store.data.defaultProvider,
    dataDir: store.data.dataDir,
    privacy: store.data.privacy,
  })
  message.value = '已保存'
  setTimeout(() => (message.value = ''), 1500)
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
        <option v-for="p in providers" :key="p" :value="p">{{ p }}</option>
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

    <div class="settings-row">
      <button type="button" class="primary" @click="saveAll">保存</button>
      <span class="saved-toast">{{ message }}</span>
      <span v-if="lastSaved" class="stage-note">上次保存：{{ lastSaved }}</span>
    </div>
  </section>
</template>