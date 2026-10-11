import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

/**
 * The platform admin build.
 *
 * A separate config, not a second entry on the customer build, so the two
 * bundles share nothing: no admin screen, label or endpoint path ends up in
 * the JavaScript a customer downloads.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: 'dist-admin',
    sourcemap: false,
    rollupOptions: {
      input: fileURLToPath(new URL('./admin.html', import.meta.url)),
      output: {
        vendor: undefined,
        manualChunks: { vendor: ['react', 'react-dom', 'react-router-dom'] },
      },
    },
  },
  preview: { port: 4174, host: true },
})
