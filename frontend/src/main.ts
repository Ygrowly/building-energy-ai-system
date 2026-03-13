import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'

import { setAuthProvider } from '@/api/http'
import { setStreamAuthProvider } from '@/api/stream_client'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Pinia 安装完成后，将 authStore 的 token 能力注入到 http 模块
// 放在 app.use(pinia) 之后，确保 useAuthStore() 可以正常调用
import('@/stores/authStore').then(({ useAuthStore }) => {
  const authStore = useAuthStore()

  setAuthProvider({
    getAccessToken: () => authStore.accessToken,
    refreshToken: () => authStore.refresh(),
    onUnauthorized: () => {
      authStore._clearTokens()
      router.push('/login')
    },
  })

  setStreamAuthProvider(() => authStore.accessToken)
})

app.mount('#app')
