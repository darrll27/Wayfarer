import React from 'react'
import Panel from '../components/Panel'
import {splitBirdGroups} from '../hooks/useBirds'

export default function FleetWorkspace({birdList, telemetry, systemRange}) {
  const {birds, nonBirds} = splitBirdGroups(birdList, systemRange)

  function renderLocation(entry, labelPrefix = 'Bird') {
    return (
      <div key={entry.sysid} className="location-card">
        <div className="location-title">{labelPrefix} {entry.sysid}</div>
        <div className="location-meta">Last seen {entry.lastSeen ? new Date(entry.lastSeen).toLocaleTimeString() : 'never'}</div>
        <div className="location-coords">
          {entry.lat !== null && entry.lon !== null ? `${entry.lat.toFixed(5)}, ${entry.lon.toFixed(5)}` : 'No GPS fix'}
        </div>
        <div className="location-meta">
          {entry.gpsCount !== null ? `GPS: ${entry.gpsCount} sats` : 'GPS: unknown'}
        </div>
      </div>
    )
  }

  return (
    <div className="grid">
      <Panel title="Fleet Locations">
        <div className="location-grid">
          {birdList.length === 0 ? (
            <div className="empty">No location updates yet.</div>
          ) : (
            <>
              {birds.length > 0 && (
                <div className="group-separator group-separator-air location-separator">
                  <span>Air</span>
                </div>
              )}
              {birds.map((bird) => renderLocation(bird, 'Bird'))}
              {nonBirds.length > 0 && (
                <>
                  <div className="group-separator group-separator-ground location-separator">
                    <span>Ground</span>
                  </div>
                  {nonBirds.map((entry) => renderLocation(entry, 'GCS'))}
                </>
              )}
            </>
          )}
        </div>
      </Panel>
      <Panel title="Fleet Telemetry Stream">
        <div className="telemetry-list">
          {telemetry.length === 0 ? (
            <div className="empty">No telemetry received yet.</div>
          ) : (
            telemetry.slice(0, 40).map((t, i) => (
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
