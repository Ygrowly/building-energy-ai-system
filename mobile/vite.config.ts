import { defineConfig } from 'vite'
import { fileURLToPath, URL } from 'node:url'
import uni from '@dcloudio/vite-plugin-uni'

const isAppBuild = process.env.UNI_PLATFORM === 'app'

export default defineConfig({
  plugins: [uni()],
  resolve: isAppBuild
    ? {
        alias: [
          {
            find: /^vue$/,
            replacement: fileURLToPath(new URL('./src/shims/vue-compat.ts', import.meta.url)),
          },
        ],
      }
    : undefined,
  server: {
    port: 5174,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  // 不再用 define 覆盖 — 让 Vite 自动从 .env.* 文件加载 VITE_API_BASE_URL
})
