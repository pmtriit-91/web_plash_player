import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    port: 5173,
    cors: true,
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'credentialless',
    },
  },
  optimizeDeps: {
    exclude: ['@ruffle-rs/ruffle']
  }
});
