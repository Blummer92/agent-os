import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    css: true,
    exclude: ['e2e/**', 'node_modules/**', 'dist/**'],
  },
});
