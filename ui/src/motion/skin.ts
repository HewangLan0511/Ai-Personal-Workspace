/**
 * Skin Engine Runtime（skin-system.md v1.0 落地）。
 *
 * 架构位置（TECH-01 §十八 的预留接口，本文件是它的实现）：
 *   Core Motion（不可变安全规则）
 *     → Motion Guard（data-motion / data-perf，硬设最终变量 —— 永远高于 Skin）
 *     → Skin Motion Profile（本模块：只写 --mt-skin-* 通道变量 + --accent）
 *     → Component Motion
 *
 * 硬规则：
 *   - Skin 只能写白名单变量（经 --mt-skin-* 通道 + --accent），Guard 与
 *     Interactive Gate 的最终值不设通道，Skin 无从触碰；
 *   - data-motion="off"/"reduced" 的 CSS 档位硬设最终值，Skin intensity>1
 *     在 reduced/off 下被完全覆盖（CSS 层保证，无 JS 特判）；
 *   - applySkin 只做 data-skin 属性 + 内联自定义属性更新：
 *     不触发页面动画 / View Transition / render（T6/T7 验收）；
 *   - Default Skin：无覆盖，移除 data-skin 与通道变量即恢复。
 */

export const SKIN_SCHEMA_VERSION = 1

/** 白名单强度变量：key → [min, max]。intensity 允许 >1（Lively）。 */
const INTENSITY_FIELDS: Record<string, [number, number]> = {
  intensity: [0, 2],
  drift: [0, 2],
  scaleOn: [0, 2],
  blur: [0, 1],
}

/** duration 白名单：key → [min, max]（ms，整数）。instant / gate 不开放。 */
const DURATION_FIELDS: Record<string, [number, number]> = {
  quick: [0, 1000],
  base: [0, 1000],
  panel: [0, 1000],
  scene: [0, 1000],
  cinematic: [0, 1000],
}

const EASING_FIELDS = ['standard', 'entry', 'exit'] as const
const STAGGER_RANGE: [number, number] = [0, 200]

/** 明确禁止的键：试图覆盖 → 整个 skin 拒绝加载（不是忽略）。 */
const FORBIDDEN_KEYS = new Set([
  'gate', 'interactiveGate', 'dwell', 'instant', 'pressScale', 'hoverLift',
  'cinema', 'layout', 'spacing', 'typography', 'radius', 'amplitude',
  'durationMap', 'pageTransition', 'shadow', 'opacity',
])

export interface SkinLoadReport {
  ok: boolean
  warnings: string[]
  errors: string[]
  skin: SkinDefinition | null
}

export interface SkinOverrides {
  intensity?: number
  drift?: number
  scaleOn?: number
  blur?: number
  stagger?: number
  duration?: Partial<Record<keyof typeof DURATION_FIELDS, number>>
  easing?: Partial<Record<(typeof EASING_FIELDS)[number], string>>
  accent?: string
}

export interface SkinDefinition {
  id: string
  name: string
  overrides: SkinOverrides
}

// ---------------------------------------------------------------- 校验

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

const EASING_RE =
  /^(ease|linear|ease-in|ease-out|ease-in-out|steps\(\s*\d+\s*(,\s*(start|end|jump-start|jump-end|jump-none|jump-both)\s*)?\)|cubic-bezier\(\s*(0|1|0?\.\d+)\s*,\s*-?(\d|\d?\.\d+)\s*,\s*(0|1|0?\.\d+)\s*,\s*-?(\d|\d?\.\d+)\s*\))$/

const COLOR_RE =
  /^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$|^rgba?\(\s*(\d{1,3}%?\s*,\s*){2}\d{1,3}%?\s*(,\s*(0|1|0?\.\d+)\s*)?\)$|^hsla?\(\s*\d{1,3}(deg)?\s*,\s*\d{1,3}%\s*,\s*\d{1,3}%\s*(,\s*(0|1|0?\.\d+)\s*)?\)$/

