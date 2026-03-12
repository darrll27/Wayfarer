import React from 'react'
import Panel from './Panel'
import {evaluateBirdStatus} from '../hooks/useBirds'

export default function Sidebar({birdFilter, setBirdFilter, birdList, selectedBird, setSelectedBird, fleetStats}) {
  const now = Date.now()

  return (
    <aside className="sidebar">
      <Panel
        title="Birds"
        actions={<input className="input" placeholder="Filter" value={birdFilter} onChange={(e) => setBirdFilter(e.target.value)} />}
      >
        <div className="bird-list">
          {birdList.length === 0 ? (
            <div className="empty">No birds observed yet.</div>
          ) : (
            birdList.map(bird => {
              const {isLive, isReady} = evaluateBirdStatus(bird, now)
              return (
                <button
                  key={bird.sysid}
                  className={`bird-card ${String(selectedBird) === String(bird.sysid) ? 'active' : ''}`}
                  onClick={() => setSelectedBird(bird.sysid)}
                >
                  <div className="summary-bird-head">
                    <div className="bird-title">Bird {bird.sysid}</div>
                    <span className={`status-dot ${isLive ? 'live pulse' : 'dead'}`} />
                  </div>
                  <div className="summary-bird-row">
                    <span className={`ready-pill ${isReady ? 'ready' : 'not-ready'}`}>{isReady ? 'READY' : 'NOT READY'}</span>
                    <span className="bird-meta">GPS {bird.gpsCount ?? 'n/a'}</span>
                  </div>
                </button>
              )
            })
          )}
        </div>
      </Panel>

      <Panel title="Fleet Summary">
        <div className="stat-grid">
          <div className="stat">
            <div className="stat-label">Total</div>
            <div className="stat-value">{fleetStats.total}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Active</div>
            <div className="stat-value">{fleetStats.active}</div>
          </div>
          <div className="stat">
            <div className="stat-label">Stale</div>
            <div className="stat-value">{fleetStats.stale}</div>
          </div>
        </div>
      </Panel>
    </aside>
  )
}
