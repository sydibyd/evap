import { useCallback, useEffect, useRef, useState } from 'react'

const TOKEN_KEY = 'evap_token'
export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const setToken = (t) => (t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY))

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

function detail(body, status) {
  if (!body) return `HTTP ${status}`
  if (typeof body.detail === 'string') return body.detail
  if (Array.isArray(body.detail)) return body.detail.map((d) => `${(d.loc || []).slice(1).join('.')}: ${d.msg}`).join('\n')
  return `HTTP ${status}`
}

export async function api(path, { method = 'GET', body, form, blob } = {}) {
  const headers = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const res = await fetch(`/api${path}`, { method, headers, body: payload })
  if (res.status === 401 && token) { setToken(null); window.dispatchEvent(new Event('evap-logout')) }
  if (!res.ok) {
    let b = null
    try { b = await res.json() } catch { /* not json */ }
    throw new ApiError(res.status, detail(b, res.status))
  }
  if (blob) return res.blob()
  return res.status === 204 ? null : res.json()
}

/** Fetch `path` and optionally re-poll every `pollMs` (used for live dashboards). */
export function useApi(path, { pollMs = 0, deps = [] } = {}) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const alive = useRef(true)
  const load = useCallback(async () => {
    if (!path) return
    try { const d = await api(path); if (alive.current) { setData(d); setError(null) } }
    catch (e) { if (alive.current) setError(e.message) }
  }, [path])
  useEffect(() => {
    alive.current = true
    load()
    let t
    if (pollMs) t = setInterval(load, pollMs)
    return () => { alive.current = false; if (t) clearInterval(t) }
  }, [load, pollMs, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  return { data, error, reload: load, setData }
}

export async function download(path, filename) {
  const b = await api(path, { blob: true })
  const url = URL.createObjectURL(b)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const fmtDate = (s) => (s ? new Date(s).toLocaleString() : '—')
export const shortSha = (s) => (s ? s.slice(0, 8) : '—')
export const fmtDur = (s) => (s == null ? '—' : `${s.toFixed(2)} s`)
