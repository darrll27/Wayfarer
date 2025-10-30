import React, { useEffect, useState } from 'react'
import DroneIcon from '../components/DroneIcon.jsx'
import { useMqtt } from '../components/MqttProvider.jsx'

function timeAgo(ts) {
  if (!ts) return 'n/a'
  const s = Math.max(0, Math.round((Date.now() - ts) / 1000))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return `${m}m`
}

function isAlive(entry, now, hbTimeoutMs = 3000) {
  if (!entry) return false
  return !!(entry.hbTs && (now - entry.hbTs) < hbTimeoutMs)
}

export default function Groups() {
  const { telemetry, version } = useMqtt()
  const [config, setConfig] = useState({ groups: [], topic_prefix: 'wayfarer/v1' })

  useEffect(() => {
    let mounted = true
    fetch('/api/config').then(r => r.json()).then(c => { if (mounted) setConfig(c) })
    return () => { mounted = false }
  }, [])

  return (
    <>
      {config.groups.map(g => (
        <div key={g.name} className="card">
          <h2>Group {g.name}</h2>
          <div className="kv">
            {g.sysids && g.sysids.length > 0 ? g.sysids.map(id => {
              const t = telemetry.get(String(id))
              const alive = isAlive(t, Date.now())
              return (
                <React.Fragment key={id}>
                  <span style={{ display:'flex', alignItems:'center', gap:8 }}>
                    <DroneIcon alive={alive} />
                    SysID {id}
                  </span>
                  <div>
                    chk #{t?.checkpoint ?? '—'}
                    {' '}
                    <span className="muted">({timeAgo(t?.ts)} ago)</span>
                  </div>
                </React.Fragment>
              )
            }) : (
              <>
                <span>SysIDs</span><div>—</div>
              </>
            )}
          </div>
        </div>
      ))}
    </>
  )
}
