import React, { useEffect, useState } from 'react'
import apiFetch from '../api'

export default function WaypointsPage() {
  const [group, setGroup] = useState<string | null>(null)
  const [groups, setGroups] = useState<string[]>([])
  const [text, setText] = useState('')
  const [format, setFormat] = useState<'yaml' | 'json'>('yaml')
  const [message, setMessage] = useState<string | null>(null)

  useEffect(() => {
    apiFetch('/groups')
      .then((r) => r.json())
      .then((d) => {
        const g = Object.keys(d || {})
        setGroups(g)
        // if another page requested a focus group, use it
        const focus = (window as any).NOMAD_FOCUS_GROUP
        if (focus && g.includes(focus)) {
          setGroup(focus)
          try { delete (window as any).NOMAD_FOCUS_GROUP } catch(e) {}
        } else {
          setGroup(g[0] || null)
        }
      })
  }, [])

  useEffect(() => {
    if (!group) return
    apiFetch(`/groups/${group}/waypoints`).then((r) => r.json()).then((d) => {
      const yaml = (window as any).YAML
      const out = format === 'yaml' ? (yaml ? yaml.stringify(d) : JSON.stringify(d, null, 2)) : JSON.stringify(d, null, 2)
      setText(out)
    }).catch(() => setText(''))
  }, [group, format])

  function validate() {
    try {
      const yaml = (window as any).YAML
      const parsed = format === 'yaml' ? (yaml ? yaml.parse(text) : JSON.parse(text)) : JSON.parse(text)
      // very small validation: must be an array of waypoints
      if (!Array.isArray(parsed)) throw new Error('expected array')
      setMessage('Valid')
    } catch (e: any) {
      setMessage(String(e))
    }
  }

  async function save() {
    if (!group) return
    try {
    const yaml = (window as any).YAML
    const parsed = format === 'yaml' ? (yaml ? yaml.parse(text) : JSON.parse(text)) : JSON.parse(text)
      const res = await apiFetch(`/groups/${group}/waypoints`, { method: 'POST', body: JSON.stringify(parsed) })
      await res.json()
      setMessage('Saved')
    } catch (e: any) {
      setMessage(String(e))
    }
  }

  return (
    <div>
      <h2>Waypoints</h2>
      <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
        <select value={group || ''} onChange={(e) => setGroup(e.target.value)}>
          {groups.map((g) => <option key={g} value={g}>{g}</option>)}
        </select>
        <div>
          <label><input type="radio" checked={format === 'yaml'} onChange={() => setFormat('yaml')} /> YAML</label>
          <label style={{ marginLeft: 8 }}><input type="radio" checked={format === 'json'} onChange={() => setFormat('json')} /> JSON</label>
        </div>
        <button className="primary" onClick={validate}>Validate</button>
        <button className="primary" onClick={save}>Save</button>
      </div>

      <div style={{ marginTop: 12 }}>
        <textarea className="mono" style={{ width: '100%', height: '60vh', maxHeight: 720, background: 'var(--card)' }} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      {message && <div style={{ marginTop: 8 }}>{message}</div>}
    </div>
  )
}
