import React, { useEffect, useState } from 'react'
import apiFetch from '../api'

export default function SettingsPage() {
  const [cfg, setCfg] = useState<any>(null)
  const [raw, setRaw] = useState('')

  useEffect(() => {
    apiFetch('/config').then((r) => r.json()).then((d) => {
      setCfg(d)
      setRaw(JSON.stringify(d, null, 2))
    }).catch(() => {})
  }, [])

  async function save() {
    try {
      const parsed = JSON.parse(raw)
      const res = await apiFetch('/config', { method: 'POST', body: JSON.stringify(parsed) })
      await res.json()
      setCfg(parsed)
    } catch (e: any) {
      alert('save error: ' + String(e))
    }
  }

  return (
    <div>
      <h2>Settings (canonical config)</h2>
      <div>
        <textarea className="mono" style={{ width: '100%', height: '55vh', maxHeight: 720, background: 'var(--card)' }} value={raw} onChange={(e) => setRaw(e.target.value)} />
      </div>
      <div style={{ marginTop: 8 }}>
        <button className="primary" onClick={save}>Save</button>
      </div>
    </div>
  )
}
