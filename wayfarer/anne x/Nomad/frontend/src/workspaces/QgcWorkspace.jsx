import React from 'react'
import Panel from '../components/Panel'

export default function QgcWorkspace({
  selectedBird,
  selectedBirdMode,
  selectedMode,
  setSelectedMode,
  armReady,
  setArmReady,
  sendModeCommand,
  sendArmCommand,
  mapScope,
  setMapScope,
  selectedBirdTelemetry,
  focusQgcMapOnBirds
}) {
  return (
    <div className="grid">
      <Panel title="QGC Control">
        <div className="controls">
          <div className="status-grid">
            <div>
              <div className="label">Selected bird</div>
              <div className="mono">{selectedBird ? `Bird ${selectedBird}` : 'none'}</div>
            </div>
            <div>
              <div className="label">Current mode</div>
              <div className="mono">{selectedBirdMode}</div>
            </div>
          </div>
          <div className="field">
            <label>Mode selection</label>
            <div className="field-row">
              <select value={selectedMode} onChange={(e) => setSelectedMode(e.target.value)} className="input">
                {['AUTO', 'GUIDED', 'LOITER', 'RTL', 'HOLD', 'MISSION', 'STABILIZE'].map(mode => (
                  <option key={mode} value={mode}>{mode}</option>
                ))}
              </select>
              <button onClick={sendModeCommand}>Set mode</button>
            </div>
          </div>
          <div className="field">
            <label>Arming</label>
            <div className="field-row">
              <label className="toggle">
                <input type="checkbox" checked={armReady} onChange={(e) => setArmReady(e.target.checked)} />
                <span>Enable arm</span>
              </label>
              <button className="primary" disabled={!armReady} onClick={async () => { await sendArmCommand(true); setArmReady(false) }}>Arm</button>
              <button onClick={async () => { await sendArmCommand(false) }}>Disarm</button>
            </div>
          </div>
        </div>
      </Panel>
      <Panel title="Multi-drone Map" actions={(
        <div className="segmented">
          <button className={mapScope === 'all' ? 'active' : ''} onClick={() => setMapScope('all')}>All birds</button>
          <button className={mapScope === 'selected' ? 'active' : ''} onClick={() => setMapScope('selected')}>Selected only</button>
          <button onClick={focusQgcMapOnBirds}>Focus birds</button>
        </div>
      )}>
        <div id="qgc-map" className="map-shell" />
      </Panel>
      <Panel title="Selected Bird Stream">
        <div className="telemetry-list">
          {selectedBirdTelemetry.length === 0 ? (
            <div className="empty">No telemetry for this bird yet.</div>
          ) : (
            selectedBirdTelemetry.map((t, i) => (
              <div key={i} className="telemetry-row">
                <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                <div className="telemetry-topic">{t.topic}</div>
                <div className="telemetry-msg">{t.msg}</div>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  )
}
