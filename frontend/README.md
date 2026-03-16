Nomad Electron frontend (dev scaffold)

This folder contains a minimal Electron + Vite + React scaffold that starts an in-process Aedes MQTT broker
(listening on websocket port 1884) and connects the renderer to it via MQTT over WebSocket.

Quick start (from repo root):

1. Install node deps

```bash
cd frontend
npm install
```

2. Start dev mode (starts Vite and Electron)

```bash
cd frontend
npm run dev
```

Notes
- The Electron main process will also attempt to spawn the Python backend using the script `backend/mav_router/run_router.py`.
  Ensure Python and required Python deps are available in your environment if you want the backend to run.
- For production packaging, you'll want to bundle the Python backend into the app and adjust paths; this scaffold focuses on dev workflow.

Design choices
- Frontend connects to a local Aedes broker over WebSocket so the UI can subscribe to MQTT topics without an external broker.
- The Python backend remains decoupled (it publishes to an external/local MQTT broker). The Electron main spawns it during dev so a single `npm run dev` can bring up the whole stack if Python deps are installed.

