import React, {useCallback, useEffect, useMemo, useRef, useState} from 'react'
import Panel from '../components/Panel'
import {evaluateBirdStatus, splitBirdGroups} from '../hooks/useBirds'

const DEFAULT_MAP_CENTER = [37.468, -122.087]
const DEFAULT_MAP_ZOOM = 11
const BIRD_COLORS = ['#22d3ee', '#34d399', '#f59e0b', '#f472b6', '#a78bfa', '#fb7185', '#2dd4bf', '#60a5fa']

function formatGpsFix(bird) {
  const hasPosition = bird && bird.lat !== null && bird.lon !== null
  if (!hasPosition) return 'No Fix'
  const fixType = bird && bird.metrics ? bird.metrics.gpsFix : undefined
  const value = Number(fixType)
  if (!Number.isFinite(value)) return 'Unknown'
  if (value <= 1) return 'No Fix'
  if (value === 2) return '2D'
  if (value === 3) return '3D'
  if (value === 4) return 'DGPS'
  if (value === 5) return 'RTK Float'
  if (value === 6) return 'RTK Fixed'
  return `Type ${value}`
}

function formatDop(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0 || n >= 65535) return 'n/a'
  return (n / 100).toFixed(1)
}

function getBatteryPercent(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return null
  return Math.max(0, Math.min(100, Math.round(n)))
}

