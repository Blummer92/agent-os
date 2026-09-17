import { defineConfig } from 'vite';

export default defineConfig({
  build: {
    lib: {
      entry: 'src/promptProjectionEntrypoint.ts',
      formats: ['es'],
      fileName: () => 'promptProjectionEntrypoint.js',
    },
    outDir: '.agent-os-projection-build',
    emptyOutDir: true,
    minify: false,
  },
});
