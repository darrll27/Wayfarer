import React, { useEffect, useMemo, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useMqtt } from '../components/MqttProvider.jsx'

export default function MapView() {
  const { telemetry, version } = useMqtt()
  const [params, setParams] = useSearchParams()
  const mapRef = useRef(null)
  const mapObjRef = useRef(null)
  const markersRef = useRef(new Map())
  const missionLayersRef = useRef(new Map()) // sysid -> { polyline, markers: [] }
  const HB_TIMEOUT_MS = 8000
  const sysids = useMemo(() => Array.from(telemetry.values()).map(e => String(e.sysid)).sort((a,b)=>Number(a)-Number(b)), [telemetry, version])
  const selected = params.get('sysid') || ''
  const hasFittedRef = useRef(false)

  // Init map
  useEffect(() => {
    if (mapObjRef.current) return
    const L = window.L
    if (!L) return
    const map = L.map(mapRef.current).setView([37.4, -122.0], 11)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map)
    mapObjRef.current = map
  }, [])

  // Update markers and overlays when telemetry changes
  useEffect(() => {
    const map = mapObjRef.current
    const L = window.L
    if (!map || !L) return
    const selected = params.get('sysid')
    const allLatlngs = []
    telemetry.forEach((e) => {
      const key = String(e.sysid)
      const labelText = `${e.group ? e.group + ' · ' : ''}SysID ${e.sysid}`

      // Mission overlay first: independent of current GPS availability
      const items = e.mission?.items || []
      const havePath = Array.isArray(items) && items.length > 0
      let layers = missionLayersRef.current.get(key)
      if (havePath) {
        const latlngs = items
          .filter(pt => typeof pt.lat === 'number' && typeof pt.lon === 'number')
          .map(pt => [pt.lat, pt.lon])
        if (latlngs.length) {
          allLatlngs.push(...latlngs)
        }
        if (!layers) {
          const poly = L.polyline(latlngs, { color: (selected === key ? '#00ffd5' : '#7a9cff'), weight: (selected === key ? 3 : 2), opacity: 0.9 }).addTo(map)
          const cps = []
          latlngs.forEach((ll, idx) => {
            const isCurrent = (typeof e.checkpoint === 'number') && (idx === e.checkpoint)
            const mk = L.circleMarker(ll, { radius: isCurrent ? 6 : 4, color: isCurrent ? '#ffd517' : (selected === key ? '#00ffd5' : '#7a9cff'), fillOpacity: 0.6 }).addTo(map)
            mk.bindTooltip(String(idx), { permanent: true, direction: 'center', className: 'leaflet-tooltip-own' })
            cps.push(mk)
          })
          // Add a label marker at the polyline center
          const center = L.latLngBounds(latlngs).getCenter()
          const labelIcon = L.divIcon({ className: `overlay-label ${selected === key ? 'selected' : ''}`, html: `<div>${labelText}</div>` })
          const label = L.marker(center, { icon: labelIcon, interactive: false }).addTo(map)
          missionLayersRef.current.set(key, { polyline: poly, markers: cps, label, count: latlngs.length })
        } else {
          // Update polyline
          layers.polyline.setLatLngs(latlngs)
          layers.polyline.setStyle({ color: (selected === key ? '#00ffd5' : '#7a9cff'), weight: (selected === key ? 3 : 2), opacity: 0.9 })
          // Rebuild markers if count changed; else update styles/positions
          if (layers.count !== latlngs.length) {
            layers.markers.forEach(mk => { try { map.removeLayer(mk) } catch {} })
            const cps = []
            latlngs.forEach((ll, idx) => {
              const isCurrent = (typeof e.checkpoint === 'number') && (idx === e.checkpoint)
              const mk = L.circleMarker(ll, { radius: isCurrent ? 6 : 4, color: isCurrent ? '#ffd517' : (selected === key ? '#00ffd5' : '#7a9cff'), fillOpacity: 0.6 }).addTo(map)
              mk.bindTooltip(String(idx), { permanent: true, direction: 'center', className: 'leaflet-tooltip-own' })
              cps.push(mk)
            })
            layers.markers = cps
            layers.count = latlngs.length
          } else {
            layers.markers.forEach((mk, idx) => {
              const ll = latlngs[idx]
              if (!ll) return
              mk.setLatLng(ll)
              const isCurrent = (typeof e.checkpoint === 'number') && (idx === e.checkpoint)
              mk.setStyle({ radius: isCurrent ? 6 : 4, color: isCurrent ? '#ffd517' : (selected === key ? '#00ffd5' : '#7a9cff') })
            })
          }
          // Update label position and style
          try {
            const center = L.latLngBounds(latlngs).getCenter()
            layers.label.setLatLng(center)
            layers.label.setIcon(L.divIcon({ className: `overlay-label ${selected === key ? 'selected' : ''}`, html: `<div>${labelText}</div>` }))
          } catch {}
        }
      } else if (layers) {
        try { map.removeLayer(layers.polyline) } catch {}
        layers.markers.forEach(mk => { try { map.removeLayer(mk) } catch {} })
        try { map.removeLayer(layers.label) } catch {}
        missionLayersRef.current.delete(key)
      }

      // Vehicle marker and status, only if we have a current location
      if (typeof e.lat === 'number' && typeof e.lon === 'number') {
        let m = markersRef.current.get(key)
        const alive = !!(e.hbTs && (Date.now() - e.hbTs) < HB_TIMEOUT_MS)
        const color = alive ? (selected === key ? '#00ffd5' : '#17ffd8') : '#e35b5b'
        if (!m) {
          m = L.circleMarker([e.lat, e.lon], { radius: (selected === key ? 8 : 6), color }).addTo(map)
          m.bindPopup(`SysID ${e.sysid}${e.group ? ' ('+e.group+')' : ''}`)
          try { m.bindTooltip(labelText, { permanent: true, direction: 'right', offset: [8, 0], className: 'overlay-label-point' }) } catch {}
          markersRef.current.set(key, m)
        } else {
          m.setLatLng([e.lat, e.lon])
          m.setStyle({ color, radius: (selected === key ? 8 : 6) })
          // Update tooltip content if present
          try { const tt = m.getTooltip && m.getTooltip(); if (tt) tt.setContent(labelText) } catch {}
        }
      }
    })
    // Center on selected sysid, else auto-fit to all overlays once
    if (selected && telemetry.get(selected) && typeof telemetry.get(selected).lat === 'number') {
      const e = telemetry.get(selected)
      map.setView([e.lat, e.lon], 18)
    } else if (!hasFittedRef.current && allLatlngs.length > 0) {
      try {
        map.fitBounds(L.latLngBounds(allLatlngs), { padding: [24, 24] })
        hasFittedRef.current = true
      } catch {}
    }
  }, [telemetry, version, params])

  // Cleanup on unmount: remove map to avoid stale instance reuse issues
  useEffect(() => {
    return () => {
      try {
        if (mapObjRef.current) {
          mapObjRef.current.remove()
        }
      } catch {}
      mapObjRef.current = null
      markersRef.current.forEach(mk => { try { mk.remove() } catch {} })
      missionLayersRef.current.forEach(l => {
        try { l.polyline.remove() } catch {}
        l.markers.forEach(mk => { try { mk.remove() } catch {} })
      })
      markersRef.current.clear()
      missionLayersRef.current.clear()
    }
  }, [])

  return (
    <div className="card" style={{ gridColumn:'1 / -1', height:'calc(100vh - 140px)' }}>
      <div className="row" style={{ justifyContent:'space-between', alignItems:'center' }}>
        <h2>Map {selected ? `— Selected: SysID ${selected}` : ''}</h2>
        <div className="row" style={{ gap:8, alignItems:'center' }}>
          <label htmlFor="sysidPick">SysID:</label>
          <select id="sysidPick" value={selected} onChange={(e) => setParams(e.target.value ? { sysid: e.target.value } : {})}>
            <option value="">(none)</option>
            {sysids.map(id => <option key={id} value={id}>{id}</option>)}
          </select>
          <button className="btn" onClick={() => {
            const map = mapObjRef.current
            const L = window.L
            if (!map || !L || !selected) return
            const layers = missionLayersRef.current.get(String(selected))
            if (layers && layers.polyline) {
              try { map.fitBounds(layers.polyline.getBounds(), { padding:[20,20] }) } catch {}
            } else {
              const e = telemetry.get(String(selected))
              if (e && typeof e.lat === 'number' && typeof e.lon === 'number') {
                try { map.setView([e.lat, e.lon], 18) } catch {}
              }
            }
          }}>Fit</button>
          {selected && <button className="btn" onClick={() => setParams({})}>Clear</button>}
        </div>
      </div>
      <div ref={mapRef} style={{ height:'100%', borderRadius:8, overflow:'hidden' }} />
      {selected && (
        <div className="card" style={{ marginTop:12 }}>
          <h3>Mission Debug — SysID {selected}</h3>
          {(() => {
            const e = telemetry.get(String(selected))
            const m = e?.mission
            if (!e) return <div className="info">No telemetry cached yet for this sysid.</div>
            if (!m) return <div className="info">No mission cached yet. Waiting for mission upload topics…</div>
            const items = Array.isArray(m.items) ? m.items : []
            const dbg = m.debug || {}
            return (
              <div>
                <div className="kv">
                  <span>Items (absolute)</span><div>{items.length}</div>
                  <span>Total received</span><div>{dbg.totalReceived ?? 'n/a'}</div>
                  <span>Topic</span><div style={{overflow:'hidden', textOverflow:'ellipsis'}}>{dbg.topic || '(unknown)'}</div>
                  <span>Received</span><div>{m.ts ? new Date(m.ts).toLocaleTimeString() : 'n/a'}</div>
                </div>
                {items.length === 0 && <div className="info">All mission items might be relative (x,y,z) — overlay requires lat/lon. If you expect absolute waypoints, check publisher payload.</div>}
                {items.length > 0 && (
                  <div style={{ marginTop:8 }}>
                    <div style={{ fontWeight:600, marginBottom:4 }}>Checkpoints (first 50)</div>
                    <pre style={{ maxHeight: 200, overflow:'auto', background:'#0c1320', padding:8, borderRadius:6 }}>
{items.slice(0,50).map((pt, idx) => `${idx}: lat=${pt.lat?.toFixed?.(6) ?? pt.lat}, lon=${pt.lon?.toFixed?.(6) ?? pt.lon}, alt=${pt.alt ?? ''}`).join('\n')}
                    </pre>
                  </div>
                )}
              </div>
            )
          })()}
        </div>
      )}
    </div>
  )
}
