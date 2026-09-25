import vue from '@vitejs/plugin-vue'
import vuetify from 'vite-plugin-vuetify'
import { defineConfig } from 'vite'

// The production build is written inside the Python package, which serves it.
export default defineConfig({
  plugins: [vue(), vuetify({ autoImport: true })],
  build: {
    outDir: '../src/swirl/app/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 5200,
  },
  server: {
    port: 5174,
    proxy: { '/api': { target: 'http://127.0.0.1:8765', changeOrigin: true } },
  },
})
