import React from 'react'
import Panel from '../components/Panel'

export default function LogsWorkspace({filteredTelemetry, logFilter, setLogFilter}) {
  return (
    <div className="grid">
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
