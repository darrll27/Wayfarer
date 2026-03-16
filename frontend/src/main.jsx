import React from 'react'
import {createRoot} from 'react-dom/client'
// Buffer polyfill for browser environments: mqtt library expects global Buffer
import { Buffer } from 'buffer'
window.Buffer = window.Buffer || Buffer
import App from './App'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
