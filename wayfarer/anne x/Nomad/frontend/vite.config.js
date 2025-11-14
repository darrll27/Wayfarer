import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // allow dev server to serve source maps to the renderer without CORS issues
    headers: {
      'Access-Control-Allow-Origin': '*'
    }
  }
})
