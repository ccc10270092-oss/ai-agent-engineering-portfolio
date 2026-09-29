import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import * as Icons from '@element-plus/icons-vue'

import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'

import App from './App.vue'
import router from './router'
import { store } from './store/app'
import './styles/theme.css'

const app = createApp(App)

// 全量注册图标(按需场景少,本地系统不必做 tree-shaking)
for (const [name, comp] of Object.entries(Icons)) {
  app.component(name, comp)
}

app.use(ElementPlus)
app.use(router)
app.mount('#app')

store.init()
