import React from 'react'
import Panel from '../components/Panel'

export default function FleetWorkspace({birdList, telemetry}) {
  return (
    <div className="grid">
      <Panel title="Fleet Locations">
        <div className="location-grid">
          {birdList.length === 0 ? (
            <div className="empty">No location updates yet.</div>
          ) : (
            birdList.map(bird => (
              <div key={bird.sysid} className="location-card">
                <div className="location-title">Bird {bird.sysid}</div>
                <div className="location-meta">Last seen {bird.lastSeen ? new Date(bird.lastSeen).toLocaleTimeString() : 'never'}</div>
                <div className="location-coords">
                  {bird.lat !== null && bird.lon !== null ? `${bird.lat.toFixed(5)}, ${bird.lon.toFixed(5)}` : 'No GPS fix'}
                </div>
                <div className="location-meta">
                  {bird.gpsCount !== null ? `GPS: ${bird.gpsCount} sats` : 'GPS: unknown'}
                </div>
              </div>
            ))
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
