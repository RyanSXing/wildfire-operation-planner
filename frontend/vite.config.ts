import react from '@vitejs/plugin-react'
import { configDefaults, defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig(() => {
  const apiProxyTarget =
    process.env.WILDFIREOPS_API_PROXY_TARGET ?? 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': {
          target: apiProxyTarget,
          changeOrigin: false,
        },
      },
    },
    build: {
      // MapLibre is lazy-loaded as its own offline-renderer chunk (about 275 kB gzip).
      chunkSizeWarningLimit: 1100,
    },
    test: {
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
      exclude: [...configDefaults.exclude, 'e2e/**'],
    },
  }
})
