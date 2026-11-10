import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// VITE_BASE: the sandbox instance is built under /plm2-sandbox/ (src/sandboxInstance)
const base = process.env.VITE_BASE || '/plm2/'
const devApi = process.env.VITE_DEV_API || 'http://claude-plm2-backend-1:8000'

export default defineConfig({
  plugins: [react()],
  base,
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['localhost', 'plm2-frontend', 'apps.ad.us.ktx.group'],
    // Behind the corporate proxy, /plm2/api is routed to the backend before
    // vite ever sees it. Hitting the dev server directly (localhost testing,
    // browser automation) had no such route, so every API call came back as
    // index.html and the app died on strings. Same mapping, dev-side.
    proxy: {
      // Depending on base handling the request reaches the middleware with
      // or without the /plm2 prefix — cover both spellings.
      [`${base}api`]: {
        target: devApi,
        changeOrigin: true,
        rewrite: (p) => p.replace(new RegExp(`^${base}api`), '/api'),
      },
      '/api': { target: devApi, changeOrigin: true },
    },
  },
  // prod may serve the built bundle via `vite preview` behind nginx (TWOS/KPI
  // pattern); nginx forwards the browser's Host header, so allow the prod name
  preview: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['localhost', 'plm2-frontend', 'plm2-sandbox-frontend', 'apps.ad.us.ktx.group'],
  },
  build: { outDir: 'dist', sourcemap: false, minify: 'esbuild' },
})
