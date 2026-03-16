import React from 'react'
import Panel from './Panel'
import {evaluateBirdStatus, splitBirdGroups} from '../hooks/useBirds'

export default function Sidebar({birdFilter, setBirdFilter, birdList, selectedBird, setSelectedBird, fleetStats, systemRange}) {
  const now = Date.now()
  const {birds, nonBirds} = splitBirdGroups(birdList, systemRange)

  function renderEntry(entry, labelPrefix = 'Bird') {
    const {isLive, isReady} = evaluateBirdStatus(entry, now)
    return (
      <button
        key={entry.sysid}
        className={`bird-card ${String(selectedBird) === String(entry.sysid) ? 'active' : ''}`}
        onClick={() => setSelectedBird(entry.sysid)}
      >
        <div className="summary-bird-head">
          <div className="bird-title">{labelPrefix} {entry.sysid}</div>
          <span className={`status-dot ${isLive ? 'live pulse' : 'dead'}`} />
        </div>
        <div className="summary-bird-row">
          <span className={`ready-pill ${isReady ? 'ready' : 'not-ready'}`}>{isReady ? 'READY' : 'NOT READY'}</span>
          <span className="bird-meta">GPS {entry.gpsCount ?? 'n/a'}</span>
        </div>
      </button>
    )
  }

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
            <>
              {birds.length > 0 && (
                <div className="group-separator group-separator-air">
                  <span>Air</span>
                </div>
              )}
              {birds.map((bird) => renderEntry(bird, 'Bird'))}
              {nonBirds.length > 0 && (
                <>
                  <div className="group-separator group-separator-ground">
                    <span>Ground</span>
                  </div>
                  {nonBirds.map((entry) => renderEntry(entry, 'GCS'))}
                </>
              )}
            </>
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
          <div className="stat">
            <div className="stat-label">Ground Systems</div>
            <div className="stat-value">{fleetStats.nonBirds ?? 0}</div>
          </div>
        </div>
      </Panel>
    </aside>
  )
}
