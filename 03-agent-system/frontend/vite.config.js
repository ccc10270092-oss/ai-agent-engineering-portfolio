import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发模式：vite 5173，/api 代理到 FastAPI 8000
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
