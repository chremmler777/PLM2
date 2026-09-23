import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Pin a non-UTC timezone so UTC-correctness tests (AuditTimeline day grouping)
// stay meaningful regardless of the host/CI timezone.
process.env.TZ = 'Europe/Berlin';

// Node 22.4+ ships a native global `localStorage`/`sessionStorage` (stable Web
// Storage API) that shadows jsdom's implementation inside the test workers,
// leaving getItem/setItem/clear undefined unless --localstorage-file is set.
// --no-experimental-webstorage disables Node's own implementation so jsdom's
// Storage (which every test, and code under test via safeStorage, relies on)
// is the one used. The flag does not exist before Node 22.4 (the frontend
// Docker images pin node:20-alpine), and an unknown execArgv flag crashes the
// worker/fork pool outright, so only pass it when this Node build supports it.
const webStorageFlag = process.allowedNodeEnvironmentFlags.has('--no-experimental-webstorage')
  ? ['--no-experimental-webstorage']
  : [];

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: false,
    poolOptions: {
      threads: { execArgv: webStorageFlag },
      forks: { execArgv: webStorageFlag },
    },
  },
});
