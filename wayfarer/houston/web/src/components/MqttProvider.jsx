import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react'
import mqtt from 'mqtt'

const MqttContext = createContext(null)

export function useMqtt() {
  return useContext(MqttContext)
}

function buildWsUrl(broker) {
  const { protocol, hostname } = window.location
  const isHttps = protocol === 'https:'
  const wsProto = isHttps ? 'wss' : 'ws'
  const host = hostname
  const port = broker?.config?.ws_port || broker?.config?.http_port || window.location.port
  const path = broker?.config?.ws_path || '/mqtt'
  return `${wsProto}://${host}:${port}${path}`
}

export default function MqttProvider({ children }) {
  const [broker, setBroker] = useState(null)
  const [topicPrefix, setTopicPrefix] = useState('wayfarer/v1')
  const [status, setStatus] = useState('idle') // idle | connecting | connected | error
  const clientRef = useRef(null)
  const telemetryRef = useRef(new Map()) // key: sysid string, value: { group, sysid, checkpoint, lat, lon, alt, t, ts, hbTs }
  const [version, setVersion] = useState(0) // monotonically increases on updates

  // Fetch broker and houston config
  useEffect(() => {
    let mounted = true
    async function load() {
      try {
        const [b, h] = await Promise.all([
          fetch('/api/broker').then(r => r.json()),
          fetch('/api/config').then(r => r.json())
        ])
        if (!mounted) return
        setBroker(b)
  setTopicPrefix(h?.topic_prefix || 'wayfarer/v1')
        // Load cached telemetry (last 30s for hb/msg; 10min for mission) to avoid blank UI after refresh
        try {
          const cached = JSON.parse(localStorage.getItem('houston.telemetry') || '[]')
          if (Array.isArray(cached)) {
            const now = Date.now()
            const m = new Map()
            for (const e of cached) {
              if (!e || !e.sysid) continue
              const hasRecentMsg = (e.ts && now - e.ts < 30000) || (e.hbTs && now - e.hbTs < 30000)
              const hasRecentMission = (e.mission?.ts && now - e.mission.ts < 10 * 60 * 1000)
              if (hasRecentMsg || hasRecentMission) {
                m.set(String(e.sysid), e)
              }
            }
            if (m.size) {
              telemetryRef.current = m
              setVersion(v => (v + 1) % 1000000)
            }
          }
        } catch {}
      } catch (e) {
        console.error('Failed to fetch broker/config', e)
      }
    }
    load()
    return () => { mounted = false }
  }, [])

  // Connect MQTT once broker known
  useEffect(() => {
    if (!broker) return
    setStatus('connecting')
    const url = buildWsUrl(broker)
    console.log('[MqttProvider] connecting', { url })
    const client = mqtt.connect(url, {
      reconnectPeriod: 2000,
    })
    clientRef.current = client
    // Topics to subscribe
  const pfTopic = `${topicPrefix}/pathfinder/+/state`
  const rawAll = `${topicPrefix}/devices/+/telem/raw/mavlink/+`
  const rawGps1 = `${topicPrefix}/devices/+/telem/raw/mavlink/GLOBAL_POSITION_INT`
  const rawGps2 = `${topicPrefix}/devices/+/telem/raw/mavlink/GPS_RAW_INT`
  const rawGps3 = `${topicPrefix}/devices/+/telem/raw/mavlink/GPS2_RAW`
  const rawMission = `${topicPrefix}/devices/+/telem/raw/mavlink/MISSION_CURRENT`
  // Listen for mission uploads (root-level only) to overlay waypoints on the map
  const missionUploadRoot = `${topicPrefix}/mission/upload`
  const heartbeat = `${topicPrefix}/devices/+/telem/state/heartbeat`
  // Alternate flat topic (no 'devices/' segment), e.g., wayfarer/v1/mav_sys1/telem/state/heartbeat
  const heartbeatFlat = `${topicPrefix}/+/telem/state/heartbeat`

    client.on('connect', () => {
      setStatus('connected')
      // Subscribe to pathfinder aggregated state
      client.subscribe(pfTopic, (err) => { if (err) console.error('Subscribe error', err); else console.log('[MqttProvider] subscribed', pfTopic) })
      // Subscribe to heartbeat topics only (alive signal)
      client.subscribe([heartbeat, heartbeatFlat], (err) => {
        if (err) console.error('Subscribe error', err); else console.log('[MqttProvider] subscribed heartbeat topics')
      })
      // Subscribe to raw GPS + mission topics (devices/*)
      // Prefer specific topics to cut down traffic; fall back to + if broker doesn't support multi-subscribe arrays
  client.subscribe([rawGps1, rawGps2, rawGps3, rawMission, missionUploadRoot], (err) => {
        if (err) {
          // last resort
          client.subscribe(rawAll, (e2) => console.log('[MqttProvider] subscribed rawAll fallback', rawAll, e2 || 'ok'))
        } else {
          console.log('[MqttProvider] subscribed MAVLink raw topics + missionUploadRoot')
        }
      })
    })

    client.on('error', (err) => {
      console.error('MQTT error', err)
      setStatus('error')
    })

    client.on('reconnect', () => setStatus('connecting'))
    client.on('close', () => setStatus('idle'))

  client.on('message', (topic, payload) => {
      const preview = (() => {
        try { return payload.length > 120 ? payload.toString().slice(0, 120) + '…' : payload.toString() } catch { return '(binary)' }
      })()
      // Verbose but useful for initial debugging
      console.debug('[MqttProvider] message', topic, preview)
      try {
        const data = JSON.parse(payload.toString())
        const now = Date.now()
        // Case 1: pathfinder sysid state just for guidance presence
        let m = topic.match(/pathfinder\/sysid_(\d+)\/state$/)
        if (m) {
          const sysid = m[1]
          const entry = {
            sysid,
            group: data.group,
            checkpoint: data.checkpoint ?? data.seq ?? null,
            lat: data.lat ?? null,
            lon: data.lon ?? null,
            alt: data.alt ?? null,
            t: data.t ?? null,
            ts: now,
          }
          telemetryRef.current.set(sysid, entry)
          try { localStorage.setItem('houston.telemetry', JSON.stringify(Array.from(telemetryRef.current.values()))) } catch {}
          setVersion(v => (v + 1) % 1000000)
          return
        }

        // Case 2: raw devices topics
        // Patterns like: <prefix>/devices/mav_sys12/telem/raw/mavlink/<MSG>
        m = topic.match(/devices\/(mav_sys\d+)\/telem\/raw\/mavlink\/([^/]+)$/)
        if (m) {
          const deviceId = m[1]
          const msgType = m[2]
          const sysid = deviceId.replace('mav_sys', '')
          const current = telemetryRef.current.get(sysid) || { sysid, ts: now }

          if (msgType === 'MISSION_CURRENT') {
            if (typeof data.seq === 'number') current.checkpoint = data.seq
          } else if (msgType === 'GLOBAL_POSITION_INT' || msgType === 'GPS_RAW_INT' || msgType === 'GPS2_RAW') {
            let { lat, lon, alt } = data
            // normalize units
            try {
              if (typeof lat === 'number' && Math.abs(lat) > 90) lat = lat / 1e7
              if (typeof lon === 'number' && Math.abs(lon) > 180) lon = lon / 1e7
              if (alt == null) alt = data.alt_ellipsoid ?? data.alt_msl
              if (typeof alt === 'number' && Math.abs(alt) > 10000) alt = alt / 1000
            } catch {}
            current.lat = typeof lat === 'number' ? lat : current.lat
            current.lon = typeof lon === 'number' ? lon : current.lon
            current.alt = typeof alt === 'number' ? alt : current.alt
          }

          current.ts = now
          telemetryRef.current.set(sysid, current)
          try { localStorage.setItem('houston.telemetry', JSON.stringify(Array.from(telemetryRef.current.values()))) } catch {}
          setVersion(v => (v + 1) % 1000000)
          return
        }

        // Case 3: root-level mission upload (payload must include sysid)
        if (topic.endsWith('/mission/upload') && typeof data?.sysid === 'number') {
          const sysid = String(data.sysid)
          const current = telemetryRef.current.get(sysid) || { sysid }
          const items = Array.isArray(data.mission_items) ? data.mission_items : []
          const norm = []
          for (const it of items) {
            let { lat, lon, alt, frame } = it || {}
            try {
              if (typeof lat === 'number' && Math.abs(lat) > 90) lat = lat / 1e7
              if (typeof lon === 'number' && Math.abs(lon) > 180) lon = lon / 1e7
              if (typeof alt === 'number' && Math.abs(alt) > 10000) alt = alt / 1000
            } catch {}
            if (typeof lat === 'number' && typeof lon === 'number') norm.push({ lat, lon, alt: typeof alt === 'number' ? alt : null, frame })
          }
          const ts = Date.now()
          current.mission = { items: norm, count: norm.length, ts, debug: { topic, totalReceived: items.length, absoluteCount: norm.length } }
          current.ts = current.ts || ts
          telemetryRef.current.set(sysid, current)
          try { localStorage.setItem('houston.telemetry', JSON.stringify(Array.from(telemetryRef.current.values()))) } catch {}
          setVersion(v => (v + 1) % 1000000)
          return
        }

        // Case 4: heartbeat (devices/* and flat)
        // Note: keep after mission upload/other handlers to avoid early returns masking them
        //       when topic patterns overlap in future.
        
        // Case 4 actually implemented below
        
        // Case 3: heartbeat (devices/* and flat)
        m = topic.match(/devices\/(mav_sys\d+)\/telem\/state\/heartbeat$/) || topic.match(/\/(mav_sys\d+)\/telem\/state\/heartbeat$/)
        if (m) {
          const deviceId = m[1]
          const sysid = deviceId.replace('mav_sys', '')
          const current = telemetryRef.current.get(sysid) || { sysid }
          current.ts = now
          current.hbTs = now
          current.hbPulseTs = now // used for transient UI pulse on heartbeat arrival
          telemetryRef.current.set(sysid, current)
          try { localStorage.setItem('houston.telemetry', JSON.stringify(Array.from(telemetryRef.current.values()))) } catch {}
          setVersion(v => (v + 1) % 1000000)
          return
        }
      } catch (e) {
        console.warn('[MqttProvider] parse error for topic', topic, e)
      }
    })

    // Periodic tick to update heartbeat freshness visuals even without new messages
  const tick = setInterval(() => setVersion(v => (v + 1) % 1000000), 1000)

    return () => {
      try { client.end(true) } catch {}
      clientRef.current = null
      setStatus('idle')
      clearInterval(tick)
    }
  }, [broker, topicPrefix])

  const value = useMemo(() => ({
    client: clientRef.current,
    status,
    broker,
    topicPrefix,
    telemetry: telemetryRef.current,
    version,
  }), [status, broker, topicPrefix, version])

  return (
    <MqttContext.Provider value={value}>
      {children}
    </MqttContext.Provider>
  )
}
