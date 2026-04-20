import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'https://sharp-jobs-flow.loca.lt',
        changeOrigin: true,
        secure: false,
      },
    },
    allowedHosts: ['.loca.lt', '.lhr.life'],
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
