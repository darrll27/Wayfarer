import React, { useEffect, useState } from 'react'

export default function Streams() {
  const [streams, setStreams] = useState([])
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState({})

  useEffect(() => { loadAll() }, [])

  async function loadAll() {
    setLoading(true)
    try {
      const res = await fetch('/api/streams')
      const data = await res.json()
  const list = data.streams || []
  setStreams(list)
    } catch (e) {
      console.error(e)
      setStreams([])
    } finally { setLoading(false) }
  }

  async function toggle(gid, sid, active) {
    await performAction(gid, sid, active ? 'stop' : 'start')
    await loadAll()
  }

  async function performAction(gid, sid, action) {
    const key = `${gid}:${sid}`
    setPending(p => ({ ...p, [key]: true }))
    try {
      const url = `/api/streams/${gid}/${sid}/${action}`
      const res = await fetch(url, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(()=>({ error: 'unknown' }))
        alert('Action failed: ' + (err.error || JSON.stringify(err)))
        return { ok: false }
      }
      return { ok: true }
    } catch (e) {
      console.error(e)
      alert('Request failed')
      return { ok: false }
    } finally {
      setPending(p => ({ ...p, [key]: false }))
    }
  }

  async function startGroup(groupId) {
    const groupStreams = streams.filter(s => s.group === groupId && !s.active)
    await Promise.all(groupStreams.map(s => performAction(s.group, s.sysid, 'start')))
    await loadAll()
  }

  async function stopGroup(groupId) {
    const groupStreams = streams.filter(s => s.group === groupId && s.active)
    await Promise.all(groupStreams.map(s => performAction(s.group, s.sysid, 'stop')))
    await loadAll()
  }

  async function startAll() {
    const toStart = streams.filter(s => !s.active)
    await Promise.all(toStart.map(s => performAction(s.group, s.sysid, 'start')))
    await loadAll()
  }

  async function stopAll() {
    const toStop = streams.filter(s => s.active)
    await Promise.all(toStop.map(s => performAction(s.group, s.sysid, 'stop')))
    await loadAll()
  }

  // preview toggling removed - streaming controlled only by Start/Stop

  if (loading) return <div className="card">Loading streams...</div>

  // group streams by group id
  const groups = streams.reduce((acc, s) => {
    acc[s.group] = acc[s.group] || []
    acc[s.group].push(s)
    return acc
  }, {})

  return (
    <div style={{ display: 'grid', gap: 20, padding: 12 }}>
      <div className="card row" style={{ justifyContent: 'space-between' }}>
        <div style={{ fontWeight: 700 }}>All Streams</div>
        <div className="row">
          <button className="btn" onClick={startAll}>Start All</button>
          <button className="btn" onClick={stopAll}>Stop All</button>
        </div>
      </div>

      {Object.keys(groups).map(gid => (
        <div key={gid}>
            <div className="card" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', padding: '12px 16px' }}>
              <div style={{ fontWeight: 700, fontSize: 16 }}>{gid}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
                <button className="btn" onClick={() => startGroup(gid)}>Start Group</button>
                <button className="btn" onClick={() => stopGroup(gid)}>Stop Group</button>
              </div>
            </div>

            <div style={{ display: 'flex', gap: 16, flexWrap: 'nowrap', overflowX: 'auto', paddingTop: 12 }}>
            {groups[gid].map(s => {
              const key = `${s.group}:${s.sysid}`
              const isPending = !!pending[key]
              const isPreviewing = !!s.active
              return (
                <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div className="card" style={{ width: 300, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: 12 }}>
                    <div style={{ minWidth: 180 }}>
                      <div style={{ fontSize: 13, fontWeight: 700 }}>{s.group} — Sys {s.sysid}</div>
                      <div className="kv"><span>Host</span><span>{s.effectiveHost}</span></div>
                      <div className="kv"><span>Port</span><span>{s.effectivePort}</span></div>
                      <div className="kv"><span>Codec</span><span>{s.effectiveCodec}</span></div>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
                      <div>{s.active ? <span className="badge">Active</span> : <span className="badge">Inactive</span>}</div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button className="btn" onClick={() => toggle(s.group, s.sysid, s.active)} disabled={isPending}>{isPending ? 'Working…' : (s.active ? 'Stop' : 'Start')}</button>
                        {/* preview button removed; streaming controlled by Start/Stop */}
                      </div>
                    </div>
                  </div>
                  <div style={{ width: 300, height: 200, background: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: 6, overflow: 'hidden' }}>
                    {isPreviewing ? (
                      <img
                        alt={`preview-${key}`}
                        src={`/api/streams/${s.group}/${s.sysid}/mjpeg`}
                        style={{ width: '100%', height: '100%', objectFit: 'cover', background: '#000' }}
                      />
                    ) : null}
                  </div>
                  <div style={{ fontSize: 12, marginTop: 8 }}>
                    Status: {isPreviewing ? 'active' : 'inactive'}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
