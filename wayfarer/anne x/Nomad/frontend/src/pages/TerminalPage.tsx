import React, { useEffect, useState } from 'react'
import apiFetch from '../api'

function getLogs() {
  // global buffer populated by apiFetch
  // @ts-ignore
  return (window.NOMAD_TERMINAL_LOGS || []).slice().reverse()
}

export default function TerminalPage() {
  const [logs, setLogs] = useState<any[]>(getLogs())
  const [rawReq, setRawReq] = useState('GET /config')
  const [lastResp, setLastResp] = useState<any>(null)

  useEffect(() => {
    const t = setInterval(() => setLogs(getLogs()), 400)
    return () => clearInterval(t)
  }, [])

  async function sendRaw() {
    try {
      const [method, path] = rawReq.split(' ', 2)
      const resp = await apiFetch(path, { method: method || 'GET' })
      const j = await resp.text()
      setLastResp(j)
    } catch (e: any) {
      setLastResp(String(e))
    }
  }

  return (
    <div>
      <h2>Terminal</h2>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input style={{ flex: 1 }} value={rawReq} onChange={(e) => setRawReq(e.target.value)} />
        <button className="primary" onClick={sendRaw}>Send</button>
      </div>
      <div style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 700 }}>Last response</div>
        <pre className="terminal-pre" style={{ maxHeight: 220, overflow: 'auto' }}>{String(lastResp)}</pre>
      </div>
      <div style={{ marginTop: 12 }}>
        <div style={{ fontWeight: 700 }}>Recent requests</div>
        <div style={{ maxHeight: 360, overflow: 'auto' }}>
          {logs.map((l) => (
            <div key={l.id} style={{ padding: 8, borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <div style={{ fontSize: 12 }}><strong>{l.method}</strong> {l.url} <span style={{ color: '#888' }}>{l.status || ''}</span></div>
              <pre className="terminal-pre">{JSON.stringify(l, null, 2)}</pre>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
