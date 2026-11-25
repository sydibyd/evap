import { Fragment, useState } from 'react'
import { api, fmtDate, fmtDur, useApi } from '../api'
import { Badge, Err, Modal, Sha, useApp } from '../components/ui'

export function RunModal({ id, onClose }) {
  const { data: r, error } = useApi(`/runs/${id}`, { pollMs: 3000 })
  const [open, setOpen] = useState(null)
  return (
    <Modal title={`Validation run #${id}`} onClose={onClose}>
      <Err msg={error} />
      {r && <>
        <div className="form2 small" style={{ marginBottom: 12 }}>
          <div><span className="muted">Repository</span> <code>{r.repo_url}</code></div>
          <div><span className="muted">Branch</span> <code>{r.branch}</code></div>
          <div><span className="muted">Commit</span> {r.commit_sha ? <><Sha sha={r.commit_sha} repo={r.repo_url} /> <code className="muted">{r.commit_sha}</code></> : <span className="muted">resolving…</span>}</div>
          <div><span className="muted">Trigger</span> {r.trigger} by {r.created_by} {r.ci_run_url && <a href={r.ci_run_url} target="_blank" rel="noreferrer">(CI job)</a>}</div>
          <div><span className="muted">Verdict</span> <Badge value={r.status} /> &nbsp; <span className="muted">Quality gate</span> <Badge value={r.quality_gate} /> <span className="muted">{r.gate_policy}</span></div>
          <div><span className="muted">Created</span> {fmtDate(r.created_at)} · <span className="muted">finished</span> {fmtDate(r.finished_at)}</div>
          <div><span className="muted">Test baseline</span> <code title={r.baseline_hash}>{r.baseline_hash.slice(0, 12)}</code></div>
          <div><span className="muted">Environment</span> {r.python_env} · timeout {r.timeout_s}s</div>
        </div>
        {r.message && <div className="warn">{r.message}</div>}
        <table>
          <thead><tr><th>Requirement</th><th>Test case</th><th>Script rev</th><th>Verdict</th><th>Duration</th><th></th></tr></thead>
          <tbody>{r.executions.map((e) => (<Fragment key={e.id}>
            <tr className="click" onClick={() => setOpen(open === e.id ? null : e.id)}>
              <td>{e.requirement_code} <span className="muted small">rev {e.requirement_revision}</span></td>
              <td>{e.tc_id}</td><td>r{e.script_revision} <code className="muted" title={e.script_sha256}>{e.script_sha256.slice(0, 10)}</code></td>
              <td><Badge value={e.status} /></td><td>{fmtDur(e.duration_s)}</td><td className="small">{open === e.id ? 'hide log ▲' : 'log ▼'}</td>
            </tr>
            {open === e.id && <tr key={`${e.id}-log`}><td colSpan={6}><pre className="log">{e.log || '(no output yet)'}</pre></td></tr>}
          </Fragment>))}</tbody>
        </table>
      </>}
    </Modal>
  )
}

const VERDICTS = ['', 'PASS', 'FAIL', 'ERROR', 'QUEUED', 'RUNNING']

export default function Results() {
  const { pid, project, notify } = useApp()
  const [f, setF] = useState({ requirement_id: '', test_case_id: '', commit: '', verdict: '' })
  const [openRun, setOpenRun] = useState(null)
  const [err, setErr] = useState(null)
  const qs = new URLSearchParams(Object.entries(f).filter(([, v]) => v)).toString()
  const { data: rows, error } = useApi(`/projects/${pid}/executions?${qs}`, { pollMs: 3000 })
  const { data: runs } = useApi(`/projects/${pid}/runs?limit=15${f.commit ? `&commit=${encodeURIComponent(f.commit)}` : ''}`, { pollMs: 3000 })
  const { data: reqs } = useApi(`/projects/${pid}/requirements`)
  const { data: tcs } = useApi(`/projects/${pid}/testcases`)
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value })
  const regression = async () => {
    try { const r = await api(`/projects/${pid}/runs`, { method: 'POST', body: {} }); notify(`Regression run #${r.id} queued`) }
    catch (e) { setErr(e.message) }
  }
  return (
    <>
      <div className="topbar"><h1 className="grow">Validation Results</h1>
        <button className="primary" onClick={regression} disabled={!project.git}>Run regression campaign</button></div>
      <Err msg={err || error} />
      <div className="card">
        <h2>Validation runs</h2>
        <div className="table-wrap"><table>
          <thead><tr><th>Run ID</th><th>Trigger</th><th>Repository</th><th>Branch</th><th>Commit</th><th>Scope</th><th>Verdict</th><th>Quality gate</th><th>Passed</th><th>Created</th></tr></thead>
          <tbody>{(runs || []).map((r) => (
            <tr key={r.id} className="click" onClick={() => setOpenRun(r.id)}>
              <td>#{r.id}</td><td>{r.trigger}</td><td className="small mono">{r.repo_url.replace(/^.*[:/]([^/]+\/[^/]+?)(\.git)?$/, '$1')}</td>
              <td><code>{r.branch}</code></td><td><Sha sha={r.commit_sha} repo={r.repo_url} /></td>
              <td className="small">{r.scope_test_case_id ? 'single test' : 'regression'}</td>
              <td><Badge value={r.status} /></td><td><Badge value={r.quality_gate} /></td><td>{r.passed}/{r.total}</td><td className="small">{fmtDate(r.created_at)}</td>
            </tr>))}</tbody>
        </table></div>
        {runs && !runs.length && <div className="empty">No validation runs yet.</div>}
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h2>Test executions</h2>
        <div className="row filters" style={{ marginBottom: 10 }}>
          <select value={f.requirement_id} onChange={set('requirement_id')}><option value="">All requirements</option>{(reqs || []).map((r) => <option key={r.id} value={r.id}>{r.req_id}</option>)}</select>
          <select value={f.test_case_id} onChange={set('test_case_id')}><option value="">All test cases</option>{(tcs || []).map((t) => <option key={t.id} value={t.id}>{t.tc_id}</option>)}</select>
          <input placeholder="Commit SHA prefix" value={f.commit} onChange={set('commit')} />
          <select value={f.verdict} onChange={set('verdict')}>{VERDICTS.map((v) => <option key={v} value={v}>{v || 'All verdicts'}</option>)}</select>
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>Run</th><th>Branch</th><th>Commit</th><th>Requirement</th><th>Test case</th><th>Script rev</th><th>Executed</th><th>Duration</th><th>Verdict</th><th>Gate</th><th>Log</th></tr></thead>
          <tbody>{(rows || []).map((e) => (
            <tr key={e.id}>
              <td>#{e.run_id}</td><td><code>{e.branch}</code></td><td><Sha sha={e.commit_sha} repo={e.repo_url} /></td>
              <td>{e.requirement_code}</td><td>{e.tc_id}</td><td>r{e.script_revision}</td>
              <td className="small">{fmtDate(e.started_at || e.finished_at)}</td><td>{fmtDur(e.duration_s)}</td>
              <td><Badge value={e.status} /></td><td><Badge value={e.quality_gate} /></td>
              <td><a href="#" onClick={(ev) => { ev.preventDefault(); setOpenRun(e.run_id) }}>view</a></td>
            </tr>))}</tbody>
        </table></div>
        {rows && !rows.length && <div className="empty">No executions match the filters.</div>}
      </div>
      {openRun && <RunModal id={openRun} onClose={() => setOpenRun(null)} />}
    </>
  )
}
