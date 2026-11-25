import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import CodeMirror from '@uiw/react-codemirror'
import { python } from '@codemirror/lang-python'
import { api, fmtDate, fmtDur, useApi } from '../api'
import { Badge, Err, Sha, useApp } from '../components/ui'
import { RunModal } from './Results'

const ENVS = ['python3.11']
const TEMPLATE = (tc, req) => `"""${tc} — SIL test for ${req}.

The System Under Test is importable directly (e.g. \`from bms import BMS\`):
EVAP checks out the exact Git commit under validation and runs this file with pytest
in an isolated sandbox (no network, non-root, time/memory limited).
"""
import pytest


@pytest.mark.parametrize("value, expected", [
    (1, 1),
])
def test_example(value, expected):
    assert value == expected
`

function TcForm({ value, onChange, reqs, isNew }) {
  const set = (k) => (e) => onChange({ ...value, [k]: k === 'requirement_id' ? Number(e.target.value) : e.target.value })
  return (
    <>
      <div className="form2">
        <label>Test case ID<input value={value.tc_id} onChange={set('tc_id')} disabled={!isNew} placeholder="TC-001" /></label>
        <label>Requirement<select value={value.requirement_id || ''} onChange={set('requirement_id')}>
          <option value="">— select —</option>{reqs.map((r) => <option key={r.id} value={r.id}>{r.req_id} · {r.subsystem}</option>)}</select></label>
        <label>Title<input value={value.title} onChange={set('title')} /></label>
        <label>SIL environment<select value={value.sil_environment} onChange={set('sil_environment')}>{ENVS.map((e) => <option key={e}>{e}</option>)}</select></label>
      </div>
      <label>Preconditions<textarea value={value.preconditions} onChange={set('preconditions')} /></label>
      <div className="form2">
        <label>Inputs<textarea value={value.inputs} onChange={set('inputs')} /></label>
        <label>Expected results<textarea value={value.expected_results} onChange={set('expected_results')} /></label>
      </div>
    </>
  )
}