function numInRange(v: unknown, range: [number, number]): boolean {
  return typeof v === 'number' && Number.isFinite(v) && v >= range[0] && v <= range[1]
}

/**
 * 解析 + 白名单校验。非法值 / 触碰禁止键 → 整个 skin 拒绝（errors 非空）；
 * 未知字段 → 忽略并记 warning；缺字段 → 缺省（即 Default 行为）。
 */
export function loadSkin(json: unknown): SkinLoadReport {
  const warnings: string[] = []
  const errors: string[] = []

  if (!isPlainObject(json)) {
    return { ok: false, warnings, errors: ['skin.json 顶层必须是对象'], skin: null }
  }
  if (json.schemaVersion !== SKIN_SCHEMA_VERSION) {
    errors.push(`schemaVersion 必须为 ${SKIN_SCHEMA_VERSION}，收到 ${JSON.stringify(json.schemaVersion)}`)
    return { ok: false, warnings, errors, skin: null }
  }

  const id = typeof json.id === 'string' && /^[a-z][a-z0-9-]{0,31}$/.test(json.id) ? json.id : null
  if (!id) errors.push('id 缺失或非法（小写字母开头，≤32 位 [a-z0-9-]）')
  const name = typeof json.name === 'string' && json.name.trim() ? json.name.trim() : id ?? ''
  if (!name) errors.push('name 缺失且 id 也无法充当名称')

  const overrides: SkinOverrides = {}

  if ('motion' in json) {
    if (!isPlainObject(json.motion)) {
      errors.push('motion 必须是对象')
    } else {
      const m = json.motion as Record<string, unknown>
      for (const [key, range] of Object.entries(INTENSITY_FIELDS)) {
        if (!(key in m)) continue
        if (!numInRange(m[key], range)) {
          errors.push(`motion.${key} 非法：${JSON.stringify(m[key])}（允许 ${range[0]}–${range[1]}）`)
        } else {
          (overrides as Record<string, number>)[key] = m[key] as number
        }
      }
      if ('stagger' in m) {
        if (!numInRange(m.stagger, STAGGER_RANGE)) {
          errors.push(`motion.stagger 非法：${JSON.stringify(m.stagger)}（允许 ${STAGGER_RANGE[0]}–${STAGGER_RANGE[1]} ms）`)
        } else {
          overrides.stagger = m.stagger as number
        }
      }
      if ('duration' in m) {
        if (!isPlainObject(m.duration)) {
          errors.push('motion.duration 必须是对象')
        } else {
          overrides.duration = {}
          for (const [key, range] of Object.entries(DURATION_FIELDS)) {
            const v = (m.duration as Record<string, unknown>)[key]
            if (!(key in (m.duration as Record<string, unknown>))) continue
            if (typeof v !== 'number' || !Number.isInteger(v) || v < range[0] || v > range[1]) {
              errors.push(`motion.duration.${key} 非法：${JSON.stringify(v)}（整数 ms，允许 ${range[0]}–${range[1]}）`)
            } else {
              overrides.duration![key as keyof typeof DURATION_FIELDS] = v
            }
          }
          for (const key of Object.keys(m.duration as Record<string, unknown>)) {
            if (FORBIDDEN_KEYS.has(key)) errors.push(`motion.duration.${key} 属于禁止覆盖的 token`)
            else if (!(key in DURATION_FIELDS)) warnings.push(`未知字段 motion.duration.${key} 已忽略`)
          }
        }
      }
      if ('easing' in m) {
        if (!isPlainObject(m.easing)) {
          errors.push('motion.easing 必须是对象')
        } else {
          overrides.easing = {}
          for (const key of EASING_FIELDS) {
            const v = (m.easing as Record<string, unknown>)[key]
            if (!(key in (m.easing as Record<string, unknown>))) continue
            if (typeof v !== 'string' || v.length > 120 || !EASING_RE.test(v.trim())) {
              errors.push(`motion.easing.${key} 非法：${JSON.stringify(v)}`)
            } else {
              overrides.easing![key] = v.trim()
            }
          }
          for (const key of Object.keys(m.easing as Record<string, unknown>)) {
            if (!(EASING_FIELDS as readonly string[]).includes(key)) {
              warnings.push(`未知字段 motion.easing.${key} 已忽略`)
            }
          }
        }
      }
      for (const key of Object.keys(m)) {
        if (['intensity', 'drift', 'scaleOn', 'blur', 'stagger', 'duration', 'easing'].includes(key)) continue
        if (FORBIDDEN_KEYS.has(key)) errors.push(`motion.${key} 属于禁止覆盖的 token（Gate/Dwell/派生幅度不可经 Skin 修改）`)
        else warnings.push(`未知字段 motion.${key} 已忽略`)
      }
    }
  }

  if ('color' in json) {
    if (!isPlainObject(json.color)) {
      errors.push('color 必须是对象')
    } else {
      const c = json.color as Record<string, unknown>
      if ('accent' in c) {
        if (typeof c.accent !== 'string' || c.accent.length > 64 || !COLOR_RE.test(c.accent.trim())) {
          errors.push(`color.accent 非法：${JSON.stringify(c.accent)}`)
        } else {
          overrides.accent = c.accent.trim()
        }
      }
      for (const key of Object.keys(c)) {
        if (key !== 'accent') warnings.push(`未知字段 color.${key} 已忽略`)
      }
    }
  }

  for (const key of Object.keys(json)) {
    if (['schemaVersion', 'id', 'name', 'motion', 'color'].includes(key)) continue
    if (FORBIDDEN_KEYS.has(key)) errors.push(`顶层字段 ${key} 属于禁止覆盖范围`)
    else warnings.push(`未知字段 ${key} 已忽略`)
  }

  if (errors.length || !id) {
    return { ok: false, warnings, errors, skin: null }
  }
  return { ok: true, warnings, errors, skin: { id, name, overrides } }
}

