import fs from 'fs';
import path from 'path';
import http from 'http';
import net from 'net';
import express from 'express';
import cors from 'cors';
import bodyParser from 'body-parser';
import aedesFactory from 'aedes';
import { WebSocketServer, createWebSocketStream } from 'ws';

const __dirname = path.dirname(new URL(import.meta.url).pathname);
const ROOT = path.resolve(__dirname, '..', '..');
const CONFIG_DIR = path.join(ROOT, 'config');
const WEB_DIR = path.join(ROOT, 'web');
const WEB_DIST = path.join(WEB_DIR, 'dist');

const brokerConfigPath = path.join(CONFIG_DIR, 'broker.config.json');
const houstonConfigPath = path.join(CONFIG_DIR, 'houston.config.json');

function readJSON(p, fallback) {
  try {
    return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch (e) {
    return fallback;
  }
}

function writeJSON(p, data) {
  fs.writeFileSync(p, JSON.stringify(data, null, 2));
}

const brokerCfg = readJSON(brokerConfigPath, {
  host: "localhost",
  http_port: 4000,
  tcp_port: 1884,
  ws_port: 9002,
  ws_path: '/mqtt',
  allow_anonymous: true,
  users: []
});

const app = express();
app.use(cors({ origin: true, credentials: true }));
app.use(bodyParser.json({ limit: '2mb' }));

// In-memory status
const aedesOptions = {};
if (!brokerCfg.allow_anonymous) {
  aedesOptions.authenticate = (client, username, password, callback) => {
    const users = brokerCfg.users || [];
    const pass = password ? password.toString() : '';
    const ok = users.some(u => u.username === username && u.password === pass);
    const err = ok ? null : new Error('Auth failed');
    callback(err, ok);
  };
}
const aedes = aedesFactory(aedesOptions);

let stats = { clients: 0, messages: 0, subscriptions: 0 };

aedes.on('client', (client) => {
  stats.clients = aedes.connectedClients;
});

aedes.on('clientDisconnect', (client) => {
  stats.clients = aedes.connectedClients;
});

aedes.on('publish', (packet, client) => {
  if (packet && packet.topic) stats.messages++;
});

aedes.on('subscribe', (subs, client) => {
  stats.subscriptions += subs?.length || 0;
});

// TCP broker
const tcpServer = net.createServer(aedes.handle);
tcpServer.listen(brokerCfg.tcp_port, () => {
  console.log(`[Houston] Aedes TCP listening on ${brokerCfg.tcp_port}`);
});

// HTTP + WS broker + API + static
const httpServer = http.createServer(app);
const wss = new WebSocketServer({ server: httpServer, path: brokerCfg.ws_path });
wss.on('connection', (socket) => {
  const stream = createWebSocketStream(socket, { decodeStrings: true });
  aedes.handle(stream);
});

// REST API
app.get('/api/config', (req, res) => {
  res.json(readJSON(houstonConfigPath, { groups: [], topic_prefix: 'wayfarer/v1' }));
});

app.put('/api/config', (req, res) => {
  const cfg = req.body;
  if (!cfg || typeof cfg !== 'object' || !Array.isArray(cfg.groups)) {
    return res.status(400).json({ error: 'Invalid config schema' });
  }
  try {
    writeJSON(houstonConfigPath, cfg);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: 'Failed to write config' });
  }
});

app.get('/api/broker', (req, res) => {
  res.json({
    config: brokerCfg,
    stats: {
      clients: stats.clients,
      messages: stats.messages,
      subscriptions: stats.subscriptions
    }
  });
});

// Serve built UI if present
if (fs.existsSync(WEB_DIST)) {
  app.use(express.static(WEB_DIST));
  app.get('*', (req, res) => {
    res.sendFile(path.join(WEB_DIST, 'index.html'));
  });
}

httpServer.listen(brokerCfg.http_port, () => {
  console.log(`[Houston] HTTP/API listening on ${brokerCfg.http_port} (WS ${brokerCfg.ws_path} @ ${brokerCfg.ws_port || brokerCfg.http_port})`);
});

// Optional standalone WS port (if ws_port differs from http_port)
if (brokerCfg.ws_port && brokerCfg.ws_port !== brokerCfg.http_port) {
  const wsOnlyServer = http.createServer();
  const wss2 = new WebSocketServer({ server: wsOnlyServer, path: brokerCfg.ws_path });
  wss2.on('connection', (socket) => {
    const stream = createWebSocketStream(socket, { decodeStrings: true });
    aedes.handle(stream);
  });
  wsOnlyServer.listen(brokerCfg.ws_port, () => {
    console.log(`[Houston] WS MQTT listening on ${brokerCfg.ws_port}${brokerCfg.ws_path}`);
  });
}
