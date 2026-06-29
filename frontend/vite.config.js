import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth':        'http://localhost:8000',
      '/models':      'http://localhost:8000',
      '/market':      'http://localhost:8000',
      '/predictions': 'http://localhost:8000',
      '/settings':    'http://localhost:8000',
      '/cc':          'http://localhost:8000',
      '/ws':          { target: 'ws://localhost:8000', ws: true },
    },
  },
})
