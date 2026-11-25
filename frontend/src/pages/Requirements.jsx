import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, download, fmtDate, useApi } from '../api'
import { Badge, Err, Modal, useApp } from '../components/ui'

const EMPTY = { req_id: '', subsystem: '', description: '', priority: 'Medium', status: 'Draft' }
const PRIORITIES = ['', 'High', 'Medium', 'Low']

function ReqForm({ value, onChange, isNew }) {
  const set = (k) => (e) => onChange({ ...value, [k]: e.target.value })
  return (
    <>
      <div className="form2">
        <label>Requirement ID<input value={value.req_id} onChange={set('req_id')} disabled={!isNew} placeholder="SW-001" /></label>
        <label>Subsystem<input value={value.subsystem} onChange={set('subsystem')} /></label>
        <label>Priority<select value={value.priority} onChange={set('priority')}>{PRIORITIES.map((p) => <option key={p}>{p}</option>)}</select></label>
        <label>Status<input value={value.status} onChange={set('status')} placeholder="Draft / Approved" /></label>
      </div>
      <label>Description<textarea rows={4} value={value.description} onChange={set('description')} /></label>
    </>
  )
}

function ReqDetail({ id, onClose, onSaved }) {
  const { data: r, error, reload } = useApi(`/requirements/${id}`)
  const [edit, setEdit] = useState(null)
  const [err, setErr] = useState(null)
  const nav = useNavigate()
  const save = async () => {
    try {
      const { subsystem, description, priority, status } = edit
      await api(`/requirements/${id}`, { method: 'PATCH', body: { subsystem, description, priority, status } })
      setEdit(null); reload(); onSaved()
    } catch (e) { setErr(e.message) }
  }
  return (
    <Modal title={r ? `${r.req_id} · revision ${r.revision}` : 'Requirement'} onClose={onClose}
      actions={r && !edit && <><button onClick={() => setEdit({ ...r })}>Edit</button>
        <button className="primary" onClick={() => nav(`/test-design?new=1&req=${r.id}`)}>+ Test case</button></>}>
      <Err msg={err || error} />
      {r && (edit ? (
        <>
          <ReqForm value={edit} onChange={setEdit} />
          <div className="row"><button className="primary" onClick={save}>Save new revision</button><button onClick={() => setEdit(null)}>Cancel</button></div>
        </>
      ) : (
        <>
          <p style={{ whiteSpace: 'pre-wrap' }}>{r.description}</p>
          <div className="row small muted"><span>Subsystem: <b>{r.subsystem || '—'}</b></span><span>Priority: <b>{r.priority || '—'}</b></span><span>Status: <b>{r.status || '—'}</b></span></div>
          <h3>Test cases ({r.test_cases.length})</h3>
          {r.test_cases.length ? (
            <table><thead><tr><th>ID</th><th>Title</th><th>Latest script</th><th>Approved revision</th></tr></thead>
              <tbody>{r.test_cases.map((t) => (
                <tr key={t.id} className="click" onClick={() => nav(`/test-design?tc=${t.id}`)}>
                  <td>{t.tc_id}</td><td>{t.title}</td><td>{t.latest_revision ? <>r{t.latest_revision} <Badge value={t.latest_status} /></> : '—'}</td>
                  <td>{t.approved_revision ? `r${t.approved_revision}` : '—'}</td>
                </tr>))}</tbody></table>
          ) : <div className="muted small">No test case yet — this requirement is not covered.</div>}
          <h3>Revision history</h3>
          <table><thead><tr><th>Rev</th><th>Description</th><th>Priority</th><th>Status</th><th>Source</th><th>Author</th><th>Date</th></tr></thead>
            <tbody>{r.revisions.map((v) => (
              <tr key={v.revision}><td>{v.revision}</td><td className="small">{v.description}</td><td>{v.priority}</td><td>{v.status}</td>
                <td className="small">{v.source}</td><td>{v.author}</td><td className="small">{fmtDate(v.created_at)}</td></tr>))}</tbody></table>
        </>
      ))}
    </Modal>
  )
}

