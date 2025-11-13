import React, { useEffect, useState } from "react"
import apiFetch from "./api"
import "./styles.css"

type Page = "missions" | "waypoints" | "drones" | "settings" | "terminal" | "map"

import MissionsPage from './pages/MissionsPage'
import WaypointsPage from './pages/WaypointsPage'
import DronesPage from './pages/DronesPage'
import SettingsPage from './pages/SettingsPage'
import TerminalPage from './pages/TerminalPage'
import MapPage from './pages/MapPage'

// WaypointsPage moved to ./pages/WaypointsPage

// DronesPage moved to ./pages/DronesPage

// SettingsPage moved to ./pages/SettingsPage

// TerminalPage moved to ./pages/TerminalPage

function App() {
  const [page, setPage] = useState<Page>("missions")
  const [groups, setGroups] = useState<string[]>([])

  useEffect(() => {
    apiFetch("/groups")
      .then((r) => r.json())
      .then((d) => setGroups(Object.keys(d)))
      .catch(() => setGroups([]))
  }, [])

  async function noopVerify() {
    // small no-op used by MissionsPage to let main App update state if needed
  }

  return (
    <div className="app">
      <header>
        <h1>NOMAD</h1>
        <nav>
          <button onClick={() => setPage("missions")} className="ghost">Missions</button>
          <button onClick={() => setPage("waypoints")} className="ghost">Waypoints</button>
          <button onClick={() => setPage("drones")} className="ghost">Drones</button>
          <button onClick={() => setPage("settings")} className="ghost">Settings</button>
          <button onClick={() => setPage("terminal")} className="ghost">Terminal</button>
          <button onClick={() => setPage("map")} className="ghost">Map</button>
        </nav>
      </header>

      <main style={{ marginTop: 20 }}>
        <div className="grid">
          <div className="panel">
            {page === "missions" && <MissionsPage onVerify={noopVerify} />}
            {page === "waypoints" && <WaypointsPage />}
            {page === "drones" && <DronesPage />}
            {page === "settings" && <SettingsPage />}
            {page === "terminal" && <TerminalPage />}
            {page === "map" && <MapPage onEdit={(g) => { try { (window as any).NOMAD_FOCUS_GROUP = g } catch(e) {} ; setPage('waypoints') }} />}
          </div>
        </div>
      </main>

      <footer>
        <span className="card-title">NOMAD</span>
        <span className="muted" style={{ marginLeft: 8 }}>Nominal Online Multiple Asset Director</span>
      </footer>
    </div>
  )
}

export default App
