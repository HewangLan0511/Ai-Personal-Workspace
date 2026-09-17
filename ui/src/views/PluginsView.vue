<script setup lang="ts">
/**
 * 插件管理页（阶段9 · 12 §A）。
 *
 * 架构成功的判据：新增插件**零核心代码改动** —— 本页只做"管理"：
 * 安装（目录 / zip）、启停、卸载、审计查看、外部 Agent 注册、小组件开关。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'

import PluginFrame from '@/components/PluginFrame.vue'
import { startPluginHost, stopPluginHost } from '@/plugin/pluginHost'
import {
  agentsList,
  agentsSave,
  agentHealth,
  pluginAudit,
  pluginsDiscover,
  pluginsInstall,
  pluginsImportZip,
  pluginsList,
  pluginsSetEnabled,
  pluginsUninstall,
  widgetSetAlwaysOnTop,
  widgetStatus,
  widgetToggle,
  type AgentSpec,
  type AuditRow,
  type DiscoveredPlugin,
  type PluginRow,
  type WidgetStatus,
} from '@/api/pluginService'

const installed = ref<PluginRow[]>([])
const discovered = ref<DiscoveredPlugin[]>([])
const audit = ref<AuditRow[]>([])
const auditPluginId = ref('')
const agents = ref<AgentSpec[]>([])
const agentSpecsText = ref('[]')
const agentMsg = ref('')
const widget = ref<WidgetStatus | null>(null)
const installDir = ref('')
const installZip = ref('')
const msg = ref('')
const previewPlugin = ref<PluginRow | null>(null)

function note(text: string): void {
  msg.value = text
}

/** 权限标识 → 普通用户能理解的说法（2026-09-13 交互重构）；未登记的回退原样显示。 */
const PERM_LABELS: Record<string, string> = {
  'data:own': '保存自己的使用数据',
  'ui:widget': '显示在桌面小组件上',
  'ui:notify': '发送系统通知',
  'system:media': '读取正在播放的音乐',
  'file:read': '读取你指定的文件',
  'net:http': '访问网络',
  'ai:invoke': '调用 AI 助手',
}

function permLabel(perm: string): string {
  return PERM_LABELS[perm] ?? perm
}

async function reload(): Promise<void> {
  installed.value = await pluginsList().catch(() => [])
  widget.value = await widgetStatus().catch(() => null)
}

onMounted(async () => {
  startPluginHost()
  await reload()
})

onBeforeUnmount(() => {
  stopPluginHost()
})

async function onDiscover(): Promise<void> {
  try {
    discovered.value = await pluginsDiscover()
    note(discovered.value.length ? `发现 ${discovered.value.length} 个候选插件` : '插件目录下没有新插件')
  } catch (err) {
    note(`扫描失败：${String(err)}`)
  }
}async function onInstall(dir: string): Promise<void> {
  try {
    const row = await pluginsInstall(dir)
    note(`已安装：${row.name}（默认禁用，请手动启用）`)
    await reload()
  } catch (err) {
    note(`安装失败：${String(err)}`)
  }
}

async function onInstallZip(): Promise<void> {
  try {
    const row = await pluginsImportZip(installZip.value.trim())
    note(`已从 zip 安装：${row.name}`)
    installZip.value = ''
    await reload()
  } catch (err) {
    note(`zip 导入失败：${String(err)}`)
  }
}

/** 红线 V5：卸载前二次确认。 */
async function onUninstall(p: PluginRow): Promise<void> {
  if (!window.confirm(`确定卸载插件「${p.name}」？目录与授权将被删除（审计保留）。`)) return
  try {
    await pluginsUninstall(p.pluginId)
    note(`已卸载：${p.pluginId}`)
    await reload()
  } catch (err) {
    note(`卸载失败：${String(err)}`)
  }
}

async function onToggle(p: PluginRow): Promise<void> {
  try {
    await pluginsSetEnabled(p.pluginId, !p.enabled)
    await reload()
  } catch (err) {
    note(`启停失败：${String(err)}`)
  }
}

async function onShowAudit(p: PluginRow): Promise<void> {
  auditPluginId.value = p.pluginId
  audit.value = await pluginAudit(p.pluginId, 20).catch(() => [])
}

async function reloadAgents(): Promise<void> {
  agents.value = await agentsList().catch(() => [])
  agentSpecsText.value = JSON.stringify(agents.value, null, 2)
}

