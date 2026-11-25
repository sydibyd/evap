import { useEffect, useMemo, useState } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { api, getToken, setToken } from './api'
import { AppCtx, Err, Modal, useToast } from './components/ui'
import Overview from './pages/Overview'
import Requirements from './pages/Requirements'
import TestDesign from './pages/TestDesign'
import CICD from './pages/CICD'
import Results from './pages/Results'

function Login({ onLogin }) {
  const [u, setU] = useState('')
  const [p, setP] = useState('')
  const [err, setErr] = useState(null)
  const submit = async (e) => {
    e.preventDefault()
    try { const r = await api('/auth/login', { method: 'POST', body: { username: u, password: p } }); setToken(r.token); onLogin(r.user) }
    catch (ex) { setErr(ex.message) }
  }
  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <h1>EVAP</h1>
        <p className="muted small">Embedded Validation Automation Platform</p>
        <Err msg={err} />
        <label>Username<input value={u} onChange={(e) => setU(e.target.value)} autoFocus /></label>
        <label>Password<input type="password" value={p} onChange={(e) => setP(e.target.value)} /></label>
        <button className="primary" style={{ width: '100%' }}>Sign in</button>
      </form>
    </div>
  )
}

function NewProject({ onClose, onCreated }) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [err, setErr] = useState(null)
  const save = async () => {
    try { onCreated(await api('/projects', { method: 'POST', body: { name, description: desc } })) }
    catch (e) { setErr(e.message) }
  }
  return (
    <Modal title="New validation project" onClose={onClose}>
      <Err msg={err} />
      <label>Project name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="Mini BMS" autoFocus /></label>
      <label>Description<textarea value={desc} onChange={(e) => setDesc(e.target.value)} /></label>
      <div className="row"><button className="primary" onClick={save} disabled={!name.trim()}>Create project</button></div>
    </Modal>
  )
}

const NAV = [['/', 'Overview'], ['/requirements', 'Requirements'], ['/test-design', 'Test Design'],
  ['/cicd', 'CI/CD Integration'], ['/results', 'Validation Results']]

export default function App() {
  const [user, setUser] = useState(null)
  const [checked, setChecked] = useState(false)
  const [projects, setProjects] = useState([])
  const [pid, setPid] = useState(() => Number(localStorage.getItem('evap_project')) || null)
  const [newProj, setNewProj] = useState(false)
  const [toast, notify] = useToast()

  useEffect(() => {
    const out = () => setUser(null)
    window.addEventListener('evap-logout', out)
    if (getToken()) api('/auth/me').then(setUser).catch(() => setToken(null)).finally(() => setChecked(true))
    else setChecked(true)
    return () => window.removeEventListener('evap-logout', out)
  }, [])

  const loadProjects = async () => {
    const ps = await api('/projects')
    setProjects(ps)
    if (ps.length && !ps.find((p) => p.id === pid)) setPid(ps[0].id)
    return ps
  }
  useEffect(() => { if (user) loadProjects() }, [user]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (pid) localStorage.setItem('evap_project', pid) }, [pid])

  const project = projects.find((p) => p.id === pid) || null
  const ctx = useMemo(() => ({ user, project, pid, notify, reloadProjects: loadProjects,
    can: { write: !!user, review: user && ['reviewer', 'admin'].includes(user.role), admin: user?.role === 'admin' } }),
  [user, project, pid]) // eslint-disable-line react-hooks/exhaustive-deps

  if (!checked) return null
  if (!user) return <Login onLogin={setUser} />

  return (
    <AppCtx.Provider value={ctx}>
      <div className="layout">
        <nav className="sidebar">
          <div className="brand">EVAP</div>
          <div className="tagline">Universal CI/CD Validation Platform for Embedded Software</div>
          {NAV.map(([to, label]) => <NavLink key={to} to={to} end={to === '/'}>{label}</NavLink>)}
          <div className="spacer" />
          <div className="who">{user.username} · {user.role}<br />
            <a href="/api/docs" target="_blank" rel="noreferrer">API docs</a> · <a href="#" onClick={(e) => { e.preventDefault(); setToken(null); setUser(null) }}>Sign out</a>
          </div>
        </nav>
        <main className="main">
          <div className="topbar">
            <span className="muted small">Project</span>
            <select style={{ width: 240 }} value={pid || ''} onChange={(e) => setPid(Number(e.target.value))}>
              {!projects.length && <option value="">— none —</option>}
              {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
            <button onClick={() => setNewProj(true)}>+ New project</button>
            <div className="grow" />
            {project?.git && <span className="small muted mono">{project.git.repo_url} · {project.git.branch}</span>}
          </div>
          {!project ? (
            <div className="card empty">
              <p>No validation project yet.</p>
              <button className="primary" onClick={() => setNewProj(true)}>Create your first project</button>
            </div>
          ) : (
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/requirements" element={<Requirements />} />
              <Route path="/test-design" element={<TestDesign />} />
              <Route path="/cicd" element={<CICD />} />
              <Route path="/results" element={<Results />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          )}
        </main>
      </div>
      {newProj && <NewProject onClose={() => setNewProj(false)} onCreated={async (p) => { setNewProj(false); await loadProjects(); setPid(p.id); notify(`Project "${p.name}" created`) }} />}
      {toast}
    </AppCtx.Provider>
  )
}
