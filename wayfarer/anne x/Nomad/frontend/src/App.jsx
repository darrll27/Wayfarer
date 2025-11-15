import React, {useEffect, useState, useRef} from 'react'

// Decide at runtime whether we're in Electron (renderer) or a browser dev server.
// Electron renderer can use the Node mqtt client to connect to tcp://localhost:1883.
// Browser dev (Vite) must use the websocket bridge at ws://localhost:1884.
const isElectron = typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes('Electron') || (typeof window !== 'undefined' && window.process && window.process.versions && window.process.versions.electron)

export default function App() {
  const [connStatus, setConnStatus] = useState('disconnected')
  const [telemetry, setTelemetry] = useState([])
  const [backendStatus, setBackendStatus] = useState(null)
  const [toasts, setToasts] = useState([])
  const [brokerConfig, setBrokerConfig] = useState(null)
  const [brokerMissing, setBrokerMissing] = useState(false)
  const [brokerError, setBrokerError] = useState(null)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [page, setPage] = useState('telemetry')
  const [wpFiles, setWpFiles] = useState([])
  const [selectedMission, setSelectedMission] = useState('')
  const [downloadedMissions, setDownloadedMissions] = useState([])
  const [downloadSysid, setDownloadSysid] = useState(1)
  const [downloadCompid, setDownloadCompid] = useState(1)

  const clientRef = useRef(null)

  // fetch broker status when config is available
  useEffect(() => {
    if (brokerConfig) {
      fetch('/api/status').then(r => r.ok ? r.json() : null).then(setBrokerStatus).catch(() => setBrokerStatus(null))
    } else {
      setBrokerStatus(null)
    }
  }, [brokerConfig])

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
        client.subscribe('Nomad/waypoints/#')
        client.subscribe('Nomad/missions/downloaded/+')
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
        // show waypoint validation toasts for Nomad/waypoints/.../validation
        if (topic.startsWith('Nomad/waypoints/') && topic.endsWith('/validation')) {
          try {
            const obj = JSON.parse(msg)
            addToast({title: 'Waypoint validation', body: `${obj.filename}: ${obj.valid ? 'OK' : 'FAIL'} (${obj.count} pts)`})
          } catch (e) {
            addToast({title: 'Waypoint validation', body: msg})
          }
        }
        // handle downloaded missions
        if (topic.startsWith('Nomad/missions/downloaded/')) {
          try {
            const obj = JSON.parse(msg)
            setDownloadedMissions((prev) => [obj].concat(prev).slice(0, 10)) // keep last 10
            addToast({title: 'Mission downloaded', body: `From sysid ${obj.sysid}: ${obj.count} waypoints`})
          } catch (e) {
            addToast({title: 'Mission download', body: msg})
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
          client.subscribe('Nomad/waypoints/#')
          client.subscribe('Nomad/missions/downloaded/+')
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
          // show waypoint validation toasts for Nomad/waypoints/.../validation
          if (topic.startsWith('Nomad/waypoints/') && topic.endsWith('/validation')) {
            try {
              const obj = JSON.parse(msg)
              addToast({title: 'Waypoint validation', body: `${obj.filename}: ${obj.valid ? 'OK' : 'FAIL'} (${obj.count} pts)`})
            } catch (e) {
              addToast({title: 'Waypoint validation', body: msg})
            }
          }
          // handle downloaded missions
          if (topic.startsWith('Nomad/missions/downloaded/')) {
            try {
              const obj = JSON.parse(msg)
              setDownloadedMissions((prev) => [obj].concat(prev).slice(0, 10)) // keep last 10
              addToast({title: 'Mission downloaded', body: `From sysid ${obj.sysid}: ${obj.count} waypoints`})
            } catch (e) {
              addToast({title: 'Mission download', body: msg})
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

  // Waypoint manager state & helpers
  const [flightPaths, setFlightPaths] = useState({}) // sysid -> array of [lat, lon] positions
  const [showFlightPaths, setShowFlightPaths] = useState(true)
  const [selectedFile, setSelectedFile] = useState(null)
  const [sendSysid, setSendSysid] = useState(1)
  const [sendCompid, setSendCompid] = useState(1)
  const mapRef = useRef(null)
  const mapLayersRef = useRef([])

  async function loadWaypointFiles() {
    try {
      const r = await fetch('/api/waypoints')
      if (!r.ok) return
      const j = await r.json()
      const files = j.files || []
      setWpFiles(files)
      
      // Set default mission to first available mission if none selected
      if (files.length > 0 && !selectedMission) {
        const missions = Object.keys(groupWaypointFiles(files))
        if (missions.length > 0) {
          setSelectedMission(missions[0])
        }
      }
    } catch (e) {
      console.error('failed to load waypoint files', e)
    }
  }

  // Group waypoint files by mission and group
  function groupWaypointFiles(files) {
    const grouped = {}
    files.forEach(f => {
      const mission = f.mission_name || 'unknown'
      const group = f.group_name || 'unknown'
      if (!grouped[mission]) grouped[mission] = {}
      if (!grouped[mission][group]) grouped[mission][group] = []
      grouped[mission][group].push(f)
    })
    return grouped
  }

  // Extract flight paths from telemetry data
  const getFlightPaths = () => {
    const paths = {}
    const positions = {}
    
    // Collect all GPS positions
    telemetry.forEach(({topic, msg}) => {
      try {
        const latMatch = topic.match(/^device\/(\d+)\/\d+\/GLOBAL_POSITION_INT\/lat$/)
        const lonMatch = topic.match(/^device\/(\d+)\/\d+\/GLOBAL_POSITION_INT\/lon$/)
        
        if (latMatch) {
          const sysid = latMatch[1]
          if (!positions[sysid]) positions[sysid] = {}
          positions[sysid].lat = JSON.parse(msg).lat / 1e7
        } else if (lonMatch) {
          const sysid = lonMatch[1]
          if (!positions[sysid]) positions[sysid] = {}
          positions[sysid].lon = JSON.parse(msg).lon / 1e7
        }
      } catch (e) {
        // ignore parse errors
      }
    })
    
    // Convert to path arrays
    Object.entries(positions).forEach(([sysid, pos]) => {
      if (pos.lat !== undefined && pos.lon !== undefined) {
        if (!paths[sysid]) paths[sysid] = []
        paths[sysid].push([pos.lat, pos.lon])
        // Keep only last 50 positions per drone
        if (paths[sysid].length > 50) paths[sysid].shift()
      }
    })
    
    return paths
  }

  // Update flight paths on map
  const updateFlightPathsOnMap = () => {
    if (!window.L || !mapRef.current || !showFlightPaths) return
    
    // Clear existing flight path layers
    if (mapLayersRef.current) {
      mapLayersRef.current.forEach(l => { 
        if (l.options && l.options.flightPath) {
          try { l.remove() } catch (e){} 
        }
      })
      mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && l.options.flightPath))
    }
    
    const paths = getFlightPaths()
    Object.entries(paths).forEach(([sysid, positions]) => {
      if (positions.length > 1) {
        // Create polyline with arrows
        const polyline = window.L.polyline(positions, {
          color: '#ff4444',
          weight: 3,
          flightPath: true
        }).addTo(mapRef.current)
        
        // Add directional arrows
        for (let i = 0; i < positions.length - 1; i++) {
          const start = positions[i]
          const end = positions[i + 1]
          const angle = Math.atan2(end[1] - start[1], end[0] - start[0]) * 180 / Math.PI
          
          // Create arrow marker
          const arrow = window.L.marker([(start[0] + end[0]) / 2, (start[1] + end[1]) / 2], {
            icon: window.L.divIcon({
              html: '▶',
              className: 'flight-arrow',
              iconSize: [16, 16],
              iconAnchor: [8, 8]
            }),
            rotationAngle: angle,
            flightPath: true
          }).addTo(mapRef.current)
          
          mapLayersRef.current.push(arrow)
        }
        
        mapLayersRef.current.push(polyline)
      }
    })
  }

  // Update downloaded missions on map
  const updateDownloadedMissionsOnMap = () => {
    if (!window.L || !mapRef.current) return
    
    // Clear existing downloaded mission layers
    if (mapLayersRef.current) {
      mapLayersRef.current.forEach(l => { 
        if (l.options && l.options.downloadedMission) {
          try { l.remove() } catch (e){} 
        }
      })
      mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && l.options.downloadedMission))
    }
    
    // Plot downloaded missions
    downloadedMissions.forEach((mission, missionIdx) => {
      if (mission.mission && mission.mission.length > 0) {
        // Convert mission waypoints to lat/lng
        const latlngs = mission.mission.map(wp => [wp.y / 1e7, wp.x / 1e7]) // MAVLink uses x=east, y=north
        
        // Create polyline for downloaded mission path
        const polyline = window.L.polyline(latlngs, {
          color: '#ff6600',
          weight: 3,
          opacity: 0.8,
          downloadedMission: true
        }).addTo(mapRef.current)
        
        // Add markers for downloaded waypoints
        mission.mission.forEach((wp, wpIdx) => {
          const marker = window.L.circleMarker([wp.y / 1e7, wp.x / 1e7], {
            radius: 7,
            color: '#ff6600',
            fillColor: '#ff6600',
            fillOpacity: 0.7,
            downloadedMission: true
          }).addTo(mapRef.current)
          
          marker.bindTooltip(`${mission.sysid}-${wpIdx + 1}<br/>Sysid ${mission.sysid}<br/>${wp.command || 'waypoint'}`, {permanent: false})
          mapLayersRef.current.push(marker)
        })
        
        mapLayersRef.current.push(polyline)
      }
    })
  }

  async function drawFileOnMap(filename) {
    if (!window.L || !mapRef.current) return
    try {
      const r = await fetch(`/api/waypoints/${filename}`)
      if (!r.ok) return
      const j = await r.json()
      const w = j.waypoints || []
      // clear previous planned waypoint layers only
      if (mapLayersRef.current) {
        mapLayersRef.current.forEach(l => { 
          if (l.options && l.options.plannedWaypoint) {
            try { l.remove() } catch (e){} 
          }
        })
        mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && l.options.plannedWaypoint))
      }
      const latlngs = w.map(p => [p.lat, p.lon])
      if (latlngs.length === 0) return
      const poly = window.L.polyline(latlngs, {color: '#ff0000', plannedWaypoint: true}).addTo(mapRef.current)
      mapLayersRef.current.push(poly)
      // add markers for planned waypoints
      w.forEach((pt, i) => {
        const sysidMatch = filename.match(/^(\d+)_/);
        const sysid = sysidMatch ? parseInt(sysidMatch[1]) : '?';
        const m = window.L.circleMarker([pt.lat, pt.lon], {radius: 3, color: '#0b6', plannedWaypoint: true}).addTo(mapRef.current)
        m.bindTooltip(`${sysid}-${i + 1}<br/>${filename}<br/>${pt.action || 'waypoint'}`, {permanent: false})
        mapLayersRef.current.push(m)
      })
      mapRef.current.fitBounds(poly.getBounds().pad(0.4))
    } catch (e) {
      console.error('drawFileOnMap failed', e)
    }
  }

  // Toast helpers
  function addToast(t) {
    const id = Date.now() + Math.random()
    const entry = {...t, id}
    setToasts((s) => [entry].concat(s).slice(0, 6))
    // auto-remove after 6s
    setTimeout(() => {
      setToasts((s) => s.filter(x => x.id !== id))
    }, 6000)
  }

  async function sendToDrone(payload) {
    try {
      const r = await fetch('/api/waypoints/send', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      const j = await r.json()
      addToast({title: 'Send result', body: JSON.stringify(j)})
    } catch (e) {
      console.error('sendToDrone failed', e)
      addToast({title: 'Send failed', body: String(e)})
    }
  }

  async function downloadMissionFromDrone(payload) {
    try {
      const r = await fetch('/api/waypoints/download', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)})
      const j = await r.json()
      addToast({title: 'Download initiated', body: JSON.stringify(j)})
    } catch (e) {
      console.error('downloadMissionFromDrone failed', e)
      addToast({title: 'Download failed', body: String(e)})
    }
  }

  async function downloadFromAllDrones() {
    // Download missions from drones with sysid 1-6 (typical demo setup)
    for (let sysid = 1; sysid <= 6; sysid++) {
      try {
        await downloadMissionFromDrone({sysid, compid: 1})
        // Small delay between requests
        await new Promise(resolve => setTimeout(resolve, 100))
      } catch (e) {
        console.error(`Failed to download from sysid ${sysid}:`, e)
      }
    }
    addToast({title: 'Bulk download initiated', body: 'Requested downloads from sysid 1-6'})
  }

  async function sendToDronePrompt(filename) {
    const sys = Number(prompt('Target sysid (e.g. 1)')) || 1
    const comp = Number(prompt('Target compid (e.g. 1)')) || 1
    await sendToDrone({sysid: sys, compid: comp, filename})
  }

  // initialize map when Waypoints page is opened
  useEffect(() => {
    if (page !== 'waypoints') {
      // Clean up map when leaving waypoints page
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
        mapLayersRef.current = []
      }
      return
    }
    // ensure leaflet is available
    const setup = () => {
      if (!window.L) {
        // leaflet not loaded yet
        setTimeout(setup, 200)
        return
      }
      if (mapRef.current) {
        // Check if map is still valid
        try {
          mapRef.current.getCenter()
          return // map already exists and is valid
        } catch (e) {
          // map is invalid, clean up
          mapRef.current = null
          mapLayersRef.current = []
        }
      }
      
      // Check if map container exists
      const mapContainer = document.getElementById('map')
      if (!mapContainer) {
        setTimeout(setup, 200)
        return
      }
      
      mapRef.current = window.L.map('map', {zoomControl: true}).setView([37.4680, -122.0870], 15)
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(mapRef.current)
      
      // Add legend control
      const legend = window.L.control({position: 'bottomright'})
      legend.onAdd = function (map) {
        const div = window.L.DomUtil.create('div', 'info legend')
        div.style.backgroundColor = 'white'
        div.style.padding = '8px'
        div.style.borderRadius = '4px'
        div.style.border = '1px solid #ccc'
        div.innerHTML = `
          <div style="font-weight: bold; margin-bottom: 4px;">Map Legend</div>
          <div style="display: flex; align-items: center; margin-bottom: 2px;">
            <div style="width: 10px; height: 10px; border-radius: 50%; background-color: #0b6; margin-right: 8px;"></div>
            <span>Waypoint (YAML)</span>
          </div>
          <div style="display: flex; align-items: center;">
            <div style="width: 8px; height: 8px; border-radius: 50%; background-color: #ff6600; margin-right: 8px;"></div>
            <span>Flightpath(onboard)</span>
          </div>
        `
        return div
      }
      legend.addTo(mapRef.current)
      
      loadWaypointFiles()
    }
    setup()
  }, [page])

  // Update downloaded missions when telemetry or data changes
  useEffect(() => {
    if (page === 'waypoints' && mapRef.current) {
      updateDownloadedMissionsOnMap()
    }
  }, [telemetry, showFlightPaths, downloadedMissions, page])

  // Settings: upload / paste waypoint YAML
  async function uploadRawWaypoint(filename, raw) {
    try {
      const r = await fetch('/api/waypoints/upload_raw', {method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({filename, raw})})
      const j = await r.json()
      if (!r.ok) {
        addToast({title: 'Upload failed', body: JSON.stringify(j)})
        return
      }
      addToast({title: 'Upload result', body: JSON.stringify(j)})
      await loadWaypointFiles()
    } catch (e) {
      console.error('uploadRawWaypoint failed', e)
      addToast({title: 'Upload error', body: String(e)})
    }
  }

  function handleFileInput(e) {
    const f = e.target.files && e.target.files[0]
    if (!f) return
    const reader = new FileReader()
    reader.onload = async (ev) => {
      const text = ev.target.result
      const filename = f.name
      await uploadRawWaypoint(filename, text)
    }
    reader.readAsText(f)
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
            <div style={{fontSize: 12, color: '#94a3b8'}}>Broker status</div>
            <div style={{fontFamily: 'monospace', fontSize: 13}}>{brokerStatus ? JSON.stringify(brokerStatus) : 'unknown'}</div>
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

      {page === 'waypoints' ? (
        <section style={{marginTop: 16}}>
          <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center'}}>
            <h2>Waypoint Manager</h2>
            <div>
              <button onClick={async () => { try { await fetch('/api/waypoints/demo', {method: 'POST'}); await loadWaypointFiles() } catch (e) { console.error(e) } }} style={{padding: '6px 8px', marginRight: 8}}>Create demo waypoints (6 drones)</button>
              <button onClick={loadWaypointFiles} style={{padding: '6px 8px'}}>Refresh</button>
            </div>
          </div>

          <div style={{display: 'flex', gap: 12, marginTop: 12}}>
            <div style={{flex: 1}}>
              <div id="map" style={{height: 480, borderRadius: 8, overflow: 'hidden', border: '1px solid #e6edf3'}} />
            </div>
            <div style={{width: 360}}>
              <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8}}>
                <h3 style={{margin: 0}}>Map Controls</h3>
              </div>
              <div style={{background: '#f8fafc', padding: 8, borderRadius: 6, marginBottom: 12}}>
                <label style={{display: 'flex', alignItems: 'center', fontSize: 13}}>
                  <input 
                    type="checkbox" 
                    checked={showFlightPaths} 
                    onChange={(e) => setShowFlightPaths(e.target.checked)} 
                    style={{marginRight: 8}}
                  />
                  Show Flightpath(onboard)
                </label>
                <div style={{marginTop: 8}}>
                  <button onClick={async () => {
                    // Clear existing layers
                    if (mapLayersRef.current) {
                      mapLayersRef.current.forEach(l => { 
                        if (l.options && (l.options.downloadedMission || l.options.plannedWaypoint)) {
                          try { l.remove() } catch (e){} 
                        }
                      })
                      mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && (l.options.downloadedMission || l.options.plannedWaypoint)))
                    }
                    
                    // Filter files by selected mission if one is selected
                    const filesToShow = selectedMission 
                      ? wpFiles.filter(f => f.mission_name === selectedMission)
                      : wpFiles
                    
                    // Show planned waypoints
                    for (const f of filesToShow) {
                      if (f.valid) {
                        try {
                          const r = await fetch(`/api/waypoints/${f.filename}`)
                          if (r.ok) {
                            const j = await r.json()
                            const w = j.waypoints || []
                            const latlngs = w.map(p => [p.lat, p.lon])
                            if (latlngs.length > 0) {
                              const poly = window.L.polyline(latlngs, {color: '#ff0000', plannedWaypoint: true}).addTo(mapRef.current)
                              mapLayersRef.current.push(poly)
                              w.forEach((pt, i) => {
                                const sysidMatch = f.filename.match(/^(\d+)_/);
                                const sysid = sysidMatch ? parseInt(sysidMatch[1]) : '?';
                                const m = window.L.circleMarker([pt.lat, pt.lon], {radius: 3, color: '#0b6', plannedWaypoint: true}).addTo(mapRef.current)
                                m.bindTooltip(`${sysid}-${i + 1}<br/>${f.filename}<br/>${pt.action || 'waypoint'}`, {permanent: false})
                                mapLayersRef.current.push(m)
                              })
                            }
                          }
                        } catch (e) {
                          console.error('Failed to load waypoints for', f.filename, e)
                        }
                      }
                    }
                    
                    // Show downloaded missions (filter by mission if selected)
                    const missionsToShow = selectedMission
                      ? downloadedMissions // For now, show all downloaded missions since we don't have mission_name in downloaded data
                      : downloadedMissions
                    
                    missionsToShow.forEach((mission) => {
                      if (mission.mission && mission.mission.length > 0) {
                        const latlngs = mission.mission.map(wp => [wp.y / 1e7, wp.x / 1e7])
                        const polyline = window.L.polyline(latlngs, {
                          color: '#ff6600',
                          weight: 3,
                          opacity: 0.8,
                          downloadedMission: true
                        }).addTo(mapRef.current)
                        
                        mission.mission.forEach((wp, wpIdx) => {
                          const marker = window.L.circleMarker([wp.y / 1e7, wp.x / 1e7], {
                            radius: 7,
                            color: '#ff6600',
                            fillColor: '#ff6600',
                            fillOpacity: 0.7,
                            downloadedMission: true
                          }).addTo(mapRef.current)
                          marker.bindTooltip(`${mission.sysid}-${wpIdx + 1}<br/>Sysid ${mission.sysid}<br/>${wp.command || 'waypoint'}`, {permanent: false})
                          mapLayersRef.current.push(marker)
                        })
                        mapLayersRef.current.push(polyline)
                      }
                    })
                    
                    // Fit bounds to show everything
                    const allBounds = []
                    mapLayersRef.current.forEach(layer => {
                      if (layer.getBounds) {
                        allBounds.push(layer.getBounds())
                      }
                    })
                    if (allBounds.length > 0) {
                      const combinedBounds = allBounds.reduce((acc, bounds) => acc.extend(bounds))
                      mapRef.current.fitBounds(combinedBounds.pad(0.1))
                    }
                  }} style={{padding: '6px 12px', fontSize: 12}}>Show All{selectedMission ? ` (${selectedMission})` : ''}</button>
                </div>
                
                {/* Debug Status Window */}
                <div style={{background: '#1f2937', padding: 8, borderRadius: 6, marginBottom: 12, border: '1px solid #374151'}}>
                  <div style={{fontWeight: 700, fontSize: 14, color: '#f3f4f6', marginBottom: 8}}>
                    Onboard Responses
                  </div>
                  <div style={{maxHeight: 200, overflow: 'auto', background: '#111827', padding: 8, borderRadius: 6}}>
                    {downloadedMissions.length === 0 ? (
                      <div style={{opacity: 0.6, color: '#9ca3af'}}>No drones have responded with onboard waypoints yet.</div>
                    ) : (
                      downloadedMissions.map((mission, idx) => (
                        <div key={idx} style={{padding: 6, borderBottom: '1px solid rgba(255,255,255,0.1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginLeft: 8}}>
                          <div>
                            <div style={{fontWeight: 500, color: '#f3f4f6'}}>Sysid {mission.sysid}</div>
                            <div style={{fontSize: 11, color: '#9ca3af'}}>count: {mission.count} waypoints</div>
                          </div>
                          <div>
                            <button onClick={() => {
                              // Clear existing layers
                              if (mapLayersRef.current) {
                                mapLayersRef.current.forEach(l => { 
                                  if (l.options && l.options.downloadedMission) {
                                    try { l.remove() } catch (e){} 
                                  }
                                })
                                mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && l.options.downloadedMission))
                              }
                              
                              // Show this downloaded mission
                              if (mission.mission && mission.mission.length > 0) {
                                const latlngs = mission.mission.map(wp => [wp.y / 1e7, wp.x / 1e7])
                                const polyline = window.L.polyline(latlngs, {
                                  color: '#ff6600',
                                  weight: 3,
                                  opacity: 0.8,
                                  downloadedMission: true
                                }).addTo(mapRef.current)
                                
                                mission.mission.forEach((wp, wpIdx) => {
                                  const marker = window.L.circleMarker([wp.y / 1e7, wp.x / 1e7], {
                                    radius: 7,
                                    color: '#ff6600',
                                    fillColor: '#ff6600',
                                    fillOpacity: 0.7,
                                    downloadedMission: true
                                  }).addTo(mapRef.current)
                                  marker.bindTooltip(`${mission.sysid}-${wpIdx + 1}<br/>Sysid ${mission.sysid}<br/>${wp.command || 'waypoint'}`, {permanent: false})
                                  mapLayersRef.current.push(marker)
                                })
                                mapLayersRef.current.push(polyline)
                                
                                // Fit bounds
                                const bounds = window.L.latLngBounds(latlngs)
                                mapRef.current.fitBounds(bounds.pad(0.1))
                              }
                            }} style={{fontSize: 11, padding: '4px 6px', backgroundColor: '#374151', color: '#f3f4f6', border: '1px solid #4b5563'}}>Show</button>
                          </div>
                        </div>
                      ))
                    )}
                  </div>
                </div>
              </div>
              <h3>Waypoint files</h3>
              <div style={{marginBottom: 12}}>
                <label style={{fontSize: 13, fontWeight: 600, color: '#374151', marginBottom: 4, display: 'block'}}>Select Mission:</label>
                <select 
                  value={selectedMission} 
                  onChange={(e) => setSelectedMission(e.target.value)}
                  style={{width: '100%', padding: '6px 8px', borderRadius: 4, border: '1px solid #d1d5db'}}
                >
                  {Object.keys(groupWaypointFiles(wpFiles)).map((mission) => (
                    <option key={mission} value={mission}>{mission}</option>
                  ))}
                  <option value="">-- All Missions --</option>
                </select>
              </div>
              <div style={{maxHeight: 280, overflow: 'auto', background: '#f8fafc', padding: 8, borderRadius: 6}}>
                {wpFiles.length === 0 ? (
                  <div style={{opacity: 0.6}}>No waypoint files. Create demo files or upload from Settings.</div>
                ) : (
                  Object.entries(groupWaypointFiles(wpFiles))
                    .filter(([mission]) => !selectedMission || mission === selectedMission)
                    .map(([mission, groups]) => (
                    <div key={mission} style={{marginBottom: 16}}>
                      <div style={{fontWeight: 700, fontSize: 14, color: '#1e293b', marginBottom: 8}}>
                        Mission: {mission}
                      </div>
                      {Object.entries(groups).map(([group, files]) => (
                        <div key={group} style={{marginLeft: 12, marginBottom: 8}}>
                          <div style={{fontWeight: 600, fontSize: 13, color: '#475569', marginBottom: 4}}>
                            Group: {group}
                          </div>
                          {files.map((f) => (
                            <div key={f.filename} style={{padding: 6, borderBottom: '1px solid rgba(0,0,0,0.06)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginLeft: 8}}>
                              <div>
                                <div style={{fontWeight: 500}}>{f.filename}</div>
                                <div style={{fontSize: 11, color: '#64748b'}}>count: {f.count} valid: {String(f.valid)}</div>
                              </div>
                              <div>
                                <button onClick={async () => { 
                                  setSelectedFile(f.filename); 
                                  await drawFileOnMap(f.filename);
                                  // Also show downloaded missions for this sysid if available
                                  const sysidMatch = f.filename.match(/^(\d+)_/);
                                  if (sysidMatch) {
                                    const sysid = parseInt(sysidMatch[1]);
                                    // Filter downloaded missions for this sysid and show them
                                    const sysidMissions = downloadedMissions.filter(m => m.sysid === sysid);
                                    if (sysidMissions.length > 0) {
                                      // Clear existing layers first
                                      if (mapLayersRef.current) {
                                        mapLayersRef.current.forEach(l => { 
                                          if (l.options && (l.options.downloadedMission || l.options.plannedWaypoint)) {
                                            try { l.remove() } catch (e){} 
                                          }
                                        })
                                        mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && (l.options.downloadedMission || l.options.plannedWaypoint)))
                                      }
                                      // Re-draw planned waypoints
                                      await drawFileOnMap(f.filename);
                                      // Add downloaded missions for this sysid
                                      sysidMissions.forEach((mission) => {
                                        if (mission.mission && mission.mission.length > 0) {
                                          const latlngs = mission.mission.map(wp => [wp.y / 1e7, wp.x / 1e7]);
                                          const polyline = window.L.polyline(latlngs, {
                                            color: '#ff6600',
                                            weight: 3,
                                            opacity: 0.8,
                                            downloadedMission: true
                                          }).addTo(mapRef.current);
                                          
                                          mission.mission.forEach((wp, wpIdx) => {
                                            const marker = window.L.circleMarker([wp.y / 1e7, wp.x / 1e7], {
                                              radius: 7,
                                              color: '#ff6600',
                                              fillColor: '#ff6600',
                                              fillOpacity: 0.7,
                                              downloadedMission: true
                                            }).addTo(mapRef.current);
                                            marker.bindTooltip(`${mission.sysid}-${wpIdx + 1}<br/>Sysid ${mission.sysid}<br/>${wp.command || 'waypoint'}`, {permanent: false})
                                            mapLayersRef.current.push(marker)
                                          })
                                          mapLayersRef.current.push(polyline)
                                        }
                                      })
                                    }
                                  }
                                }} style={{marginRight: 4, fontSize: 11, padding: '4px 6px'}}>Show</button>
                                <button onClick={async () => { await sendToDronePrompt(f.filename) }} style={{fontSize: 11, padding: '4px 6px'}}>Send</button>
                              </div>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  ))
                )}
              </div>

              <div style={{marginTop: 12}}>
                <h4>Manual send</h4>
                <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
                  <label>sysid</label>
                  <input type="number" value={sendSysid} onChange={(e) => setSendSysid(Number(e.target.value))} style={{width: 64}} />
                  <label>compid</label>
                  <input type="number" value={sendCompid} onChange={(e) => setSendCompid(Number(e.target.value))} style={{width: 64}} />
                </div>
                <div style={{marginTop: 8}}>
                  <select value={selectedFile || ''} onChange={(e) => setSelectedFile(e.target.value)} style={{width: '100%'}}>
                    <option value="">-- select file --</option>
                    {Object.entries(groupWaypointFiles(wpFiles)).map(([mission, groups]) =>
                      Object.entries(groups).map(([group, files]) =>
                        files.map(f => (
                          <option key={f.filename} value={f.filename}>
                            {mission}/{group}/{f.filename}
                          </option>
                        ))
                      )
                    )}
                  </select>
                  <div style={{marginTop: 8}}>
                    <button onClick={async () => { if (selectedFile) await sendToDrone({sysid: sendSysid, compid: sendCompid, filename: selectedFile}) }} style={{padding: '8px 12px'}}>Send to Drone</button>
                  </div>
                </div>
              </div>

              <div style={{marginTop: 12}}>
                <h4>Download Mission</h4>
                <div style={{display: 'flex', gap: 8, alignItems: 'center'}}>
                  <label>sysid</label>
                  <input type="number" value={downloadSysid || 1} onChange={(e) => setDownloadSysid(Number(e.target.value))} style={{width: 64}} />
                  <label>compid</label>
                  <input type="number" value={downloadCompid || 1} onChange={(e) => setDownloadCompid(Number(e.target.value))} style={{width: 64}} />
                  <button onClick={async () => { await downloadMissionFromDrone({sysid: downloadSysid || 1, compid: downloadCompid || 1}) }} style={{padding: '8px 12px'}}>Download from Drone</button>
                  <button onClick={downloadFromAllDrones} style={{padding: '8px 12px', backgroundColor: '#4CAF50', color: 'white'}}>Download from All Drones</button>
                </div>
              </div>

              {downloadedMissions.length > 0 && (
                <div style={{marginTop: 12}}>
                  <h4>Downloaded Missions</h4>
                  <div style={{maxHeight: 200, overflow: 'auto', background: '#f8fafc', padding: 8, borderRadius: 6}}>
                    {downloadedMissions.map((mission, idx) => (
                      <div key={idx} style={{padding: 8, borderBottom: '1px solid rgba(0,0,0,0.06)', marginBottom: 8}}>
                        <div style={{fontWeight: 600}}>Sysid {mission.sysid}, {mission.count} waypoints</div>
                        <div style={{fontSize: 12, color: '#475569', marginTop: 4}}>
                          {mission.mission.slice(0, 3).map((wp, i) => (
                            <div key={i}>WP {wp.seq}: {wp.command} at ({wp.x}, {wp.y}, {wp.z})</div>
                          ))}
                          {mission.mission.length > 3 && <div>... and {mission.mission.length - 3} more</div>}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>
      ) : (
        <div style={{flex: 1}} />
      )}

      {page === 'settings' && (
        <section style={{marginTop: 16}}>
          <h2>Settings — Waypoint Upload</h2>
          <div style={{display: 'flex', gap: 12, marginTop: 12}}>
            <div style={{flex: 1}}>
              <div style={{background: '#f8fafc', padding: 12, borderRadius: 8}}>
                <div style={{marginBottom: 8}}>Upload a waypoint YAML file (.yaml/.yml):</div>
                <input type="file" accept=".yaml,.yml" onChange={handleFileInput} />
              </div>
              <div style={{height: 12}} />
              <div style={{background: '#f8fafc', padding: 12, borderRadius: 8}}>
                <div style={{marginBottom: 8}}>Or paste raw YAML and save to a filename:</div>
                <input id="upload-filename" placeholder="filename.yaml" style={{width: '100%', marginBottom: 8}} />
                <textarea id="upload-raw" rows={10} style={{width: '100%'}} placeholder={'waypoints:\n  - lat: ...\n  - ...'} />
                <div style={{marginTop: 8}}>
                  <button onClick={async () => {
                    const fn = document.getElementById('upload-filename').value || `uploaded-${Date.now()}.yaml`
                    const raw = document.getElementById('upload-raw').value || ''
                    if (!raw) {
                      alert('paste YAML or use file upload')
                      return
                    }
                    await uploadRawWaypoint(fn, raw)
                  }} style={{padding: '8px 12px'}}>Save</button>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}

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
      {/* Toast stack */}
      <div style={{position: 'fixed', right: 12, top: 12, zIndex: 9999}}>
        {toasts.map(t => (
          <div key={t.id} style={{background: '#111827', color: '#fff', padding: 10, borderRadius: 6, boxShadow: '0 6px 18px rgba(0,0,0,0.2)', marginBottom: 8, minWidth: 240}}>
            <div style={{fontWeight: 700}}>{t.title}</div>
            <div style={{fontSize: 13, opacity: 0.9, marginTop: 6}}>{t.body}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
