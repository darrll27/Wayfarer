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
  isElectron,
  notifications,
  notificationCenterOpen,
  setNotificationCenterOpen,
  clearNotifications
}) {
  const unreadCount = (notifications || []).filter((item) => !item.read).length

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
        <div className="header-actions">
          <button
            className={`notification-center-toggle ${notificationCenterOpen ? 'active' : ''}`}
            onClick={() => setNotificationCenterOpen((open) => !open)}
            aria-label="Open notification center"
          >
            <span>Notifications</span>
            <span className={`notification-count ${unreadCount > 0 ? 'has-unread' : ''}`}>{unreadCount}</span>
          </button>
        </div>
        {notificationCenterOpen ? (
          <div className="notification-center">
            <div className="notification-center-header">
              <div className="notification-center-title">Notification Center</div>
              <button className="ghost" onClick={clearNotifications}>Clear</button>
            </div>
            <div className="notification-center-list">
              {(notifications || []).length === 0 ? (
                <div className="empty">No notifications yet.</div>
              ) : (
                notifications.map((item) => (
                  <div key={item.id} className={`notification-item ${item.read ? '' : 'unread'}`}>
                    <div className="notification-item-head">
                      <div className="notification-item-title">{item.title}</div>
                      <div className="notification-item-time">
                        {item.ts ? new Date(item.ts).toLocaleTimeString() : ''}
                      </div>
                    </div>
                    <div className="notification-item-body">{item.body}</div>
                  </div>
                ))
              )}
            </div>
          </div>
        ) : null}
      </div>
    </header>
  )
}
