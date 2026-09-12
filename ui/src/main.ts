import { createPinia } from 'pinia'
import { createApp } from 'vue'

import App from './App.vue'
import { createAppRouter } from './router'
import './styles/base.css'

const app = createApp(App)
app.use(createPinia())
app.use(createAppRouter())
app.mount('#app')
