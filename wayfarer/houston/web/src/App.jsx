import React from 'react'
import { Routes, Route, NavLink } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import Groups from './pages/Groups.jsx'
import Config from './pages/Config.jsx'
import Broker from './pages/Broker.jsx'
import Streams from './pages/Streams.jsx'
import MapView from './pages/MapView.jsx'

export default function App() {
  return (
    <div className="app">
      <nav className="topnav">
        <div className="brand">HOUSTON</div>
        <div className="links">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/groups">Groups</NavLink>
          <NavLink to="/map">Map</NavLink>
          <NavLink to="/streams">Streams</NavLink>
          <NavLink to="/config">Config</NavLink>
          <NavLink to="/broker">Broker</NavLink>
        </div>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/groups" element={<Groups />} />
          <Route path="/map" element={<MapView />} />
          <Route path="/streams" element={<Streams />} />
          <Route path="/config" element={<Config />} />
          <Route path="/broker" element={<Broker />} />
        </Routes>
      </main>
    </div>
  )
}
