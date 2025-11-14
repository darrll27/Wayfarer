// Aedes broker runner for local development
// Reads config/broker.json to decide whether to spawn an internal broker or assume an external one.
const fs = require('fs')
const path = require('path')
const aedes = require('aedes')()
const net = require('net')
const http = require('http')
const websocket = require('websocket-stream')

// load broker config from repo root (frontend/scripts -> ../.. -> repo root)
let cfg = null
try {
  const cfgPath = path.join(__dirname, '..', '..', 'config', 'broker.json')
  const raw = fs.readFileSync(cfgPath, 'utf8')
  cfg = JSON.parse(raw)
} catch (e) {
  console.warn('[aedes] failed to read config/broker.json; falling back to env/defaults')
  cfg = { mode: 'internal', host: 'localhost', tcp_port: process.env.AEDES_TCP_PORT || 1883, ws_port: process.env.AEDES_WS_PORT || 1884 }
}

const MODE = (cfg.mode || 'internal')
const TCP_PORT = cfg.tcp_port || 1883
const WS_PORT = cfg.ws_port || 1884
const HOST = cfg.host || 'localhost'

if (MODE !== 'internal') {
  console.log(`[aedes] broker configured as external (mode=${MODE}); not spawning local broker`).
  console.log(`[aedes] expected broker at mqtt://${HOST}:${TCP_PORT} and ws://${HOST}:${WS_PORT}`)
  process.exit(0)
}

// Before spawning Aedes, poll the backend /api/status until the backend config service is online
// This prevents the broker from starting before the backend is ready to serve config.
const httpGet = (url) => new Promise((resolve) => {
  const req = http.request(url, {method: 'GET', timeout: 1000}, (res) => {
    let buf = ''
    res.on('data', (d) => buf += d)
    res.on('end', () => resolve({status: res.statusCode, body: buf}))
  })
  req.on('error', () => resolve(null))
  req.on('timeout', () => { req.destroy(); resolve(null) })
  req.end()
})

async function waitForBackendAndStart(timeoutMs = 20000) {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    try {
      const resp = await httpGet('http://localhost:8000/api/status')
      if (resp && resp.status === 200) {
        // backend is responding — proceed to start Aedes
        console.log('[aedes] backend config service is up; starting broker')
        startBroker()
        return
      }
    } catch (e) {
      // ignore
    }
    // wait a bit and retry
    await new Promise((r) => setTimeout(r, 500))
  }
  console.log('[aedes] backend did not become available in time; starting broker anyway')
  startBroker()
}

function startBroker() {
  const tcpServer = net.createServer(aedes.handle)
  tcpServer.listen(TCP_PORT, function () {
    console.log(`[aedes] MQTT TCP broker listening on mqtt://${HOST}:${TCP_PORT}`)
  })

  const httpServer = http.createServer()
  websocket.createServer({server: httpServer}, aedes.handle)
  httpServer.listen(WS_PORT, function () {
    console.log(`[aedes] MQTT over WebSocket broker listening on ws://${HOST}:${WS_PORT}`)
  })

  process.on('SIGINT', () => {
    console.log('[aedes] shutting down')
    tcpServer.close()
    httpServer.close()
    aedes.close(() => process.exit(0))
  })

  // Keep process alive
  console.log('[aedes] broker started (internal)')
}

// Wait for backend config service and then start the broker. If backend doesn't respond within
// 20s, start broker anyway so dev loop can continue.
waitForBackendAndStart(20000)
