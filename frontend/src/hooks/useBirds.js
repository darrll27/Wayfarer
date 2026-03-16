import {useEffect, useMemo, useRef} from 'react'

const HEARTBEAT_LIVE_MS = 10000

export function evaluateBirdStatus(bird, now = Date.now()) {
  const isLive = now - (bird.lastSeen || 0) <= HEARTBEAT_LIVE_MS
  const systemStatus = Number(bird.metrics && bird.metrics.systemStatus)
  const gpsFix = Number(bird.metrics && bird.metrics.gpsFix)
  const gpsCount = Number(bird.gpsCount)
  const battery = Number(bird.metrics && bird.metrics.battery)
  const hasPosition = bird.lat !== null && bird.lon !== null

  const hasGpsFixReading = Number.isFinite(gpsFix)
  const hasNavigation = hasGpsFixReading
    ? gpsFix >= 3
    : (Number.isFinite(gpsCount) && gpsCount >= 6)
  const batteryOk = !Number.isFinite(battery) || battery >= 20
  const stateReady = systemStatus === 3 || systemStatus === 4
  const isReady = isLive && stateReady && hasNavigation && hasPosition && batteryOk

  return {
    isLive,
    isReady
  }
}

function extractHeartbeatMode(parsedMsg) {
  const fields = parsedMsg && parsedMsg.fields ? parsedMsg.fields : parsedMsg
  if (!fields || typeof fields !== 'object') return null
  const autopilot = Number(fields.autopilot)
  const customMode = Number(fields.custom_mode)
  if (!Number.isNaN(autopilot) && autopilot === 12 && !Number.isNaN(customMode)) {
    const px4Mode = decodePx4CustomMode(customMode)
    if (px4Mode) return px4Mode
  }
  if (typeof fields.mode !== 'undefined') return String(fields.mode)
  if (typeof fields.custom_mode !== 'undefined') return `custom:${fields.custom_mode}`
  if (typeof fields.base_mode !== 'undefined') return `base:${fields.base_mode}`
  return null
}

function decodePx4CustomMode(customMode) {
  const value = Number(customMode)
  if (!Number.isFinite(value)) return null
  const mainMode = (value >> 16) & 0xff
  const subMode = (value >> 24) & 0xff

  const mainModeLabel = {
    1: 'PX4_CUSTOM_MAIN_MODE_MANUAL',
    2: 'PX4_CUSTOM_MAIN_MODE_ALTCTL',
    3: 'PX4_CUSTOM_MAIN_MODE_POSCTL',
    4: 'PX4_CUSTOM_MAIN_MODE_AUTO',
    5: 'PX4_CUSTOM_MAIN_MODE_ACRO',
    6: 'PX4_CUSTOM_MAIN_MODE_OFFBOARD',
    7: 'PX4_CUSTOM_MAIN_MODE_STABILIZED',
    8: 'PX4_CUSTOM_MAIN_MODE_RATTITUDE_LEGACY',
    9: 'PX4_CUSTOM_MAIN_MODE_SIMPLE',
    10: 'PX4_CUSTOM_MAIN_MODE_TERMINATION',
    11: 'PX4_CUSTOM_MAIN_MODE_ALTITUDE_CRUISE'
  }[mainMode]

  if (!mainModeLabel) return null
  if (mainModeLabel === 'PX4_CUSTOM_MAIN_MODE_POSCTL') {
    const posctlSubModeLabel = {
      0: 'PX4_CUSTOM_SUB_MODE_POSCTL_POSCTL',
      1: 'PX4_CUSTOM_SUB_MODE_POSCTL_ORBIT',
      2: 'PX4_CUSTOM_SUB_MODE_POSCTL_SLOW'
    }[subMode]
    if (posctlSubModeLabel) {
      return `${mainModeLabel}:${posctlSubModeLabel}`
    }
  }
  if (mainModeLabel !== 'PX4_CUSTOM_MAIN_MODE_AUTO') return mainModeLabel

  const subModeLabel = {
    1: 'PX4_CUSTOM_SUB_MODE_AUTO_READY',
    2: 'PX4_CUSTOM_SUB_MODE_AUTO_TAKEOFF',
    3: 'PX4_CUSTOM_SUB_MODE_AUTO_LOITER',
    4: 'PX4_CUSTOM_SUB_MODE_AUTO_MISSION',
    5: 'PX4_CUSTOM_SUB_MODE_AUTO_RTL',
    6: 'PX4_CUSTOM_SUB_MODE_AUTO_LAND',
    7: 'PX4_CUSTOM_SUB_MODE_AUTO_RESERVED_DO_NOT_USE',
    8: 'PX4_CUSTOM_SUB_MODE_AUTO_FOLLOW_TARGET',
    9: 'PX4_CUSTOM_SUB_MODE_AUTO_PRECLAND',
    10: 'PX4_CUSTOM_SUB_MODE_AUTO_VTOL_TAKEOFF',
    11: 'PX4_CUSTOM_SUB_MODE_EXTERNAL1',
    12: 'PX4_CUSTOM_SUB_MODE_EXTERNAL2',
    13: 'PX4_CUSTOM_SUB_MODE_EXTERNAL3',
    14: 'PX4_CUSTOM_SUB_MODE_EXTERNAL4',
    15: 'PX4_CUSTOM_SUB_MODE_EXTERNAL5',
    16: 'PX4_CUSTOM_SUB_MODE_EXTERNAL6',
    17: 'PX4_CUSTOM_SUB_MODE_EXTERNAL7',
    18: 'PX4_CUSTOM_SUB_MODE_EXTERNAL8'
  }[subMode]

  if (!subModeLabel) return mainModeLabel
  return `${mainModeLabel}:${subModeLabel}`
}

