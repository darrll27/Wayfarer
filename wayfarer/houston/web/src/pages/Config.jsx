import React, { useEffect, useState } from 'react'

export default function Config() {
  const [text, setText] = useState('')
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    let mounted = true
    fetch('/api/config').then(r => r.json()).then(c => {
      if (mounted) setText(JSON.stringify(c, null, 2))
    })
    return () => { mounted = false }
  }, [])

  const onSave = async () => {
    setMsg('')
    setSaving(true)
    try {
      const body = JSON.parse(text)
      const res = await fetch('/api/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
      const out = await res.json()
      if (!res.ok) throw new Error(out?.error || 'Failed to save')
      setMsg('Saved!')
    } catch (e) {
      setMsg(`Error: ${e.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="card" style={{ gridColumn: '1 / -1' }}>
      <h2>Houston Config</h2>
      <div className="row" style={{ marginBottom: 8 }}>
        <button className="btn" onClick={onSave} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>
        {msg && <div className={msg.startsWith('Error') ? 'warn' : 'info'}>{msg}</div>}
      </div>
      <textarea value={text} onChange={e => setText(e.target.value)} spellCheck={false} />
    </div>
  )
}
