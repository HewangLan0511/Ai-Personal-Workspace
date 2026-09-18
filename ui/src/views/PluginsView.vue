<script setup lang="ts">
/**
 * 插件管理页（阶段9 · 12 §A）。
 *
 * 版式（UI-FUSION-FULL）：按设计稿 `ROUTES.plugins` 复刻 —— `page-head` +
 * 「已安装」`row-item` 列表卡（图标 / 名称简介 / 权限 chip / 版本 / 开关 / 详情箭头）
 * + 「更多组件」`tile` 网格 + 插件详情**抽屉**（权限开关 / 卸载）。
 *
 * 架构成功的判据：新增插件**零核心代码改动** —— 本页只做"管理"：
 * 安装（目录 / zip）、启停、卸载、审计查看、外部 Agent 注册、小组件开关。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import PluginFrame from '@/components/PluginFrame.vue'
import PwIcon from '@/components/PwIcon.vue'
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
/** 详情抽屉（设计稿 openPlugin 的等价物：权限 / 启停 / 卸载都在这里） */
const detailPlugin = ref<PluginRow | null>(null)
const detailPerms = ref<Record<string, boolean>>({})

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

const enabledCount = computed(() => installed.value.filter((p) => p.enabled).length)

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
}

async function onInstall(dir: string): Promise<void> {
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
    detailPlugin.value = null
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

/** 打开详情抽屉：权限开关状态取自插件清单（当前只能整体启停，权限是展示+审计口径）。 */
async function openDetail(p: PluginRow): Promise<void> {
  detailPlugin.value = p
  detailPerms.value = Object.fromEntries(p.permissions.map((x) => [x.permission, p.enabled]))
  await onShowAudit(p)
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
    <!-- page-head：标题 + 计数副标 + 搜索 + 获取更多 -->
    <div class="page-head">
      <div class="grow">
        <h2 class="t-page">插件</h2>
        <div class="t-cap" style="margin-top: 2px">
          已安装 {{ installed.length }} 个 · {{ enabledCount }} 个启用中 · 权限在插件详情里管理
        </div>
      </div>
      <button class="btn btn--secondary btn--sm" type="button" @click="onDiscover">
        <PwIcon name="refresh" :size="15" /> 扫描插件目录
      </button>
    </div>

    <p v-if="msg" class="t-cap" style="margin-bottom: var(--gap-card)">{{ msg }}</p>

    <!-- 已安装：设计稿 row-item 列表形态 -->
    <div class="sec" style="margin-top: 0">
      <div class="sec-head">
        <div class="t-section grow">已安装</div>
        <span class="t-cap">点插件可以查看详情与权限</span>
      </div>
      <div v-if="installed.length" class="card" style="padding: var(--space-2)">
        <div
          v-for="p in installed"
          :key="p.pluginId"
          class="row-item"
          style="cursor: pointer"
          @click="openDetail(p)"
        >
          <span class="app tint4 sm"><PwIcon name="blocks" :size="16" /></span>
          <div class="main">
            <div class="title">{{ p.name }}</div>
            <div class="t-cap">{{ p.description || '（暂无简介）' }}</div>
          </div>
          <span class="chip chip--outline" style="height: 22px">
            {{ p.permissions.length ? p.permissions.map((x) => permLabel(x.permission)).join(' · ') : '无额外能力' }}
          </span>
          <span class="t-cap mono" style="width: 44px; text-align: right">v{{ p.version }}</span>
          <button
            class="switch"
            :class="{ on: p.enabled }"
            type="button"
            :title="p.enabled ? '点击停用' : '点击启用'"
            @click.stop="onToggle(p)"
          />
          <button class="icon-btn sm" type="button" title="详情" @click.stop="openDetail(p)">
            <PwIcon name="chev-r" :size="16" />
          </button>
        </div>
      </div>
      <div v-else class="t-cap">还没有安装插件。从下面的「获取插件」开始。</div>
    </div>

    <!-- 更多组件：设计稿 tile 网格 -->
    <div class="sec">
      <div class="sec-head">
        <div class="t-section grow">更多组件</div>
        <span class="t-cap">{{ discovered.length }} 个可用</span>
      </div>
      <div class="grid" style="grid-template-columns: repeat(3, 1fr)">
        <div v-for="d in discovered" :key="d.pluginId" class="tile">
          <div class="row" style="justify-content: space-between">
            <span class="app tint4 sm"><PwIcon name="blocks" :size="16" /></span>
            <span class="badge">未安装</span>
          </div>
          <div class="t-sm" style="font-weight: 600">{{ String(d.manifest.name ?? d.pluginId) }}</div>
          <div class="t-cap">{{ String(d.manifest.description ?? '') || '（暂无简介）' }}</div>
          <button
            class="btn btn--secondary btn--sm"
            type="button"
            style="align-self: flex-start; margin-top: var(--space-1)"
            @click="onInstall(d.dir)"
          >
            安装
          </button>
        </div>
        <div v-if="!discovered.length" class="tile" style="border-style: dashed">
          <div class="t-sm" style="font-weight: 600">没有发现候选插件</div>
          <div class="t-cap">点右上「扫描插件目录」，或从下面的压缩包安装。</div>
        </div>
      </div>
    </div>

    <!-- 获取插件（压缩包） -->
    <div class="sec">
      <div class="sec-head">
        <div class="t-section grow">从压缩包安装</div>
        <span class="t-cap">插件被严格隔离运行，敏感数据不经过插件</span>
      </div>
      <div class="row" style="gap: var(--space-2)">
        <label class="input grow">
          <input v-model="installZip" placeholder="粘贴插件压缩包（zip）路径" />
        </label>
        <button class="btn btn--secondary btn--sm" type="button" :disabled="!installZip.trim()" @click="onInstallZip">
          从压缩包安装
        </button>
      </div>
    </div>

    <!-- 桌面小组件 -->
    <div class="sec">
      <div class="sec-head">
        <div class="t-section grow">桌面小组件</div>
        <span class="t-cap">{{ widget?.open ? '小组件正在桌面上显示' : '小组件未打开' }}</span>
      </div>
      <div class="card" style="padding: var(--space-2)">
        <div class="row-item">
          <span class="app tint6 sm"><PwIcon name="panel" :size="16" /></span>
          <div class="main">
            <div class="title">在桌面上显示小组件</div>
            <div class="t-cap">独立窗口，可保持在其他窗口之上</div>
          </div>
          <button
            class="switch"
            :class="{ on: !!widget?.open }"
            type="button"
            title="打开 / 关闭小组件"
            @click="onWidgetToggle"
          />
        </div>
        <div class="row-item">
          <span class="app tint1 sm"><PwIcon name="pin" :size="16" /></span>
          <div class="main">
            <div class="title">保持在前</div>
            <div class="t-cap">小组件始终显示在其他窗口之上</div>
          </div>
          <button class="switch" type="button" title="保持在前" @click="onWidgetAot(true)" />
        </div>
      </div>
    </div>

    <!-- 插件 UI 预览（沙箱 iframe） -->
    <div v-if="previewPlugin" class="sec">
      <div class="sec-head">
        <div class="t-section grow">{{ previewPlugin.name }} · 预览</div>
        <span class="t-cap">沙箱 iframe，与主应用隔离</span>
      </div>
      <div class="card">
        <PluginFrame :plugin-id="previewPlugin.pluginId" :entry="previewPlugin.entry" height="220px" />
      </div>
    </div>

    <!-- 使用记录（审计） -->
    <div v-if="auditPluginId" class="sec">
      <div class="sec-head">
        <div class="t-section grow">使用记录</div>
        <span class="t-cap">{{ auditPluginId }} · 最近 {{ audit.length }} 条</span>
      </div>
      <div class="card" style="padding: var(--space-2)">
        <div v-for="row in audit" :key="row.id" class="row-item">
          <span
            class="badge"
            :class="row.outcome === 'ok' ? 'badge--success' : row.outcome === 'denied' ? 'badge--danger' : 'badge--warning'"
          >
            {{ row.outcome }}
          </span>
          <div class="main">
            <div class="title">{{ row.action }}</div>
            <div class="t-cap">{{ row.createdAt }}</div>
          </div>
        </div>
        <div v-if="!audit.length" class="t-cap" style="padding: var(--space-3)">暂无记录。</div>
      </div>
    </div>

    <!-- 高级 / 开发者设置（设计稿：普通用户不默认看到） -->
    <details class="sec">
      <summary class="t-sm" style="cursor: pointer; color: var(--text-3)">高级 / 开发者设置</summary>
      <div class="card card--ghost" style="margin-top: var(--space-3)">
        <div class="t-section" style="margin-bottom: var(--space-2)">外部 Agent</div>
        <div class="t-cap" style="margin-bottom: var(--space-3)">
          能力白名单：mode:read / project:read / profile:read / mode:switch（每次调用仍需 confirm）/ ai:invoke。
          默认为空 = 无任何外部 Agent。
        </div>
        <label class="input" style="align-items: stretch">
          <textarea v-model="agentSpecsText" rows="8" class="mono" spellcheck="false" />
        </label>
        <div class="row" style="gap: var(--space-2); margin-top: var(--space-3)">
          <button class="btn btn--secondary btn--sm" type="button" @click="onAgentsSave">保存清单</button>
          <button
            v-for="a in agents"
            :key="a.name"
            class="btn btn--ghost btn--sm"
            type="button"
            @click="onAgentHealth(a.name)"
          >
            检查 {{ a.name }}
          </button>
          <span v-if="agentMsg" class="t-cap">{{ agentMsg }}</span>
        </div>

        <div class="t-section" style="margin: var(--space-6) 0 var(--space-3)">从目录安装（开发调试）</div>
        <div class="row" style="gap: var(--space-2)">
          <label class="input grow"><input v-model="installDir" placeholder="插件目录绝对路径" /></label>
          <button class="btn btn--secondary btn--sm" type="button" :disabled="!installDir.trim()" @click="onInstall(installDir.trim())">
            从目录安装
          </button>
        </div>
      </div>
    </details>

    <!-- 插件详情抽屉（设计稿 openPlugin 同构：功能 / 权限 / 停用 / 卸载） -->
    <div v-if="detailPlugin" class="scrim" @click.self="detailPlugin = null">
      <aside class="drawer" role="dialog" :aria-label="`${detailPlugin.name}插件`">
        <div class="drawer-head">
          <div class="t-card grow">插件详情</div>
          <button class="icon-btn" type="button" title="关闭" @click="detailPlugin = null">
            <PwIcon name="x" :size="18" />
          </button>
        </div>
        <div class="drawer-body">
          <div class="row" style="gap: var(--space-4); align-items: center">
            <span class="app tint4 xl"><PwIcon name="blocks" :size="28" /></span>
            <div class="grow">
              <div class="t-page">{{ detailPlugin.name }}</div>
              <div class="t-cap">版本 {{ detailPlugin.version }} · {{ detailPlugin.description || '（暂无简介）' }}</div>
            </div>
          </div>

          <div
            class="card card--ghost"
            style="margin-top: var(--space-5); display: flex; align-items: center; gap: var(--space-3); padding: var(--space-3) var(--space-4)"
          >
            <PwIcon name="shield" :size="18" />
            <span class="t-sm" style="flex: 1">{{ detailPlugin.enabled ? '插件正在运行' : '插件已停用' }}</span>
            <button
              class="switch"
              :class="{ on: detailPlugin.enabled }"
              type="button"
              @click="onToggle(detailPlugin)"
            />
          </div>

          <div class="t-label" style="margin: var(--space-6) 0 var(--space-3)">权限</div>
          <div class="stack" style="gap: var(--space-2)">
            <div v-for="perm in detailPlugin.permissions" :key="perm.permission" class="row-item" style="padding: var(--space-3) 0">
              <div class="main">
                <div class="title">{{ permLabel(perm.permission) }}</div>
                <div class="t-cap mono">{{ perm.permission }}</div>
              </div>
              <span class="switch" :class="{ on: !!detailPerms[perm.permission] }" />
            </div>
            <div v-if="!detailPlugin.permissions.length" class="t-cap">
              该插件没有申请额外能力，只能展示自己的界面。
            </div>
          </div>
          <div class="t-cap" style="margin-top: var(--space-3)">
            关掉权限后，插件对应的内容会从工作台隐藏。标识：{{ detailPlugin.pluginId }}
          </div>

          <div class="t-label" style="margin: var(--space-6) 0 var(--space-3)">使用记录</div>
          <div class="stack" style="gap: var(--space-1)">
            <div v-for="row in audit" :key="row.id" class="row" style="gap: var(--space-2)">
              <span
                class="badge"
                :class="row.outcome === 'ok' ? 'badge--success' : row.outcome === 'denied' ? 'badge--danger' : 'badge--warning'"
              >
                {{ row.outcome }}
              </span>
              <span class="t-cap">{{ row.action }}</span>
              <span class="t-cap" style="color: var(--text-4)">{{ row.createdAt }}</span>
            </div>
            <div v-if="!audit.length" class="t-cap">暂无记录。</div>
          </div>
        </div>
        <div class="drawer-foot">
          <button class="btn btn--danger" type="button" @click="onUninstall(detailPlugin)">
            <PwIcon name="trash" :size="15" /> 卸载
          </button>
          <div class="spacer" style="flex: 1" />
          <button
            v-if="detailPlugin.ui && detailPlugin.enabled"
            class="btn btn--secondary"
            type="button"
            @click="showPreview(detailPlugin)"
          >
            打开预览
          </button>
          <button class="btn btn--primary" type="button" @click="detailPlugin = null">完成</button>
        </div>
      </aside>
    </div>
  </section>
</template>
