const path = require('path');
const fs = require('fs');
const net = require('net');
const {app, BrowserWindow} = require('electron');
const isDev = process.env.NODE_ENV !== 'production';

let mainWindow;
let aedesServer;
let backendProc;
let backendApiProc;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  });

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173');
    mainWindow.webContents.openDevTools();
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'));
  }
}

function readBrokerConfig() {
  try {
    const cfgPath = path.resolve(__dirname, '..', '..', 'config', 'broker.json');
    return JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
  } catch (e) {
    console.warn('[main] Failed to read broker.json, using defaults:', e.message);
    return {
      mode: 'internal',
      host: 'localhost',
      tcp_port: 1883,
      ws_port: 1884,
    };
  }
}

function startAedes() {
  try {
    const broker = readBrokerConfig();
    if ((broker.mode || 'internal') !== 'internal') {
      console.log(`[main] Broker mode is external; not starting local Aedes. Expected broker at mqtt://${broker.host}:${broker.tcp_port} and ws://${broker.host}:${broker.ws_port}`);
      return;
    }
    const aedes = require('aedes')();
    const http = require('http');
    const websocket = require('websocket-stream');
    const host = broker.host || 'localhost';
    const tcpPort = Number(broker.tcp_port || 1883);
    const wsPort = Number(broker.ws_port || 1884);

    const tcpServer = net.createServer(aedes.handle);
    tcpServer.listen(tcpPort, host, () => {
      console.log(`[main] Aedes TCP broker listening on mqtt://${host}:${tcpPort}`);
    });

    const wsServer = http.createServer();
    websocket.createServer({server: wsServer}, aedes.handle);
    wsServer.listen(wsPort, host, () => {
      console.log(`[main] Aedes websocket broker listening on ws://${host}:${wsPort}`);
    });
    aedesServer = {aedes, tcpServer, wsServer};
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

function startBackendApi() {
  const {spawn} = require('child_process');
  const repoRoot = path.resolve(__dirname, '..', '..');
  // run uvicorn to serve backend config/status API
  // do not enable uvicorn --reload when spawning from Electron to avoid
  // duplicate process/reloader behavior which interferes with router subprocess startup.
  const args = ['-m', 'uvicorn', 'backend.config_api:app', '--port', '8000'];
  try {
    backendApiProc = spawn('python3', args, {cwd: repoRoot, env: process.env});
    backendApiProc.stdout.on('data', (d) => console.log(`[backend-api] ${d.toString().trim()}`));
    backendApiProc.stderr.on('data', (d) => console.error(`[backend-api-err] ${d.toString().trim()}`));
    backendApiProc.on('exit', (code, sig) => console.log(`[backend-api] exited code=${code} sig=${sig}`));
  } catch (e) {
    console.error('[main] Failed to spawn backend API:', e);
  }
}

app.whenReady().then(() => {
  // Start local Aedes broker for both backend TCP clients and renderer WS clients.
  startAedes();

  // Optionally start the Python backend so the packaged app contains it.
  // Use a separate process so the router remains decoupled.
  // start the backend API first so the router and Aedes scripts can query config/status
  startBackendApi();
  // then start the main run_router process
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
    if (backendApiProc) backendApiProc.kill();
  } catch (e) {}
  try {
    if (aedesServer && aedesServer.tcpServer) aedesServer.tcpServer.close();
  } catch (e) {}
  try {
    if (aedesServer && aedesServer.wsServer) aedesServer.wsServer.close();
  } catch (e) {}
  try {
    if (aedesServer && aedesServer.aedes) aedesServer.aedes.close();
  } catch (e) {}
});
