/**
 * TECH-01 · Conflict Guard（§十一）。
 *
 * 规则：同一元素同时产生多个 Motion 时，只允许一个 Primary；
 * 优先级（高 → 低）：system > cinema > drag > overlay > page > local > hover > idle。
 *
 * Hover → Drag：drag 声明时 hover 立即被让位（onSuperseded 回调触发，
 * 调用方负责让 hover 动画快速收敛到最终态）。
 * Press → Drag：press 快速结束并进入 drag（同一机制）。
 */

import { priorityRank, type MotionPriority } from './config'

export interface MotionClaim {
  readonly id: number
  /** 是否仍是该元素的 Primary Motion。 */
  readonly isPrimary: boolean
  /** 释放声明（动画结束/取消时必须调用）。 */
  release(): void
}

interface Entry {
  id: number
  rank: number
  onSuperseded?: () => void
}

/** el → rank → entry（同一优先级同一时间只保留一条）。 */
const active = new WeakMap<Element, Map<number, Entry>>()

let nextId = 1

export function claim(
  el: Element,
  priority: MotionPriority,
  onSuperseded?: () => void,
): MotionClaim {
  const rank = priorityRank(priority)
  let map = active.get(el)
  if (!map) {
    map = new Map<number, Entry>()
    active.set(el, map)
  }

  const entry: Entry = { id: nextId++, rank, onSuperseded }

  // 已存在更高优先级（rank 更小）的 Primary → 本次声明不成为 Primary。
  let primary = true
  for (const r of map.keys()) {
    if (r < rank) primary = false
  }

  if (primary) {
    // 让位所有更低优先级的现有 claim（它们快速收敛到最终态）。
    for (const [r, e] of map) {
      if (r > rank) {
        e.onSuperseded?.()
        map.delete(r)
      }
    }
  }
  map.set(rank, entry)

  const claimObj: MotionClaim = {
    id: entry.id,
    get isPrimary(): boolean {
      return primary && map!.get(rank) === entry
    },
    release(): void {
      if (map!.get(rank) === entry) map!.delete(rank)
      if (map!.size === 0) active.delete(el)
    },
  }
  return claimObj
}

/** 测试/调试用：元素当前是否有任何活跃声明。 */
export function hasActiveClaims(el: Element): boolean {
  return (active.get(el)?.size ?? 0) > 0
}