// ---------------------------------------------------------------- Registry

/** 内置 skin。Default：无任何覆盖（移除 data-skin 即恢复）。 */
export const BUILTIN_SKINS: SkinDefinition[] = [
  { id: 'default', name: 'Default', overrides: {} },
  {
    id: 'calm',
    name: 'Calm',
    overrides: {
      intensity: 0.7,
      drift: 0.4,
      scaleOn: 0.6,
      blur: 0.2,
      stagger: 18,
      accent: '#5b8def',
    },
  },
  {
    id: 'lively',
    name: 'Lively',
    overrides: {
      intensity: 1.35, // 故意 >1：T4 验证 reduced/off 必须压过它
      drift: 1.5,
      scaleOn: 1.2,
      blur: 1,
      stagger: 32,
      duration: { quick: 100, base: 150 },
      accent: '#ff6b3d',
    },
  },
]

const registry = new Map<string, SkinDefinition>()
for (const s of BUILTIN_SKINS) registry.set(s.id, s)

export function registerSkin(def: SkinDefinition): void {
  registry.set(def.id, def)
}

export function listSkins(): SkinDefinition[] {
  return [...registry.values()]
}

// ---------------------------------------------------------------- Apply

let activeSkinId: string | null = null // null = Default（无 data-skin）
let appliedProps: string[] = [] // 本 skin 写入的内联属性，clear 时精确移除

/* ---------------------------------------------------------------- 持久化
 * skin-system.md §9.2 第 6/7 项：`localStorage("pw.skin")`，启动时恢复。
 * 为什么不吃 Core config：本条是**设计稿指定的落点**（皮肤包自带 JSON，
 * 选择是"本地口味"而不是工作区数据）；而且 localStorage 读写失败必须降级成
 * "这一次不记住"，不能让皮肤层成为启动依赖（I4/F4：绝不白屏）。
 */
const LS_KEY = 'pw.skin'

