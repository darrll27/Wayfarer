import React, { useEffect, useState } from 'react'
import { useMqtt } from '../components/MqttProvider.jsx'

function buildWsUrl(broker) {
  const { protocol, hostname } = window.location
  const isHttps = protocol === 'https:'
  const wsProto = isHttps ? 'wss' : 'ws'
  const host = hostname
  const port = broker?.config?.ws_port || broker?.config?.http_port || window.location.port
  const path = broker?.config?.ws_path || '/mqtt'
  return `${wsProto}://${host}:${port}${path}`
}

export default function Broker() {
  const { status, broker: brokerCtx } = useMqtt()
  const [broker, setBroker] = useState(null)
  useEffect(() => {
    let mounted = true
    fetch('/api/broker').then(r => r.json()).then(b => { if (mounted) setBroker(b) })
    return () => { mounted = false }
  }, [])

  const cfg = broker?.config
  const stats = broker?.stats
  const wsUrl = buildWsUrl(broker || brokerCtx)

  return (
    <>
      <div className="card">
        <h2>Broker Status</h2>
        <div className="kv">
          <span>HTTP Port</span><div>{cfg?.http_port ?? '—'}</div>
          <span>TCP Port</span><div>{cfg?.tcp_port ?? '—'}</div>
          <span>WS Path</span><div>{cfg?.ws_path ?? '/mqtt'}</div>
          <span>WS URL</span><div>{wsUrl}</div>
          <span>MQTT Client</span><div>{status}</div>
          <span>Clients</span><div>{stats?.clients ?? 0}</div>
          <span>Messages</span><div>{stats?.messages ?? 0}</div>
          <span>Subscriptions</span><div>{stats?.subscriptions ?? 0}</div>
        </div>
      </div>
    </>
  )
}
