import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import AppHeader from './components/AppHeader'
import Sidebar from './components/Sidebar'
import ToastStack from './components/ToastStack'
import OverviewWorkspace from './workspaces/OverviewWorkspace'
import FleetWorkspace from './workspaces/FleetWorkspace'
import BirdWorkspace from './workspaces/BirdWorkspace'
import QgcWorkspace from './workspaces/QgcWorkspace'
import MissionsWorkspace from './workspaces/MissionsWorkspace'
import LogsWorkspace from './workspaces/LogsWorkspace'
import SettingsWorkspace from './workspaces/SettingsWorkspace'
import useTelemetry from './hooks/useTelemetry'
import {isNonBirdSysid, parseDeviceTopic, useBirds} from './hooks/useBirds'

const isElectron = typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes('Electron') || (typeof window !== 'undefined' && window.process && window.process.versions && window.process.versions.electron)

const WORKSPACES = [
  {id: 'overview', label: 'Summary'},
  {id: 'fleet', label: 'Fleet Map'},
  {id: 'bird', label: 'Bird Detail'},
  {id: 'qgc', label: 'QGC Panel'},
  {id: 'missions', label: 'Missions'},
  {id: 'logs', label: 'Logs'},
  {id: 'settings', label: 'Settings'}
]

const DEFAULT_MAP_CENTER = [37.4680, -122.0870]
const DEFAULT_MISSIONS_ZOOM = 16
const DEFAULT_QGC_ZOOM = 16
const FOCUS_BIRDS_MAX_ZOOM = 19

