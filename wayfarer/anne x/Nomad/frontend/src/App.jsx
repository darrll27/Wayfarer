import React, {useEffect, useState, useRef, useMemo} from 'react'

// Decide at runtime whether we're in Electron (renderer) or a browser dev server.
// Electron renderer can use the Node mqtt client to connect to tcp://localhost:1883.
// Browser dev (Vite) must use the websocket bridge at ws://localhost:1884.
const isElectron = typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes('Electron') || (typeof window !== 'undefined' && window.process && window.process.versions && window.process.versions.electron)

const WORKSPACES = [
  {id: 'overview', label: 'Overview'},
  {id: 'fleet', label: 'Fleet Map'},
  {id: 'bird', label: 'Bird Detail'},
  {id: 'qgc', label: 'QGC Panel'},
  {id: 'missions', label: 'Missions'},
  {id: 'logs', label: 'Logs'},
  {id: 'settings', label: 'Settings'}
]

function Panel({title, actions, children, className = ''}) {
  return (
    <div className={`panel ${className}`}>
      <div className="panel-header">
        <div className="panel-title">{title}</div>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      <div className="panel-body">{children}</div>
    </div>
  )
}

function Badge({label, tone = 'neutral'}) {
  return <span className={`badge badge-${tone}`}>{label}</span>
}

