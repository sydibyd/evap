import { createContext, useContext, useEffect, useState } from 'react'

export function Badge({ value }) {
  if (!value) return <span className="muted">—</span>
  return <span className={`badge b-${value}`}>{value}</span>
}

export function Modal({ title, onClose, children, actions }) {
  useEffect(() => {
    const h = (e) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={title}>
        <div className="head"><h2>{title}</h2>{actions}<button onClick={onClose} aria-label="Close">✕</button></div>
        {children}
      </div>
    </div>
  )
}

export function Err({ msg }) { return msg ? <div className="err">{msg}</div> : null }

export function Kpi({ label, value, sub, pct }) {
  return (
    <div className="card kpi">
      <div className="label">{label}</div>
      <div className="value">{value}</div>
      {sub && <div className="sub">{sub}</div>}
      {pct != null && <div className="bar"><div style={{ width: `${Math.min(100, pct)}%` }} /></div>}
    </div>
  )
}

export function Sha({ sha, repo }) {
  if (!sha) return <span className="muted">—</span>
  const m = repo && repo.match(/github\.com[:/](.+?)(\.git)?$/)
  const short = <code title={sha}>{sha.slice(0, 8)}</code>
  return m ? <a href={`https://github.com/${m[1]}/commit/${sha}`} target="_blank" rel="noreferrer">{short}</a> : short
}

// --- App-wide context: current user, selected project, toast -----------------------
export const AppCtx = createContext(null)
export const useApp = () => useContext(AppCtx)

export function useToast() {
  const [msg, setMsg] = useState(null)
  useEffect(() => { if (msg) { const t = setTimeout(() => setMsg(null), 3500); return () => clearTimeout(t) } }, [msg])
  return [msg ? <div className="toast">{msg}</div> : null, setMsg]
}