async function onAgentsSave(): Promise<void> {
  try {
    const specs = JSON.parse(agentSpecsText.value) as AgentSpec[]
    const r = await agentsSave(specs)
    agentMsg.value = `已保存 ${r.count} 个外部 Agent`
    await reloadAgents()
  } catch (err) {
    agentMsg.value = `保存失败：${String(err)}`
  }
}

async function onAgentHealth(name: string): Promise<void> {
  try {
    await agentHealth(name)
    agentMsg.value = `${name} 健康检查通过`
  } catch (err) {
    agentMsg.value = `${name} 健康检查失败：${String(err)}`
  }
}

async function onWidgetToggle(): Promise<void> {
  await widgetToggle().catch(() => null)
  await reload()
}

async function onWidgetAot(on: boolean): Promise<void> {
  await widgetSetAlwaysOnTop(on).catch(() => null)
  await reload()
}

function showPreview(p: PluginRow): void {
  previewPlugin.value = p.ui && p.enabled ? p : null
}
</script>

<template>
  <section class="page-skeleton">
    <h2>插件</h2>
    <p class="stage-note">
      插件是小工具：装好后可以在插件预览和桌面小组件里使用。
      它们被严格隔离运行，敏感数据不经过插件；每次取用都有记录。
    </p>
    <p v-if="msg" class="hint">{{ msg }}</p>

    <!-- 已安装（普通用户视图：名称 + 简介 + 启停；权限/审计/卸载收进「详情」） -->
    <h3>已安装（{{ installed.length }}）</h3>
    <div v-if="installed.length" class="plugin-cards">
      <article v-for="p in installed" :key="p.pluginId" class="plugin-card">
        <header class="plugin-card__head">
          <strong class="plugin-card__name">{{ p.name }}</strong>
          <span class="plugin-card__ver">v{{ p.version }}</span>
          <span class="plugin-card__state" :class="{ on: p.enabled }">{{ p.enabled ? '已启用' : '已停用' }}</span>
        </header>
        <p class="plugin-card__desc">{{ p.description || '（暂无简介）' }}</p>
        <div class="row-actions">
          <button type="button" class="primary" @click="onToggle(p)">{{ p.enabled ? '停用' : '启用' }}</button>
          <button v-if="p.ui && p.enabled" type="button" @click="showPreview(p)">打开</button>
          <button type="button" @click="onShowAudit(p)">使用记录</button>
        </div>
        <details class="plugin-card__adv">
          <summary>权限与详情</summary>
          <p class="stage-note">标识：{{ p.pluginId }}</p>
          <p class="stage-note">
            它可以使用的能力：
            <template v-for="(perm, i) in p.permissions" :key="perm.permission">
              <template v-if="i">、</template>{{ permLabel(perm.permission) }}
            </template>
            <template v-if="!p.permissions.length">无（只展示自己界面）</template>
          </p>
          <div class="row-actions">
            <button type="button" class="danger" @click="onUninstall(p)">卸载</button>
          </div>
        </details>
      </article>
    </div>
    <p v-else class="stage-note">还没有安装插件。从下面的「获取插件」开始。</p>

    <!-- 插件 UI 预览（沙箱 iframe） -->
    <div v-if="previewPlugin" class="plugin-preview">
      <h4>{{ previewPlugin.name }}</h4>
      <PluginFrame :plugin-id="previewPlugin.pluginId" :entry="previewPlugin.entry" height="220px" />
    </div>

    <!-- 审计 -->
    <div v-if="auditPluginId" class="audit-block">
      <h4>使用记录：{{ auditPluginId }}（最近 {{ audit.length }} 条）</h4>
      <ul class="audit-list">
        <li v-for="row in audit" :key="row.id">
          <span class="audit-outcome" :class="row.outcome">{{ row.outcome }}</span>
          {{ row.action }}
          <span class="stage-note">{{ row.createdAt }}</span>
        </li>
        <li v-if="!audit.length" class="stage-note">暂无记录。</li>
      </ul>
    </div>

    <!-- 获取插件 -->
    <h3>获取插件</h3>
    <div class="install-row">
      <button type="button" @click="onDiscover">扫描插件目录</button>
      <input v-model="installZip" placeholder="粘贴插件压缩包（zip）路径" />
      <button type="button" :disabled="!installZip.trim()" @click="onInstallZip">从压缩包安装</button>
    </div>
    <ul v-if="discovered.length" class="discover-list">
      <li v-for="d in discovered" :key="d.pluginId">
        <strong>{{ String(d.manifest.name ?? d.pluginId) }}</strong>
        <span class="stage-note">{{ String(d.manifest.description ?? '') }}</span>
        <button type="button" @click="onInstall(d.dir)">安装</button>
      </li>
    </ul>

    <!-- 桌面小组件 -->
    <h3>桌面小组件</h3>
    <p v-if="widget" class="hint">
      {{ widget.open ? '小组件正在桌面上显示' : '小组件未打开' }}
    </p>
    <div class="install-row">
      <button type="button" @click="onWidgetToggle">{{ widget?.open ? '关闭小组件' : '打开小组件' }}</button>
      <button type="button" @click="onWidgetAot(true)">保持在前</button>
      <button type="button" @click="onWidgetAot(false)">取消保持</button>
    </div>

    <!-- 开发者设置（整块折叠） -->
    <details class="dev-settings">
      <summary>高级 / 开发者设置</summary>
      <h4>外部 Agent（默认为空 = 无任何外部 Agent）</h4>
      <p class="hint">
        能力白名单：mode:read / project:read / profile:read / mode:switch（每次调用仍需 confirm）/ ai:invoke。
      </p>
      <textarea v-model="agentSpecsText" rows="8" class="agents-editor" spellcheck="false" />
      <div class="install-row">
        <button type="button" @click="onAgentsSave">保存清单</button>
        <button
          v-for="a in agents"
          :key="a.name"
          type="button"
          @click="onAgentHealth(a.name)"
        >
          检查 {{ a.name }}
        </button>
        <span v-if="agentMsg" class="stage-note">{{ agentMsg }}</span>
      </div>
      <h4>从目录安装（开发调试）</h4>
      <div class="install-row">
        <input v-model="installDir" placeholder="插件目录绝对路径" />
        <button type="button" :disabled="!installDir.trim()" @click="onInstall(installDir.trim())">
          从目录安装
        </button>
      </div>
    </details>
  </section>
