import { useState } from 'react'
import { api, fmtDate, fmtDur, useApi } from '../api'
import { Badge, Err, Kpi, Sha, useApp } from '../components/ui'
import { RunModal } from './Results'

const COLORS = { PASS: 'var(--pass)', FAIL: 'var(--fail)', ERROR: 'var(--error)' }

export default function Overview() {
  const { pid, project, notify } = useApp()
  const { data: o, error, reload } = useApi(`/projects/${pid}/overview`, { pollMs: 4000 })
  const [openRun, setOpenRun] = useState(null)
  const [err, setErr] = useState(null)
  const regression = async () => {
    try { const r = await api(`/projects/${pid}/runs`, { method: 'POST', body: {} }); notify(`Regression run #${r.id} queued`); reload() }
    catch (e) { setErr(e.message) }
  }
  if (!o) return <Err msg={error} />
  const lr = o.latest_run
  return (
    <>
      <div className="topbar">
        <h1 className="grow">Overview · {project.name}</h1>
        {o.active_runs > 0 && <Badge value="RUNNING" />}
        <button className="primary" onClick={regression} disabled={!project.git}>Run regression campaign</button>
      </div>
      <Err msg={err || error} />
      <div className="grid kpis">
        <Kpi label="Requirements" value={o.total_requirements} />
        <Kpi label="Test cases" value={o.total_test_cases} />
        <Kpi label="Mapping coverage" value={`${o.mapping_coverage}%`} pct={o.mapping_coverage}
          sub={`${o.mapped_requirements}/${o.total_requirements} requirements have ≥1 test case`} />
        <Kpi label="Execution coverage" value={`${o.execution_coverage}%`} pct={o.execution_coverage}
          sub={`${o.executed_requirements}/${o.total_requirements} requirements executed in latest campaign`} />
        <Kpi label="Pass rate" value={o.pass_rate == null ? '—' : `${o.pass_rate}%`} pct={o.pass_rate}
          sub={lr ? `${lr.passed}/${lr.total} test executions passed in run #${lr.id}` : 'no completed campaign'} />
      </div>
      <div className="grid two" style={{ marginTop: 14 }}>
        <div className="card">
          <h2>Latest validation status</h2>
          {lr ? (
            <table><tbody>
              <tr><td className="muted">Run</td><td><a href="#" onClick={(e) => { e.preventDefault(); setOpenRun(lr.id) }}>#{lr.id}</a> · {lr.trigger}</td></tr>
              <tr><td className="muted">Verdict</td><td><Badge value={lr.status} /></td></tr>
              <tr><td className="muted">Quality gate</td><td><Badge value={lr.quality_gate} /> <span className="small muted">{lr.gate_policy}</span></td></tr>
              <tr><td className="muted">Commit</td><td><Sha sha={lr.commit_sha} repo={lr.repo_url} /> on <code>{lr.branch}</code></td></tr>
              <tr><td className="muted">Finished</td><td>{fmtDate(lr.finished_at)}</td></tr>
              <tr><td className="muted">Latest validated commit</td><td>{o.last_passing_run ? <><Sha sha={o.last_passing_run.commit_sha} repo={o.last_passing_run.repo_url} /> <span className="small muted">(run #{o.last_passing_run.id}, gate passed)</span></> : '—'}</td></tr>
            </tbody></table>
          ) : <div className="empty">No regression campaign has completed yet.</div>}
        </div>
        <div className="card">
          <h2>Validation history <span className="muted small">(last {o.history.length} campaigns, bar height = pass rate)</span></h2>
          {o.history.length ? (
            <>
              <div className="hist">
                {o.history.map((h) => (
                  <div key={h.id} title={`#${h.id} ${h.status} ${h.passed}/${h.total} · ${h.commit_sha?.slice(0, 8)}`}
                    onClick={() => setOpenRun(h.id)} style={{ cursor: 'pointer', background: COLORS[h.status] || '#9ca3af',
                      height: `${Math.max(6, (h.total ? h.passed / h.total : 0) * 100)}%` }} />
                ))}
              </div>
              <div className="table-wrap" style={{ maxHeight: 180, overflowY: 'auto', marginTop: 8 }}>
                <table><tbody>
                  {[...o.history].reverse().map((h) => (
                    <tr key={h.id} className="click" onClick={() => setOpenRun(h.id)}>
                      <td>#{h.id}</td><td><Sha sha={h.commit_sha} /></td><td><Badge value={h.status} /></td>
                      <td className="small">{h.passed}/{h.total}</td><td className="small muted">{h.trigger}</td><td className="small muted">{fmtDate(h.created_at)}</td>
                    </tr>))}
                </tbody></table>
              </div>
            </>
          ) : <div className="empty">No history yet.</div>}
        </div>
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <h2>Recent executions</h2>
        {o.recent_executions.length ? (
          <div className="table-wrap"><table>
            <thead><tr><th>Run</th><th>Requirement</th><th>Test case</th><th>Script rev</th><th>Commit</th><th>Verdict</th><th>Duration</th><th>Finished</th></tr></thead>
            <tbody>{o.recent_executions.map((e) => (
              <tr key={e.id} className="click" onClick={() => setOpenRun(e.run_id)}>
                <td>#{e.run_id}</td><td>{e.requirement_code}</td><td>{e.tc_id}</td><td>r{e.script_revision}</td>
                <td><Sha sha={e.commit_sha} /></td><td><Badge value={e.status} /></td><td>{fmtDur(e.duration_s)}</td><td className="small">{fmtDate(e.finished_at)}</td>
              </tr>))}</tbody>
          </table></div>
        ) : <div className="empty">No executions yet.</div>}
      </div>
      {openRun && <RunModal id={openRun} onClose={() => setOpenRun(null)} />}
    </>
  )
}
