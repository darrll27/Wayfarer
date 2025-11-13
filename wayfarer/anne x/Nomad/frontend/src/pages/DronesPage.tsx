import React, { useEffect, useState } from 'react'
import apiFetch from '../api'

export default function DronesPage() {
  const [groups, setGroups] = useState<any>({})

  useEffect(() => {
    apiFetch('/groups').then((r) => r.json()).then((d) => setGroups(d || {})).catch(() => setGroups({}))
  }, [])

  async function startSerial(bridge: any) {
    try {
      await apiFetch('/serial/start', { method: 'POST', body: JSON.stringify(bridge) })
      // refresh
      const d = await (await apiFetch('/groups')).json()
      setGroups(d)
    } catch (e) {
      console.error(e)
    }
  }

  async function stopSerial(name: string) {
    try {
      await apiFetch('/serial/stop', { method: 'POST', body: JSON.stringify({ name }) })
      const d = await (await apiFetch('/groups')).json()
      setGroups(d)
    } catch (e) {
      console.error(e)
    }
  }

  return (
    <div>
      <h2>Drones & Transports</h2>
      <div style={{ display: 'grid', gap: 12 }}>
        {Object.keys(groups).length === 0 && <div className="muted">No groups defined</div>}
        {Object.entries(groups).map(([g, data]: any) => (
          <div key={g} style={{ padding: 12, background: 'var(--card)', borderRadius: 8 }}>
            <div style={{ fontWeight: 700 }}>{g}</div>
            <div style={{ marginTop: 8 }}>
              <div>Transports: {JSON.stringify(data.transports || {}, null, 2)}</div>
              <div style={{ marginTop: 8 }}>
                <button className="ghost" onClick={() => startSerial({ serial: '/dev/ttyUSB0', baud: 115200 })}>Start serial (example)</button>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
