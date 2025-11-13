import React, { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, Polyline, Marker, Popup, useMap } from 'react-leaflet'
import L from 'leaflet'
// import marker images via ESM so the bundler can emit them correctly
import markerIcon2x from 'leaflet/dist/images/marker-icon-2x.png'
import markerIcon from 'leaflet/dist/images/marker-icon.png'
import markerShadow from 'leaflet/dist/images/marker-shadow.png'
import apiFetch from '../api'
import 'leaflet/dist/leaflet.css'

// Fix default icon paths for leaflet in many bundlers
delete (L.Icon.Default.prototype as any)._getIconUrl
L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x as unknown as string,
  iconUrl: markerIcon as unknown as string,
  shadowUrl: markerShadow as unknown as string,
})

function FitBounds({ points }: { points: [number, number][] }) {
  const map = useMap()
  useEffect(() => {
    if (!points || points.length === 0) return
    const bounds = L.latLngBounds(points.map((p) => L.latLng(p[0], p[1])))
    map.fitBounds(bounds, { padding: [40, 40] })
  }, [map, points])
  return null
}

export default function MapPage({ onEdit }: { onEdit?: (group?: string) => void }) {
  const [groups, setGroups] = useState<any>({})
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null)

  useEffect(() => {
    apiFetch('/groups').then((r) => r.json()).then((d) => setGroups(d || {})).catch(() => setGroups({}))
  }, [])

  const allPolylines = useMemo(() => {
    const list: { group: string; sysid: string; coords: [number, number][] }[] = []
    const entries = Object.entries(groups || {}) as [string, any][]
    for (const [gname, group] of entries) {
      const way = group?.waypoints || group?.waypoints_file || null
      // prefer per-drone previews if provided by backend
      const per = group?.per_drone || null
      if (per && typeof per === 'object') {
        for (const [sid, obj] of Object.entries(per)) {
          const coords = (obj as any[]).map((wp: any) => [Number(wp.lat), Number(wp.lon)]) as [number, number][]
          list.push({ group: gname, sysid: sid, coords })
        }
      } else if (Array.isArray(way)) {
        const coords = (way as any[]).map((w: any) => [Number(w.lat), Number(w.lon)]) as [number, number][]
        list.push({ group: gname, sysid: 'group', coords })
      }
    }
    return list
  }, [groups])

  // compute a center point
  const allPoints = allPolylines.flatMap((p) => p.coords)
  const center: [number, number] = allPoints.length ? allPoints[Math.floor(allPoints.length / 2)] : [0, 0]

  return (
    <div>
      <h2>Map (Telemetry)</h2>
      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ minWidth: 240, maxWidth: 360 }}>
          <div style={{ marginBottom: 8 }}>
            <strong>Groups</strong>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {Object.keys(groups).length === 0 && <div className="muted">No groups</div>}
            {Object.entries(groups).map(([gname, g]: any) => (
              <div key={gname} style={{ padding: 8, background: 'var(--card)', borderRadius: 8 }}>
                <div style={{ fontWeight: 700 }}>{gname}</div>
                <div style={{ marginTop: 6, display: 'flex', gap: 8 }}>
                  <button className="ghost" onClick={() => setSelectedGroup(gname)}>Show</button>
                  <button className="ghost" onClick={() => onEdit ? onEdit(gname) : null}>Edit waypoints</button>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ flex: 1 }}>
          <div style={{ height: '70vh', borderRadius: 8, overflow: 'hidden' }}>
            <MapContainer center={center} zoom={6} style={{ height: '100%', width: '100%' }}>
              <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
              {allPolylines.map((p, idx) => (
                <React.Fragment key={idx}>
                  <Polyline positions={p.coords} color={idx % 6 === 0 ? '#00a' : '#a00'} />
                  {p.coords.length > 0 && (
                    <Marker position={p.coords[p.coords.length - 1]}>
                      <Popup>
                        <div>
                          <div><strong>{p.group}</strong></div>
                          <div>sysid: {p.sysid}</div>
                          <div><button className="ghost" onClick={() => onEdit ? onEdit(p.group) : null}>Edit</button></div>
                        </div>
                      </Popup>
                    </Marker>
                  )}
                </React.Fragment>
              ))}
              <FitBounds points={allPoints} />
            </MapContainer>
          </div>
        </div>
      </div>
    </div>
  )
}
