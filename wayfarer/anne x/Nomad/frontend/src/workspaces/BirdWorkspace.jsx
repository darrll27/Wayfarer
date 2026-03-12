import React from 'react'
import Panel from '../components/Panel'

function formatGpsFix(record) {
  const hasPosition = record && record.lat !== null && record.lon !== null
  if (!hasPosition) return 'No Fix'
  const value = Number(record && record.metrics ? record.metrics.gpsFix : undefined)
  if (!Number.isFinite(value)) return 'Unknown'
  if (value <= 1) return 'No Fix'
  if (value === 2) return '2D'
  if (value === 3) return '3D'
  if (value === 4) return 'DGPS'
  if (value === 5) return 'RTK Float'
  if (value === 6) return 'RTK Fixed'
  return `Type ${value}`
}

export default function BirdWorkspace({
  selectedBird,
  selectedBirdRecord,
  selectedBirdHeartbeat,
  selectedBirdTelemetry
}) {
  return (
    <div className="grid">
      <Panel title={selectedBird ? `Bird ${selectedBird} Overview` : 'Select a Bird'}>
        {selectedBirdRecord ? (
          <div className="status-grid">
            <div>
              <div className="label">Last seen</div>
              <div className="mono">{selectedBirdRecord.lastSeen ? new Date(selectedBirdRecord.lastSeen).toLocaleTimeString() : 'never'}</div>
            </div>
            <div>
              <div className="label">Heartbeat</div>
              <div className="mono">{selectedBirdHeartbeat ? new Date(selectedBirdHeartbeat).toLocaleTimeString() : 'not seen'}</div>
            </div>
            <div>
              <div className="label">Position</div>
              <div className="mono">{selectedBirdRecord.lat !== null && selectedBirdRecord.lon !== null ? `${selectedBirdRecord.lat.toFixed(5)}, ${selectedBirdRecord.lon.toFixed(5)}` : 'no fix'}</div>
            </div>
          </div>
        ) : (
          <div className="empty">Pick a bird from the left.</div>
        )}
      </Panel>
      <Panel title="Bird Metrics">
        {selectedBirdRecord ? (
          <div className="metric-grid">
            <div className="metric">
              <div className="label">GPS fix</div>
              <div className="mono">{formatGpsFix(selectedBirdRecord)}</div>
            </div>
            <div className="metric">
              <div className="label">Satellites</div>
              <div className="mono">{selectedBirdRecord.gpsCount ?? 'unknown'}</div>
            </div>
            <div className="metric">
              <div className="label">Alt (m)</div>
              <div className="mono">{selectedBirdRecord.metrics.alt ?? selectedBirdRecord.metrics.hudAlt ?? 'n/a'}</div>
            </div>
            <div className="metric">
              <div className="label">Groundspeed</div>
              <div className="mono">{selectedBirdRecord.metrics.groundspeed ?? 'n/a'}</div>
            </div>
            <div className="metric">
              <div className="label">Heading</div>
              <div className="mono">{selectedBirdRecord.metrics.heading ?? 'n/a'}</div>
            </div>
            <div className="metric">
              <div className="label">Mission Seq</div>
              <div className="mono">{selectedBirdRecord.metrics.missionSeq ?? 'n/a'}</div>
            </div>
            <div className="metric">
              <div className="label">Roll/Pitch/Yaw</div>
              <div className="mono">{selectedBirdRecord.metrics.roll ?? 'n/a'} / {selectedBirdRecord.metrics.pitch ?? 'n/a'} / {selectedBirdRecord.metrics.yaw ?? 'n/a'}</div>
            </div>
            <div className="metric">
              <div className="label">Local NED</div>
              <div className="mono">{selectedBirdRecord.metrics.localX ?? 'n/a'}, {selectedBirdRecord.metrics.localY ?? 'n/a'}, {selectedBirdRecord.metrics.localZ ?? 'n/a'}</div>
            </div>
            <div className="metric">
              <div className="label">Battery</div>
              <div className="mono">{selectedBirdRecord.metrics.battery ?? 'n/a'}%</div>
            </div>
          </div>
        ) : (
          <div className="empty">No metrics yet.</div>
        )}
      </Panel>
      <Panel title="Bird Telemetry">
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