function ScriptPanel({ tc, onChanged }) {
  const { user, can, pid, notify, project } = useApp()
  const { data: revs, reload } = useApi(`/testcases/${tc.id}/scripts`)
  const { data: execs } = useApi(`/projects/${pid}/executions?test_case_id=${tc.id}&limit=5`, { pollMs: 3000 })
  const [selRev, setSelRev] = useState(null)
  const [source, setSource] = useState('')
  const [loaded, setLoaded] = useState(null)
  const [check, setCheck] = useState(null)
  const [err, setErr] = useState(null)
  const [comment, setComment] = useState('')
  const [openRun, setOpenRun] = useState(null)
  const fileRef = useRef()

  useEffect(() => { // select newest revision when the list changes
    if (!revs) return
    if (!revs.length) { setSelRev(null); setSource(TEMPLATE(tc.tc_id, tc.requirement_code)); setLoaded(null); return }
    if (!selRev || !revs.find((r) => r.id === selRev)) setSelRev(revs[0].id)
  }, [revs]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!selRev) return
    api(`/scripts/${selRev}`).then((s) => { setSource(s.source); setLoaded(s); setCheck(null) }).catch((e) => setErr(e.message))
  }, [selRev])

  const dirty = loaded ? source !== loaded.source : true
  const validate = async () => { try { setCheck(await api('/scripts/validate', { method: 'POST', body: { source } })); setErr(null) } catch (e) { setErr(e.message) } }
  const save = async () => {
    try {
      const s = await api(`/testcases/${tc.id}/scripts`, { method: 'POST', body: { source } })
      setCheck(s.check); setErr(null); await reload(); setSelRev(s.id); onChanged(); notify(`Saved revision r${s.revision} (draft, awaiting review)`)
    } catch (e) { setErr(e.message) }
  }
  const review = async (decision) => {
    try {
      await api(`/scripts/${loaded.id}/review`, { method: 'POST', body: { decision, comment } })
      setComment(''); await reload(); const s = await api(`/scripts/${loaded.id}`); setLoaded(s); onChanged()
      notify(`Revision r${loaded.revision} ${decision === 'approve' ? 'approved' : 'rejected'}`)
    } catch (e) { setErr(e.message) }
  }
  const run = async () => {
    try { const r = await api(`/projects/${pid}/runs`, { method: 'POST', body: { test_case_id: tc.id } }); notify(`Run #${r.id} queued`); setOpenRun(r.id) }
    catch (e) { setErr(e.message) }
  }
  const importPy = async (e) => {
    const f = e.target.files[0]; e.target.value = ''
    if (f) { setSource(await f.text()); setCheck(null) }
  }
  const approved = (revs || []).find((r) => r.approval_status === 'approved')
  const canReview = loaded && loaded.approval_status === 'draft' && can.review && loaded.author !== user.username

  return (
    <div className="card" style={{ marginTop: 14 }}>
      <div className="row" style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, flex: 1 }}>Test script</h2>
        <select style={{ width: 'auto' }} value={selRev || ''} onChange={(e) => setSelRev(Number(e.target.value))}>
          {!revs?.length && <option value="">new script</option>}
          {(revs || []).map((r) => <option key={r.id} value={r.id}>r{r.revision} · {r.approval_status} · {r.author}</option>)}
        </select>
        <button onClick={() => fileRef.current.click()}>Import .py</button>
        <input ref={fileRef} type="file" accept=".py,text/x-python" hidden onChange={importPy} />
        <button onClick={validate}>Validate</button>
        <button className="primary" onClick={save} disabled={!dirty}>Save as new revision</button>
      </div>
      <Err msg={err} />
      {check && (check.ok
        ? <div className="ok">Syntax OK · tests found: {check.tests.join(', ')}{check.warnings.length ? '' : ''}</div>
        : <div className="err">{check.errors.join('\n')}</div>)}
      {check?.warnings?.length > 0 && <div className="warn">Reviewer attention: {check.warnings.join('; ')}</div>}
      {loaded && (
        <div className="row small muted" style={{ marginBottom: 8 }}>
          <span>Revision <b>r{loaded.revision}</b></span><Badge value={loaded.approval_status} />
          <span>by {loaded.author} · {fmtDate(loaded.created_at)}</span>
          <span>SHA-256 <code title={loaded.sha256}>{loaded.sha256.slice(0, 16)}…</code></span>
          {loaded.reviewer && <span>reviewed by {loaded.reviewer}{loaded.review_comment && `: “${loaded.review_comment}”`}</span>}
          {dirty && <span className="badge b-ERROR">unsaved changes</span>}
        </div>
      )}
      <div className="editor">
        <CodeMirror value={source} height="380px" extensions={[python()]} onChange={setSource} basicSetup={{ tabSize: 4 }} />
      </div>
      {canReview && (
        <div className="row" style={{ marginTop: 10 }}>
          <input placeholder="Review comment" value={comment} onChange={(e) => setComment(e.target.value)} style={{ flex: 1, width: 'auto' }} />
          <button className="good" onClick={() => review('approve')} disabled={dirty}>Approve r{loaded.revision}</button>
          <button className="danger" onClick={() => review('reject')}>Reject</button>
        </div>
      )}
      {loaded && loaded.approval_status === 'draft' && !canReview && (
        <p className="small muted">Awaiting review by a reviewer other than the author (four-eyes rule).</p>
      )}
      <h3>Execution</h3>
      <div className="row">
        <button className="primary" onClick={run} disabled={!approved || !project.git}>
          {approved ? `Execute approved r${approved.revision}` : 'No approved revision'}
        </button>
        <span className="small muted">Only approved revisions execute. Runs against the head of <code>{project.git?.branch || '—'}</code>.</span>
      </div>
      {execs?.length > 0 && (
        <table style={{ marginTop: 10 }}><thead><tr><th>Run</th><th>Commit</th><th>Script rev</th><th>Verdict</th><th>Duration</th><th>Date</th></tr></thead>
          <tbody>{execs.map((e) => (
            <tr key={e.id} className="click" onClick={() => setOpenRun(e.run_id)}><td>#{e.run_id}</td><td><Sha sha={e.commit_sha} /></td><td>r{e.script_revision}</td>
              <td><Badge value={e.status} /></td><td>{fmtDur(e.duration_s)}</td><td className="small">{fmtDate(e.finished_at || e.started_at)}</td></tr>))}</tbody></table>
      )}
      {openRun && <RunModal id={openRun} onClose={() => setOpenRun(null)} />}
    </div>
  )
}

