import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/plm2/',
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    allowedHosts: ['localhost', 'plm2-frontend'],
  },
  build: { outDir: 'dist', sourcemap: false, minify: 'esbuild' },
})
