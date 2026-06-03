import {useEffect, useRef, useState} from 'react'
import subscriptions from '../subscriptions.json'

const isElectron = typeof navigator !== 'undefined' && navigator.userAgent && navigator.userAgent.includes('Electron') || (typeof window !== 'undefined' && window.process && window.process.versions && window.process.versions.electron)
const MISSION_CACHE_KEY = 'nomad_mission_cache_v1'

function loadMissionCache() {
  if (typeof window === 'undefined') return {downloadedMissions: [], downloadedMissionBySysid: {}}
  try {
    const raw = window.localStorage.getItem(MISSION_CACHE_KEY)
    if (!raw) return {downloadedMissions: [], downloadedMissionBySysid: {}}
    const parsed = JSON.parse(raw)
    const list = Array.isArray(parsed && parsed.downloadedMissions) ? parsed.downloadedMissions : []
    const bySysid = parsed && typeof parsed.downloadedMissionBySysid === 'object' && parsed.downloadedMissionBySysid
      ? parsed.downloadedMissionBySysid
      : {}
    const markStale = (m) => ({...m, stale: true})
    return {
      downloadedMissions: list.map(markStale).slice(0, 20),
      downloadedMissionBySysid: Object.fromEntries(
        Object.entries(bySysid).map(([k, v]) => [k, markStale(v)])
      )
    }
  } catch (e) {
    return {downloadedMissions: [], downloadedMissionBySysid: {}}
  }
}

