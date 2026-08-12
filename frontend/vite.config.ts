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
    // Behind the corporate proxy, /plm2/api is routed to the backend before
    // vite ever sees it. Hitting the dev server directly (localhost testing,
    // browser automation) had no such route, so every API call came back as
    // index.html and the app died on strings. Same mapping, dev-side.
    proxy: {
      // Depending on base handling the request reaches the middleware with
      // or without the /plm2 prefix — cover both spellings.
      '/plm2/api': {
        target: 'http://claude-plm2-backend-1:8000',
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/plm2\/api/, '/api'),
      },
      '/api': { target: 'http://claude-plm2-backend-1:8000', changeOrigin: true },
    },
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
