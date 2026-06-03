import React, {useMemo, useState} from 'react'
import Panel from '../components/Panel'
import {evaluateBirdStatus, isNonBirdSysid} from '../hooks/useBirds'

function formatTime(ts) {
  const value = Number(ts)
  if (!Number.isFinite(value) || value <= 0) return 'n/a'
  return new Date(value).toLocaleString()
}

export default function MissionsWorkspace({
  loadWaypointFiles,
  selectedMission,
  setSelectedMission,
  showFlightPaths,
  setShowFlightPaths,
  showPlannedLayers,
  setShowPlannedLayers,
  showDownloadedLayers,
  setShowDownloadedLayers,
  wpFiles,
  groupWaypointFiles,
  drawFileOnMap,
  zoomMissionMap,
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
  missionDownloadLogBySysid,
  downloadedMissions,
  downloadedMissionBySysid,
  birdList,
  systemRange,
  visibleMissionTargets,
  selectedBird,
  focusMissionsOnMap,
  focusBirdsOnMap,
  clearDownloadedMissions
}) {
  const [inspectSysid, setInspectSysid] = useState(null)
  const missionGroups = groupWaypointFiles(wpFiles)
  const now = Date.now()

  const missionTargets = useMemo(
    () => (birdList || [])
      .filter((bird) => !isNonBirdSysid(bird && bird.sysid, systemRange))
      .sort((a, b) => Number(a.sysid) - Number(b.sysid)),
    [birdList, systemRange]
  )

  const missionCards = useMemo(
    () => missionTargets.map((bird) => {
      const sysid = Number(bird && bird.sysid)
      const compid = Number(bird && bird.compid) || 1
      const hasPosition = bird && bird.lat !== null && bird.lon !== null
      const isLive = evaluateBirdStatus(bird, now).isLive
      const isVisible = isLive && hasPosition
      const status = missionDownloadStatusBySysid && missionDownloadStatusBySysid[String(sysid)]
      const mission = downloadedMissionBySysid && downloadedMissionBySysid[String(sysid)]
      const statusText = String((status && status.status) || '').toLowerCase()
      const hasDownloaded = !!(mission && mission.complete !== false && mission.partial !== true)
      const hasIntercepted = !!mission && !hasDownloaded
      const isPending = isVisible && (statusText.includes('intercept') || statusText.includes('request') || statusText.includes('passive_observing') || (statusText && !statusText.includes('completed') && !statusText.includes('failed')))
      const cardClass = !isVisible
        ? 'mission-target-card unavailable'
        : hasDownloaded
          ? 'mission-target-card downloaded'
          : ((isPending || hasIntercepted) ? 'mission-target-card pending' : 'mission-target-card online not-downloaded')
      return {
        sysid,
        compid,
        isVisible,
        hasDownloaded,
        hasIntercepted,
        isPending,
        status,
        mission,
        cardClass
      }
    }),
    [missionTargets, missionDownloadStatusBySysid, downloadedMissionBySysid, now]
  )

  const statusRows = useMemo(
    () => Object.values(missionDownloadStatusBySysid || {}).sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0)),
    [missionDownloadStatusBySysid]
  )
  const selectedBirdMission = downloadedMissionBySysid && downloadedMissionBySysid[String(selectedBird || '')]
  const targetMission = downloadedMissionBySysid && downloadedMissionBySysid[String(downloadSysid || 1)]
  const currentMission = selectedBirdMission || targetMission || ((downloadedMissions || [])[0] || null)
  const currentMissionItems = Array.isArray(currentMission && currentMission.mission) ? currentMission.mission : []
  const currentMissionPreview = currentMissionItems.slice(0, 8)
  const missionLabel = selectedBirdMission
    ? `Selected Bird ${selectedBirdMission.sysid}`
    : targetMission
      ? `Bird ${targetMission.sysid}`
      : currentMission
        ? `Latest Download ${currentMission.sysid}`
        : ''

  const inspectTargetSysid = Number(inspectSysid || downloadSysid || selectedBird || 0)
  const statusRowsForInspect = useMemo(() => {
    if (!inspectTargetSysid) return statusRows
    return statusRows.filter((row) => Number(row && row.sysid) === Number(inspectTargetSysid))
  }, [inspectTargetSysid, statusRows])
  const latestInspectStatus = statusRowsForInspect[0] || null
  const inspectLogs = useMemo(() => {
    const key = String(inspectTargetSysid || '')
    return (missionDownloadLogBySysid && missionDownloadLogBySysid[key]) || []
  }, [inspectTargetSysid, missionDownloadLogBySysid])

  return (
    <div className="missions-layout">
      <Panel
        className="missions-map-panel"
        title="Mission Map"
        actions={(
          <div className="panel-actions">
            <label className="toggle">
              <input type="checkbox" checked={showPlannedLayers} onChange={(e) => setShowPlannedLayers(e.target.checked)} />
              all planned
            </label>
            <label className="toggle">
              <input type="checkbox" checked={showDownloadedLayers} onChange={(e) => setShowDownloadedLayers(e.target.checked)} />
              all downloaded
            </label>
            <button onClick={focusMissionsOnMap}>Focus waypoints</button>
            <button onClick={focusBirdsOnMap}>Focus birds</button>
            <button onClick={clearDownloadedMissions}>Clear</button>
            <button onClick={() => zoomMissionMap(-1)}>−</button>
            <button onClick={() => zoomMissionMap(1)}>+</button>
          </div>
        )}
      >
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
              <button className="primary" onClick={downloadFromAllDrones}>Download All Visible ({visibleMissionTargets.length})</button>
            </div>
            <div className="field-row">
              <label>sysid</label>
              <input type="number" value={downloadSysid || 1} onChange={(e) => setDownloadSysid(Number(e.target.value))} className="input" />
              <label>compid</label>
              <input type="number" value={downloadCompid || 1} onChange={(e) => setDownloadCompid(Number(e.target.value))} className="input" />
              <button onClick={async () => { await downloadMissionFromDrone({sysid: downloadSysid || 1, compid: downloadCompid || 1}) }}>Download</button>
            </div>
            <div className="field-help">
              Pick any drone by `sysid`/`compid` above, or click a live bird card below for one-click download.
            </div>
            <div className="mission-target-grid">
              {missionCards.length === 0 ? (
                <div className="empty">No bird IDs observed yet.</div>
              ) : (
                missionCards.map((card) => (
                  <button
                    key={card.sysid}
                    className={card.cardClass}
                    type="button"
                    onClick={async () => {
                      setDownloadSysid(card.sysid)
                      setDownloadCompid(card.compid)
                      setInspectSysid(card.sysid)
                      if (card.isVisible) {
                        await downloadMissionFromDrone({sysid: card.sysid, compid: card.compid})
                      }
                    }}
                  >
                    <div className="mission-target-head">
                      <span className="mission-target-id">Bird {card.sysid}</span>
                      <span className={`mission-target-dot ${card.isVisible ? 'online' : 'offline'}`} />
                    </div>
                    <div className="mission-target-meta">
                      {!card.isVisible
                        ? 'Unavailable'
                        : (card.hasDownloaded
                          ? 'Downloaded'
                          : (card.hasIntercepted
                            ? `Intercepted ${card.mission?.captured_count || 0}/${card.mission?.count || '?'}`
                            : (card.isPending ? 'Download in progress' : 'Online · not downloaded')))}
                    </div>
                    <div className="mission-target-meta">
                      Last downloaded: {card.mission ? formatTime(card.mission && card.mission.ts) : 'not yet'}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </Panel>
        <Panel title={`Current Bird Mission Profile${missionLabel ? ` - ${missionLabel}` : ''}`}>
          {!currentMission ? (
            <div className="empty">No downloaded mission cached yet. Start a mission download to populate this panel.</div>
          ) : (
            <div className="mission-profile">
              <div className="metric-grid">
                <div className="metric">
                  <div className="stat-label">Waypoints</div>
                  <div className="stat-value">{currentMission.captured_count ? `${currentMission.captured_count}/${currentMission.count || currentMissionItems.length || 0}` : (currentMission.count || currentMissionItems.length || 0)}</div>
                </div>
                <div className="metric">
                  <div className="stat-label">Comp ID</div>
                  <div className="stat-value">{currentMission.compid ?? '?'}</div>
                </div>
                <div className="metric">
                  <div className="stat-label">Download Time</div>
                  <div className="stat-value">{currentMission.download_duration ? `${Number(currentMission.download_duration).toFixed(1)}s` : 'n/a'}</div>
                </div>
                <div className="metric">
                  <div className="stat-label">Last Downloaded</div>
                  <div className="stat-value">{formatTime(currentMission.ts)}</div>
                </div>
                <div className="metric">
                  <div className="stat-label">Cache State</div>
                  <div className="stat-value">{currentMission.stale ? 'stale (cached)' : 'fresh'}{currentMission.partial ? ' · partial' : ''}</div>
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
        <Panel title="Mission Troubleshooting Log">
          <div className="controls">
            <div className="field-row">
              <label>Inspect sysid</label>
              <input
                type="number"
                value={inspectTargetSysid || ''}
                onChange={(e) => setInspectSysid(Number(e.target.value) || null)}
                className="input"
              />
            </div>
            {inspectLogs.length === 0 ? (
              <div className="empty">No mission transfer logs for this sysid yet.</div>
            ) : (
              <div className="download-status-list">
                {inspectLogs.map((row, index) => (
                  <div key={`${row.sysid ?? 'unknown'}-${row.ts ?? 0}-${index}`} className="download-status-row">
                    <div className="download-status-main">sysid {row.sysid ?? '?'}: {row.status || 'unknown'}</div>
                    <div className="download-status-meta">
                      {row.phase ? `phase=${row.phase}` : ''}
                      {typeof row.seq === 'number' ? ` seq=${row.seq}` : ''}
                      {typeof row.count === 'number' ? ` count=${row.count}` : ''}
                      {typeof row.downloadDuration === 'number' ? ` duration=${row.downloadDuration.toFixed(1)}s` : ''}
                      {row.source ? ` via ${row.source}` : ''}
                      {row.ts ? ` at ${new Date(row.ts).toLocaleTimeString()}` : ''}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>
        <Panel title={`Latest Mission Status${inspectTargetSysid ? ` - sysid ${inspectTargetSysid}` : ''}`}>
          {statusRowsForInspect.length === 0 ? (
            <div className="empty">No mission transfer status yet.</div>
          ) : (
            <div className="download-status-list">
              {statusRowsForInspect.map((row) => (
                <div key={`${row.sysid ?? 'unknown'}-${row.ts ?? 0}`} className="download-status-row">
                  <div className="download-status-main">sysid {row.sysid ?? '?'}: {row.status || 'unknown'}</div>
                  <div className="download-status-meta">
                    {row.phase ? `phase=${row.phase}` : ''}
                    {typeof row.seq === 'number' ? ` seq=${row.seq}` : ''}
                    {typeof row.count === 'number' ? ` count=${row.count}` : ''}
                    {row.source ? ` via ${row.source}` : ''}
                    {row.ts ? ` at ${new Date(row.ts).toLocaleTimeString()}` : ''}
                  </div>
                </div>
              ))}
              {latestInspectStatus && String(latestInspectStatus.status || '').includes('request_sent') && (
                <div className="empty">Waiting for vehicle response. If this stays here, the backend is not seeing `MISSION_COUNT` or `MISSION_ITEM` traffic for this sysid.</div>
              )}
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
