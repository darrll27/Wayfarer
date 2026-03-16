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
  downloadFromAllDrones,
  missionDownloadStatusBySysid,
  downloadedMissions,
  selectedBird
}) {
  const statusRows = Object.values(missionDownloadStatusBySysid || {}).sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0))
  const missionGroups = groupWaypointFiles(wpFiles)
  const selectedBirdMission = (downloadedMissions || []).find((mission) => Number(mission.sysid) === Number(selectedBird || 0)) || null
  const targetMission = (downloadedMissions || []).find((mission) => Number(mission.sysid) === Number(downloadSysid || 1)) || null
  const currentMission = selectedBirdMission || targetMission || ((downloadedMissions || [])[0] || null)
  const currentMissionItems = Array.isArray(currentMission && currentMission.mission) ? currentMission.mission : []
  const currentMissionPreview = currentMissionItems.slice(0, 5)
  const missionLabel = selectedBirdMission
    ? `Selected Bird ${selectedBirdMission.sysid}`
    : targetMission
      ? `Bird ${targetMission.sysid}`
      : currentMission
        ? `Latest Download ${currentMission.sysid}`
        : ''

  return (
    <div className="missions-layout">
      <Panel className="missions-map-panel" title="Mission Map">
        <div id="map" className="map-shell" />
      </Panel>
      <div className="missions-section missions-top">
        <Panel
          title="Mission Download"
          actions={<button className="ghost" onClick={loadWaypointFiles}>Refresh</button>}
        >
          <div className="controls">
            <div className="field">
              <label>Select Mission</label>
              <select value={selectedMission} onChange={(e) => setSelectedMission(e.target.value)} className="input">
                {Object.keys(missionGroups).map((mission) => (
                  <option key={mission} value={mission}>{mission}</option>
                ))}
                <option value="">-- All Missions --</option>
              </select>
            </div>
            <div className="button-row">
              <button onClick={async () => { try { await fetch('/api/waypoints/demo', {method: 'POST'}); await loadWaypointFiles() } catch (e) { console.error(e) } }}>Create demo waypoints</button>
              <button onClick={() => setShowFlightPaths(!showFlightPaths)}>{showFlightPaths ? 'Hide' : 'Show'} onboard paths</button>
            </div>
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
        <Panel title={`Current Bird Mission Profile${missionLabel ? ` - ${missionLabel}` : ''}`}>
          {!currentMission ? (
            <div className="empty">No downloaded mission cached yet. Start a mission download to populate the current bird mission panel.</div>
          ) : (
            <div className="mission-profile">
              <div className="metric-grid">
                <div className="metric">
                  <div className="stat-label">Waypoints</div>
                  <div className="stat-value">{currentMission.count || currentMissionItems.length || 0}</div>
                </div>
                <div className="metric">
                  <div className="stat-label">Comp ID</div>
                  <div className="stat-value">{currentMission.compid ?? '?'}</div>
                </div>
                <div className="metric">
                  <div className="stat-label">Download Time</div>
                  <div className="stat-value">{currentMission.download_duration ? `${Number(currentMission.download_duration).toFixed(1)}s` : 'n/a'}</div>
                </div>
              </div>
              <div className="mission-profile-list">
                {currentMissionPreview.map((item, index) => (
                  <div key={`${item.seq ?? index}-${item.command ?? 'wp'}`} className="mission-profile-row">
                    <div className="mission-profile-seq">#{item.seq ?? index}</div>
                    <div className="mission-profile-body">
                      <div>cmd {item.command ?? '?'}</div>
                      <div className="download-status-meta">x={item.x ?? '?'} y={item.y ?? '?'} z={item.z ?? '?'}</div>
                    </div>
                  </div>
                ))}
                {currentMissionItems.length > currentMissionPreview.length && (
                  <div className="download-status-meta">+ {currentMissionItems.length - currentMissionPreview.length} more items</div>
                )}
              </div>
            </div>
          )}
        </Panel>
        <Panel title="Upload / Download Status">
          {statusRows.length === 0 ? (
            <div className="empty">No mission transfer status yet.</div>
          ) : (
            <div className="download-status-list">
              {statusRows.map((row) => (
                <div key={`${row.sysid ?? 'unknown'}-${row.ts ?? 0}`} className="download-status-row">
                  <div className="download-status-main">sysid {row.sysid ?? '?'}: {row.status || 'unknown'}</div>
                  <div className="download-status-meta">
                    {row.phase ? `phase=${row.phase}` : ''}
                    {typeof row.seq === 'number' ? ` seq=${row.seq}` : ''}
                    {row.source ? ` via ${row.source}` : ''}
                    {row.ts ? ` at ${new Date(row.ts).toLocaleTimeString()}` : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
      <div className="missions-section missions-bottom">
        <Panel title="Waypoint Files">
          <div className="file-list">
            {wpFiles.length === 0 ? (
              <div className="empty">No waypoint files. Create demo files or upload from Settings.</div>
            ) : (
              Object.entries(missionGroups)
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
        <Panel title="Mission Upload">
          <div className="controls">
            <div className="field-row">
              <label>sysid</label>
              <input type="number" value={sendSysid} onChange={(e) => setSendSysid(Number(e.target.value))} className="input" />
              <label>compid</label>
              <input type="number" value={sendCompid} onChange={(e) => setSendCompid(Number(e.target.value))} className="input" />
            </div>
            <select value={selectedFile || ''} onChange={(e) => setSelectedFile(e.target.value)} className="input">
              <option value="">-- select file --</option>
              {Object.entries(missionGroups).map(([mission, groups]) =>
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
              <button className="primary" onClick={async () => { if (selectedFile) await sendToDrone({sysid: sendSysid, compid: sendCompid, filename: selectedFile}) }}>Send to Drone</button>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  )
}
