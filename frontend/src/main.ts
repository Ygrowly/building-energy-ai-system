import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import './styles/home-dashboard.css'

import { setAuthProvider } from '@/api/http'
import { setStreamAuthProvider } from '@/api/stream_client'
import { useAuthStore } from '@/stores/authStore'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

// Pinia 已安装，同步注入 authProvider，杜绝路由守卫先于 provider 就绪的竞态
const authStore = useAuthStore()

setAuthProvider({
  getAccessToken: () => authStore.getAccessToken(),
  refreshToken: () => authStore.refresh(),
  onUnauthorized: () => {
    authStore._clearTokens()
    const currentRoute = router.currentRoute.value
    const redirect = currentRoute.meta.requiresAuth === false ? undefined : currentRoute.fullPath
    void router.replace(
      redirect
        ? { name: 'Login', query: { redirect } }
        : { name: 'Login' },
    )
  },
})

setStreamAuthProvider(() => authStore.getAccessToken())

async function bootstrap() {
  await router.isReady()
  app.mount('#app')
}

void bootstrap()
