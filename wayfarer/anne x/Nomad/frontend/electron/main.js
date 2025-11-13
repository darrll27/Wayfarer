const path = require('path');
const {app, BrowserWindow} = require('electron');
const isDev = process.env.NODE_ENV !== 'production';

let mainWindow;
let aedesServer;
let backendProc;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
}

function startAedes(wsPort = 1884) {
  try {
    const aedes = require('aedes')();
    const http = require('http');
    const websocket = require('websocket-stream');
    const server = http.createServer();
    websocket.createServer({server: server}, aedes.handle);
    server.listen(wsPort, () => {
      console.log(`[main] Aedes websocket broker listening on ws://localhost:${wsPort}`);
    });
    aedesServer = {aedes, server};
  } catch (e) {
    console.error('[main] Failed to start Aedes broker:', e);
  }
}

function startBackend() {
  const {spawn} = require('child_process');
  // spawn the Python backend run script from repo root
  const repoRoot = path.resolve(__dirname, '..', '..');
  const script = path.join(repoRoot, 'backend', 'mav_router', 'run_router.py');

  try {
    backendProc = spawn('python3', [script], {cwd: repoRoot, env: process.env});

    backendProc.stdout.on('data', (d) => console.log(`[backend] ${d.toString().trim()}`));
    backendProc.stderr.on('data', (d) => console.error(`[backend-err] ${d.toString().trim()}`));
    backendProc.on('exit', (code, sig) => console.log(`[backend] exited code=${code} sig=${sig}`));
  } catch (e) {
    console.error('[main] Failed to spawn backend:', e);
  }
}

app.whenReady().then(() => {
  // Start local Aedes broker for the renderer to connect via MQTT over WS
  startAedes(1884);

  // Optionally start the Python backend so the packaged app contains it.
  // Use a separate process so the router remains decoupled.
  startBackend();

  createWindow();

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  try {
    if (backendProc) backendProc.kill();
  } catch (e) {}
  try {
    if (aedesServer && aedesServer.server) aedesServer.server.close();
  } catch (e) {}
});
