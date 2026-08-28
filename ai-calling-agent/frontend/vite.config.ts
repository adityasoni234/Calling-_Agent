import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  resolve: {
    // Mirrors the `@/*` path mapping in tsconfig.app.json.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    host: true,
    strictPort: true,
    watch: { usePolling: true }, // bind mounts in Docker don't emit inotify events
  },
  preview: { port: 4173, host: true },
  build: { outDir: 'dist', sourcemap: false },
})
