import React from 'react'
import Panel from '../components/Panel'

export default function SettingsWorkspace({
  handleFileInput,
  uploadRawWaypoint,
  dataLossGraceMs,
  setDataLossGraceMs
}) {
  return (
    <div className="grid">
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
