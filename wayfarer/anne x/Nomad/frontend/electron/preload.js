const { contextBridge } = require('electron')
const fs = require('fs')
const path = require('path')

// Expose a tiny API to the renderer so packaged Electron apps can read `config/broker.json` from disk.
contextBridge.exposeInMainWorld('electronAPI', {
  getBrokerConfig: async () => {
    try {
      // repo root relative to frontend/electron/preload.js -> ../../config/broker.json
      const cfgPath = path.resolve(__dirname, '..', '..', '..', 'config', 'broker.json')
      const raw = fs.readFileSync(cfgPath, 'utf8')
      return JSON.parse(raw)
    } catch (e) {
      return null
    }
  }
})
// preload: expose a minimal API if needed later
const {contextBridge} = require('electron');

contextBridge.exposeInMainWorld('nomad', {
  // placeholder - renderer will use MQTT directly over WebSocket
  platform: process.platform,
});
