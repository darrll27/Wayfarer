const { contextBridge } = require('electron')
const fs = require('fs')
const path = require('path')

contextBridge.exposeInMainWorld('electronAPI', {
  getBrokerConfig: async () => {
    try {
      // repo root relative to frontend/electron/preload.js -> ../../config/broker.json
      const cfgPath = path.resolve(__dirname, '..', '..', 'config', 'broker.json')
      const raw = fs.readFileSync(cfgPath, 'utf8')
      return JSON.parse(raw)
    } catch (e) {
      return null
    }
  }
})

contextBridge.exposeInMainWorld('nomad', {
  platform: process.platform
})
