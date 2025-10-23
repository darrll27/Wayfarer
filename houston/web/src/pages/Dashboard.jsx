import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMqtt } from '../components/MqttProvider.jsx'
import DroneIcon from '../components/DroneIcon.jsx'

function fmt(val, digits = 6) {
  if (val === null || val === undefined || Number.isNaN(val)) return '—'
  if (typeof val === 'number') return val.toFixed(digits)
  return String(val)
}

function timeAgo(ts) {
  if (!ts) return 'n/a'
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  return `${m}m ago`
}

function isAlive(entry, now, hbTimeoutMs = 8000) {
  if (!entry) return false
  return !!(entry.hbTs && (now - entry.hbTs) < hbTimeoutMs)
}

export default function Dashboard() {
  const { telemetry, status, version } = useMqtt()
  const entries = React.useMemo(() => {
    return Array.from(telemetry.values()).sort((a, b) => Number(a.sysid) - Number(b.sysid))
  }, [telemetry, status, version])
  const [selected, setSelected] = useState(null)
  const mapRef = useRef(null)
  const mapObjRef = useRef(null)
  const markerRef = useRef(null)
  const now = Date.now()

  // Clean up the detail map when closing the side pane so it can be recreated cleanly on reopen
  useEffect(() => {
    if (!selected && mapObjRef.current) {
      try { mapObjRef.current.remove() } catch {}
      mapObjRef.current = null
    }
    if (!selected && markerRef.current) {
      try { markerRef.current.remove() } catch {}
      markerRef.current = null
    }
  }, [selected])

  return (
    <>
      <div className="card" style={{ gridColumn: '1 / -1' }}>
        <h2>Live Telemetry</h2>
        <div className="info">Connection: {status}</div>
      </div>

      {entries.length === 0 && (
        <div className="card">
          <h2>No telemetry yet</h2>
          <div className="info">Waiting for messages on pathfinder state topics…</div>
        </div>
      )}

      {entries.map(e => {
        const alive = isAlive(e, now)
        const hbAgo = e.hbTs ? timeAgo(e.hbTs) : 'n/a'
        const msgAgo = e.ts ? timeAgo(e.ts) : 'n/a'
        const pulse = e.hbPulseTs && (now - e.hbPulseTs) < 800
        return (
          <div key={e.sysid} className="card" onClick={() => setSelected(String(e.sysid))} style={{ cursor:'pointer' }}>
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <h2 style={{ display:'flex', alignItems:'center', gap:8 }}>
                <DroneIcon alive={alive} />
                SysID {e.sysid}
                <span className="badge" style={{ marginLeft: 8 }}>{e.group || 'unknown'}</span>
              </h2>
              <div className="row" style={{ gap:8, alignItems:'center' }}>
                <Link
                  to={`/map?sysid=${e.sysid}`}
                  onClick={(ev) => ev.stopPropagation()}
                  className="btn"
                  style={{ padding:'6px 10px' }}
                  title="Open on Map"
                >Map</Link>
                <span className={`hb-badge ${alive ? 'alive' : 'lost'} ${pulse ? 'pulse' : ''}`}>{alive ? 'HEARTBEAT' : 'NO HB'}</span>
              </div>
            </div>
            <div className="kv">
              <span>Checkpoint</span><div>{e.checkpoint ?? '—'}</div>
              <span>Latitude</span><div>{fmt(e.lat, 6)}</div>
              <span>Longitude</span><div>{fmt(e.lon, 6)}</div>
              <span>Altitude</span><div>{fmt(e.alt, 1)} m</div>
              <span>Last HB</span><div>{hbAgo}</div>
              <span>Last Msg</span><div>{msgAgo}</div>
            </div>
          </div>
        )
      })}

      {/* Side detail pane: slides in when a sysid is selected */}
      <SidePane open={!!selected} onClose={() => setSelected(null)}>
        {selected && (
          <DetailPane
            sysid={selected}
            entry={telemetry.get(String(selected))}
            mapRef={mapRef}
            mapObjRef={mapObjRef}
            markerRef={markerRef}
          />
        )}
      </SidePane>
    </>
  )
}

function SidePane({ open, onClose, children }) {
  return (
    <div className={`sidepane ${open ? 'open' : ''}`}>
      <div className="sidepane-header">
        <div className="spacer" />
        <button className="btn" onClick={onClose}>Close</button>
      </div>
      <div className="sidepane-body">
        {children}
      </div>
    </div>
  )
}

function DetailPane({ sysid, entry, mapRef, mapObjRef, markerRef }) {
  const L = window.L
  useEffect(() => {
    if (!L) return
    if (!mapObjRef.current) {
      const map = L.map(mapRef.current).setView([37.4, -122.0], 11)
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; OpenStreetMap contributors'
      }).addTo(map)
      mapObjRef.current = map
      // Ensure proper sizing when pane slides in
      setTimeout(() => { try { map.invalidateSize() } catch {} }, 60)
    }
  }, [L])

  useEffect(() => {
    const map = mapObjRef.current
    if (!map || !L || !entry) return
    try { map.invalidateSize() } catch {}
    if (typeof entry.lat === 'number' && typeof entry.lon === 'number') {
      if (!markerRef.current) {
        markerRef.current = L.circleMarker([entry.lat, entry.lon], { radius: 7, color: '#17ffd8' }).addTo(map)
      } else {
        markerRef.current.setLatLng([entry.lat, entry.lon])
      }
      map.setView([entry.lat, entry.lon], 14)
    }
  }, [entry, L])

  const alive = entry && entry.hbTs && (Date.now() - entry.hbTs) < 3000

  return (
    <div className="card" style={{ background:'transparent', border:'none', boxShadow:'none' }}>
      <h2 style={{ display:'flex', alignItems:'center', gap:8 }}>
        <DroneIcon alive={alive} />
        Details — SysID {sysid}
      </h2>
      <div style={{ height: 260, borderRadius: 8, overflow:'hidden', marginBottom: 12 }} ref={mapRef} />
      <div className="kv">
        <span>Checkpoint</span><div>{entry?.checkpoint ?? '—'}</div>
        <span>Latitude</span><div>{fmt(entry?.lat, 6)}</div>
        <span>Longitude</span><div>{fmt(entry?.lon, 6)}</div>
        <span>Altitude</span><div>{fmt(entry?.alt, 1)} m</div>
        <span>Last HB</span><div>{entry?.hbTs ? timeAgo(entry.hbTs) : 'n/a'}</div>
        <span>Last Msg</span><div>{entry?.ts ? timeAgo(entry.ts) : 'n/a'}</div>
      </div>
    </div>
  )
}
