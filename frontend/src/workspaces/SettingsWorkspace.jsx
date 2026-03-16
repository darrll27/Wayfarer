import React, {useEffect, useState} from 'react'
import Panel from '../components/Panel'

export default function SettingsWorkspace({
  handleFileInput,
  uploadRawWaypoint,
  dataLossGraceMs,
  setDataLossGraceMs,
  systemRange,
  setSystemRange,
  brokerConfig,
  saveBrokerConfig
}) {
  const [openHelp, setOpenHelp] = useState(null)
  const [mode, setMode] = useState('internal')
  const [host, setHost] = useState('localhost')
  const [tcpPort, setTcpPort] = useState(1883)
  const [wsPort, setWsPort] = useState(1884)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (!brokerConfig) return
    setMode(String(brokerConfig.mode || 'internal'))
    setHost(String(brokerConfig.host || 'localhost'))
    setTcpPort(Number(brokerConfig.tcp_port || 1883))
    setWsPort(Number(brokerConfig.ws_port || 1884))
    setUsername(String(brokerConfig.username || ''))
    setPassword(String(brokerConfig.password || ''))
    setNotes(String(brokerConfig.notes || ''))
  }, [brokerConfig])

  const saveBroker = async () => {
    const payload = {
      mode,
      host: String(host || '').trim(),
      tcp_port: Number(tcpPort),
      ws_port: Number(wsPort),
      username: username.trim() ? username.trim() : null,
      password: password.trim() ? password.trim() : null,
      notes: notes.trim() ? notes : null
    }
    if (!payload.host) {
      alert('Broker host is required')
      return
    }
    await saveBrokerConfig(payload)
  }

  const toggleHelp = (key) => {
    setOpenHelp((current) => current === key ? null : key)
  }

  return (
    <div className="grid">
      <Panel title="Settings - Broker Connection">
        <div className="controls">
          <div className="info-banner warn">
            Broker configuration is saved immediately, but broker mode changes and local Aedes process changes are fully applied on the next app restart.
          </div>

          <div className="field">
            <label>Broker Mode</label>
            <select className="input" value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="internal">internal (spawn local Aedes)</option>
              <option value="external">external (use remote broker)</option>
            </select>
            <div className="field-help">
              `internal` starts the bundled local broker. `external` skips local broker startup and connects to the configured remote host.
            </div>
          </div>

          <div className="field">
            <label>Broker Host / IP</label>
            <input
              type="text"
              className="input"
              placeholder="localhost or 192.168.1.100"
              value={host}
              onChange={(e) => setHost(e.target.value)}
            />
          </div>

          <div className="field">
            <div className="label-with-help">
              <label>TCP Port</label>
              <button
                type="button"
                className="info-button"
                aria-label="TCP port help"
                aria-expanded={openHelp === 'tcp'}
                onClick={() => toggleHelp('tcp')}
              >
                i
              </button>
            </div>
            <input
              type="number"
              min="1"
              max="65535"
              className="input"
              value={tcpPort}
              onChange={(e) => setTcpPort(Number(e.target.value))}
            />
            {openHelp === 'tcp' ? (
              <div className="field-help">
                TCP port is used by the Python backend, router, and other native MQTT clients that connect over standard MQTT TCP. Default: `1883`.
              </div>
            ) : null}
          </div>

          <div className="field">
            <div className="label-with-help">
              <label>WebSocket Port (WS)</label>
              <button
                type="button"
                className="info-button"
                aria-label="WebSocket port help"
                aria-expanded={openHelp === 'ws'}
                onClick={() => toggleHelp('ws')}
              >
                i
              </button>
            </div>
            <input
              type="number"
              min="1"
              max="65535"
              className="input"
              value={wsPort}
              onChange={(e) => setWsPort(Number(e.target.value))}
            />
            {openHelp === 'ws' ? (
              <div className="field-help">
                WebSocket port is used by the React and Electron renderer UI when it connects to MQTT from the browser-like frontend runtime. Default: `1884`.
              </div>
            ) : null}
          </div>

          <div className="field">
            <label>Username (optional)</label>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>

          <div className="field">
            <label>Password (optional)</label>
            <input type="password" className="input" value={password} onChange={(e) => setPassword(e.target.value)} />
          </div>

          <div className="field">
            <label>Notes</label>
            <textarea className="input" rows={3} value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>

          <div className="button-row">
            <button className="primary" onClick={saveBroker}>Save Broker Settings</button>
          </div>
        </div>
      </Panel>

      <Panel title="Settings — Waypoint Upload">
        <div className="controls">
          <div className="field">
            <label>Telemetry loss grace (ms)</label>
            <input
              type="number"
              min="1000"
              step="50"
              value={dataLossGraceMs}
              onChange={(e) => {
                const next = Number(e.target.value)
                if (Number.isFinite(next) && next >= 1000) {
                  setDataLossGraceMs(next)
                }
              }}
              className="input"
            />
          </div>
          <div className="field">
            <label>Ground sysid range</label>
            <div className="field-row">
              <input
                type="number"
                min="1"
                max="255"
                value={systemRange.start}
                onChange={(e) => {
                  const next = Number(e.target.value)
                  if (Number.isFinite(next)) {
                    setSystemRange((current) => ({...current, start: next}))
                  }
                }}
                className="input"
              />
              <span className="label">to</span>
              <input
                type="number"
                min="1"
                max="255"
                value={systemRange.end}
                onChange={(e) => {
                  const next = Number(e.target.value)
                  if (Number.isFinite(next)) {
                    setSystemRange((current) => ({...current, end: next}))
                  }
                }}
                className="input"
              />
            </div>
            <div className="field-help">
              Sysids inside this inclusive range are grouped under `Ground`. Everything else is grouped under `Air`.
            </div>
          </div>
          <div className="field">
            <label>Upload a waypoint YAML file (.yaml/.yml)</label>
            <input type="file" accept=".yaml,.yml" onChange={handleFileInput} className="input" />
          </div>
          <div className="field">
            <label>Paste raw YAML and save to filename</label>
            <input id="upload-filename" placeholder="filename.yaml" className="input" />
            <textarea id="upload-raw" rows={8} className="input" placeholder={'waypoints:\n  - lat: ...\n  - ...'} />
            <div className="button-row">
              <button onClick={async () => {
                const fn = document.getElementById('upload-filename').value || `uploaded-${Date.now()}.yaml`
                const raw = document.getElementById('upload-raw').value || ''
                if (!raw) {
                  alert('paste YAML or use file upload')
                  return
                }
                await uploadRawWaypoint(fn, raw)
              }}>Save</button>
            </div>
          </div>
        </div>
      </Panel>
    </div>
  )
}
