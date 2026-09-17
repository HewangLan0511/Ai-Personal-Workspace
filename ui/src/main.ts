import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import DesktopWidgetView from './views/DesktopWidgetView.vue'
import { createAppRouter } from './router'
import { initMotionRuntime } from '@/motion'
// TECH-01：token 是视觉值单一来源 —— tokens.css（Foundation→Semantic）
// 必须先于 base.css 加载；motion-tokens.css 提供 duration/intensity/gate 变量。
import './styles/tokens.css'
import './styles/motion-tokens.css'
import './styles/base.css'
// TECH-05-C §P0：共享原语层（card / chip / button / drawer / field 等）。
// 它只消费上面三份 token，不新增 token、不含 @keyframes。
import './components/ui/primitives.css'

// TECH-01：Motion Runtime 初始化（Motion Guard 读取系统 reduced-motion
// 偏好 + `?motion=novt` 标记 + window.__pwMotion 调试口）。桌面小组件窗口
// 同样初始化——Guard 是全局安全底座，不随宿主窗口类型变化。
initMotionRuntime()

// 阶段9：桌面小组件以独立 Tauri 窗口承载，core 以 `index.html?pwWindow=desktop-widget`
// 打开；命中该参数时挂载**无侧栏**的组件宿主（不经路由，避免与主窗口的状态/导航耦合）。
const params = new URLSearchParams(window.location.search)
const pwWindow = params.get('pwWindow')

if (pwWindow === 'desktop-widget') {
  createApp(DesktopWidgetView).mount('#app')
} else {
  const app = createApp(App)
  app.use(createPinia())
  app.use(createAppRouter())
  app.mount('#app')
}
