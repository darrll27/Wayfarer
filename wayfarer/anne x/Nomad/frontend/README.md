NOMAD Frontend

Quick start (dev):

1. Install dependencies

```bash
cd frontend
npm install
```

2. Start dev + Electron (runs Vite and opens Electron window):

```bash
npm start
```

- `npm run dev` runs the Vite dev server (http://localhost:5173).
- `npm run electron:dev` waits for the dev server and opens Electron.

Build for production:

```bash
npm run build
# then package electron app with your preferred packager (electron-builder, electron-forge, etc.)
```

Notes:
- The app uses a canonical backend config (`/config`) and endpoints under `/groups` and `/groups/:name/waypoints`.
- The footer displays: "NOMAD — Nominal Online Multiple Asset Director".

