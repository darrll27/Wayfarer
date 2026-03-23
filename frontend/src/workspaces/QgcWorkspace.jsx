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
  setQgcScopeAndFocus,
  qgcMapView,
  setQgcMapView,
  focusQgcMapOnBirds
}) {
  const handleMapViewChange = (nextView) => {
    setQgcMapView((current) => (current === nextView ? current : nextView))
  }

  return (
    <div className="grid qgc-grid">
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
      <Panel className="qgc-map-panel" title="Multi-drone Map" actions={(
        <div className="panel-actions">
          <div className="segmented">
            <button className={qgcMapView === 'map' ? 'active' : ''} onClick={() => handleMapViewChange('map')}>Map</button>
            <button className={qgcMapView === 'satellite' ? 'active' : ''} onClick={() => handleMapViewChange('satellite')}>Satellite</button>
          </div>
          <div className="segmented">
            <button className={mapScope === 'all' ? 'active' : ''} onClick={() => setQgcScopeAndFocus('all')}>All birds</button>
            <button className={mapScope === 'selected' ? 'active' : ''} onClick={() => setQgcScopeAndFocus('selected')}>Selected only</button>
            <button onClick={focusQgcMapOnBirds}>Focus birds</button>
          </div>
        </div>
      )}>
        <div id="qgc-map" className="map-shell" />
      </Panel>
    </div>
  )
}
