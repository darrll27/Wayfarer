export const API_BASE = (typeof (import.meta as any).env !== 'undefined' && (import.meta as any).env?.VITE_API_BASE) || (typeof window !== 'undefined' && (window as any).NOMAD_API_BASE) || 'http://localhost:8000'

export async function apiFetch(input: string, init?: RequestInit) {
  const url = input.startsWith('http') ? input : `${API_BASE}${input.startsWith('/') ? '' : '/'}${input}`
  const method = (init && init.method) || 'GET'
  // capture request body if present
  let reqBody: any = undefined
  try {
    if (init && init.body) {
      if (typeof init.body === 'string') reqBody = init.body
      else reqBody = JSON.stringify(init.body)
    }
  } catch (e) {
    reqBody = String(e)
  }

  const start = Date.now()
  try {
    const res = await fetch(url, init)
    // try to read response text for terminal logging (clone so caller can still use it)
    let resText = ''
    try {
      const clone = res.clone()
      resText = await clone.text()
    } catch (e) {
      resText = `<<unreadable response: ${e}>>`
    }

    if (typeof window !== 'undefined') {
      ;(window as any).NOMAD_TERMINAL_LOGS = (window as any).NOMAD_TERMINAL_LOGS || []
      ;(window as any).NOMAD_TERMINAL_LOGS.push({
        ts: new Date().toISOString(),
        elapsed_ms: Date.now() - start,
        method,
        url,
        req: reqBody,
        status: res.status,
        res: resText,
      })
    }

    return res
  } catch (err: any) {
    if (typeof window !== 'undefined') {
      ;(window as any).NOMAD_TERMINAL_LOGS = (window as any).NOMAD_TERMINAL_LOGS || []
      ;(window as any).NOMAD_TERMINAL_LOGS.push({
        ts: new Date().toISOString(),
        elapsed_ms: Date.now() - start,
        method,
        url,
        req: reqBody,
        error: String(err),
      })
    }
    throw err
  }
}

export default apiFetch
