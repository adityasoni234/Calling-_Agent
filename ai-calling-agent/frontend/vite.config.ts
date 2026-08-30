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
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // Charts are the bulk of the bundle and change far less often than app
        // code; splitting them keeps the app chunk small and cacheable.
        manualChunks: { charts: ['recharts'], vendor: ['react', 'react-dom', 'react-router-dom'] },
      },
    },
  },
})
