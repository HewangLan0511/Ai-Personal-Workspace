/**
 * Widget 行为编排：上移/下移/启用停用/使用计数。组件层只关心展示，
 * 不重复实现 store 行为（04 §3 动态布局对外只有这一个门面）。
 */
import { useWidgetStore } from '@/stores/widgets'

export function useWidgets(): {
  moveUp: (id: string) => Promise<void>
  moveDown: (id: string) => Promise<void>
  toggleEnabled: (id: string) => Promise<void>
  recordUse: (id: string) => Promise<void>
} {
  const store = useWidgetStore()
  return {
    moveUp: (id: string) => store.moveUp(id),
    moveDown: (id: string) => store.moveDown(id),
    toggleEnabled: (id: string) => store.toggleEnabled(id),
    recordUse: (id: string) => store.recordUse(id),
  }
}
