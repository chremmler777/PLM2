import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Pin a non-UTC timezone so UTC-correctness tests (AuditTimeline day grouping)
// stay meaningful regardless of the host/CI timezone.
process.env.TZ = 'Europe/Berlin';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    // Node 22+ ships a native global `localStorage`/`sessionStorage` (stable Web
    // Storage API) that shadows jsdom's implementation inside the test workers,
    // leaving getItem/setItem/clear undefined unless --localstorage-file is set.
    // Disable Node's own implementation in the worker so jsdom's Storage (which
    // every test, and code under test via safeStorage, relies on) is the one used.
    poolOptions: {
      threads: { execArgv: ['--no-experimental-webstorage'] },
      forks: { execArgv: ['--no-experimental-webstorage'] },
    },
  },
});
