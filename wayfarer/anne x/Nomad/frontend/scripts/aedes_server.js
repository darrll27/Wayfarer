// Simple Aedes broker runner for local development
// Starts a TCP MQTT listener on 1883 (for Python backend) and a websocket listener on 1884 (for renderer)
const aedes = require('aedes')()
const net = require('net')
const http = require('http')
const websocket = require('websocket-stream')

const TCP_PORT = process.env.AEDES_TCP_PORT || 1883
const WS_PORT = process.env.AEDES_WS_PORT || 1884

const tcpServer = net.createServer(aedes.handle)
tcpServer.listen(TCP_PORT, function () {
  console.log(`[aedes] MQTT TCP broker listening on mqtt://localhost:${TCP_PORT}`)
})

const httpServer = http.createServer()
websocket.createServer({server: httpServer}, aedes.handle)
httpServer.listen(WS_PORT, function () {
  console.log(`[aedes] MQTT over WebSocket broker listening on ws://localhost:${WS_PORT}`)
})

process.on('SIGINT', () => {
  console.log('[aedes] shutting down')
  tcpServer.close()
  httpServer.close()
  aedes.close(() => process.exit(0))
})

// Keep process alive
console.log('[aedes] broker started')