</template>

<style scoped>
/* ---- 2026-09-13 交互重构：插件卡片（普通用户视图） ---- */
.plugin-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}
.plugin-card {
  border: 1px solid var(--pw-border, rgba(0, 0, 0, 0.08));
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--pw-card, #fff);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.plugin-card__head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.plugin-card__name {
  font-size: 14px;
}
.plugin-card__ver {
  color: var(--pw-muted, #888);
  font-size: 12px;
}
.plugin-card__state {
  margin-left: auto;
  font-size: 12px;
  color: var(--pw-muted, #888);
}
.plugin-card__state.on {
  color: var(--pw-ok, #2e9e5b);
  font-weight: 600;
}
.plugin-card__desc {
  margin: 0;
  font-size: 13px;
  min-height: 18px;
}
.plugin-card__adv {
  border-top: 1px dashed var(--pw-border, rgba(0, 0, 0, 0.08));
  padding-top: 6px;
}
.plugin-card__adv summary {
  cursor: pointer;
  color: var(--pw-muted, #888);
  font-size: 12px;
}
.dev-settings {
  border: 1px solid var(--pw-border, rgba(0, 0, 0, 0.08));
  border-radius: 8px;
  padding: 10px 14px;
}
.dev-settings summary {
  cursor: pointer;
  color: var(--pw-muted, #888);
}

.pw-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.pw-table th,
.pw-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid var(--pw-border, rgba(0, 0, 0, 0.08));
  vertical-align: top;
}
.perm-chip {
  display: inline-block;
  margin: 0 4px 4px 0;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--pw-bg-subtle, rgba(0, 0, 0, 0.05));
  font-size: 12px;
}
.row-actions button {
  margin-right: 4px;
}
.danger {
  color: #c0392b;
}
.install-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin: 8px 0;
}
.install-row input {
  flex: 1;
  min-width: 220px;
}
.discover-list,
.audit-list {
  font-size: 13px;
  line-height: 1.8;
}
.audit-outcome.ok {
  color: #1e8e3e;
}
.audit-outcome.denied {
  color: #c0392b;
}
.audit-outcome.error {
  color: #b45309;
}
.plugin-preview {
  margin: 12px 0;
  padding: 8px;
  border: 1px dashed var(--pw-border, rgba(0, 0, 0, 0.15));
  border-radius: 6px;
}
.agents-editor {
  width: 100%;
  font-family: monospace;
  font-size: 12px;
}
</style>
