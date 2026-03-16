import React from 'react'
import Badge from './Badge'

export default function AppHeader({
  workspaces,
  workspace,
  setWorkspace,
  connStatus,
  backendStatusLabel,
  brokerConfig,
  brokerMissing,
  isElectron
}) {
  return (
    <header className="app-header">
      <div className="app-title">
        <div>
          <div className="title">Nomad</div>
          <div className="subtitle">Fleet console</div>
        </div>
        <div className="status-chips">
          <Badge label={`MQTT: ${connStatus}`} tone={connStatus === 'connected' ? 'ok' : 'warn'} />
          <Badge label={`Backend: ${backendStatusLabel}`} tone={backendStatusLabel === 'online' ? 'ok' : 'neutral'} />
        </div>
      </div>
      <nav className="tabs">
        {workspaces.map(tab => (
          <button
            key={tab.id}
            className={`tab ${workspace === tab.id ? 'active' : ''}`}
            onClick={() => setWorkspace(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </nav>
      <div className="broker-summary">
        <div className="label">Broker</div>
        <div className="value">
          {brokerConfig ? `${brokerConfig.host}:${isElectron ? brokerConfig.tcp_port : brokerConfig.ws_port}` : (brokerMissing ? 'missing' : 'loading...')}
        </div>
      </div>
    </header>
  )
}
