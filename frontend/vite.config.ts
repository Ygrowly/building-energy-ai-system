import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('/echarts/') || id.includes('/zrender/') || id.includes('/vue-echarts/')) {
            return 'vendor-charts'
          }
          if (id.includes('/html2pdf.js/')) {
            return 'vendor-export'
          }
          if (id.includes('/marked/')) {
            return 'vendor-markdown'
          }
          if (id.includes('/@iconify/')) {
            return 'vendor-icons'
          }
          if (id.includes('/@lottiefiles/')) {
            return 'vendor-lottie'
          }
          if (id.includes('/pinia/') || id.includes('/vue-router/') || id.includes('/vue/')) {
            return 'vendor-vue'
          }
          return 'vendor-misc'
        },
      },
    },
  },
  resolve: {
    alias: {
      '@': new URL('./src', import.meta.url).pathname,
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
