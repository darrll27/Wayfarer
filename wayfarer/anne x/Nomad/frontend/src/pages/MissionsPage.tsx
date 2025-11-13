import React, { useEffect, useState } from 'react'
import apiFetch from '../api'

export default function MissionsPage({ onVerify }: { onVerify: () => Promise<void> }) {
  const [groups, setGroups] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<any | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch('/groups')
      .then((r) => r.json())
      .then((d) => setGroups(Object.keys(d || {})))
      .catch(() => setGroups([]))
  }, [])

  async function sendGroup(group: string) {
    setBusy(true)
    setError(null)
    setResults(null)
    try {
      const res = await apiFetch(`/groups/${group}/send_missions`, { method: 'POST' })
      const data = await res.json()
      setResults({ type: 'send', group, data })
    } catch (e: any) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function verifyGroup(group: string) {
    setBusy(true)
    setError(null)
    setResults(null)
    try {
      const res = await apiFetch(`/groups/${group}/verify_missions`, { method: 'POST' })
      const data = await res.json()
      setResults({ type: 'verify', group, data })
    } catch (e: any) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  function renderResult() {
    if (!results) return null
    if (results.type === 'send') {
      return (
        <div>
          <h3>Send results ({results.group})</h3>
          {(results.data.results || []).map((r: any, i: number) => (
            <div key={i} style={{ padding: 8, borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <div><strong>Drone #{i + 1}</strong></div>
              <div>Status: <span style={{ color: r.ok ? 'lightgreen' : '#f88' }}>{r.ok ? 'OK' : 'ERROR'}</span></div>
              {r.last_sent && <div>last_sent: {r.last_sent}</div>}
              {r.persisted && <div>persisted: {r.persisted}</div>}
              {r.reason && <div style={{ color: '#f88' }}>reason: {r.reason}</div>}
              {r.errors && <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(r.errors, null, 2)}</pre>}
            </div>
          ))}
        </div>
      )
    }
    if (results.type === 'verify') {
      return (
        <div>
          <h3>Verify results ({results.group})</h3>
          {(results.data.results || []).map((r: any, i: number) => (
            <div key={i} style={{ padding: 8, borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
              <div><strong>Drone #{i + 1}</strong></div>
              <div>verified: <span style={{ color: r.verified ? 'lightgreen' : '#f88' }}>{String(r.verified)}</span></div>
              {r.reason && <div style={{ color: '#f88' }}>{r.reason}</div>}
              {r.diffs && r.diffs.length > 0 && <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(r.diffs, null, 2)}</pre>}
            </div>
          ))}
        </div>
      )
    }
    return null
  }

  return (
    <div>
      <h2>Mission Control</h2>
      <div style={{ marginBottom: 12 }}>
        <strong>Groups:</strong>
        <div className="group-grid" style={{ marginTop: 8 }}>
          {groups.length === 0 && <div className="muted">No groups found</div>}
          {groups.map((g) => (
            <div key={g} className="group-card">
              <div style={{ fontWeight: 600 }}>{g}</div>
              <div style={{ marginTop: 8, display: 'flex', gap: 8 }}>
                <button className="primary" onClick={() => sendGroup(g)} disabled={busy}>Send</button>
                <button className="ghost" onClick={() => verifyGroup(g)} disabled={busy}>Verify</button>
              </div>
            </div>
          ))}
        </div>
      </div>

      {busy && <div style={{ marginBottom: 12 }}>Processing...</div>}
      {error && <div style={{ color: '#f88', marginBottom: 12 }}>{error}</div>}

      <div style={{ marginTop: 12 }}>{renderResult()}</div>
    </div>
  )
}
