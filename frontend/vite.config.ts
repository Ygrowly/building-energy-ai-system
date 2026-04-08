import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          if (id.includes('/zrender/')) {
            return 'vendor-zrender'
          }
          if (id.includes('/echarts/')) {
            return 'vendor-echarts'
          }
          if (id.includes('/vue-echarts/')) {
            return 'vendor-echarts-vue'
          }
          if (id.includes('/jspdf/')) {
            return 'vendor-pdf'
          }
          if (id.includes('/html2canvas/')) {
            return 'vendor-html2canvas'
          }
          if (id.includes('/dompurify/')) {
            return 'vendor-dompurify'
          }
          if (id.includes('/html2pdf.js/')) {
            return 'vendor-html2pdf'
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
