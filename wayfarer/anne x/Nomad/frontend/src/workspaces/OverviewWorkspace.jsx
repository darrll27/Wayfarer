import React from 'react'
import Panel from '../components/Panel'
import {evaluateBirdStatus} from '../hooks/useBirds'

function formatGpsFix(bird) {
  const hasPosition = bird && bird.lat !== null && bird.lon !== null
  if (!hasPosition) return 'No Fix'
  const fixType = bird && bird.metrics ? bird.metrics.gpsFix : undefined
  const value = Number(fixType)
  if (!Number.isFinite(value)) return 'Unknown'
  if (value <= 1) return 'No Fix'
  if (value === 2) return '2D'
  if (value === 3) return '3D'
  if (value === 4) return 'DGPS'
  if (value === 5) return 'RTK Float'
  if (value === 6) return 'RTK Fixed'
  return `Type ${value}`
}

function formatDop(value) {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0 || n >= 65535) return 'n/a'
  return (n / 100).toFixed(1)
}

export default function OverviewWorkspace({birdList, telemetry, sendLoadWaypointsDemo}) {
  const now = Date.now()
  const birds = birdList || []
  const live = birds.filter((b) => evaluateBirdStatus(b, now).isLive)
  const dead = birds.length - live.length
  const ready = birds.filter((b) => evaluateBirdStatus(b, now).isReady)
  const notReady = birds.length - ready.length
  const birdById = new Map()
  birds.forEach((bird) => {
    const id = Number(bird.sysid)
    if (Number.isInteger(id) && id >= 1 && id <= 90 && !birdById.has(id)) {
      birdById.set(id, bird)
    }
  })
  const ids = Array.from({length: 90}, (_, i) => i + 1)

  return (
    <div className="grid">
      <Panel title="Fleet Summary" actions={<button className="ghost" onClick={sendLoadWaypointsDemo}>Send demo waypoints</button>}>
        <div className="stat-grid">
          <div className="stat"><div className="stat-label">Birds</div><div className="stat-value">{birds.length}</div></div>
          <div className="stat"><div className="stat-label">Live</div><div className="stat-value">{live.length}</div></div>
          <div className="stat"><div className="stat-label">Dead</div><div className="stat-value">{dead}</div></div>
          <div className="stat"><div className="stat-label">Ready</div><div className="stat-value">{ready.length}</div></div>
          <div className="stat"><div className="stat-label">Not Ready</div><div className="stat-value">{notReady}</div></div>
        </div>
        <div className="matrix-legend">
          <span className="legend-item"><span className="legend-dot ready" />Ready (green pulse)</span>
          <span className="legend-item"><span className="legend-dot not-ready pulse-red" />Not Ready (red pulse)</span>
          <span className="legend-item"><span className="legend-dot missing" />Missing</span>
        </div>
        <div className="status-matrix" aria-label="Bird IDs 1 to 90 matrix (15 rows x 6 columns)">
          {ids.map((id) => {
            const bird = birdById.get(id)
            if (!bird) {
              return <div key={id} className="status-light missing" title={`Bird ${id}: missing`}>{id}</div>
            }
            const {isLive, isReady} = evaluateBirdStatus(bird, now)
            const stateClass = !isLive ? 'stale' : (isReady ? 'ready' : 'not-ready')
            const pulseClass = isLive ? (isReady ? 'pulse-green' : 'pulse-red') : ''
            return (
              <div
                key={id}
                className={`status-light ${stateClass} ${pulseClass}`}
                title={`Bird ${id}: ${!isLive ? 'stale' : (isReady ? 'ready' : 'not ready')}${isLive ? ' (live)' : ''}`}
              >
                {id}
              </div>
            )
          })}
        </div>
      </Panel>

      <Panel title="Bird Status">
        <div className="summary-bird-grid">
          {birds.length === 0 ? (
            <div className="empty">No birds observed yet.</div>
          ) : (
            birds.map((bird) => {
              const {isLive, isReady} = evaluateBirdStatus(bird, now)
              return (
                <div key={bird.sysid} className="summary-bird-card">
                  <div className="summary-bird-head">
                    <div className="bird-title">Bird {bird.sysid}</div>
                    <span className={`status-dot ${isLive ? 'live pulse' : 'dead'}`} title={isLive ? 'live telemetry' : 'dead'} />
                  </div>
                  <div className="summary-bird-row">
                    <span className={`ready-pill ${isReady ? 'ready' : 'not-ready'}`}>{isReady ? 'READY' : 'NOT READY'}</span>
                    <span className="bird-meta">GPS {bird.gpsCount ?? 'n/a'}</span>
                  </div>
                  <div className="bird-meta">
                    GPS Fix: {formatGpsFix(bird)}
                  </div>
                  <div className="bird-meta">
                    HDOP {formatDop(bird.metrics && bird.metrics.eph)} · VDOP {formatDop(bird.metrics && bird.metrics.epv)}
                  </div>
                </div>
              )
            })
          )}
        </div>
      </Panel>

      <Panel title="Latest Telemetry">
        <div className="telemetry-list compact">
          {telemetry.length === 0 ? (
            <div className="empty">No telemetry received yet.</div>
          ) : (
            telemetry.slice(0, 10).map((t, i) => (
              <div key={i} className="telemetry-row compact">
                <div className="telemetry-time">{new Date(t.ts).toLocaleTimeString()}</div>
                <div className="telemetry-topic">{t.topic}</div>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  )
}