export default function App() {
  const [connStatus, setConnStatus] = useState('disconnected')
  const [telemetry, setTelemetry] = useState([])
  const [backendStatus, setBackendStatus] = useState(null)
  const [toasts, setToasts] = useState([])
  const [brokerConfig, setBrokerConfig] = useState(null)
  const [brokerMissing, setBrokerMissing] = useState(false)
  const [brokerError, setBrokerError] = useState(null)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [workspace, setWorkspace] = useState('overview')
  const [wpFiles, setWpFiles] = useState([])
  const [selectedMission, setSelectedMission] = useState('')
  const [downloadedMissions, setDownloadedMissions] = useState([])
  const [downloadSysid, setDownloadSysid] = useState(1)
  const [downloadCompid, setDownloadCompid] = useState(1)
  const [birdFilter, setBirdFilter] = useState('')
  const [selectedBird, setSelectedBird] = useState(null)
  const [logFilter, setLogFilter] = useState('')
  const [selectedMode, setSelectedMode] = useState('AUTO')
  const [armReady, setArmReady] = useState(false)
  const [mapScope, setMapScope] = useState('all')

  const clientRef = useRef(null)
  const mapRef = useRef(null)
  const mapLayersRef = useRef([])
  const qgcMapRef = useRef(null)
  const qgcMapLayersRef = useRef([])

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
            setDownloadedMissions((prev) => [obj].concat(prev).slice(0, 10))
            addToast({title: 'Mission downloaded', body: `From sysid ${obj.sysid}: ${obj.count} waypoints`})
          } catch (e) {
            addToast({title: 'Mission download', body: msg})
          }
        }
        setTelemetry((s) => [{topic, msg, ts: Date.now()}].concat(s).slice(0, 160))
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
              setDownloadedMissions((prev) => [obj].concat(prev).slice(0, 10))
              addToast({title: 'Mission downloaded', body: `From sysid ${obj.sysid}: ${obj.count} waypoints`})
            } catch (e) {
              addToast({title: 'Mission download', body: msg})
            }
          }
          setTelemetry((s) => [{topic, msg, ts: Date.now()}].concat(s).slice(0, 160))
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
  const [showFlightPaths, setShowFlightPaths] = useState(true)
  const [selectedFile, setSelectedFile] = useState(null)
  const [sendSysid, setSendSysid] = useState(1)
  const [sendCompid, setSendCompid] = useState(1)

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

  const parseDeviceTopic = (topic) => {
    let match = topic.match(/^device\/(\d+)\/(\d+)\/([^/]+)(?:\/([^/]+))?$/)
    if (match) {
      return {sysid: match[1], compid: match[2], msgType: match[3], field: match[4]}
    }
    match = topic.match(/^device\/sysid_(\d+)\/compid_(\d+)\/([^/]+)(?:\/([^/]+))?$/)
    if (match) {
      return {sysid: match[1], compid: match[2], msgType: match[3], field: match[4]}
    }
    return null
  }

  const birdRecords = useMemo(() => {
    const map = {}
    telemetry.forEach(({topic, msg, ts}) => {
      const parsed = parseDeviceTopic(topic)
      if (!parsed) return
      const {sysid, compid, msgType, field} = parsed

      if (!map[sysid]) {
        map[sysid] = {
          sysid,
          compid,
          lastSeen: ts,
          lastHeartbeat: 0,
          topics: new Set(),
          lat: null,
          lon: null,
          lastMessage: null
        }
      }
      const bird = map[sysid]
      bird.lastSeen = Math.max(bird.lastSeen, ts)
      bird.topics.add(msgType)
      bird.lastMessage = {topic, msg, ts}

      if (msgType === 'HEARTBEAT') {
        bird.lastHeartbeat = Math.max(bird.lastHeartbeat, ts)
      }

      if (msgType === 'GLOBAL_POSITION_INT' && field) {
        let value = null
        try {
          const parsed = JSON.parse(msg)
          if (parsed && typeof parsed[field] !== 'undefined') {
            value = parsed[field]
          }
        } catch (e) {
          const num = Number(msg)
          if (!Number.isNaN(num)) value = num
        }
        if (value !== null) {
          if (field === 'lat') bird.lat = value / 1e7
          if (field === 'lon') bird.lon = value / 1e7
        }
      }
    })
    return map
  }, [telemetry])

  const birdList = useMemo(() => {
    const list = Object.values(birdRecords)
    list.sort((a, b) => (b.lastSeen || 0) - (a.lastSeen || 0))
    if (!birdFilter) return list
    const q = birdFilter.toLowerCase()
    return list.filter(b => String(b.sysid).includes(q) || String(b.compid).includes(q))
  }, [birdRecords, birdFilter])

  useEffect(() => {
    if (!selectedBird && birdList.length > 0) {
      setSelectedBird(birdList[0].sysid)
    }
  }, [birdList, selectedBird])

  const selectedBirdRecord = selectedBird ? birdRecords[selectedBird] : null
  const selectedBirdTelemetry = selectedBird
    ? telemetry.filter(t => {
      const parsed = parseDeviceTopic(t.topic)
      return parsed && String(parsed.sysid) === String(selectedBird)
    }).slice(0, 80)
    : []

  const selectedBirdMode = useMemo(() => {
    if (!selectedBird) return 'unknown'
    const entry = telemetry.find(t => {
      const parsed = parseDeviceTopic(t.topic)
      return parsed && String(parsed.sysid) === String(selectedBird) && parsed.msgType === 'HEARTBEAT'
    })
    if (!entry) return 'unknown'
    try {
      const parsed = JSON.parse(entry.msg)
      if (parsed.mode) return String(parsed.mode)
      if (parsed.custom_mode) return `custom:${parsed.custom_mode}`
      if (parsed.base_mode) return `base:${parsed.base_mode}`
    } catch (e) {
      // ignore
    }
    return 'unknown'
  }, [selectedBird, telemetry])

  const fleetStats = useMemo(() => {
    const now = Date.now()
    const all = Object.values(birdRecords)
    const active = all.filter(b => now - (b.lastSeen || 0) < 10000)
    return {
      total: all.length,
      active: active.length,
      stale: all.length - active.length
    }
  }, [birdRecords])

  const updateQgcMapMarkers = () => {
    if (!window.L || !qgcMapRef.current) return
    if (qgcMapLayersRef.current) {
      qgcMapLayersRef.current.forEach(l => {
        try { l.remove() } catch (e){}
      })
      qgcMapLayersRef.current = []
    }
    const birds = mapScope === 'selected' && selectedBirdRecord ? [selectedBirdRecord] : birdList
    birds.forEach(bird => {
      if (bird.lat == null || bird.lon == null) return
      const marker = window.L.circleMarker([bird.lat, bird.lon], {
        radius: 6,
        color: '#5eead4',
        fillColor: '#5eead4',
        fillOpacity: 0.9
      }).addTo(qgcMapRef.current)
      marker.bindTooltip(`Bird ${bird.sysid}`, {permanent: false})
      qgcMapLayersRef.current.push(marker)
    })
  }

  const getFlightPaths = () => {
    const paths = {}
    const positions = {}
    telemetry.forEach(({topic, msg}) => {
      try {
        const latMatch = topic.match(/^device\/(\d+)\/\d+\/GLOBAL_POSITION_INT\/lat$/)
        const lonMatch = topic.match(/^device\/(\d+)\/\d+\/GLOBAL_POSITION_INT\/lon$/)
        if (latMatch) {
          const sysid = latMatch[1]
          if (!positions[sysid]) positions[sysid] = {}
          const parsed = JSON.parse(msg)
          const value = parsed && typeof parsed.lat !== 'undefined' ? parsed.lat : Number(msg)
          if (!Number.isNaN(value)) positions[sysid].lat = value / 1e7
        } else if (lonMatch) {
          const sysid = lonMatch[1]
          if (!positions[sysid]) positions[sysid] = {}
          const parsed = JSON.parse(msg)
          const value = parsed && typeof parsed.lon !== 'undefined' ? parsed.lon : Number(msg)
          if (!Number.isNaN(value)) positions[sysid].lon = value / 1e7
        }
      } catch (e) {
        // ignore parse errors
      }
    })
    Object.entries(positions).forEach(([sysid, pos]) => {
      if (pos.lat !== undefined && pos.lon !== undefined) {
        if (!paths[sysid]) paths[sysid] = []
        paths[sysid].push([pos.lat, pos.lon])
        if (paths[sysid].length > 50) paths[sysid].shift()
      }
    })
    return paths
  }

  // initialize map when Missions workspace is opened
  useEffect(() => {
    if (workspace !== 'missions') {
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
        mapLayersRef.current = []
      }
      return
    }
    const setup = () => {
      if (!window.L) {
        setTimeout(setup, 200)
        return
      }
      if (mapRef.current) {
        try {
          mapRef.current.getCenter()
          return
        } catch (e) {
          mapRef.current = null
          mapLayersRef.current = []
        }
      }
      const mapContainer = document.getElementById('map')
      if (!mapContainer) {
        setTimeout(setup, 200)
        return
      }
      mapRef.current = window.L.map('map', {zoomControl: true}).setView([37.4680, -122.0870], 15)
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(mapRef.current)

      loadWaypointFiles()
    }
    setup()
  }, [workspace])

  useEffect(() => {
    if (workspace !== 'qgc') {
      if (qgcMapRef.current) {
        qgcMapRef.current.remove()
        qgcMapRef.current = null
        qgcMapLayersRef.current = []
      }
      return
    }
    const setup = () => {
      if (!window.L) {
        setTimeout(setup, 200)
        return
      }
      if (qgcMapRef.current) {
        try {
          qgcMapRef.current.getCenter()
          return
        } catch (e) {
          qgcMapRef.current = null
          qgcMapLayersRef.current = []
        }
      }
      const mapContainer = document.getElementById('qgc-map')
      if (!mapContainer) {
        setTimeout(setup, 200)
        return
      }
      qgcMapRef.current = window.L.map('qgc-map', {zoomControl: true}).setView([37.4680, -122.0870], 14)
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(qgcMapRef.current)
      updateQgcMapMarkers()
    }
    setup()
  }, [workspace])

  // Update downloaded missions when telemetry or data changes
  useEffect(() => {
    if (workspace === 'missions' && mapRef.current) {
      updateDownloadedMissionsOnMap()
      updateFlightPathsOnMap()
    }
  }, [telemetry, showFlightPaths, downloadedMissions, workspace])

  useEffect(() => {
    if (workspace === 'qgc' && qgcMapRef.current) {
      updateQgcMapMarkers()
    }
  }, [telemetry, workspace, mapScope, selectedBird, birdList])

  const updateFlightPathsOnMap = () => {
    if (!window.L || !mapRef.current) return
    if (mapLayersRef.current) {
      mapLayersRef.current.forEach(l => {
        if (l.options && l.options.flightPath) {
          try { l.remove() } catch (e){}
        }
      })
      mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && l.options.flightPath))
    }
    if (!showFlightPaths) return

    const paths = getFlightPaths()
    Object.entries(paths).forEach(([sysid, positions]) => {
      if (positions.length > 1) {
        const polyline = window.L.polyline(positions, {
          color: '#38bdf8',
          weight: 2,
          flightPath: true
        }).addTo(mapRef.current)
        mapLayersRef.current.push(polyline)
        const last = positions[positions.length - 1]
        const marker = window.L.circleMarker(last, {
          radius: 5,
          color: '#38bdf8',
          fillColor: '#38bdf8',
          fillOpacity: 0.8,
          flightPath: true
        }).addTo(mapRef.current)
        marker.bindTooltip(`Sysid ${sysid}`, {permanent: false})
        mapLayersRef.current.push(marker)
      }
    })
  }

  const updateDownloadedMissionsOnMap = () => {
    if (!window.L || !mapRef.current) return

    if (mapLayersRef.current) {
      mapLayersRef.current.forEach(l => {
        if (l.options && l.options.downloadedMission) {
          try { l.remove() } catch (e){}
        }
      })
      mapLayersRef.current = mapLayersRef.current.filter(l => !(l.options && l.options.downloadedMission))
    }

    downloadedMissions.forEach((mission) => {
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
  }

  async function drawFileOnMap(filename) {
    if (!window.L || !mapRef.current) return
    try {
      const r = await fetch(`/api/waypoints/${filename}`)
      if (!r.ok) return
      const j = await r.json()
      const w = j.waypoints || []
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
      w.forEach((pt, i) => {
        const sysidMatch = filename.match(/^(\d+)_/)
        const sysid = sysidMatch ? parseInt(sysidMatch[1]) : '?'
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
    for (let sysid = 1; sysid <= 6; sysid++) {
      try {
        await downloadMissionFromDrone({sysid, compid: 1})
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

  const sendModeCommand = async () => {
    if (!selectedBird || !clientRef.current) return
    const sysid = Number(selectedBird)
    const compid = selectedBirdRecord ? Number(selectedBirdRecord.compid) : 1
    const payload = {
      command: 'SET_MODE',
      mode: selectedMode,
      params: [],
      src_sysid: 250,
      src_compid: 1
    }
    clientRef.current.publish(`command/${sysid}/${compid}/details`, JSON.stringify(payload))
    addToast({title: 'Mode sent', body: `Bird ${sysid} -> ${selectedMode}`})
  }

  const sendArmCommand = async (armFlag) => {
    if (!selectedBird || !clientRef.current) return
    const sysid = Number(selectedBird)
    const compid = selectedBirdRecord ? Number(selectedBirdRecord.compid) : 1
    const payload = {
      command: 'MAV_CMD_COMPONENT_ARM_DISARM',
      params: [armFlag ? 1 : 0, 0, 0, 0, 0, 0, 0],
      src_sysid: 250,
      src_compid: 1
    }
    clientRef.current.publish(`command/${sysid}/${compid}/details`, JSON.stringify(payload))
    addToast({title: armFlag ? 'Arm command sent' : 'Disarm command sent', body: `Bird ${sysid}`})
  }

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

  const filteredTelemetry = logFilter
    ? telemetry.filter(t => t.topic.toLowerCase().includes(logFilter.toLowerCase()) || t.msg.toLowerCase().includes(logFilter.toLowerCase()))
    : telemetry

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-title">
          <div>
            <div className="title">Nomad</div>
            <div className="subtitle">Fleet console</div>
          </div>
          <div className="status-chips">
            <Badge label={`MQTT: ${connStatus}`} tone={connStatus === 'connected' ? 'ok' : 'warn'} />
            <Badge label={`Backend: ${backendStatus && backendStatus.ok ? 'online' : 'unknown'}`} tone={backendStatus && backendStatus.ok ? 'ok' : 'neutral'} />
          </div>
        </div>
        <nav className="tabs">
          {WORKSPACES.map(tab => (
            <button
              key={tab.id}
              className={`tab ${workspace === tab.id ? 'active' : ''}`}
              onClick={() => setWorkspace(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="broker-summary">
          <div className="label">Broker</div>
          <div className="value">
            {brokerConfig ? `${brokerConfig.host}:${isElectron ? brokerConfig.tcp_port : brokerConfig.ws_port}` : (brokerMissing ? 'missing' : 'loading...')}
          </div>
        </div>
      </header>

      <div className="app-body">
        <aside className="sidebar">
          <Panel
            title="Birds"
            actions={<input className="input" placeholder="Filter" value={birdFilter} onChange={(e) => setBirdFilter(e.target.value)} />}
          >
            <div className="bird-list">
              {birdList.length === 0 ? (
                <div className="empty">No birds observed yet.</div>
              ) : (
                birdList.map(bird => (
                  <button
                    key={bird.sysid}
                    className={`bird-card ${String(selectedBird) === String(bird.sysid) ? 'active' : ''}`}
                    onClick={() => setSelectedBird(bird.sysid)}
                  >
                    <div className="bird-title">Bird {bird.sysid}</div>
                    <div className="bird-meta">Comp {bird.compid} · Topics {bird.topics.size}</div>
                    <div className="bird-meta">Last seen {bird.lastSeen ? new Date(bird.lastSeen).toLocaleTimeString() : 'never'}</div>
                    {bird.lat && bird.lon ? (
                      <div className="bird-meta">{bird.lat.toFixed(5)}, {bird.lon.toFixed(5)}</div>
                    ) : (
                      <div className="bird-meta muted">No position yet</div>
                    )}
                  </button>
                ))
              )}
            </div>
          </Panel>

          <Panel title="Fleet Summary">
            <div className="stat-grid">
              <div className="stat">
                <div className="stat-label">Total</div>
                <div className="stat-value">{fleetStats.total}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Active</div>
                <div className="stat-value">{fleetStats.active}</div>
              </div>
              <div className="stat">
                <div className="stat-label">Stale</div>
                <div className="stat-value">{fleetStats.stale}</div>
              </div>
            </div>
          </Panel>
        </aside>

        <main className="workspace">
          {workspace === 'overview' && (
            <div className="grid">
              <Panel title="Live Telemetry" actions={<button className="ghost" onClick={sendLoadWaypointsDemo}>Send demo waypoints</button>}>
                <div className="telemetry-list">
                  {telemetry.length === 0 ? (
                    <div className="empty">No telemetry received yet.</div>
                  ) : (
                    telemetry.slice(0, 30).map((t, i) => (
                      <div key={i} className="telemetry-row">
                        <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                        <div className="telemetry-topic">{t.topic}</div>
                        <div className="telemetry-msg">{t.msg}</div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
              <Panel title="System Status">
                <div className="status-grid">
                  <div>
                    <div className="label">Backend</div>
                    <div className="mono">{backendStatus ? JSON.stringify(backendStatus) : 'offline'}</div>
                  </div>
                  <div>
                    <div className="label">Broker</div>
                    <div className="mono">{brokerStatus ? JSON.stringify(brokerStatus) : 'unknown'}</div>
                  </div>
                </div>
              </Panel>
              <Panel title="Recent Missions">
                <div className="mission-list">
                  {downloadedMissions.length === 0 ? (
                    <div className="empty">No missions downloaded yet.</div>
                  ) : (
                    downloadedMissions.slice(0, 5).map((mission, idx) => (
                      <div key={idx} className="mission-row">
                        <div>Sysid {mission.sysid}</div>
                        <div className="muted">{mission.count} waypoints</div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
            </div>
          )}

          {workspace === 'fleet' && (
            <div className="grid">
              <Panel title="Fleet Locations">
                <div className="location-grid">
                  {birdList.length === 0 ? (
                    <div className="empty">No location updates yet.</div>
                  ) : (
                    birdList.map(bird => (
                      <div key={bird.sysid} className="location-card">
                        <div className="location-title">Bird {bird.sysid}</div>
                        <div className="location-meta">Last seen {bird.lastSeen ? new Date(bird.lastSeen).toLocaleTimeString() : 'never'}</div>
                        <div className="location-coords">
                          {bird.lat && bird.lon ? `${bird.lat.toFixed(5)}, ${bird.lon.toFixed(5)}` : 'No GPS fix'}
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
              <Panel title="Fleet Telemetry Stream">
                <div className="telemetry-list">
                  {telemetry.length === 0 ? (
                    <div className="empty">No telemetry received yet.</div>
                  ) : (
                    telemetry.slice(0, 40).map((t, i) => (
                      <div key={i} className="telemetry-row">
                        <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                        <div className="telemetry-topic">{t.topic}</div>
                        <div className="telemetry-msg">{t.msg}</div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
            </div>
          )}

          {workspace === 'bird' && (
            <div className="grid">
              <Panel title={selectedBird ? `Bird ${selectedBird} Overview` : 'Select a Bird'}>
                {selectedBirdRecord ? (
                  <div className="status-grid">
                    <div>
                      <div className="label">Last seen</div>
                      <div className="mono">{selectedBirdRecord.lastSeen ? new Date(selectedBirdRecord.lastSeen).toLocaleTimeString() : 'never'}</div>
                    </div>
                    <div>
                      <div className="label">Heartbeat</div>
                      <div className="mono">{selectedBirdRecord.lastHeartbeat ? new Date(selectedBirdRecord.lastHeartbeat).toLocaleTimeString() : 'not seen'}</div>
                    </div>
                    <div>
                      <div className="label">Position</div>
                      <div className="mono">{selectedBirdRecord.lat && selectedBirdRecord.lon ? `${selectedBirdRecord.lat.toFixed(5)}, ${selectedBirdRecord.lon.toFixed(5)}` : 'no fix'}</div>
                    </div>
                  </div>
                ) : (
                  <div className="empty">Pick a bird from the left.</div>
                )}
              </Panel>
              <Panel title="Bird Telemetry">
                <div className="telemetry-list">
                  {selectedBirdTelemetry.length === 0 ? (
                    <div className="empty">No telemetry for this bird yet.</div>
                  ) : (
                    selectedBirdTelemetry.map((t, i) => (
                      <div key={i} className="telemetry-row">
                        <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                        <div className="telemetry-topic">{t.topic}</div>
                        <div className="telemetry-msg">{t.msg}</div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
            </div>
          )}

          {workspace === 'missions' && (
            <div className="grid">
              <Panel title="Mission Map">
                <div id="map" className="map-shell" />
              </Panel>
              <Panel
                title="Mission Controls"
                actions={<button className="ghost" onClick={loadWaypointFiles}>Refresh</button>}
              >
                <div className="controls">
                  <div className="field">
                    <label>Select Mission</label>
                    <select value={selectedMission} onChange={(e) => setSelectedMission(e.target.value)} className="input">
                      {Object.keys(groupWaypointFiles(wpFiles)).map((mission) => (
                        <option key={mission} value={mission}>{mission}</option>
                      ))}
                      <option value="">-- All Missions --</option>
                    </select>
                  </div>
                  <div className="button-row">
                    <button onClick={async () => { try { await fetch('/api/waypoints/demo', {method: 'POST'}); await loadWaypointFiles() } catch (e) { console.error(e) } }}>Create demo waypoints</button>
                    <button onClick={() => setShowFlightPaths(!showFlightPaths)}>{showFlightPaths ? 'Hide' : 'Show'} onboard paths</button>
                  </div>
                </div>
              </Panel>
              <Panel title="Waypoint Files">
                <div className="file-list">
                  {wpFiles.length === 0 ? (
                    <div className="empty">No waypoint files. Create demo files or upload from Settings.</div>
                  ) : (
                    Object.entries(groupWaypointFiles(wpFiles))
                      .filter(([mission]) => !selectedMission || mission === selectedMission)
                      .map(([mission, groups]) => (
                        <div key={mission} className="file-group">
                          <div className="file-group-title">Mission: {mission}</div>
                          {Object.entries(groups).map(([group, files]) => (
                            <div key={group} className="file-subgroup">
                              <div className="file-subgroup-title">Group: {group}</div>
                              {files.map((f) => (
                                <div key={f.filename} className="file-row">
                                  <div>
                                    <div className="file-name">{f.filename}</div>
                                    <div className="muted">count: {f.count} valid: {String(f.valid)}</div>
                                  </div>
                                  <div className="file-actions">
                                    <button onClick={async () => { setSelectedFile(f.filename); await drawFileOnMap(f.filename) }}>Show</button>
                                    <button onClick={async () => { await sendToDronePrompt(f.filename) }}>Send</button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          ))}
                        </div>
                      ))
                  )}
                </div>
              </Panel>
              <Panel title="Manual Send">
                <div className="controls">
                  <div className="field-row">
                    <label>sysid</label>
                    <input type="number" value={sendSysid} onChange={(e) => setSendSysid(Number(e.target.value))} className="input" />
                    <label>compid</label>
                    <input type="number" value={sendCompid} onChange={(e) => setSendCompid(Number(e.target.value))} className="input" />
                  </div>
                  <select value={selectedFile || ''} onChange={(e) => setSelectedFile(e.target.value)} className="input">
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
                  <div className="button-row">
                    <button onClick={async () => { if (selectedFile) await sendToDrone({sysid: sendSysid, compid: sendCompid, filename: selectedFile}) }}>Send to Drone</button>
                  </div>
                </div>
              </Panel>
              <Panel title="Download Mission">
                <div className="controls">
                  <div className="field-row">
                    <label>sysid</label>
                    <input type="number" value={downloadSysid || 1} onChange={(e) => setDownloadSysid(Number(e.target.value))} className="input" />
                    <label>compid</label>
                    <input type="number" value={downloadCompid || 1} onChange={(e) => setDownloadCompid(Number(e.target.value))} className="input" />
                  </div>
                  <div className="button-row">
                    <button onClick={async () => { await downloadMissionFromDrone({sysid: downloadSysid || 1, compid: downloadCompid || 1}) }}>Download from Drone</button>
                    <button className="primary" onClick={downloadFromAllDrones}>Download from All Drones</button>
                  </div>
                </div>
              </Panel>
            </div>
          )}

          {workspace === 'qgc' && (
            <div className="grid">
              <Panel title="QGC Control">
                <div className="controls">
                  <div className="status-grid">
                    <div>
                      <div className="label">Selected bird</div>
                      <div className="mono">{selectedBird ? `Bird ${selectedBird}` : 'none'}</div>
                    </div>
                    <div>
                      <div className="label">Current mode</div>
                      <div className="mono">{selectedBirdMode}</div>
                    </div>
                  </div>
                  <div className="field">
                    <label>Mode selection</label>
                    <div className="field-row">
                      <select value={selectedMode} onChange={(e) => setSelectedMode(e.target.value)} className="input">
                        {['AUTO', 'GUIDED', 'LOITER', 'RTL', 'HOLD', 'MISSION', 'STABILIZE'].map(mode => (
                          <option key={mode} value={mode}>{mode}</option>
                        ))}
                      </select>
                      <button onClick={sendModeCommand}>Set mode</button>
                    </div>
                  </div>
                  <div className="field">
                    <label>Arming</label>
                    <div className="field-row">
                      <label className="toggle">
                        <input type="checkbox" checked={armReady} onChange={(e) => setArmReady(e.target.checked)} />
                        <span>Enable arm</span>
                      </label>
                      <button className="primary" disabled={!armReady} onClick={async () => { await sendArmCommand(true); setArmReady(false) }}>Arm</button>
                      <button onClick={async () => { await sendArmCommand(false) }}>Disarm</button>
                    </div>
                  </div>
                </div>
              </Panel>
              <Panel title="Multi-drone Map" actions={(
                <div className="segmented">
                  <button className={mapScope === 'all' ? 'active' : ''} onClick={() => setMapScope('all')}>All birds</button>
                  <button className={mapScope === 'selected' ? 'active' : ''} onClick={() => setMapScope('selected')}>Selected only</button>
                </div>
              )}>
                <div id="qgc-map" className="map-shell" />
              </Panel>
              <Panel title="Selected Bird Stream">
                <div className="telemetry-list">
                  {selectedBirdTelemetry.length === 0 ? (
                    <div className="empty">No telemetry for this bird yet.</div>
                  ) : (
                    selectedBirdTelemetry.map((t, i) => (
                      <div key={i} className="telemetry-row">
                        <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                        <div className="telemetry-topic">{t.topic}</div>
                        <div className="telemetry-msg">{t.msg}</div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
            </div>
          )}

          {workspace === 'logs' && (
            <div className="grid">
              <Panel title="Telemetry Logs" actions={<input className="input" placeholder="Filter logs" value={logFilter} onChange={(e) => setLogFilter(e.target.value)} />}>
                <div className="telemetry-list">
                  {filteredTelemetry.length === 0 ? (
                    <div className="empty">No telemetry matching the filter.</div>
                  ) : (
                    filteredTelemetry.map((t, i) => (
                      <div key={i} className="telemetry-row">
                        <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                        <div className="telemetry-topic">{t.topic}</div>
                        <div className="telemetry-msg">{t.msg}</div>
                      </div>
                    ))
                  )}
                </div>
              </Panel>
            </div>
          )}

          {workspace === 'settings' && (
            <div className="grid">
              <Panel title="Settings — Waypoint Upload">
                <div className="controls">
                  <div className="field">
                    <label>Upload a waypoint YAML file (.yaml/.yml)</label>
                    <input type="file" accept=".yaml,.yml" onChange={handleFileInput} className="input" />
                  </div>
                  <div className="field">
                    <label>Paste raw YAML and save to filename</label>
                    <input id="upload-filename" placeholder="filename.yaml" className="input" />
                    <textarea id="upload-raw" rows={8} className="input" placeholder={'waypoints:\n  - lat: ...\n  - ...'} />
                    <div className="button-row">
                      <button onClick={async () => {
                        const fn = document.getElementById('upload-filename').value || `uploaded-${Date.now()}.yaml`
                        const raw = document.getElementById('upload-raw').value || ''
                        if (!raw) {
                          alert('paste YAML or use file upload')
                          return
                        }
                        await uploadRawWaypoint(fn, raw)
                      }}>Save</button>
                    </div>
                  </div>
                </div>
              </Panel>
            </div>
          )}
        </main>
      </div>

      <footer className="app-footer">
        <div>Backend: {backendStatus ? (backendStatus.ok ? 'online' : 'offline') : 'unknown'}</div>
        <div>Broker: {brokerConfig ? `${brokerConfig.host}:${isElectron ? brokerConfig.tcp_port : brokerConfig.ws_port}` : (brokerMissing ? 'missing' : 'loading')}</div>
        <div className="footer-meta">
          {brokerMissing ? (
            <div>
              <div className="danger">broker.json missing or incomplete — see <code>config/broker.json</code></div>
              <div className="button-row">
                <button onClick={retryFetchBroker}>Reload broker config</button>
              </div>
            </div>
          ) : brokerError ? (
            <div className="danger">Broker error: {brokerError}</div>
          ) : brokerConfig ? (
            <div className="mono">{JSON.stringify(brokerConfig)}</div>
          ) : (
            <div className="muted">config loading...</div>
          )}
        </div>
      </footer>

      <div className="toast-stack">
        {toasts.map(t => (
          <div key={t.id} className="toast">
            <div className="toast-title">{t.title}</div>
            <div className="toast-body">{t.body}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
