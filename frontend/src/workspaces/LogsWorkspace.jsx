import React, {useMemo} from 'react'
import Panel from '../components/Panel'
import {parseDeviceTopic} from '../hooks/useBirds'

const STRUCTURED_TYPES = new Set([
  'HEARTBEAT',
  'GLOBAL_POSITION_INT',
  'GPS_RAW_INT',
  'LOCAL_POSITION_NED',
  'ATTITUDE',
  'VFR_HUD',
  'SYS_STATUS',
  'MISSION_CURRENT'
])

export default function LogsWorkspace({telemetry, filteredTelemetry, logFilter, setLogFilter}) {
  const coverage = useMemo(() => {
    const all = Array.isArray(telemetry) ? telemetry : []
    let structuredPackets = 0
    let rawOnlyPackets = 0
    let undecodedPackets = 0
    const countsByType = new Map()
    let newestTs = 0
    let oldestTs = 0

    all.forEach((entry) => {
      const ts = Number(entry.ts) || 0
      if (ts > 0) {
        newestTs = Math.max(newestTs, ts)
        oldestTs = oldestTs === 0 ? ts : Math.min(oldestTs, ts)
      }
      const parsed = parseDeviceTopic(entry.topic)
      if (!parsed || !parsed.msgType) {
        undecodedPackets += 1
        return
      }
      const msgType = parsed.msgType
      countsByType.set(msgType, (countsByType.get(msgType) || 0) + 1)
      if (msgType === 'RAW') {
        undecodedPackets += 1
      } else if (STRUCTURED_TYPES.has(msgType)) {
        structuredPackets += 1
      } else {
        rawOnlyPackets += 1
      }
    })

    const totalDecodedPackets = structuredPackets + rawOnlyPackets
    const totalPackets = totalDecodedPackets + undecodedPackets
    const bufferSpanMs = newestTs > 0 && oldestTs > 0 ? Math.max(newestTs - oldestTs, 0) : 0
    const packetsPerSecond = bufferSpanMs > 0 ? (totalPackets * 1000) / bufferSpanMs : 0
    const rows = Array.from(countsByType.entries())
      .map(([msgType, count]) => ({
        msgType,
        count,
        coverage: msgType === 'RAW'
          ? 'Raw fallback'
          : (STRUCTURED_TYPES.has(msgType) ? 'Structured UI' : 'Raw-only UI')
      }))
      .sort((a, b) => {
        if (b.count !== a.count) return b.count - a.count
        return a.msgType.localeCompare(b.msgType)
      })

    return {
      totalPackets,
      totalDecodedPackets,
      structuredPackets,
      rawOnlyPackets,
      undecodedPackets,
      bufferSpanMs,
      packetsPerSecond,
      structuredTypesSeen: rows.filter((row) => row.coverage === 'Structured UI').length,
      rawOnlyTypesSeen: rows.filter((row) => row.coverage === 'Raw-only UI').length,
      rows
    }
  }, [telemetry])

  const structuredPacketPct = coverage.totalDecodedPackets > 0
    ? (coverage.structuredPackets / coverage.totalDecodedPackets) * 100
    : 0
  const structuredTypePct = (coverage.structuredTypesSeen + coverage.rawOnlyTypesSeen) > 0
    ? (coverage.structuredTypesSeen / (coverage.structuredTypesSeen + coverage.rawOnlyTypesSeen)) * 100
    : 0

  return (
    <div className="grid">
      <Panel title="Telemetry Coverage">
        <div className="stat-grid telemetry-coverage-grid">
          <div className="stat">
            <div className="stat-label">Buffer Packets</div>
            <div className="stat-value">{coverage.totalPackets}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Structured Packets</div>
            <div className="stat-value">{coverage.structuredPackets}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Raw-Only Packets</div>
            <div className="stat-value">{coverage.rawOnlyPackets}</div>
          </div>
          <div className="stat">
            <div className="stat-label">RAW Fallback</div>
            <div className="stat-value">{coverage.undecodedPackets}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Observed Rate</div>
            <div className="stat-value">{coverage.packetsPerSecond > 0 ? `${coverage.packetsPerSecond.toFixed(0)}/s` : 'n/a'}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Buffer Span</div>
            <div className="stat-value">{coverage.bufferSpanMs > 0 ? `${(coverage.bufferSpanMs / 1000).toFixed(2)}s` : 'n/a'}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Structured Packet %</div>
            <div className="stat-value">{coverage.totalDecodedPackets > 0 ? `${structuredPacketPct.toFixed(1)}%` : 'n/a'}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Structured Type %</div>
            <div className="stat-value">{(coverage.structuredTypesSeen + coverage.rawOnlyTypesSeen) > 0 ? `${structuredTypePct.toFixed(1)}%` : 'n/a'}</div>
          </div>
        </div>
        <div className="field-help">
          Based on the current frontend telemetry buffer. `Observed Rate` is computed from packet timestamps in the buffer, so high-rate streams can show thousands of packets per second even though the buffer itself is capped. `Structured` means the UI turns that MAVLink packet type into bird state, maps, or metrics. `Raw-only` means it is visible in logs but not elevated into structured panels.
        </div>
        <div className="packet-rate-table-wrap">
          <table className="packet-rate-table">
            <thead>
              <tr>
                <th>Type</th>
                <th>Packets</th>
                <th>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {coverage.rows.length === 0 ? (
                <tr>
                  <td colSpan="3" className="empty telemetry-coverage-empty">No telemetry in buffer yet.</td>
                </tr>
              ) : (
                coverage.rows.map((row) => (
                  <tr key={row.msgType}>
                    <td className="packet-type-cell">{row.msgType}</td>
                    <td>{row.count}</td>
                    <td className={row.coverage === 'Structured UI' ? 'packet-rate-hot' : (row.coverage === 'Raw-only UI' ? 'telemetry-coverage-rawonly' : 'packet-rate-cold')}>
                      {row.coverage}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>
      <Panel title="Telemetry Logs" actions={<input className="input" placeholder="Filter logs" value={logFilter} onChange={(e) => setLogFilter(e.target.value)} />}>
        <div className="telemetry-list">
          {filteredTelemetry.length === 0 ? (
            <div className="empty">No telemetry matching the filter.</div>
          ) : (
            filteredTelemetry.map((t, i) => (
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
