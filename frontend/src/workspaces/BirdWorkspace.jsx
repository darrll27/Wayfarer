import React, {useEffect, useMemo, useRef} from 'react'
import Panel from '../components/Panel'
import {parseDeviceTopic} from '../hooks/useBirds'

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
  const recentTelemetry = Array.isArray(selectedBirdTelemetry) ? selectedBirdTelemetry : []
  const seenPacketTypesRef = useRef(new Map())

  useEffect(() => {
    const birdKey = selectedBird ? String(selectedBird) : '__none__'
    if (!seenPacketTypesRef.current.has(birdKey)) {
      seenPacketTypesRef.current.set(birdKey, new Map())
    }
    const registry = seenPacketTypesRef.current.get(birdKey)
    recentTelemetry.forEach((entry) => {
      const parsed = parseDeviceTopic(entry.topic)
      if (!parsed || !parsed.msgType) return
      const ts = Number(entry.ts) || 0
      const existing = registry.get(parsed.msgType) || {lastSeen: 0, totalCount: 0}
      registry.set(parsed.msgType, {
        lastSeen: Math.max(existing.lastSeen, ts),
        totalCount: existing.totalCount + 1
      })
    })
  }, [recentTelemetry, selectedBird])

  const packetRates = useMemo(() => {
    const WINDOW_MS = 8000
    const nowCutoff = Date.now() - WINDOW_MS
    const liveGroups = new Map()
    recentTelemetry.forEach((entry) => {
      const parsed = parseDeviceTopic(entry.topic)
      if (!parsed || !parsed.msgType) return
      const bucket = liveGroups.get(parsed.msgType) || []
      bucket.push(Number(entry.ts))
      liveGroups.set(parsed.msgType, bucket)
    })

    const birdKey = selectedBird ? String(selectedBird) : '__none__'
    const registry = seenPacketTypesRef.current.get(birdKey) || new Map()
    const allTypes = new Set([...registry.keys(), ...liveGroups.keys()])

    return Array.from(allTypes)
      .map((msgType) => {
        const samples = (liveGroups.get(msgType) || []).slice().sort((a, b) => a - b)
        const active = samples.filter((ts) => ts >= nowCutoff)
        const spanMs = active.length > 1 ? Math.max(active[active.length - 1] - active[0], 1000) : WINDOW_MS
        const hz = active.length > 1 ? ((active.length - 1) * 1000) / spanMs : (active.length * 1000) / WINDOW_MS
        const historical = registry.get(msgType) || {lastSeen: 0, totalCount: 0}
        const liveLastSeen = samples.length > 0 ? samples[samples.length - 1] : 0
        return {
          msgType,
          hz: active.length > 0 ? hz : 0,
          activeCount: active.length,
          totalCount: Math.max(historical.totalCount, samples.length),
          lastSeen: Math.max(historical.lastSeen, liveLastSeen)
        }
      })
      .sort((a, b) => a.msgType.localeCompare(b.msgType))
  }, [recentTelemetry, selectedBird])

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
              <div className="label">Ingress</div>
              <div className="mono">{packetRates.length > 0 ? `${packetRates.length} packet classes tracked` : 'no packet types observed yet'}</div>
            </div>
          </div>
        ) : (
          <div className="empty">Pick a bird from the left.</div>
        )}
      </Panel>
      <Panel title="Packet Rates">
        {selectedBirdRecord ? (
          packetRates.length === 0 ? (
            <div className="empty">No recent packet rates for this bird yet.</div>
          ) : (
            <div className="packet-rate-table-wrap">
              <table className="packet-rate-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Ingress</th>
                    <th>Window</th>
                    <th>Last Seen</th>
                  </tr>
                </thead>
                <tbody>
                  {packetRates.map((item) => (
                    <tr key={item.msgType}>
                      <td className="packet-type-cell">{item.msgType}</td>
                      <td className={item.hz > 0 ? 'packet-rate-hot' : 'packet-rate-cold'}>
                        {item.hz.toFixed(item.hz >= 10 ? 0 : 1)} Hz
                      </td>
                      <td>{item.activeCount} / 8s</td>
                      <td>{item.lastSeen ? new Date(item.lastSeen).toLocaleTimeString() : 'n/a'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <div className="empty">No bird selected.</div>
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
            <div className="metric">
              <div className="label">Position</div>
              <div className="mono">{selectedBirdRecord.lat !== null && selectedBirdRecord.lon !== null ? `${selectedBirdRecord.lat.toFixed(5)}, ${selectedBirdRecord.lon.toFixed(5)}` : 'no fix'}</div>
            </div>
          </div>
        ) : (
          <div className="empty">No metrics yet.</div>
        )}
      </Panel>
      <Panel title="Latest Telemetry Bursts">
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
