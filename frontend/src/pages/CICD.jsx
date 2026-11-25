import { useEffect, useState } from 'react'
import { api, fmtDate, useApi } from '../api'
import { Badge, Err, useApp } from '../components/ui'

const DEFAULT_GIT = { repo_url: '', branch: 'main', auto_validation: false, python_env: 'python3.11', timeout_s: 60, gate_policy: 'all_pass', gate_threshold: 100 }

const WORKFLOW = (branch) => `# .github/workflows/evap-validation.yml  (in the System Under Test repository)
name: EVAP SIL validation
on:
  push:
    branches: [${branch}]        # trusted branch only — no pull_request triggers
permissions:
  contents: read
concurrency:
  group: evap-\${{ github.sha }}
jobs:
  evap:
    if: github.event_name == 'push' && github.repository_owner == '<owner>'
    runs-on: [self-hosted, evap-local]
    timeout-minutes: 20
    steps:
      - name: Trigger EVAP and wait for the quality gate
        env:
          EVAP_URL: http://127.0.0.1:8300
          EVAP_CI_TOKEN: \${{ secrets.EVAP_CI_TOKEN }}
        run: python3 - <<'PY'
          # evap_ci.py from the EVAP repository (stdlib only)
        PY`

function Users() {
  const { data: users, reload, error } = useApi('/users')
  const [f, setF] = useState({ username: '', password: '', role: 'engineer' })
  const [err, setErr] = useState(null)
  const add = async () => { try { await api('/users', { method: 'POST', body: f }); setF({ username: '', password: '', role: 'engineer' }); setErr(null); reload() } catch (e) { setErr(e.message) } }
  const patch = async (u, body) => { try { await api(`/users/${u.id}`, { method: 'PATCH', body }); reload() } catch (e) { setErr(e.message) } }
  return (
    <div className="card" style={{ marginTop: 14 }}>
      <h2>Users &amp; roles</h2>
      <p className="small muted">Engineers write requirements, test cases and scripts. Reviewers (and admins) approve scripts and configure CI. Nobody can approve their own script.</p>
      <Err msg={err || error} />
      <table><thead><tr><th>User</th><th>Role</th><th>Active</th><th>Created</th></tr></thead>
        <tbody>{(users || []).map((u) => (
          <tr key={u.id}><td>{u.username}</td>
            <td><select style={{ width: 'auto' }} value={u.role} onChange={(e) => patch(u, { role: e.target.value })}>{['engineer', 'reviewer', 'admin'].map((r) => <option key={r}>{r}</option>)}</select></td>
            <td><input type="checkbox" style={{ width: 'auto' }} checked={u.active} onChange={(e) => patch(u, { active: e.target.checked })} /></td>
            <td className="small">{fmtDate(u.created_at)}</td></tr>))}</tbody></table>
      <div className="row" style={{ marginTop: 10 }}>
        <input style={{ width: 160 }} placeholder="username" value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} />
        <input style={{ width: 200 }} type="password" placeholder="password (min 10 chars)" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <select style={{ width: 'auto' }} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>{['engineer', 'reviewer', 'admin'].map((r) => <option key={r}>{r}</option>)}</select>
        <button onClick={add}>Add user</button>
      </div>
    </div>
  )
}

