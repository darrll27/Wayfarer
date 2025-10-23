import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxy /api routes to the server during dev
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://localhost:4000'
    }
  },
})