export default function Requirements() {
  const { pid, notify } = useApp()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [priority, setPriority] = useState('')
  const qs = new URLSearchParams(Object.entries({ q, status, priority }).filter(([, v]) => v)).toString()
  const { data: reqs, error, reload } = useApi(`/projects/${pid}/requirements?${qs}`)
  const { data: all } = useApi(`/projects/${pid}/requirements`, { deps: [reqs] })
  const [creating, setCreating] = useState(null)
  const [detail, setDetail] = useState(null)
  const [err, setErr] = useState(null)
  const [result, setResult] = useState(null)
  const fileRef = useRef()

  const doImport = async (e) => {
    const file = e.target.files[0]
    e.target.value = ''
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      const r = await api(`/projects/${pid}/requirements/import`, { method: 'POST', form })
      setResult(r); setErr(null); reload()
    } catch (ex) { setErr(ex.message) }
  }
  const create = async () => {
    try { await api(`/projects/${pid}/requirements`, { method: 'POST', body: creating }); setCreating(null); reload(); notify('Requirement created') }
    catch (e) { setErr(e.message) }
  }
  const statuses = [...new Set((all || []).map((r) => r.status).filter(Boolean))]

  return (
    <>
      <div className="topbar">
        <h1 className="grow">Requirements</h1>
        <button onClick={() => download('/requirements/template.xlsx', 'EVAP_SRS_template.xlsx')}>Download Excel template</button>
        <button onClick={() => fileRef.current.click()}>Import Excel SRS</button>
        <input ref={fileRef} type="file" accept=".xlsx" hidden onChange={doImport} data-testid="srs-file" />
        <button className="primary" onClick={() => setCreating({ ...EMPTY })}>+ New requirement</button>
      </div>
      <Err msg={err || error} />
      {result && (
        <div className="ok">
          Import complete — created: {result.created.join(', ') || 'none'} · revised: {result.revised.join(', ') || 'none'} · unchanged: {result.unchanged.length}
          {result.not_in_file_kept.length > 0 && <> · kept (not in file, never deleted): {result.not_in_file_kept.join(', ')}</>}
          <button style={{ marginLeft: 10 }} onClick={() => setResult(null)}>OK</button>
        </div>
      )}
      <div className="card">
        <div className="row filters" style={{ marginBottom: 10 }}>
          <input placeholder="Search ID, subsystem, description…" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 280 }} />
          <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All statuses</option>{statuses.map((s) => <option key={s}>{s}</option>)}</select>
          <select value={priority} onChange={(e) => setPriority(e.target.value)}>{PRIORITIES.map((p) => <option key={p} value={p}>{p || 'All priorities'}</option>)}</select>
        </div>
        <div className="table-wrap"><table>
          <thead><tr><th>ID</th><th>Subsystem</th><th>Description</th><th>Priority</th><th>Status</th><th>Rev</th><th>Test cases</th></tr></thead>
          <tbody>{(reqs || []).map((r) => (
            <tr key={r.id} className="click" onClick={() => setDetail(r.id)}>
              <td><b>{r.req_id}</b></td><td>{r.subsystem}</td><td className="small">{r.description.length > 140 ? `${r.description.slice(0, 140)}…` : r.description}</td>
              <td>{r.priority}</td><td>{r.status}</td><td>{r.revision}</td>
              <td>{r.test_case_count ? r.test_case_count : <span className="badge b-FAIL">uncovered</span>}</td>
            </tr>))}</tbody>
        </table></div>
        {reqs && !reqs.length && <div className="empty">No requirements. Import an Excel SRS or create one manually.</div>}
      </div>
      {creating && (
        <Modal title="New requirement" onClose={() => setCreating(null)}>
          <ReqForm value={creating} onChange={setCreating} isNew />
          <div className="row"><button className="primary" onClick={create} disabled={!creating.req_id}>Create</button></div>
        </Modal>
      )}
      {detail && <ReqDetail id={detail} onClose={() => setDetail(null)} onSaved={reload} />}
    </>
  )
}