export default function CICD() {
  const { pid, project, can, notify, reloadProjects } = useApp()
  const [proj, setProj] = useState({ name: project.name, description: project.description })
  const [g, setG] = useState(project.git || DEFAULT_GIT)
  const [token, setToken] = useState(null)
  const [err, setErr] = useState(null)
  const { data: registry } = useApi(`/projects/${pid}/registry`)
  useEffect(() => { setProj({ name: project.name, description: project.description }); setG(project.git || DEFAULT_GIT); setToken(null) }, [project.id]) // eslint-disable-line react-hooks/exhaustive-deps
  const set = (k, num) => (e) => setG({ ...g, [k]: e.target.type === 'checkbox' ? e.target.checked : num ? Number(e.target.value) : e.target.value })

  const saveProject = async () => { try { await api(`/projects/${pid}`, { method: 'PATCH', body: proj }); await reloadProjects(); notify('Project saved'); setErr(null) } catch (e) { setErr(e.message) } }
  const saveGit = async () => {
    try {
      const { repo_url, branch, auto_validation, python_env, timeout_s, gate_policy, gate_threshold } = g
      await api(`/projects/${pid}/git`, { method: 'PUT', body: { repo_url, branch, auto_validation, python_env, timeout_s, gate_policy, gate_threshold } })
      await reloadProjects(); notify('Git integration saved'); setErr(null)
    } catch (e) { setErr(e.message) }
  }
  const rotate = async () => {
    if (project.git?.ci_token_configured && !window.confirm('Generate a new CI token? The old token stops working immediately.')) return
    try { setToken((await api(`/projects/${pid}/git/ci-token`, { method: 'POST' })).token); await reloadProjects() } catch (e) { setErr(e.message) }
  }
  const ro = !can.review

  return (
    <>
      <div className="topbar"><h1 className="grow">CI/CD Integration</h1></div>
      <Err msg={err} />
      {ro && <div className="warn">Read-only: configuring CI/CD requires the reviewer or admin role.</div>}
      <div className="grid two">
        <div className="card">
          <h2>Project</h2>
          <label>Project name<input value={proj.name} onChange={(e) => setProj({ ...proj, name: e.target.value })} /></label>
          <label>Description<textarea value={proj.description} onChange={(e) => setProj({ ...proj, description: e.target.value })} /></label>
          <button onClick={saveProject}>Save project</button>
          <h3>Git repository &amp; validation policy</h3>
          <label>Git repository URL<input value={g.repo_url} onChange={set('repo_url')} placeholder="git@github.com:owner/mini-bms.git" disabled={ro} /></label>
          <div className="form2">
            <label>Branch<input value={g.branch} onChange={set('branch')} disabled={ro} /></label>
            <label>Python environment<select value={g.python_env} onChange={set('python_env')} disabled={ro}><option>python3.11</option></select></label>
            <label>Test timeout (s)<input type="number" min={5} max={1800} value={g.timeout_s} onChange={set('timeout_s', true)} disabled={ro} /></label>
            <label>Quality gate policy<select value={g.gate_policy} onChange={set('gate_policy')} disabled={ro}>
              <option value="all_pass">All executed tests must pass</option><option value="pass_rate">Minimum pass rate</option></select></label>
            {g.gate_policy === 'pass_rate' && <label>Minimum pass rate (%)<input type="number" min={0} max={100} value={g.gate_threshold} onChange={set('gate_threshold', true)} disabled={ro} /></label>}
          </div>
          <label className="row" style={{ color: 'var(--text)', fontSize: 14 }}>
            <input type="checkbox" style={{ width: 'auto' }} checked={g.auto_validation} onChange={set('auto_validation')} disabled={ro} />
            Automatic validation on every push to <code>{g.branch}</code>
          </label>
          <button className="primary" onClick={saveGit} disabled={ro || !g.repo_url}>Save Git integration</button>
          {project.git && <span className="small muted" style={{ marginLeft: 10 }}>last saved {fmtDate(project.git.updated_at)}</span>}
        </div>
        <div className="card">
          <h2>GitHub Actions connection</h2>
          <p className="small">Status: {project.git?.auto_validation ? <Badge value="PASSED" /> : <Badge value="PENDING" />} automatic validation {project.git?.auto_validation ? 'enabled' : 'disabled'} ·
            CI token {project.git?.ci_token_configured ? <>configured (…{project.git.ci_token_hint})</> : 'not generated'}</p>
          <ol className="small">
            <li>Generate a CI token and store it as the <code>EVAP_CI_TOKEN</code> secret of the SUT repository.</li>
            <li>Register a GitHub <b>self-hosted runner</b> (label <code>evap-local</code>) on the EVAP host — it connects outbound to GitHub, so EVAP is never exposed publicly. Use it only on a <b>private</b> repository.</li>
            <li>Add the workflow below; every push to <code>{g.branch}</code> triggers validation of that exact commit and the job passes/fails with the quality gate.</li>
          </ol>
          <button onClick={rotate} disabled={ro || !project.git}>{project.git?.ci_token_configured ? 'Rotate CI token' : 'Generate CI token'}</button>
          {token && <div className="ok" style={{ marginTop: 10 }}>Copy now — shown only once:<br /><code style={{ wordBreak: 'break-all' }}>{token}</code></div>}
          <h3>Workflow</h3>
          <pre className="snippet">{WORKFLOW(g.branch)}</pre>
          <p className="small muted">The complete workflow and the <code>evap_ci.py</code> client are in <code>ci/</code> of the EVAP repository and in the Mini BMS demo repository.</p>
          <h3>Dynamic test registry ({(registry || []).length} executable)</h3>
          <table><thead><tr><th>Test case</th><th>Requirement</th><th>Approved rev</th><th>SHA-256</th><th>Approved by</th></tr></thead>
            <tbody>{(registry || []).map((s) => <tr key={s.id}><td>{s.tc_id}</td><td>{s.requirement_code}</td><td>r{s.revision}</td><td><code>{s.sha256.slice(0, 12)}</code></td><td>{s.reviewer}</td></tr>)}</tbody></table>
          {registry && !registry.length && <div className="muted small">No approved scripts — automatic validation would report ERROR.</div>}
        </div>
      </div>
      {can.admin && <Users />}
    </>
  )
}