export default function useTelemetry(addToast) {
  const initialMissionCache = loadMissionCache()
  const [connStatus, setConnStatus] = useState('disconnected')
  const [telemetry, setTelemetry] = useState([])
  const [backendStatus, setBackendStatus] = useState(null)
  const [backendHeartbeatTs, setBackendHeartbeatTs] = useState(0)
  const [brokerConfig, setBrokerConfig] = useState(null)
  const [brokerMissing, setBrokerMissing] = useState(false)
  const [brokerError, setBrokerError] = useState(null)
  const [brokerStatus, setBrokerStatus] = useState(null)
  const [downloadedMissions, setDownloadedMissions] = useState(initialMissionCache.downloadedMissions)
  const [downloadedMissionBySysid, setDownloadedMissionBySysid] = useState(initialMissionCache.downloadedMissionBySysid)
  const [missionDownloadStatusBySysid, setMissionDownloadStatusBySysid] = useState({})
  const [missionDownloadLogBySysid, setMissionDownloadLogBySysid] = useState({})

  const clientRef = useRef(null)
  const brokerRef = useRef(null)
  const addToastRef = useRef(addToast)
  const telemetryBufferRef = useRef([])
  const lastMessageTsRef = useRef(0)
  const reconnectingRef = useRef(false)
  const connStatusRef = useRef('disconnected')
  const recentMissionEventRef = useRef({})
  const recentMissionToastRef = useRef({})

  function isDuplicateMissionEvent(signature, windowMs = 8000) {
    const now = Date.now()
    const seenTs = Number(recentMissionEventRef.current[signature] || 0)
    recentMissionEventRef.current[signature] = now
    if (seenTs > 0 && (now - seenTs) <= windowMs) return true
    // prune old keys occasionally
    if (Object.keys(recentMissionEventRef.current).length > 400) {
      const minTs = now - 120000
      recentMissionEventRef.current = Object.fromEntries(
        Object.entries(recentMissionEventRef.current).filter(([, ts]) => Number(ts) >= minTs)
      )
    }
    return false
  }

  function shouldShowMissionToast(signature, windowMs = 12000) {
    const now = Date.now()
    const seenTs = Number(recentMissionToastRef.current[signature] || 0)
    recentMissionToastRef.current[signature] = now
    return !(seenTs > 0 && (now - seenTs) <= windowMs)
  }

  function appendMissionDownloadLog(sysid, entry) {
    const key = String(sysid ?? 'unknown')
    const withTs = {
      ...entry,
      ts: Number(entry && entry.ts) || Date.now()
    }
    setMissionDownloadLogBySysid((prev) => {
      const existing = Array.isArray(prev[key]) ? prev[key] : []
      const latest = existing[0]
      if (
        latest &&
        String(latest.status || '') === String(withTs.status || '') &&
        String(latest.phase || '') === String(withTs.phase || '') &&
        Number(latest.seq ?? -1) === Number(withTs.seq ?? -1) &&
        String(latest.source || '') === String(withTs.source || '') &&
        (Number(withTs.ts) - Number(latest.ts || 0)) <= 2000
      ) {
        return prev
      }
      return {
        ...prev,
        [key]: [withTs].concat(existing).slice(0, 120)
      }
    })
  }

  useEffect(() => {
    connStatusRef.current = connStatus
  }, [connStatus])

  useEffect(() => {
    if (typeof window === 'undefined') return
    try {
      window.localStorage.setItem(
        MISSION_CACHE_KEY,
        JSON.stringify({
          downloadedMissions,
          downloadedMissionBySysid
        })
      )
    } catch (e) {
      // ignore cache write failures
    }
  }, [downloadedMissions, downloadedMissionBySysid])

  useEffect(() => {
    addToastRef.current = addToast
  }, [addToast])

  useEffect(() => {
    if (brokerConfig) {
      fetch('/api/status').then(r => r.ok ? r.json() : null).then(setBrokerStatus).catch(() => setBrokerStatus(null))
    } else {
      setBrokerStatus(null)
    }
  }, [brokerConfig])

  async function fetchBrokerConfig() {
    try {
      if (isElectron && window && window.electronAPI && typeof window.electronAPI.getBrokerConfig === 'function') {
        const cfg = await window.electronAPI.getBrokerConfig()
        if (!cfg) {
          setBrokerMissing(true)
          setBrokerError('electron preload: no broker.json found')
          setBrokerConfig(null)
          return null
        }
        setBrokerConfig(cfg)
        setBrokerMissing(false)
        setBrokerError(null)
        return cfg
      }

      const resp = await fetch('/api/config')
      if (!resp.ok) {
        const text = await resp.text()
        const err = `HTTP ${resp.status} ${resp.statusText}: ${text}`
        setBrokerMissing(true)
        setBrokerError(err)
        setBrokerConfig(null)
        console.warn('broker config fetch failed:', err)
        return null
      }
      const json = await resp.json()
      setBrokerConfig(json)
      setBrokerMissing(false)
      setBrokerError(null)
      return json
    } catch (e) {
      setBrokerMissing(true)
      setBrokerError(String(e))
      setBrokerConfig(null)
      console.warn('broker config fetch error', e)
      return null
    }
  }

  async function connectWithBroker(broker, mountedRef) {
    let client = null
    try {
      const host = broker.host
      const ws_port = broker.ws_port
      // Renderer runs in a browser-like sandbox (including Electron renderer),
      // so always use the browser MQTT bundle over WebSocket.
      const connectUrl = `ws://${host}:${ws_port}`
      const mqttModule = await import('mqtt/dist/mqtt.min')
      const mqttConnect = mqttModule.connect || (mqttModule.default && mqttModule.default.connect)
      if (!mqttConnect) {
        throw new Error('mqtt browser bundle does not expose connect()')
      }
      const auth = {}
      if (broker.username) auth.username = broker.username
      if (broker.password) auth.password = broker.password
      brokerRef.current = broker
      client = mqttConnect(connectUrl, {
        keepalive: 20,
        reconnectPeriod: 1000,
        connectTimeout: 4000,
        clean: true,
        resubscribe: true,
        ...auth
      })
      clientRef.current = client

      client.on('connect', () => {
        if (!mountedRef.current) return
        reconnectingRef.current = false
        setConnStatus('connected')
        subscriptions.forEach((topic) => client.subscribe(topic))
      })

      client.on('message', (topic, payload) => {
        const msg = payload.toString()
        if (topic === 'nomad/status') {
          try {
            const obj = JSON.parse(msg)
            setBackendStatus(obj)
            setBackendHeartbeatTs(Date.now())
          } catch (e) {
            setBackendStatus({raw: msg})
            setBackendHeartbeatTs(Date.now())
          }
        }
        if (topic.startsWith('Nomad/waypoints/') && topic.endsWith('/validation')) {
          try {
            const obj = JSON.parse(msg)
            if (addToastRef.current) {
              addToastRef.current({title: 'Waypoint validation', body: `${obj.filename}: ${obj.valid ? 'OK' : 'FAIL'} (${obj.count} pts)`})
            }
          } catch (e) {
            if (addToastRef.current) {
              addToastRef.current({title: 'Waypoint validation', body: msg})
            }
          }
        }
        if (topic.startsWith('Nomad/missions/downloaded/')) {
          try {
            const obj = JSON.parse(msg)
            if (topic.endsWith('/status')) {
              const sysidKey = String(obj.sysid ?? 'unknown')
              const statusEntry = {
                sysid: obj.sysid ?? null,
                status: String(obj.status || 'unknown'),
                phase: obj.phase || null,
                seq: typeof obj.seq === 'number' ? obj.seq : null,
                ts: Date.now(),
                source: 'status-topic'
              }
              const statusSig = [
                sysidKey,
                statusEntry.status,
                statusEntry.phase || '',
                String(statusEntry.seq ?? ''),
                statusEntry.source
              ].join('|')
              if (isDuplicateMissionEvent(statusSig, 8000)) return
              setMissionDownloadStatusBySysid((prev) => ({
                ...prev,
                [sysidKey]: statusEntry
              }))
              appendMissionDownloadLog(obj.sysid, statusEntry)
              if (addToastRef.current && shouldShowMissionToast(`status:${statusSig}`, 10000)) {
                addToastRef.current({title: 'Mission download status', body: `${obj.status || 'unknown'} (sysid ${obj.sysid ?? '?'})`})
              }
            } else {
              const now = Date.now()
              const isComplete = obj.complete === false || obj.partial === true ? false : true
              const payloadSig = [
                String(obj.sysid ?? 'unknown'),
                String(obj.count ?? ''),
                String(obj.captured_count ?? ''),
                String(isComplete ? 'complete' : 'partial')
              ].join('|')
              if (isDuplicateMissionEvent(`payload:${payloadSig}`, isComplete ? 4800 : 3200)) return
              const normalizedMission = {
                ...obj,
                ts: Number(obj.ts) || now,
                stale: false
              }
              setDownloadedMissions((prev) => [normalizedMission].concat(prev.filter((item) => Number(item.sysid) !== Number(obj.sysid))).slice(0, 20))
              if (typeof obj.sysid !== 'undefined') {
                const sysidKey = String(obj.sysid)
                setDownloadedMissionBySysid((prev) => ({
                  ...prev,
                  [sysidKey]: normalizedMission
                }))
              }
              if (typeof obj.sysid !== 'undefined') {
                const sysidKey = String(obj.sysid)
                const missionStatus = {
                  sysid: obj.sysid,
                  status: isComplete ? 'completed' : 'intercepting',
                  phase: null,
                  seq: null,
                  ts: now,
                  source: 'mission-payload',
                  count: Number(obj.count) || Number(obj.captured_count) || 0,
                  downloadDuration: Number(obj.download_duration) || null
                }
                setMissionDownloadStatusBySysid((prev) => ({
                  ...prev,
                  [sysidKey]: missionStatus
                }))
                appendMissionDownloadLog(obj.sysid, missionStatus)
              }
              if (addToastRef.current && shouldShowMissionToast(`payload:${payloadSig}`, isComplete ? 16000 : 12000)) {
                if (isComplete) {
                  addToastRef.current({title: 'Mission downloaded', body: `From sysid ${obj.sysid}: ${obj.count} waypoints`})
                } else {
                  addToastRef.current({title: 'Mission intercept', body: `Sysid ${obj.sysid}: ${obj.captured_count || 0}/${obj.count || '?'} waypoints observed`})
                }
              }
            }
          } catch (e) {
            if (addToastRef.current) {
              addToastRef.current({title: 'Mission download', body: msg})
            }
          }
        }
        if (topic.startsWith('command/') && topic.endsWith('/ack')) {
          try {
            const obj = JSON.parse(msg)
            const status = String(obj.status || '')
            if (status.includes('download') || status.includes('request')) {
              const parts = topic.split('/')
              const sysidKey = String(obj.sysid ?? parts[1] ?? 'unknown')
              const ackEntry = {
                sysid: obj.sysid ?? (Number(parts[1]) || null),
                status,
                phase: null,
                seq: null,
                ts: Date.now(),
                source: 'command-ack'
              }
              const ackSig = [
                String(sysidKey),
                String(status || ''),
                String(ackEntry.source)
              ].join('|')
              if (isDuplicateMissionEvent(`ack:${ackSig}`, 8000)) return
              setMissionDownloadStatusBySysid((prev) => ({
                ...prev,
                [sysidKey]: ackEntry
              }))
              appendMissionDownloadLog(obj.sysid ?? (Number(parts[1]) || null), ackEntry)
              if (addToastRef.current && shouldShowMissionToast(`ack:${ackSig}`, 10000)) {
                addToastRef.current({title: 'Download command ACK', body: status})
              }
            }
          } catch (e) {
            // ignore malformed ack payloads
          }
        }
        lastMessageTsRef.current = Date.now()
        telemetryBufferRef.current.push({topic, msg, ts: Date.now()})
      })

      client.on('reconnect', () => setConnStatus('reconnecting'))
      client.on('close', () => setConnStatus('disconnected'))
      client.on('error', (e) => {
        console.error('mqtt error', e)
        setBrokerError(String(e))
      })
    } catch (e) {
      console.error('failed to start mqtt client', e)
      setBrokerError(String(e))
    }
    return client
  }

  useEffect(() => {
    let mounted = true

    let statusInterval = null
    let telemetryFlushInterval = null
    let telemetryWatchdogInterval = null
    async function pollStatus() {
      try {
        const r = await fetch('/api/status')
        if (!r.ok) return
        const j = await r.json()
        setBackendStatus(j)
        setBackendHeartbeatTs(Date.now())
      } catch (e) {
        // ignore
      }
    }
    pollStatus()
    statusInterval = setInterval(pollStatus, 3000)
    telemetryFlushInterval = setInterval(() => {
      const pending = telemetryBufferRef.current
      if (!pending.length) return
      telemetryBufferRef.current = []
      setTelemetry((s) => pending.concat(s).slice(0, 5000))
    }, 120)
    telemetryWatchdogInterval = setInterval(async () => {
      if (connStatusRef.current !== 'connected') return
      if (!brokerRef.current || !clientRef.current) return
      const lastTs = lastMessageTsRef.current
      if (!lastTs) return
      const idleMs = Date.now() - lastTs
      if (idleMs < 8000) return
      if (reconnectingRef.current) return

      reconnectingRef.current = true
      setConnStatus('reconnecting')
      try {
        clientRef.current.end(true)
      } catch (e) {
        // ignore
      }
      try {
        await connectWithBroker(brokerRef.current, {current: mounted})
      } catch (e) {
        reconnectingRef.current = false
      }
    }, 2000)

    async function startClient() {
      try {
        const broker = await fetchBrokerConfig()
        if (!broker) {
          setConnStatus('no-broker-config')
          return
        }
        await connectWithBroker(broker, { current: mounted })
      } catch (e) {
        console.error('failed to start mqtt client', e)
      }
    }

    startClient()

    return () => {
      try {
        if (clientRef.current) clientRef.current.end()
      } catch (e) {
        // ignore
      }
      mounted = false
      if (statusInterval) clearInterval(statusInterval)
      if (telemetryFlushInterval) clearInterval(telemetryFlushInterval)
      if (telemetryWatchdogInterval) clearInterval(telemetryWatchdogInterval)
    }
  }, [])

  const retryFetchBroker = async () => {
    setBrokerError(null)
    setBrokerMissing(false)
    setConnStatus('reloading-broker-config')
    const b = await fetchBrokerConfig()
    if (b) {
      setConnStatus('connecting')
      try {
        const client = await connectWithBroker(b, { current: true })
        if (client) {
          setConnStatus('connected')
        }
      } catch (e) {
        console.error('connectWithBroker failed', e)
        setBrokerError(String(e))
        setConnStatus('connect-failed')
      }
    } else {
      setConnStatus('no-broker-config')
    }
  }

  function clearDownloadedMissions() {
    setDownloadedMissions([])
    setDownloadedMissionBySysid({})
    setMissionDownloadStatusBySysid({})
    setMissionDownloadLogBySysid({})
    try { window.localStorage.removeItem(MISSION_CACHE_KEY) } catch (e) {}
  }

  return {
    connStatus,
    telemetry,
    backendStatus,
    backendHeartbeatTs,
    brokerConfig,
    brokerMissing,
    brokerError,
    brokerStatus,
    downloadedMissions,
    downloadedMissionBySysid,
    missionDownloadStatusBySysid,
    missionDownloadLogBySysid,
    clientRef,
    retryFetchBroker,
    fetchBrokerConfig,
    connectWithBroker,
    clearDownloadedMissions
  }
}
