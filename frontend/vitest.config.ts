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
  },
});
