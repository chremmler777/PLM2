import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/plm2/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['localhost', 'plm2-frontend', 'apps.ad.us.ktx.group'],
  },
  // prod may serve the built bundle via `vite preview` behind nginx (TWOS/KPI
  // pattern); nginx forwards the browser's Host header, so allow the prod name
  preview: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['localhost', 'plm2-frontend', 'apps.ad.us.ktx.group'],
  },
  build: { outDir: 'dist', sourcemap: false, minify: 'esbuild' },
})