export function parseDeviceTopic(topic) {
  let match = topic.match(/^device\/(\d+)\/(\d+)\/([^/]+)(?:\/([^/]+))?$/)
  if (match) {
    return {sysid: match[1], compid: match[2], msgType: match[3], field: match[4]}
  }
  match = topic.match(/^device\/sysid_(\d+)\/compid_(\d+)\/([^/]+)(?:\/([^/]+))?$/)
  if (match) {
    return {sysid: match[1], compid: match[2], msgType: match[3], field: match[4]}
  }
  match = topic.match(/^sources\/source_sysid_(\d+)\/source_compid_(\d+)\/dest_sysid_\d+\/dest_compid_\d+\/([^/]+)(?:\/([^/]+))?$/)
  if (match) {
    return {sysid: match[1], compid: match[2], msgType: match[3], field: match[4]}
  }
  return null
}

export function useBirds(telemetry, birdFilter, selectedBird, dataLossGraceMs) {
  const modeCacheRef = useRef({})
  const heartbeatCacheRef = useRef({})
  const retainedBirdsRef = useRef({})
  const birdRecords = useMemo(() => {
    const BIRD_RETENTION_MS = 30 * 60 * 1000
    const now = Date.now()
    const map = {}
    const heartbeatIntervals = {}
    const lastHeartbeatTs = {}
    telemetry.forEach(({topic, msg, ts}) => {
      const parsed = parseDeviceTopic(topic)
      if (!parsed) return
      const {sysid, compid, msgType, field} = parsed

      if (!map[sysid]) {
        map[sysid] = {
          sysid,
          compid,
          lastSeen: ts,
          lastHeartbeat: 0,
          topics: new Set(),
          lat: null,
          lon: null,
          gpsCount: null,
          metrics: {},
          lastMessage: null
        }
      }
      const bird = map[sysid]
      bird.lastSeen = Math.max(bird.lastSeen, ts)
      bird.topics.add(msgType)
      bird.lastMessage = {topic, msg, ts}

      const parsedMsg = (() => {
        try {
          return JSON.parse(msg)
        } catch (e) {
          return null
        }
      })()
      const fields = parsedMsg && parsedMsg.fields ? parsedMsg.fields : parsedMsg

      if (msgType === 'HEARTBEAT') {
        bird.lastHeartbeat = Math.max(bird.lastHeartbeat, ts)
        const mode = extractHeartbeatMode(parsedMsg)
        if (mode) {
          bird.metrics.mode = mode
        }
        if (fields && typeof fields.base_mode !== 'undefined') {
          const baseMode = Number(fields.base_mode)
          if (Number.isFinite(baseMode)) {
            bird.metrics.baseMode = baseMode
            bird.metrics.armed = (baseMode & 0x80) !== 0
          }
        }
        if (fields && typeof fields.system_status !== 'undefined') {
          const systemStatus = Number(fields.system_status)
          if (Number.isFinite(systemStatus)) {
            bird.metrics.systemStatus = systemStatus
          }
        }
        const prevTs = lastHeartbeatTs[sysid]
        if (!heartbeatIntervals[sysid] && prevTs) {
          heartbeatIntervals[sysid] = Math.abs(prevTs - ts)
        }
        lastHeartbeatTs[sysid] = ts
      }

      if (msgType === 'GLOBAL_POSITION_INT') {
        if (field) {
          const value = fields && typeof fields[field] !== 'undefined' ? fields[field] : Number(msg)
          if (!Number.isNaN(value)) {
            if (field === 'lat') bird.lat = value / 1e7
            if (field === 'lon') bird.lon = value / 1e7
            if (field === 'alt') bird.metrics.alt = value / 1000
            if (field === 'relative_alt') bird.metrics.relativeAlt = value / 1000
            if (field === 'vx') bird.metrics.vx = value / 100
            if (field === 'vy') bird.metrics.vy = value / 100
            if (field === 'vz') bird.metrics.vz = value / 100
          }
        } else if (fields) {
          if (typeof fields.lat !== 'undefined' && typeof fields.lon !== 'undefined') {
            bird.lat = Number(fields.lat) / 1e7
            bird.lon = Number(fields.lon) / 1e7
          }
          if (typeof fields.alt !== 'undefined') bird.metrics.alt = Number(fields.alt) / 1000
          if (typeof fields.relative_alt !== 'undefined') bird.metrics.relativeAlt = Number(fields.relative_alt) / 1000
          if (typeof fields.vx !== 'undefined') bird.metrics.vx = Number(fields.vx) / 100
          if (typeof fields.vy !== 'undefined') bird.metrics.vy = Number(fields.vy) / 100
          if (typeof fields.vz !== 'undefined') bird.metrics.vz = Number(fields.vz) / 100
        }
      }

      if (msgType === 'GPS_RAW_INT' && fields) {
        if (typeof fields.satellites_visible !== 'undefined') {
          bird.gpsCount = Number(fields.satellites_visible)
        }
        if (typeof fields.fix_type !== 'undefined') bird.metrics.gpsFix = fields.fix_type
        if (typeof fields.eph !== 'undefined') bird.metrics.eph = fields.eph
        if (typeof fields.epv !== 'undefined') bird.metrics.epv = fields.epv
      }

      if (msgType === 'LOCAL_POSITION_NED') {
        if (field) {
          const value = fields && typeof fields[field] !== 'undefined' ? fields[field] : Number(msg)
          if (!Number.isNaN(value)) {
            if (field === 'x') bird.metrics.localX = value
            if (field === 'y') bird.metrics.localY = value
            if (field === 'z') bird.metrics.localZ = value
          }
        } else if (fields) {
          if (typeof fields.x !== 'undefined') bird.metrics.localX = Number(fields.x)
          if (typeof fields.y !== 'undefined') bird.metrics.localY = Number(fields.y)
          if (typeof fields.z !== 'undefined') bird.metrics.localZ = Number(fields.z)
        }
      }

      if (msgType === 'ATTITUDE') {
        if (field) {
          const value = fields && typeof fields[field] !== 'undefined' ? fields[field] : Number(msg)
          if (!Number.isNaN(value)) {
            if (field === 'roll') bird.metrics.roll = value
            if (field === 'pitch') bird.metrics.pitch = value
            if (field === 'yaw') bird.metrics.yaw = value
          }
        } else if (fields) {
          if (typeof fields.roll !== 'undefined') bird.metrics.roll = Number(fields.roll)
          if (typeof fields.pitch !== 'undefined') bird.metrics.pitch = Number(fields.pitch)
          if (typeof fields.yaw !== 'undefined') bird.metrics.yaw = Number(fields.yaw)
        }
      }

      if (msgType === 'VFR_HUD') {
        if (field) {
          const value = fields && typeof fields[field] !== 'undefined' ? fields[field] : Number(msg)
          if (!Number.isNaN(value)) {
            if (field === 'airspeed') bird.metrics.airspeed = value
            if (field === 'groundspeed') bird.metrics.groundspeed = value
            if (field === 'heading') bird.metrics.heading = value
            if (field === 'throttle') bird.metrics.throttle = value
            if (field === 'alt') bird.metrics.hudAlt = value
            if (field === 'climb') bird.metrics.climb = value
          }
        } else if (fields) {
          if (typeof fields.airspeed !== 'undefined') bird.metrics.airspeed = Number(fields.airspeed)
          if (typeof fields.groundspeed !== 'undefined') bird.metrics.groundspeed = Number(fields.groundspeed)
          if (typeof fields.heading !== 'undefined') bird.metrics.heading = Number(fields.heading)
          if (typeof fields.throttle !== 'undefined') bird.metrics.throttle = Number(fields.throttle)
          if (typeof fields.alt !== 'undefined') bird.metrics.hudAlt = Number(fields.alt)
          if (typeof fields.climb !== 'undefined') bird.metrics.climb = Number(fields.climb)
        }
      }

      if (msgType === 'SYS_STATUS' && fields) {
        if (typeof fields.voltage_battery !== 'undefined') bird.metrics.voltage = Number(fields.voltage_battery) / 1000
        if (typeof fields.current_battery !== 'undefined') bird.metrics.current = Number(fields.current_battery) / 100
        if (typeof fields.battery_remaining !== 'undefined') bird.metrics.battery = Number(fields.battery_remaining)
      }

      if (msgType === 'MISSION_CURRENT' && fields) {
        if (typeof fields.seq !== 'undefined') bird.metrics.missionSeq = Number(fields.seq)
      }
    })
    Object.values(map).forEach((bird) => {
      const interval = heartbeatIntervals[bird.sysid]
      if (interval) {
        bird.metrics.heartbeatIntervalMs = interval
      }

      const retained = retainedBirdsRef.current[bird.sysid]
      if (retained) {
        bird.lastSeen = Math.max(retained.lastSeen || 0, bird.lastSeen || 0)
        bird.lastHeartbeat = Math.max(retained.lastHeartbeat || 0, bird.lastHeartbeat || 0)
        bird.topics = new Set([...(retained.topics || []), ...(bird.topics || [])])
        bird.lat = bird.lat !== null ? bird.lat : retained.lat
        bird.lon = bird.lon !== null ? bird.lon : retained.lon
        bird.gpsCount = bird.gpsCount !== null ? bird.gpsCount : retained.gpsCount
        bird.metrics = {...(retained.metrics || {}), ...(bird.metrics || {})}
        bird.lastMessage = bird.lastMessage || retained.lastMessage
      }

      retainedBirdsRef.current[bird.sysid] = bird
    })

    Object.keys(retainedBirdsRef.current).forEach((sysid) => {
      const bird = retainedBirdsRef.current[sysid]
      const isExpired = now - (bird.lastSeen || 0) > BIRD_RETENTION_MS
      if (isExpired) {
        delete retainedBirdsRef.current[sysid]
        return
      }
      if (!map[sysid]) {
        map[sysid] = bird
      }
    })

    return map
  }, [telemetry])

  const birdList = useMemo(() => {
    const list = Object.values(birdRecords)
    list.sort((a, b) => {
      const aSysid = Number(a.sysid)
      const bSysid = Number(b.sysid)
      if (aSysid !== bSysid) return aSysid - bSysid

      const aCompid = Number(a.compid)
      const bCompid = Number(b.compid)
      if (aCompid !== bCompid) return aCompid - bCompid

      return String(a.sysid).localeCompare(String(b.sysid))
    })
    if (!birdFilter) return list
    const q = birdFilter.toLowerCase()
    return list.filter(b => String(b.sysid).includes(q) || String(b.compid).includes(q))
  }, [birdRecords, birdFilter])

  const selectedBirdTelemetry = selectedBird
    ? telemetry.filter(t => {
      const parsed = parseDeviceTopic(t.topic)
      return parsed && String(parsed.sysid) === String(selectedBird)
    }).slice(0, 80)
    : []

  const selectedBirdRecord = selectedBird ? birdRecords[selectedBird] : null

  useEffect(() => {
    Object.values(birdRecords).forEach((bird) => {
      if (bird.metrics && bird.metrics.mode) {
        modeCacheRef.current[bird.sysid] = {
          mode: bird.metrics.mode,
          ts: bird.lastHeartbeat || bird.lastSeen || Date.now()
        }
      }
      if (bird.lastHeartbeat) {
        heartbeatCacheRef.current[bird.sysid] = {
          ts: bird.lastHeartbeat,
          intervalMs: bird.metrics.heartbeatIntervalMs || 0
        }
      }
    })
  }, [birdRecords])

  const selectedBirdHeartbeat = useMemo(() => {
    if (!selectedBird) return 0
    if (selectedBirdRecord && selectedBirdRecord.lastHeartbeat) {
      return selectedBirdRecord.lastHeartbeat
    }
    const cached = heartbeatCacheRef.current[selectedBird]
    if (!cached) return 0
    const graceMs = Number.isFinite(dataLossGraceMs) ? dataLossGraceMs : 500
    const effectiveGraceMs = Math.max(graceMs, 1000, cached.intervalMs * 1.5)
    if (Date.now() - cached.ts <= effectiveGraceMs) {
      return cached.ts
    }
    return 0
  }, [selectedBird, selectedBirdRecord, dataLossGraceMs])

  const selectedBirdMode = useMemo(() => {
    if (!selectedBird) return 'unknown'
    const record = selectedBirdRecord
    if (record && record.metrics && record.metrics.mode) {
      return record.metrics.mode
    }
    const cached = modeCacheRef.current[selectedBird]
    if (!cached) return 'unknown'
    const graceMs = Number.isFinite(dataLossGraceMs) ? dataLossGraceMs : 500
    const heartbeatIntervalMs = record && record.metrics && record.metrics.heartbeatIntervalMs
      ? record.metrics.heartbeatIntervalMs
      : (heartbeatCacheRef.current[selectedBird] ? heartbeatCacheRef.current[selectedBird].intervalMs : 0)
    const effectiveGraceMs = Math.max(graceMs, 1000, heartbeatIntervalMs * 1.5)
    if (Date.now() - cached.ts <= effectiveGraceMs) {
      return cached.mode
    }
    return 'unknown'
  }, [selectedBird, selectedBirdRecord, dataLossGraceMs])

  const fleetStats = useMemo(() => {
    const now = Date.now()
    const all = Object.values(birdRecords)
    const active = all.filter(b => now - (b.lastSeen || 0) < 10000)
    return {
      total: all.length,
      active: active.length,
      stale: all.length - active.length
    }
  }, [birdRecords])

  return {
    birdRecords,
    birdList,
    selectedBirdRecord,
    selectedBirdHeartbeat,
    selectedBirdTelemetry,
    selectedBirdMode,
    fleetStats
  }
}