export default function App() {
  const [toasts, setToasts] = useState([])
  const [notifications, setNotifications] = useState([])
  const [notificationCenterOpen, setNotificationCenterOpen] = useState(false)
  const [workspace, setWorkspace] = useState('overview')
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [birdFilter, setBirdFilter] = useState('')
  const [selectedBird, setSelectedBird] = useState(null)
  const [logFilter, setLogFilter] = useState('')
  const [selectedMission, setSelectedMission] = useState('')
  const [selectedMode, setSelectedMode] = useState('AUTO')
  const [armReady, setArmReady] = useState(false)
  const [mapScope, setMapScope] = useState('all')
  const [qgcMapView, setQgcMapView] = useState('map')
  const [showFlightPaths, setShowFlightPaths] = useState(true)
  const [selectedFile, setSelectedFile] = useState(null)
  const [sendSysid, setSendSysid] = useState(1)
  const [sendCompid, setSendCompid] = useState(1)
  const [downloadSysid, setDownloadSysid] = useState(1)
  const [downloadCompid, setDownloadCompid] = useState(1)
  const [dataLossGraceMs, setDataLossGraceMs] = useState(() => {
    if (typeof window === 'undefined') return 1000
    const stored = Number(window.localStorage.getItem('telemetryLossGraceMs'))
    if (Number.isFinite(stored) && stored >= 1000) return stored
    return 1000
  })
  const [systemRange, setSystemRange] = useState(() => {
    if (typeof window === 'undefined') return {start: 250, end: 255}
    const start = Number(window.localStorage.getItem('groundSysidRangeStart'))
    const end = Number(window.localStorage.getItem('groundSysidRangeEnd'))
    return {
      start: Number.isFinite(start) ? start : 250,
      end: Number.isFinite(end) ? end : 255
    }
  })

  const mapRef = useRef(null)
  const mapLayersRef = useRef([])
  const qgcMapRef = useRef(null)
  const qgcMapLayersRef = useRef([])
  const qgcBaseLayerRef = useRef(null)
  const qgcHasAutoFocusedRef = useRef(false)

  const addToast = useCallback((t) => {
    const id = Date.now() + Math.random()
    const entry = {...t, id, ts: Date.now(), read: false}
    setToasts((s) => [entry].concat(s).slice(0, 6))
    setNotifications((s) => [entry].concat(s).slice(0, 100))
    setTimeout(() => {
      setToasts((s) => s.filter(x => x.id !== id))
    }, 6000)
  }, [])

  const clearNotifications = useCallback(() => {
    setNotifications([])
  }, [])

  const {
    connStatus,
    telemetry,
    backendStatus,
    backendHeartbeatTs,
    brokerConfig,
    brokerMissing,
    brokerError,
    downloadedMissions,
    missionDownloadStatusBySysid,
    clientRef,
    retryFetchBroker
  } = useTelemetry(addToast)

  const {
    birdList,
    selectedBirdRecord,
    selectedBirdHeartbeat,
    selectedBirdTelemetry,
    selectedBirdMode,
    fleetStats
  } = useBirds(telemetry, birdFilter, selectedBird, dataLossGraceMs, systemRange)

  const backendStatusGraceMs = 7000
  const backendIsOnline = backendHeartbeatTs > 0 && Date.now() - backendHeartbeatTs <= backendStatusGraceMs
  const backendStatusLabel = backendIsOnline
    ? (backendStatus && backendStatus.ok === false ? 'offline' : 'online')
    : 'unknown'

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('telemetryLossGraceMs', String(dataLossGraceMs))
  }, [dataLossGraceMs])

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('groundSysidRangeStart', String(systemRange.start))
    window.localStorage.setItem('groundSysidRangeEnd', String(systemRange.end))
  }, [systemRange])

  useEffect(() => {
    if (!selectedBird && birdList.length > 0) {
      setSelectedBird(birdList[0].sysid)
    }
  }, [birdList, selectedBird])

  useEffect(() => {
    const onKeyDown = (e) => {
      if (e.key === 'Escape') {
        setSidebarOpen(false)
        setNotificationCenterOpen(false)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (!notificationCenterOpen) return
    setNotifications((items) => items.map((item) => ({...item, read: true})))
  }, [notificationCenterOpen])

  const filteredTelemetry = logFilter
    ? telemetry.filter(t => t.topic.toLowerCase().includes(logFilter.toLowerCase()) || t.msg.toLowerCase().includes(logFilter.toLowerCase()))
    : telemetry

  const getFlightPaths = () => {
    const paths = {}
    const positions = {}
    telemetry.forEach(({topic, msg}) => {
      try {
        const parsed = parseDeviceTopic(topic)
        if (!parsed || parsed.msgType !== 'GLOBAL_POSITION_INT' || !parsed.field) return
        const sysid = parsed.sysid
        if (!positions[sysid]) positions[sysid] = {}
        const parsedMsg = JSON.parse(msg)
        const value = parsedMsg && typeof parsedMsg[parsed.field] !== 'undefined' ? parsedMsg[parsed.field] : Number(msg)
        if (Number.isNaN(value)) return
        if (parsed.field === 'lat') positions[sysid].lat = value / 1e7
        if (parsed.field === 'lon') positions[sysid].lon = value / 1e7
      } catch (e) {
        // ignore
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

  const updateQgcMapMarkers = () => {
    if (!window.L || !qgcMapRef.current) return
    if (qgcMapLayersRef.current) {
      qgcMapLayersRef.current.forEach(l => {
        try { l.remove() } catch (e){}
      })
      qgcMapLayersRef.current = []
    }
    const birds = birdList
    const highlightSelected = mapScope === 'selected' && selectedBirdRecord
    birds.forEach(bird => {
      if (bird.lat == null || bird.lon == null) return
      const heading = Number(bird.metrics && bird.metrics.heading)
      const rotation = Number.isFinite(heading) ? heading : 0
      const birdLabel = String(bird.sysid)
      const isNonBird = isNonBirdSysid(bird.sysid, systemRange)
      const isSelected = highlightSelected && String(selectedBirdRecord.sysid) === String(bird.sysid)
      const iconStateClass = [
        highlightSelected ? (isSelected ? 'selected' : 'muted') : '',
        isNonBird ? 'nonbird' : ''
      ].filter(Boolean).join(' ')
      const idStateClass = [
        highlightSelected ? (isSelected ? 'selected' : 'muted') : '',
        isNonBird ? 'nonbird' : ''
      ].filter(Boolean).join(' ')
      const icon = window.L.divIcon({
        className: 'qgc-bird-marker',
        html: `<div class="qgc-bird-wrap"><div class="qgc-bird-icon ${iconStateClass}" style="transform: rotate(${rotation}deg)">▲</div><div class="qgc-bird-id ${idStateClass}">${birdLabel}</div></div>`,
        iconSize: [54, 40],
        iconAnchor: [18, 18]
      })
      const marker = window.L.marker([bird.lat, bird.lon], {
        icon,
        zIndexOffset: isSelected ? 1000 : (isNonBird ? -50 : 0)
      }).addTo(qgcMapRef.current)
      marker.bindTooltip(`${isNonBird ? 'Ground' : 'Air'} ${bird.sysid}`, {permanent: false})
      qgcMapLayersRef.current.push(marker)
    })
  }

  const focusQgcMapOnBirds = useCallback((scope = mapScope) => {
    if (!window.L || !qgcMapRef.current) return
    const birds = scope === 'selected' && selectedBirdRecord ? [selectedBirdRecord] : birdList
    const points = birds
      .filter(bird => bird.lat != null && bird.lon != null)
      .map(bird => [bird.lat, bird.lon])
    if (points.length === 0) return
    const bounds = window.L.latLngBounds(points)
    qgcMapRef.current.fitBounds(bounds.pad(0.3), {maxZoom: FOCUS_BIRDS_MAX_ZOOM})
  }, [mapScope, selectedBirdRecord, birdList])

  const setQgcScopeAndFocus = useCallback((scope) => {
    setMapScope(scope)
    // Trigger fit specifically on user click, not on every state refresh.
    setTimeout(() => {
      focusQgcMapOnBirds(scope)
    }, 0)
  }, [focusQgcMapOnBirds])

  const updateQgcBaseLayer = useCallback(() => {
    if (!window.L || !qgcMapRef.current) return
    const currentCenter = qgcMapRef.current.getCenter()
    const currentZoom = qgcMapRef.current.getZoom()
    if (qgcBaseLayerRef.current) {
      try { qgcMapRef.current.removeLayer(qgcBaseLayerRef.current) } catch (e) {}
      qgcBaseLayerRef.current = null
    }
    const isSatellite = qgcMapView === 'satellite'
    const layer = isSatellite
      ? window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri',
        maxNativeZoom: 19,
        maxZoom: 28
      })
      : window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxNativeZoom: 19,
        maxZoom: 28
      })
    layer.addTo(qgcMapRef.current)
    qgcBaseLayerRef.current = layer
    if (currentCenter && Number.isFinite(currentZoom)) {
      qgcMapRef.current.setView(currentCenter, currentZoom, {animate: false})
    }
  }, [qgcMapView])

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
      mapRef.current = window.L.map('map', {zoomControl: true}).setView(DEFAULT_MAP_CENTER, DEFAULT_MISSIONS_ZOOM)
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(mapRef.current)
      window.L.control.scale({position: 'bottomleft', metric: true, imperial: false}).addTo(mapRef.current)

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
      qgcHasAutoFocusedRef.current = false
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
      qgcMapRef.current = window.L.map('qgc-map', {
        zoomControl: true,
        maxZoom: 28,
        zoomSnap: 0.1,
        zoomDelta: 0.1
      }).setView(DEFAULT_MAP_CENTER, DEFAULT_QGC_ZOOM)
      updateQgcBaseLayer()
      window.L.control.scale({position: 'bottomleft', metric: true, imperial: false}).addTo(qgcMapRef.current)
      updateQgcMapMarkers()
      setTimeout(() => {
        if (!qgcHasAutoFocusedRef.current) {
          focusQgcMapOnBirds()
          qgcHasAutoFocusedRef.current = true
        }
      }, 0)
    }
    setup()
  }, [workspace, updateQgcBaseLayer, focusQgcMapOnBirds])

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

  useEffect(() => {
    if (workspace !== 'qgc' || !qgcMapRef.current) return
    const points = birdList
      .filter((bird) => bird.lat != null && bird.lon != null)
      .map((bird) => [bird.lat, bird.lon])
    if (points.length === 0) {
      qgcHasAutoFocusedRef.current = false
      return
    }
    if (!qgcHasAutoFocusedRef.current) {
      focusQgcMapOnBirds()
      qgcHasAutoFocusedRef.current = true
    }
  }, [workspace, birdList, focusQgcMapOnBirds])

  useEffect(() => {
    if (workspace !== 'qgc' || !qgcMapRef.current) return
    updateQgcBaseLayer()
  }, [workspace, qgcMapView, updateQgcBaseLayer])

  // Waypoint manager state & helpers
  async function loadWaypointFiles() {
    try {
      const r = await fetch('/api/waypoints')
      if (!r.ok) return
      const j = await r.json()
      const files = j.files || []
      // update state in place
      setWpFiles(files)

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

  const [wpFiles, setWpFiles] = useState([])

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

  const sendLoadWaypointsDemo = () => {
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
      const j = await r.json().catch(() => ({}))
      if (!r.ok) {
        addToast({title: 'Download request failed', body: j.detail ? String(j.detail) : `HTTP ${r.status}`})
        return
      }
      if (!j.ok) {
        addToast({title: 'Download request not sent', body: `sysid ${payload.sysid} compid ${payload.compid || 1}`})
        return
      }
      addToast({title: 'Download requested', body: `${j.topic || `command/${payload.sysid}/${payload.compid || 1}/download_mission`}`})
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
      params: []
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
      params: [armFlag ? 1 : 0, 0, 0, 0, 0, 0, 0]
    }
    clientRef.current.publish(`command/${sysid}/${compid}/details`, JSON.stringify(payload))
    addToast({title: armFlag ? 'Arm command sent' : 'Disarm command sent', body: `Bird ${sysid}`})
  }

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

  async function saveBrokerConfig(nextConfig) {
    try {
      let r = await fetch('/api/config', {
        method: 'PUT',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(nextConfig)
      })
      if (r.status === 405) {
        r = await fetch('/api/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(nextConfig)
        })
      }
      const j = await r.json()
      if (!r.ok || !j.ok) {
        addToast({title: 'Broker config save failed', body: JSON.stringify(j)})
        return
      }
      try {
        await fetch('/api/router/restart', {method: 'POST'})
      } catch (e) {
        // non-fatal; reconnect still attempted below
      }
      addToast({title: 'Broker config updated', body: `${j.config.host}:${j.config.ws_port} (${j.config.mode})`})
      await retryFetchBroker()
    } catch (e) {
      addToast({title: 'Broker config error', body: String(e)})
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

  return (
    <div className="app">
      <AppHeader
        workspaces={WORKSPACES}
        workspace={workspace}
        setWorkspace={setWorkspace}
        connStatus={connStatus}
          backendStatusLabel={backendStatusLabel}
          brokerConfig={brokerConfig}
          brokerMissing={brokerMissing}
          isElectron={isElectron}
          notifications={notifications}
          notificationCenterOpen={notificationCenterOpen}
          setNotificationCenterOpen={setNotificationCenterOpen}
          clearNotifications={clearNotifications}
        />

      <div className="app-body">
        <button
          className="sidebar-toggle"
          type="button"
          aria-expanded={sidebarOpen}
          aria-controls="fleet-sidebar"
          onClick={() => setSidebarOpen((open) => !open)}
        >
          {sidebarOpen ? 'Hide Fleet' : 'Show Fleet'}
        </button>

        <main className="workspace">
          {workspace === 'overview' && (
            <OverviewWorkspace
              telemetry={telemetry}
              birdList={birdList}
              sendLoadWaypointsDemo={sendLoadWaypointsDemo}
              systemRange={systemRange}
            />
          )}

          {workspace === 'fleet' && (
            <FleetWorkspace birdList={birdList} telemetry={telemetry} systemRange={systemRange} />
          )}

          {workspace === 'bird' && (
            <BirdWorkspace
              selectedBird={selectedBird}
              selectedBirdRecord={selectedBirdRecord}
              selectedBirdHeartbeat={selectedBirdHeartbeat}
              selectedBirdTelemetry={selectedBirdTelemetry}
            />
          )}

          {workspace === 'qgc' && (
            <QgcWorkspace
              selectedBird={selectedBird}
              selectedBirdMode={selectedBirdMode}
              selectedMode={selectedMode}
              setSelectedMode={setSelectedMode}
              armReady={armReady}
              setArmReady={setArmReady}
              sendModeCommand={sendModeCommand}
              sendArmCommand={sendArmCommand}
              mapScope={mapScope}
              setQgcScopeAndFocus={setQgcScopeAndFocus}
              qgcMapView={qgcMapView}
              setQgcMapView={setQgcMapView}
              focusQgcMapOnBirds={focusQgcMapOnBirds}
            />
          )}

          {workspace === 'missions' && (
            <MissionsWorkspace
              loadWaypointFiles={loadWaypointFiles}
              selectedMission={selectedMission}
              setSelectedMission={setSelectedMission}
              showFlightPaths={showFlightPaths}
              setShowFlightPaths={setShowFlightPaths}
              wpFiles={wpFiles}
              groupWaypointFiles={groupWaypointFiles}
              drawFileOnMap={drawFileOnMap}
              sendToDronePrompt={sendToDronePrompt}
              selectedFile={selectedFile}
              setSelectedFile={setSelectedFile}
              sendSysid={sendSysid}
              setSendSysid={setSendSysid}
              sendCompid={sendCompid}
              setSendCompid={setSendCompid}
              sendToDrone={sendToDrone}
              downloadSysid={downloadSysid}
              setDownloadSysid={setDownloadSysid}
              downloadCompid={downloadCompid}
              setDownloadCompid={setDownloadCompid}
              downloadMissionFromDrone={downloadMissionFromDrone}
              downloadFromAllDrones={downloadFromAllDrones}
              missionDownloadStatusBySysid={missionDownloadStatusBySysid}
              downloadedMissions={downloadedMissions}
              selectedBird={selectedBird}
            />
          )}

          {workspace === 'logs' && (
            <LogsWorkspace
              telemetry={telemetry}
              filteredTelemetry={filteredTelemetry}
              logFilter={logFilter}
              setLogFilter={setLogFilter}
            />
          )}

          {workspace === 'settings' && (
            <SettingsWorkspace
              handleFileInput={handleFileInput}
              uploadRawWaypoint={uploadRawWaypoint}
              dataLossGraceMs={dataLossGraceMs}
              setDataLossGraceMs={setDataLossGraceMs}
              systemRange={systemRange}
              setSystemRange={setSystemRange}
              brokerConfig={brokerConfig}
              saveBrokerConfig={saveBrokerConfig}
            />
          )}
        </main>
      </div>

      <div
        className={`sidebar-backdrop ${sidebarOpen ? 'open' : ''}`}
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />
      <aside
        id="fleet-sidebar"
        className={`sidebar-drawer ${sidebarOpen ? 'open' : ''}`}
        aria-hidden={!sidebarOpen}
      >
        <Sidebar
          birdFilter={birdFilter}
          setBirdFilter={setBirdFilter}
          birdList={birdList}
          selectedBird={selectedBird}
          setSelectedBird={setSelectedBird}
          fleetStats={fleetStats}
          systemRange={systemRange}
        />
      </aside>

      <footer className="app-footer">
        <div>Backend: {backendStatusLabel}</div>
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

      <ToastStack toasts={toasts} />
    </div>
  )
}
