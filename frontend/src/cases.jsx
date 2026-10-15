import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useAuth } from './App.jsx'
import { api } from './api'
import { Status, fmt, useLoad } from './components.jsx'

export const notifyCasesChanged = () => window.dispatchEvent(new Event('cases-updated'))

function CaseDialog({ title, onClose, children, busy }) {
  const ref = useRef(null)
  useEffect(() => {
    const previous = document.activeElement
    const dialog = ref.current
    dialog.showModal()
    return () => { dialog.close(); previous?.focus() }
  }, [])
  return createPortal(<dialog ref={ref} className="rule-dialog" aria-label={title}
    onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
    <h2 className="h5">{title}</h2>{children}
  </dialog>, document.body)
}

export function AssignmentDialog({ alert, onClose, onComplete }) {
  const workload = useLoad(() => api.teamWorkload())
  const [owner, setOwner] = useState(alert.owner || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const submit = async event => {
    event.preventDefault()
    setBusy(true); setError(null)
    try {
      await api.assignAlert(alert.id, owner)
      notifyCasesChanged(); onComplete(); onClose()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <CaseDialog title={`${alert.owner ? 'Reassign' : 'Assign'} Case #${alert.id}`} onClose={onClose} busy={busy}>
    <form onSubmit={submit}>
      <Status loading={workload.loading} error={workload.error}>
        <label htmlFor="case-owner" className="form-label">Analyst</label>
        <select id="case-owner" className="form-select" value={owner} required disabled={busy} onChange={e => setOwner(e.target.value)}>
          <option value="">Select an analyst</option>
          {(workload.data || []).map(a => <option key={a.username} value={a.username}>{a.username} ({a.open + a.under_investigation} active cases)</option>)}
        </select>
        {!workload.loading && !workload.error && !workload.data?.length && <p className="text-muted">Create an analyst account before assigning a case.</p>}
      </Status>
      {error && <p className="alert alert-danger mt-2" role="alert">{error}</p>}
      <div className="rule-dialog-actions mt-3">
        <button type="button" className="btn btn-outline-secondary btn-sm" onClick={onClose} disabled={busy}>Cancel</button>
        <button className="btn btn-primary btn-sm" disabled={busy || !owner || workload.loading || !!workload.error}>Save owner</button>
      </div>
    </form>
  </CaseDialog>
}

export function ReleaseDialog({ alertId, onClose, onComplete }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(null)
    try { await api.releaseAlert(alertId, reason.trim()); notifyCasesChanged(); onComplete() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <CaseDialog title={`Release Case #${alertId}`} busy={busy} onClose={onClose}>
    <form onSubmit={submit}>
      <p>The case returns to the queue. Under investigation cases return to Open.</p>
      <label htmlFor="release-reason" className="form-label">Reason</label>
      <textarea id="release-reason" className="form-control" minLength={3} maxLength={2000} required value={reason} onChange={e => setReason(e.target.value)} disabled={busy} />
      {error && <p role="alert" className="alert alert-danger mt-2">{error}</p>}
      <div className="rule-dialog-actions mt-3"><button type="button" className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn btn-sm btn-danger" disabled={busy || reason.trim().length < 3}>Release case</button></div>
    </form>
  </CaseDialog>
}

export function CaseActions({ alert, onComplete, detail = false }) {
  const { auth } = useAuth() || {}
  const [assigning, setAssigning] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const claim = async () => {
    setBusy(true); setError(null)
    try { await api.claimAlert(alert.id); notifyCasesChanged(); onComplete() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="case-actions" onClick={event => event.stopPropagation()}>
    {auth?.role === 'admin' ? <>
      <button className="btn btn-sm btn-outline-primary" onClick={() => setAssigning(true)}>{alert.owner ? 'Reassign' : 'Assign'}</button>
      {!detail && <Link to={`/alerts/${alert.id}`}>View</Link>}
    </> : auth?.role === 'analyst' && <>
      {alert.status !== 'closed' && !alert.owner && <button className="btn btn-sm btn-primary" disabled={busy} onClick={claim}>Assign to me</button>}
      {alert.owner === auth.username && (detail || alert.status !== 'closed')
        ? <Link className="btn btn-sm btn-outline-primary" to={`/my-cases/${alert.id}`}>{detail ? 'Open in My cases' : 'Investigate'}</Link>
        : !detail && <Link to={`/alerts/${alert.id}`}>View</Link>}
    </>}
    {error && <span className="small text-danger" role="alert">{error}</span>}
    {assigning && <AssignmentDialog alert={alert} onClose={() => setAssigning(false)} onComplete={onComplete} />}
  </div>
}

export function TeamWorkload({ query }) {
  return <section className="card dash-panel" aria-label="Team workload">
    <div className="dash-panel-heading"><h2>Team workload</h2></div>
    <Status loading={query.loading} error={query.error}>
      <div className="table-responsive"><table className="table table-sm align-middle mb-0">
        <thead><tr>{['Analyst', 'Open', 'Under investigation', 'Closed total', 'Closed last 7 days', 'Oldest open (hours)', 'Critical', 'High'].map(h => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{(query.data || []).map(a => <tr key={a.username}><td>{a.username}</td>{['open', 'under_investigation', 'closed_total', 'closed_last_7_days', 'oldest_open_age_hours', 'critical', 'high'].map(k => <td key={k}>{a[k] ?? '—'}</td>)}</tr>)}</tbody>
      </table></div>
      {query.data?.length === 0 && <p className="text-muted">No analyst accounts yet.</p>}
    </Status>
  </section>
}

export function CaseEvents({ events }) {
  return <section className="mt-3" aria-label="Case event timeline"><h3 className="h6">Case event timeline</h3>
    <Status loading={events.loading} error={events.error}>
      <ol className="case-event-list">{(events.data || []).map(e => <li key={e.id}>
        <strong>{e.action.replaceAll('_', ' ')}</strong> <span className="small text-muted">{e.actor} · {fmt(e.created_at)}</span>
        {(e.detail?.from || e.detail?.to) && <div className="small">{e.detail.from || 'Unassigned'} → {e.detail.to || 'Unassigned'}</div>}
        {e.detail?.reason && <div className="small">{e.detail.reason}</div>}
      </li>)}</ol>
      {events.data?.length === 0 && <p className="small text-muted">No case events yet.</p>}
    </Status>
  </section>
}
