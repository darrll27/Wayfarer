// preload: expose a minimal API if needed later
const {contextBridge} = require('electron');

contextBridge.exposeInMainWorld('nomad', {
  // placeholder - renderer will use MQTT directly over WebSocket
  platform: process.platform,
});