export default function TestDesign() {
  const { pid, notify } = useApp()
  const [params, setParams] = useSearchParams()
  const [reqFilter, setReqFilter] = useState('')
  const { data: tcs, reload } = useApi(`/projects/${pid}/testcases${reqFilter ? `?requirement_id=${reqFilter}` : ''}`)
  const { data: reqs } = useApi(`/projects/${pid}/requirements`)
  const [form, setForm] = useState(null)
  const [isNew, setIsNew] = useState(false)
  const [err, setErr] = useState(null)
  const sel = Number(params.get('tc')) || null
  const tc = (tcs || []).find((t) => t.id === sel)

  useEffect(() => {
    if (params.get('new')) {
      const n = (tcs || []).length + 1
      setIsNew(true)
      setForm({ tc_id: `TC-${String(n).padStart(3, '0')}`, requirement_id: Number(params.get('req')) || '', title: '', preconditions: '', inputs: '', expected_results: '', sil_environment: 'python3.11' })
    }
  }, [params.get('new'), tcs === null]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (tc && !isNew) setForm({ ...tc }) }, [tc?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const saveTc = async () => {
    try {
      const body = { requirement_id: form.requirement_id, title: form.title, preconditions: form.preconditions, inputs: form.inputs, expected_results: form.expected_results, sil_environment: form.sil_environment }
      if (isNew) {
        const t = await api(`/projects/${pid}/testcases`, { method: 'POST', body: { ...body, tc_id: form.tc_id } })
        setIsNew(false); await reload(); setParams({ tc: t.id }); notify(`Test case ${t.tc_id} created`)
      } else {
        await api(`/testcases/${tc.id}`, { method: 'PATCH', body }); await reload(); notify('Test case saved')
      }
      setErr(null)
    } catch (e) { setErr(e.message) }
  }

  return (
    <>
      <div className="topbar"><h1 className="grow">Test Design</h1>
        <button className="primary" onClick={() => setParams({ new: '1', ...(reqFilter ? { req: reqFilter } : {}) })}>+ New test case</button></div>
      <div className="grid split">
        <div className="card">
          <select value={reqFilter} onChange={(e) => setReqFilter(e.target.value)} style={{ marginBottom: 10 }}>
            <option value="">All requirements</option>{(reqs || []).map((r) => <option key={r.id} value={r.id}>{r.req_id}</option>)}</select>
          {(tcs || []).map((t) => (
            <div key={t.id} className={`list-item ${t.id === sel && !isNew ? 'sel' : ''}`} onClick={() => { setIsNew(false); setParams({ tc: t.id }) }}>
              <div className="row"><b>{t.tc_id}</b><span className="small muted">→ {t.requirement_code}</span></div>
              <div className="small">{t.title || <span className="muted">untitled</span>}</div>
              <div className="row small" style={{ marginTop: 4 }}>
                {t.latest_revision ? <>r{t.latest_revision} <Badge value={t.latest_status} /></> : <span className="muted">no script</span>}
                {t.approved_revision && <span className="muted">approved: r{t.approved_revision}</span>}
              </div>
            </div>))}
          {tcs && !tcs.length && <div className="empty">No test cases yet.</div>}
        </div>
        <div>
          {form && (isNew || tc) ? (
            <>
              <div className="card">
                <h2>{isNew ? 'New test case' : `${tc.tc_id} — ${tc.title || 'untitled'}`}</h2>
                <Err msg={err} />
                <TcForm value={form} onChange={setForm} reqs={reqs || []} isNew={isNew} />
                <div className="row"><button className="primary" onClick={saveTc} disabled={!form.tc_id || !form.requirement_id}>{isNew ? 'Create test case' : 'Save test case'}</button>
                  {isNew && <button onClick={() => { setIsNew(false); setParams({}) }}>Cancel</button>}</div>
              </div>
              {!isNew && tc && <ScriptPanel key={tc.id} tc={tc} onChanged={reload} />}
            </>
          ) : <div className="card empty">Select a test case, or create one (also possible directly from a requirement).</div>}
        </div>
      </div>
    </>
  )
}