export default function OverviewWorkspace({birdList, telemetry, sendLoadWaypointsDemo, systemRange}) {
  const now = Date.now()
  const {birds, nonBirds} = splitBirdGroups(birdList || [], systemRange)
  const [mapView, setMapView] = useState('map')
  const airLocations = useMemo(
    () => birds.filter((bird) => bird.lat !== null && bird.lon !== null),
    [birds]
  )
  const mapContainerRef = useRef(null)
  const mapRef = useRef(null)
  const mapMarkersRef = useRef([])
  const mapBaseLayerRef = useRef(null)
  const hasAutoFocusedRef = useRef(false)
  const live = birds.filter((b) => evaluateBirdStatus(b, now).isLive)
  const dead = birds.length - live.length
  const ready = birds.filter((b) => evaluateBirdStatus(b, now).isReady)
  const notReady = birds.length - ready.length
  const birdById = new Map()
  birds.forEach((bird) => {
    const id = Number(bird.sysid)
    if (Number.isInteger(id) && id >= 1 && id <= 90 && !birdById.has(id)) {
      birdById.set(id, bird)
    }
  })
  const ids = Array.from({length: 90}, (_, i) => i + 1)

  const focusBirds = useCallback(() => {
    if (!window.L || !mapRef.current) return
    if (airLocations.length === 0) {
      mapRef.current.setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM)
      return
    }
    const points = airLocations.map((bird) => [bird.lat, bird.lon])
    if (points.length === 1) {
      mapRef.current.setView(points[0], Math.max(mapRef.current.getZoom(), 14))
      return
    }
    mapRef.current.fitBounds(window.L.latLngBounds(points).pad(0.3), {maxZoom: 16})
  }, [airLocations])

  const updateBaseLayer = useCallback(() => {
    if (!window.L || !mapRef.current) return
    if (mapBaseLayerRef.current) {
      try { mapRef.current.removeLayer(mapBaseLayerRef.current) } catch (e) {}
      mapBaseLayerRef.current = null
    }
    const layer = mapView === 'satellite'
      ? window.L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri',
        maxNativeZoom: 19,
        maxZoom: 24
      })
      : window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
        maxNativeZoom: 19,
        maxZoom: 24
      })
    layer.addTo(mapRef.current)
    mapBaseLayerRef.current = layer
  }, [mapView])

  useEffect(() => {
    let cancelled = false

    const setup = () => {
      if (cancelled) return
      if (!window.L || !mapContainerRef.current) {
        window.setTimeout(setup, 150)
        return
      }
      if (mapRef.current) return
      mapRef.current = window.L.map(mapContainerRef.current, {
        zoomControl: true,
        attributionControl: true
      }).setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM)
      updateBaseLayer()
      window.L.control.scale({position: 'bottomleft', metric: true, imperial: false}).addTo(mapRef.current)
    }

    setup()
    return () => {
      cancelled = true
      if (mapRef.current) {
        mapRef.current.remove()
        mapRef.current = null
      }
      mapMarkersRef.current = []
      mapBaseLayerRef.current = null
    }
  }, [updateBaseLayer])

  useEffect(() => {
    if (!mapRef.current) return
    updateBaseLayer()
  }, [updateBaseLayer])

  useEffect(() => {
    if (!window.L || !mapRef.current) return

    mapMarkersRef.current.forEach((layer) => {
      try { layer.remove() } catch (e) {}
    })
    mapMarkersRef.current = []

    if (airLocations.length === 0) {
      hasAutoFocusedRef.current = false
      mapRef.current.setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM)
      return
    }

    airLocations.forEach((bird, index) => {
      const status = evaluateBirdStatus(bird, now)
      const hue = BIRD_COLORS[index % BIRD_COLORS.length]
      const rotation = Number.isFinite(Number(bird.metrics && bird.metrics.heading)) ? Number(bird.metrics.heading) : 0
      const iconStateClass = [
        status.isLive ? '' : 'muted',
        'overview-bird-icon'
      ].filter(Boolean).join(' ')
      const idStateClass = [
        status.isLive ? '' : 'muted',
        'overview-bird-id'
      ].filter(Boolean).join(' ')
      const icon = window.L.divIcon({
        className: 'qgc-bird-marker overview-bird-marker',
        html: `<div class="qgc-bird-wrap"><div class="qgc-bird-icon ${iconStateClass}" style="transform: rotate(${rotation}deg); border-color: ${hue}; color: ${hue};">➤</div><div class="qgc-bird-id ${idStateClass}" style="border-color: ${hue}; color: ${hue};">${bird.sysid}</div></div>`,
        iconSize: [54, 40],
        iconAnchor: [18, 18]
      })
      const marker = window.L.marker([bird.lat, bird.lon], {icon}).addTo(mapRef.current)
      marker.bindTooltip(
        `Air ${bird.sysid}<br/>${bird.lat.toFixed(5)}, ${bird.lon.toFixed(5)}<br/>${bird.metrics.alt ?? bird.metrics.hudAlt ?? 'n/a'} m`,
        {permanent: false}
      )
      mapMarkersRef.current.push(marker)
    })

    if (!hasAutoFocusedRef.current) {
      focusBirds()
      hasAutoFocusedRef.current = true
    }
  }, [airLocations, now, focusBirds])

  return (
    <div className="grid">
      <Panel title="Fleet Summary" actions={<button className="ghost" onClick={sendLoadWaypointsDemo}>Send demo waypoints</button>}>
        <div className="stat-grid">
          <div className="stat"><div className="stat-label">Birds</div><div className="stat-value">{birds.length}</div></div>
          <div className="stat"><div className="stat-label">Live</div><div className="stat-value">{live.length}</div></div>
          <div className="stat"><div className="stat-label">Dead</div><div className="stat-value">{dead}</div></div>
          <div className="stat"><div className="stat-label">Ready</div><div className="stat-value">{ready.length}</div></div>
          <div className="stat"><div className="stat-label">Not Ready</div><div className="stat-value">{notReady}</div></div>
          <div className="stat"><div className="stat-label">Ground Systems</div><div className="stat-value">{nonBirds.length}</div></div>
        </div>
        <div className="matrix-legend">
          <span className="legend-item"><span className="legend-dot ready" />Ready (green pulse)</span>
          <span className="legend-item"><span className="legend-dot not-ready pulse-red" />Not Ready (red pulse)</span>
          <span className="legend-item"><span className="legend-dot missing" />Missing</span>
        </div>
        <div className="status-matrix" aria-label="Bird IDs 1 to 90 matrix (15 rows x 6 columns)">
          {ids.map((id) => {
            const bird = birdById.get(id)
            if (!bird) {
              return <div key={id} className="status-light missing" title={`Bird ${id}: missing`}>{id}</div>
            }
            const {isLive, isReady} = evaluateBirdStatus(bird, now)
            const stateClass = !isLive ? 'stale' : (isReady ? 'ready' : 'not-ready')
            const pulseClass = isLive ? (isReady ? 'pulse-green' : 'pulse-red') : ''
            return (
              <div
                key={id}
                className={`status-light ${stateClass} ${pulseClass}`}
                title={`Bird ${id}: ${!isLive ? 'stale' : (isReady ? 'ready' : 'not ready')}${isLive ? ' (live)' : ''}`}
              >
                {id}
              </div>
            )
          })}
        </div>
      </Panel>

      <Panel title="Bird Status">
        <div className="summary-bird-grid">
          {birds.length === 0 ? (
            <div className="empty">No birds observed yet.</div>
          ) : (
            <>
              {birds.length > 0 && (
                <div className="group-separator group-separator-air summary-separator">
                  <span>Air</span>
                </div>
              )}
              {birds.map((bird) => {
                const {isLive, isReady} = evaluateBirdStatus(bird, now)
                const batteryPct = getBatteryPercent(bird.metrics && bird.metrics.battery)
                return (
                  <div key={bird.sysid} className="summary-bird-card summary-air-card">
                    <div className="summary-bird-head">
                      <div className="bird-title">Bird {bird.sysid}</div>
                      <span className={`status-dot ${isLive ? 'live pulse' : 'dead'}`} title={isLive ? 'live telemetry' : 'dead'} />
                    </div>
                    <div className="summary-bird-row">
                      <span className={`ready-pill ${isReady ? 'ready' : 'not-ready'}`}>{isReady ? 'READY' : 'NOT READY'}</span>
                      <span className="bird-meta">GPS {bird.gpsCount ?? 'n/a'}</span>
                    </div>
                    <div className="bird-meta">
                      GPS Fix: {formatGpsFix(bird)}
                    </div>
                    <div className="bird-meta">
                      HDOP {formatDop(bird.metrics && bird.metrics.eph)} · VDOP {formatDop(bird.metrics && bird.metrics.epv)}
                    </div>
                    <div className="summary-bird-row battery-row">
                      <span className="bird-meta">Battery</span>
                      <span className="battery-inline">
                        <span className="battery-meter" aria-label="battery level">
                          <span className="battery-fill" style={{width: `${batteryPct ?? 0}%`}} />
                        </span>
                        <span className="bird-meta battery-value">{batteryPct !== null ? `${batteryPct}%` : 'n/a'}</span>
                      </span>
                    </div>
                  </div>
                )
              })}
              {nonBirds.length > 0 && (
                <>
                  <div className="group-separator group-separator-ground summary-separator">
                    <span>Ground</span>
                  </div>
                  {nonBirds.map((entry) => {
                    const {isLive} = evaluateBirdStatus(entry, now)
                    return (
                      <div key={entry.sysid} className="summary-bird-card summary-nonbird-card">
                        <div className="summary-bird-head">
                          <div className="bird-title">GCS {entry.sysid}</div>
                          <span className={`status-dot ${isLive ? 'live pulse' : 'dead'}`} />
                        </div>
                        <div className="bird-meta">Component {entry.compid ?? 'n/a'}</div>
                        <div className="bird-meta">Last seen {entry.lastSeen ? new Date(entry.lastSeen).toLocaleTimeString() : 'never'}</div>
                        <div className="bird-meta">Mode {entry.metrics && entry.metrics.mode ? entry.metrics.mode : 'unknown'}</div>
                      </div>
                    )
                  })}
                </>
              )}
            </>
          )}
        </div>
      </Panel>

      <Panel
        title="Air Locations"
        className="overview-map-panel"
        actions={(
          <div className="panel-actions">
            <div className="segmented">
              <button className={mapView === 'map' ? 'active' : ''} onClick={() => setMapView('map')}>Map</button>
              <button className={mapView === 'satellite' ? 'active' : ''} onClick={() => setMapView('satellite')}>Satellite</button>
            </div>
            <button onClick={focusBirds}>Focus Birds</button>
          </div>
        )}
      >
        <div className="overview-map-wrap">
          <div ref={mapContainerRef} className="map-shell overview-map-shell" />
          {airLocations.length === 0 ? (
            <div className="overview-map-empty">No air tracks observed yet.</div>
          ) : (
            <div className="overview-map-caption">
              Tracking {airLocations.length} air {airLocations.length === 1 ? 'asset' : 'assets'} with live position.
            </div>
          )}
        </div>
      </Panel>
    </div>
  )
}
