import React, {useEffect, useState, useRef} from 'react'

// Decide at runtime whether we're in Electron (renderer) or a browser dev server.
// Electron renderer can use the Node mqtt client to connect to tcp://localhost:1883.
// Browser dev (Vite) must use the websocket bridge at ws://localhost:1884.
const isElectron = typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes('Electron') || (typeof window !== 'undefined' && window.process && window.process.versions && window.process.versions.electron)

export default function App() {
  const [connStatus, setConnStatus] = useState('disconnected')
  const [telemetry, setTelemetry] = useState([])
  const [backendStatus, setBackendStatus] = useState(null)
  const [brokerConfig, setBrokerConfig] = useState(null)
  const [brokerMissing, setBrokerMissing] = useState(false)
  const [brokerError, setBrokerError] = useState(null)
  const [page, setPage] = useState('telemetry')

  const clientRef = useRef(null)

  // fetch the centralized broker config. returns object or null
  async function fetchBrokerConfig() {
    try {
      // If running in packaged Electron, prefer the preload API which reads the file from disk
      if (isElectron && window && window.electronAPI && typeof window.electronAPI.getBrokerConfig === 'function') {
        const cfg = await window.electronAPI.getBrokerConfig()
        if (!cfg) {
          setBrokerMissing(true)
          setBrokerError('electron preload: no broker.json found')
          setBrokerConfig(null)
          return null
        }
        setBrokerConfig(cfg)
        setBrokerMissing(false)
        setBrokerError(null)
        return cfg
      }

      const resp = await fetch('/api/config')
      if (!resp.ok) {
        const text = await resp.text()
        const err = `HTTP ${resp.status} ${resp.statusText}: ${text}`
        setBrokerMissing(true)
        setBrokerError(err)
        setBrokerConfig(null)
        console.warn('broker config fetch failed:', err)
        return null
      }
      const json = await resp.json()
      setBrokerConfig(json)
      setBrokerMissing(false)
      setBrokerError(null)
      return json
    } catch (e) {
      setBrokerMissing(true)
      setBrokerError(String(e))
      setBrokerConfig(null)
      console.warn('broker config fetch error', e)
      return null
    }
  }

  // connect using a broker config object
  async function connectWithBroker(broker, mountedRef) {
    let client = null
    try {
      const host = broker.host
      const tcp_port = broker.tcp_port
      const ws_port = broker.ws_port
      const connectUrl = isElectron ? `mqtt://${host}:${tcp_port}` : `ws://${host}:${ws_port}`
      const mqttModule = isElectron ? await import('mqtt') : await import('mqtt/dist/mqtt')
      client = mqttModule.connect(connectUrl)
      clientRef.current = client

      client.on('connect', () => {
        if (!mountedRef.current) return
        setConnStatus('connected')
        client.subscribe('device/+/+/HEARTBEAT/#')
        client.subscribe('device/+/+/RAW')
        client.subscribe('nomad/status')
        client.subscribe('Nomad/config')
      })

      client.on('message', (topic, payload) => {
        const msg = payload.toString()
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
      client.on('error', (e) => {
        console.error('mqtt error', e)
        setBrokerError(String(e))
      })
    } catch (e) {
      console.error('failed to start mqtt client', e)
      setBrokerError(String(e))
    }
    return client
  }

  useEffect(() => {
    let mounted = true
    const mountedRef = { current: true }
    let client = null

    // poll backend status endpoint so we can show whether backend service is up
    let statusInterval = null
    async function pollStatus() {
      try {
        const r = await fetch('/api/status')
        if (!r.ok) return
        const j = await r.json()
        setBackendStatus(j)
      } catch (e) {
        // ignore
      }
    }
    pollStatus()
    statusInterval = setInterval(pollStatus, 3000)

    async function startClient() {
      try {
        const broker = await fetchBrokerConfig()
        if (!broker) {
          setConnStatus('no-broker-config')
          return
        }
        client = await connectWithBroker(broker, { current: mounted })
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
      try {
        if (clientRef.current) clientRef.current.end()
      } catch (e) {
        // ignore
      }
      mountedRef.current = false
      if (statusInterval) clearInterval(statusInterval)
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

  const retryFetchBroker = async () => {
    setBrokerError(null)
    setBrokerMissing(false)
    setConnStatus('reloading-broker-config')
    const b = await fetchBrokerConfig()
    if (b) {
      setConnStatus('connecting')
      try {
        const client = await connectWithBroker(b, { current: true })
        if (client) {
          setConnStatus('connected')
        }
      } catch (e) {
        console.error('connectWithBroker failed', e)
        setBrokerError(String(e))
        setConnStatus('connect-failed')
      }
    } else {
      setConnStatus('no-broker-config')
    }
  }

    return (
    <div style={{fontFamily: 'Inter, system-ui, sans-serif', padding: 12, display: 'flex', flexDirection: 'column', minHeight: '100vh'}}>
      <header style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '12px 16px', borderBottom: '1px solid #e6edf3'}}>
        <div style={{display: 'flex', alignItems: 'center', gap: 12}}>
          <h1 style={{margin: 0}}>Nomad</h1>
          <nav>
            <button onClick={() => setPage('telemetry')} style={{marginRight: 8}}>Telemetry</button>
            <button onClick={() => setPage('waypoints')} style={{marginRight: 8}}>Waypoints</button>
            <button onClick={() => setPage('settings')} style={{marginRight: 8}}>Settings</button>
          </nav>
        </div>
        <div style={{textAlign: 'right'}}>
          <div style={{fontSize: 12, color: '#6b7280'}}>Connection: <strong>{connStatus}</strong></div>
          <div style={{fontSize: 12, color: '#6b7280'}}>{brokerConfig ? `${brokerConfig.host}:${isElectron ? brokerConfig.tcp_port : brokerConfig.ws_port}` : (brokerMissing ? 'no broker config' : 'loading...')}</div>
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

      <div style={{flex: 1}} />

      <footer style={{borderTop: '1px solid #e6edf3', padding: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
        <div style={{fontSize: 12, color: '#6b7280'}}>Backend: {backendStatus ? (backendStatus.ok ? 'online' : 'offline') : 'unknown'}</div>
        <div style={{fontSize: 12, color: '#6b7280'}}>Broker: {brokerConfig ? `${brokerConfig.host}:${isElectron ? brokerConfig.tcp_port : brokerConfig.ws_port}` : (brokerMissing ? 'missing' : 'loading')}</div>
        <div style={{fontSize: 12, color: '#6b7280', textAlign: 'right', maxWidth: '40%'}}>
          {brokerMissing ? (
            <div>
              <div style={{color: '#b91c1c'}}>broker.json missing or incomplete — see <code>config/broker.json</code></div>
              <div style={{marginTop: 6}}>
                <button onClick={retryFetchBroker} style={{padding: '6px 8px', borderRadius: 6}}>Reload broker config</button>
              </div>
            </div>
          ) : brokerError ? (
            <div style={{color: '#b91c1c'}}>Broker error: {brokerError}</div>
          ) : brokerConfig ? (
            <div style={{fontFamily: 'monospace', fontSize: 12, overflowX: 'auto'}}>{JSON.stringify(brokerConfig)}</div>
          ) : (
            <div style={{color: '#94a3b8'}}>config loading...</div>
          )}
        </div>
      </footer>
    </div>
  )
}
