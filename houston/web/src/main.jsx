import React from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './styles.css'
import MqttProvider from './components/MqttProvider.jsx'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <MqttProvider>
        <App />
      </MqttProvider>
    </BrowserRouter>
  </React.StrictMode>
)
