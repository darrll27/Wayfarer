import React from 'react'
import Panel from '../components/Panel'

export default function MissionsWorkspace({
  loadWaypointFiles,
  selectedMission,
  setSelectedMission,
  showFlightPaths,
  setShowFlightPaths,
  wpFiles,
  groupWaypointFiles,
  drawFileOnMap,
  sendToDronePrompt,
  selectedFile,
  setSelectedFile,
  sendSysid,
  setSendSysid,
  sendCompid,
  setSendCompid,
  sendToDrone,
  downloadSysid,
  setDownloadSysid,
  downloadCompid,
  setDownloadCompid,
  downloadMissionFromDrone,
  downloadFromAllDrones
}) {
  return (
    <div className="grid">
      <Panel title="Mission Map">
        <div id="map" className="map-shell" />
      </Panel>
      <Panel
        title="Mission Controls"
        actions={<button className="ghost" onClick={loadWaypointFiles}>Refresh</button>}
      >
        <div className="controls">
          <div className="field">
            <label>Select Mission</label>
            <select value={selectedMission} onChange={(e) => setSelectedMission(e.target.value)} className="input">
              {Object.keys(groupWaypointFiles(wpFiles)).map((mission) => (
                <option key={mission} value={mission}>{mission}</option>
              ))}
              <option value="">-- All Missions --</option>
            </select>
          </div>
          <div className="button-row">
            <button onClick={async () => { try { await fetch('/api/waypoints/demo', {method: 'POST'}); await loadWaypointFiles() } catch (e) { console.error(e) } }}>Create demo waypoints</button>
            <button onClick={() => setShowFlightPaths(!showFlightPaths)}>{showFlightPaths ? 'Hide' : 'Show'} onboard paths</button>
          </div>
        </div>
      </Panel>
      <Panel title="Waypoint Files">
        <div className="file-list">
          {wpFiles.length === 0 ? (
            <div className="empty">No waypoint files. Create demo files or upload from Settings.</div>
          ) : (
            Object.entries(groupWaypointFiles(wpFiles))
              .filter(([mission]) => !selectedMission || mission === selectedMission)
              .map(([mission, groups]) => (
                <div key={mission} className="file-group">
                  <div className="file-group-title">Mission: {mission}</div>
                  {Object.entries(groups).map(([group, files]) => (
                    <div key={group} className="file-subgroup">
                      <div className="file-subgroup-title">Group: {group}</div>
                      {files.map((f) => (
                        <div key={f.filename} className="file-row">
                          <div>
                            <div className="file-name">{f.filename}</div>
                            <div className="muted">count: {f.count} valid: {String(f.valid)}</div>
                          </div>
                          <div className="file-actions">
                            <button onClick={async () => { setSelectedFile(f.filename); await drawFileOnMap(f.filename) }}>Show</button>
                            <button onClick={async () => { await sendToDronePrompt(f.filename) }}>Send</button>
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              ))
          )}
        </div>
      </Panel>
      <Panel title="Manual Send">
        <div className="controls">
          <div className="field-row">
            <label>sysid</label>
            <input type="number" value={sendSysid} onChange={(e) => setSendSysid(Number(e.target.value))} className="input" />
            <label>compid</label>
            <input type="number" value={sendCompid} onChange={(e) => setSendCompid(Number(e.target.value))} className="input" />
          </div>
          <select value={selectedFile || ''} onChange={(e) => setSelectedFile(e.target.value)} className="input">
            <option value="">-- select file --</option>
            {Object.entries(groupWaypointFiles(wpFiles)).map(([mission, groups]) =>
              Object.entries(groups).map(([group, files]) =>
                files.map(f => (
                  <option key={f.filename} value={f.filename}>
                    {mission}/{group}/{f.filename}
                  </option>
                ))
              )
            )}
          </select>
          <div className="button-row">
            <button onClick={async () => { if (selectedFile) await sendToDrone({sysid: sendSysid, compid: sendCompid, filename: selectedFile}) }}>Send to Drone</button>
          </div>
        </div>
      </Panel>
      <Panel title="Download Mission">
        <div className="controls">
          <div className="field-row">
            <label>sysid</label>
            <input type="number" value={downloadSysid || 1} onChange={(e) => setDownloadSysid(Number(e.target.value))} className="input" />
            <label>compid</label>
            <input type="number" value={downloadCompid || 1} onChange={(e) => setDownloadCompid(Number(e.target.value))} className="input" />
          </div>
          <div className="button-row">
            <button onClick={async () => { await downloadMissionFromDrone({sysid: downloadSysid || 1, compid: downloadCompid || 1}) }}>Download from Drone</button>
            <button className="primary" onClick={downloadFromAllDrones}>Download from All Drones</button>
          </div>
        </div>
      </Panel>
    </div>
  )
}
