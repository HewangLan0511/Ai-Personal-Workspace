/**
 * 插件宿主桥（阶段9 · 契约 3.2.7）。
 *
 * 插件 JS 运行在沙箱 iframe（`sandbox` 无 `allow-same-origin`，opaque origin，
 * 消息 origin 序列化为 "null"），通过 postMessage 调用宿主能力。本模块是**唯一**的 message 监听方：
 *  - 按 event.source 反查 iframe 对应的 pluginId（防止伪造来源冒充其他插件）——**安全主边界**；
 *  - 来源 origin 仅做宽松校验（接受 opaque "null"），不做强校验（见 handleMessage 注释）；
 *  - 能力调用统一转发 core 权限网关（plugin_api → plugins::api_call，core 审计）；
 *  - `ai.invoke`：core 网关只做权限判定（返回 delegated=host），宿主再以
 *    consult 模式调 `ai_chat` command —— AI 永不经 HTTP（阶段5 订正口径）。
 *
 * 信封（契约 3.2.7）：
 *   iframe → 宿主：{ __pwPlugin: true, reqId, api, method, payload }
 *   宿主 → iframe：{ __pwPlugin: true, reqId, ok, data } / { ..., ok: false, error: { code, message } }
 */

import { invokeCore } from '@/api/client'
import { pluginApi } from '@/api/pluginService'

const PLUGIN_ORIGIN = 'http://pwplugin.localhost'

/**
 * 已注册的 iframe 窗口 → pluginId（WeakMap 防泄漏；iframe 销毁后自动失效）。
 * MessageEventSource 是 WindowProxy | MessagePort | ServiceWorker 的联合，
 * 插件桥只会来自 WindowProxy，故以 object 为键收窄（WeakMap 键约束）。
 */
const knownFrames = new WeakMap<object, string>()
let started = false

/** 宿主通知（ui.notify）：视图层监听 window 上的 CustomEvent 展示。 */
export const PLUGIN_NOTIFY_EVENT = 'pw-plugin-notify'

export function startPluginHost(): void {
  if (started) return
  started = true
  window.addEventListener('message', handleMessage)
}

export function stopPluginHost(): void {
  if (!started) return
  started = false
  window.removeEventListener('message', handleMessage)
}

/** iframe 挂载后向宿主登记（由 PluginFrame 组件调用）。 */
export function registerFrame(source: MessageEventSource | null, pluginId: string): void {
  if (source && typeof source === 'object') knownFrames.set(source, pluginId)
}

export function unregisterFrame(source: MessageEventSource | null): void {
  if (source && typeof source === 'object') knownFrames.delete(source)
}

async function handleMessage(ev: MessageEvent): Promise<void> {
  const data = ev.data as
    | { __pwPlugin?: boolean; reqId?: unknown; api?: unknown; method?: unknown; payload?: unknown }
    | undefined
  if (!data || data.__pwPlugin !== true) return
  // ⚠️ sandbox="allow-scripts"（无 allow-same-origin）的 iframe 运行在 **opaque origin**，
  // 其 postMessage 的 ev.origin 序列化为字符串 "null"——不是 http://pwplugin.localhost
  // （那是 iframe 文档的加载 URL，不是它的 origin）。两个值都接受：
  //   - "null"：opaque origin（生产态实际路径）
  //   - PLUGIN_ORIGIN：防御 WebView2 未来对自定义协议 origin 序列化的变化
  // 真正的安全边界是下面的 knownFrames 反查：消息来源必须是登记过的 iframe WindowProxy，
  // 伪造页面即使伪装 origin 也拿不到任何 pluginId。
  if (ev.origin !== PLUGIN_ORIGIN && ev.origin !== 'null') return

  const pluginId = ev.source && typeof ev.source === 'object' ? knownFrames.get(ev.source) : undefined
  if (!pluginId) {
    reply(ev.source, ev.origin, data.reqId, false, undefined, {
      code: 'unknown_frame',
      message: 'iframe 未向宿主登记（或已销毁）',
    })
    return
  }

  const api = String(data.api ?? '')
  const method = String(data.method ?? '')
  const payload = (data.payload ?? {}) as Record<string, unknown>
  const reqId = data.reqId

  try {
    const result = (await pluginApi(pluginId, api, method, payload)) as {
      delegated?: string
    }
    if (result?.delegated === 'host') {
      // core 只做权限判定与审计；实际能力由宿主执行
      const hostResult = await runHostCapability(api, method, payload)
      reply(ev.source, ev.origin, reqId, true, hostResult, undefined)
    } else {
      reply(ev.source, ev.origin, reqId, true, result, undefined)
    }
  } catch (err) {
    const message = String(err)
    const code = message.includes('PERMISSION_DENIED:') ? 'permission_denied' : 'api_failed'
    reply(ev.source, ev.origin, reqId, false, undefined, { code, message })
  }
}

async function runHostCapability(
  api: string,
  method: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  if (api === 'ui' && method === 'notify') {
    window.dispatchEvent(
      new CustomEvent(PLUGIN_NOTIFY_EVENT, {
        detail: { title: String(payload.title ?? ''), body: String(payload.body ?? '') },
      }),
    )
    return { notified: true }
  }
  if (api === 'ai' && method === 'invoke') {
    // consult 模式：不注入用户数据；直接取最终文本（不走流式，插件侧无 UI 需求）
    const prompt = String(payload.prompt ?? '')
    if (!prompt.trim()) throw new Error('ai.invoke 需要 prompt')
    const provider = await invokeCore<string>('get_config', { key: 'ai.default_provider' })
    const result = await invokeCore<unknown>('ai_chat', {
      args: {
        provider: typeof provider === 'string' ? provider : '',
        messages: [{ role: 'user', content: prompt }],
        mode: 'consult',
      },
    })
    return result
  }
  throw new Error(`宿主能力不存在：${api}.${method}`)
}

function reply(
  source: MessageEventSource | null,
  _origin: string,
  reqId: unknown,
  ok: boolean,
  data: unknown,
  error?: { code: string; message: string },
): void {
  if (!source) return
  const envelope: Record<string, unknown> = { __pwPlugin: true, reqId, ok }
  if (ok) envelope.data = data
  else envelope.error = error
  // 插件桥的 source 恒为 iframe 的 WindowProxy（window.parent 往来），按 Window 发。
  // targetOrigin 用 '*'：目标窗口已被 knownFrames 明确限定，而 iframe 是 opaque origin
  // （序列化 'null'），发 'null' 依赖实现细节，'*' 语义最稳——消息只发往这个指定窗口。
  ;(source as Window).postMessage(envelope, '*')
}