function persist(id: string | null): void {
  try {
    if (id === null || id === 'default') localStorage.removeItem(LS_KEY)
    else localStorage.setItem(LS_KEY, id)
  } catch {
    /* 隐私模式 / 配额满：只影响"下次启动还记得吗"，不影响本次生效 */
  }
}

function readPersisted(): string | null {
  try {
    return localStorage.getItem(LS_KEY)
  } catch {
    return null
  }
}

/**
 * 启动时恢复上次选的皮肤（`initMotionRuntime` 调用一次）。
 *
 * 任何异常路径都回到**无皮肤态**：注册表里没有这个 id（皮肤包被删/被手改坏）、
 * `applySkin` 失败、localStorage 不可用 —— 一律清掉持久值并保持 Default。
 * 这正是 F4「运行时的恢复动作永远是回到无皮肤态」。
 */
export function restoreSkin(): { id: string | null } {
  const id = readPersisted()
  if (!id) return { id: null }
  if (!registry.has(id)) {
    persist(null)
    return { id: null }
  }
  const r = applySkin(id)
  if (!r.ok) {
    persist(null)
    return { id: null }
  }
  return { id }
}

/** 强度/模糊等 → --mt-skin-* 通道；accent → --accent（语义层主题色覆盖）。 */
function propNames(o: SkinOverrides): Array<[string, string]> {
  const props: Array<[string, string]> = []
  if (o.intensity !== undefined) props.push(['--mt-skin-intensity', String(o.intensity)])
  if (o.drift !== undefined) props.push(['--mt-skin-drift', String(o.drift)])
  if (o.scaleOn !== undefined) props.push(['--mt-skin-scale-on', String(o.scaleOn)])
  if (o.blur !== undefined) props.push(['--mt-skin-blur', String(o.blur)])
  if (o.stagger !== undefined) props.push(['--mt-skin-stagger', `${o.stagger}ms`])
  for (const [k, v] of Object.entries(o.duration ?? {})) {
    props.push([`--mt-skin-dur-${k}`, `${v}ms`])
  }
  for (const [k, v] of Object.entries(o.easing ?? {})) {
    props.push([`--mt-skin-ease-${k}`, v])
  }
  if (o.accent !== undefined) props.push(['--accent', o.accent])
  return props
}

/**
 * 切换 skin。只更新变量层：documentElement 的 data-skin 属性 + 内联
 * 自定义属性。不调用 Page Transition / Cinema / View Transition / WAAPI。
 */
export function applySkin(id: string): { ok: boolean; error?: string } {
  const def = registry.get(id)
  if (!def) return { ok: false, error: `unknown skin: ${id}` }
  const root = document.documentElement

  // 1) 清掉上一个 skin 的内联通道（Default 无覆盖 = 回到 :root 表）
  for (const name of appliedProps) root.style.removeProperty(name)
  appliedProps = []

  if (def.id === 'default' || Object.keys(def.overrides).length === 0) {
    // Default：删除 data-skin 即恢复
    delete root.dataset.skin
    activeSkinId = null
    persist(null)
    return { ok: true }
  }

  // 2) 写通道变量 + data-skin 标记（纯属性/变量更新，无动画调用）
  for (const [name, value] of propNames(def.overrides)) {
    root.style.setProperty(name, value)
    appliedProps.push(name)
  }
  root.dataset.skin = def.id
  activeSkinId = def.id
  persist(def.id)
  return { ok: true }
}

/** 校验 + 注册 + 应用（skin.json 入口）。失败时保持现状不变。 */
export function applySkinJson(json: unknown): SkinLoadReport {
  const report = loadSkin(json)
  if (!report.ok || !report.skin) return report
  registerSkin(report.skin)
  const applied = applySkin(report.skin.id)
  if (!applied.ok) {
    report.ok = false
    report.errors.push(applied.error ?? 'apply 失败')
  }
  return report
}

export function clearSkin(): { ok: boolean } {
  return applySkin('default')
}

export function getActiveSkinId(): string | null {
  return activeSkinId
}
