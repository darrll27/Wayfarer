import React, {useEffect, useState, useRef} from 'react'

// Decide at runtime whether we're in Electron (renderer) or a browser dev server.
// Electron renderer can use the Node mqtt client to connect to tcp://localhost:1883.
// Browser dev (Vite) must use the websocket bridge at ws://localhost:1884.
const isElectron = typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes('Electron') || (typeof window !== 'undefined' && window.process && window.process.versions && window.process.versions.electron)

export default function App() {
  const [connStatus, setConnStatus] = useState('disconnected')
  const [telemetry, setTelemetry] = useState([])
  const [backendStatus, setBackendStatus] = useState(null)

  const clientRef = useRef(null)

  useEffect(() => {
    let mounted = true
    let client = null

    async function startClient() {
      try {
        const connectUrl = isElectron ? 'mqtt://localhost:1883' : 'ws://localhost:1884'
        // dynamic import to avoid bundling node-only mqtt into browser build
        const mqttModule = isElectron ? await import('mqtt') : await import('mqtt/dist/mqtt')
        client = mqttModule.connect(connectUrl)
        clientRef.current = client

        client.on('connect', () => {
          if (!mounted) return
          setConnStatus('connected')
          // subscribe to a few useful topics
          client.subscribe('device/+/+/HEARTBEAT/#')
          client.subscribe('device/+/+/RAW')
          client.subscribe('nomad/status')
          client.subscribe('Nomad/config')
        })

        client.on('message', (topic, payload) => {
          const msg = payload.toString()
          // if this is a backend status message, parse and store separately
          if (topic === 'nomad/status') {
            try {
              const obj = JSON.parse(msg)
              setBackendStatus(obj)
            } catch (e) {
              setBackendStatus({raw: msg})
            }
          }
          setTelemetry((s) => [{topic, msg, ts: Date.now()}].concat(s).slice(0, 50))
        })

        client.on('reconnect', () => setConnStatus('reconnecting'))
        client.on('close', () => setConnStatus('disconnected'))
        client.on('error', (e) => console.error('mqtt error', e))
      } catch (e) {
        console.error('failed to start mqtt client', e)
      }
    }

    startClient()

    return () => {
      mounted = false
      try {
        if (clientRef.current) clientRef.current.end()
      } catch (e) {
        // ignore
      }
    }
  }, [])

  const sendLoadWaypointsDemo = () => {
    // publish a simple load_waypoints command that will be validated by the backend
    const payload = {
      action: 'load_waypoints',
      filename: `demo-${Date.now()}.yaml`,
      waypoints: [
        {lat: 37.7749, lon: -122.4194, alt: 30},
        {lat: 37.7750, lon: -122.4180, alt: 35},
      ],
    }
    if (clientRef.current) {
      clientRef.current.publish('command/1/1/load_waypoints', JSON.stringify(payload))
    }
  }

    return (
    <div style={{fontFamily: 'Inter, system-ui, sans-serif', padding: 24}}>
      <header style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <h1>Nomad</h1>
        <div>
          <strong>Broker:</strong> Aedes (ws://localhost:1884)
          <br />
          <strong>Connection:</strong> {connStatus}
        </div>
      </header>

      <section style={{marginTop: 16}}>
        <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
          <h2>Live telemetry (most recent)</h2>
          <div style={{textAlign: 'right'}}>
            <div style={{fontSize: 12, color: '#94a3b8'}}>Backend status</div>
            <div style={{fontFamily: 'monospace', fontSize: 13}}>{backendStatus ? JSON.stringify(backendStatus) : 'offline'}</div>
          </div>
        </div>

        <div style={{marginTop: 12, display: 'flex', gap: 12}}>
          <button onClick={sendLoadWaypointsDemo} style={{padding: '8px 12px', borderRadius: 6}}>Send demo waypoints (validate)</button>
          <div style={{fontSize: 12, color: '#94a3b8'}}>Config: <span style={{fontFamily: 'monospace'}}>{/* show latest config if any */}</span></div>
        </div>
        <div style={{maxHeight: 400, overflow: 'auto', background: '#0f172a', color: '#cbd5e1', padding: 8, borderRadius: 6}}>
          {telemetry.length === 0 ? (
            <div style={{opacity: 0.6}}>No telemetry received yet.</div>
          ) : (
            telemetry.map((t, i) => (
              <div key={i} style={{padding: '6px 8px', borderBottom: '1px solid rgba(255,255,255,0.03)'}}>
                <div style={{fontSize: 12, color: '#94a3b8'}}>{new Date(t.ts).toLocaleTimeString()}</div>
                <div style={{fontFamily: 'monospace', fontSize: 13}}>{t.topic}: {t.msg}</div>
              </div>
            ))
          )}
        </div>
      </section>

      <footer style={{marginTop: 24, color: '#6b7280'}}>
        Small demo UI — subscribes to `device/...` and `nomad/status` topics. Customize to match the project's MQTT topic schema.
      </footer>
    </div>
  )
}
