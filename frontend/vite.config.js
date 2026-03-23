import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const brokerConfigPath = path.resolve(__dirname, '../config/broker.json')

function readFrontendHostMode() {
  try {
    if (!fs.existsSync(brokerConfigPath)) return 'localhost'
    const raw = fs.readFileSync(brokerConfigPath, 'utf8')
    const parsed = JSON.parse(raw)
    return String(parsed.frontend_host_mode || 'localhost').toLowerCase() === 'lan' ? 'lan' : 'localhost'
  } catch (e) {
    return 'localhost'
  }
}

const frontendHostMode = readFrontendHostMode()
const viteHost = frontendHostMode === 'lan' ? '0.0.0.0' : '127.0.0.1'

export default defineConfig({
  plugins: [react()],
  server: {
    host: viteHost,
    port: 5173,
    watch: {
      usePolling: process.env.CHOKIDAR_USEPOLLING === '1',
      interval: Number(process.env.CHOKIDAR_INTERVAL || 300)
    },
    // allow dev server to serve source maps to the renderer without CORS issues
    headers: {
      'Access-Control-Allow-Origin': '*'
    },
    // Proxy API requests to a tiny backend service (FastAPI) that serves config and status.
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api/, '/api')
      }
    }
  }
})
