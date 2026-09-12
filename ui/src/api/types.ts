/** 类型定义：与 core 契约对齐（03-数据契约与接口规范.md）。 */

/** Widget 卡片（04 §3） */
export interface Widget {
  id: string
  name: string
  size: 'small' | 'medium' | 'large'
  position: { row: number; col: number }
  priority: number
  enabled: boolean
}

/** 设置页模型（04 §4） */
export interface Settings {
  theme: 'light' | 'dark'
  autostart: boolean
  defaultProvider: string
  dataDir: string
  privacy: boolean
}
