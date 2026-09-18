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
  /**
   * 主题：设计稿「设置 · 外观」是三档分段控件（浅色 / 深色 / 跟随系统）。
   * `system` 是**意图**，落盘到 `data-theme` 的永远是解析后的 `light|dark`
   * （设计稿 `setTheme()` 同款：`real = system ? matchMedia(...) : v`）。
   */
  theme: 'light' | 'dark' | 'system'
  autostart: boolean
  defaultProvider: string
  dataDir: string
  privacy: boolean
}
