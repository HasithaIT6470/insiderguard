import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { CategoryBadge, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'
import { CaseDialog } from '../cases.jsx'
import { ACTIVE_ESCALATIONS, ESCALATION_STATUS, EscalationStatus, PriorityBadge, RECOMMENDATIONS, notifyEscalationsChanged } from '../escalations.jsx'

function ActionDialog({ action, id, onClose, onComplete }) {
  const [text, setText] = useState('')
  const [method, setMethod] = useState('email')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const title = { info: 'Request more info', contact: 'Log contact', complete: 'Mark as handled', withdraw: 'Withdraw escalation' }[action]
  const label = action === 'info' ? 'Message' : action === 'contact' ? 'Contact summary (admin only)' : 'Handling note'
  const minimum = action === 'complete' ? 10 : 1
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      if (action === 'info') await api.requestEscalationInfo(id, text.trim())
      else if (action === 'contact') await api.contactEscalation(id, { contact_method: method, summary: text.trim() })
      else if (action === 'complete') await api.completeEscalation(id, text.trim())
      else await api.withdrawEscalation(id)
      onComplete(); onClose()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <CaseDialog title={title} busy={busy} onClose={onClose}><form onSubmit={submit}>
    {action === 'withdraw' ? <p>Withdraw this submitted escalation? Its history will remain available.</p> : <>
      {action === 'contact' && <label className="d-block mb-3">Contact method<select className="form-select" value={method} onChange={e => setMethod(e.target.value)}>{['email', 'phone', 'in_person', 'other'].map(m => <option key={m} value={m}>{m.replaceAll('_', ' ')}</option>)}</select></label>}
      <label className="d-block mb-2">{label}<textarea className="form-control" maxLength={4000} required value={text} onChange={e => setText(e.target.value)} /></label>
      <p className="small text-muted">{text.trim().length}/4000 characters (minimum {minimum}). {action === 'contact' ? 'This summary is stored only in the admin contact log.' : 'Visible to analysts; omit personal contact details.'}</p>
    </>}
    {error && <p role="alert" className="alert alert-danger">{error}</p>}
    <div className="d-flex justify-content-end gap-2"><button type="button" className="btn btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button><button className={`btn ${action === 'withdraw' ? 'btn-outline-danger' : 'btn-primary'}`} disabled={busy || (action !== 'withdraw' && text.trim().length < minimum)}>{title}</button></div>
  </form></CaseDialog>
}

function EscalationDetail({ id }) {
  const { auth } = useAuth()
  const admin = auth.role === 'admin'
  const query = useLoad(() => api.escalation(id), [id])
  const [action, setAction] = useState(null)
  const [reply, setReply] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const data = query.data
  const refresh = () => { query.reload(); notifyEscalationsChanged() }
  const act = async fn => {
    setBusy(true); setError(null)
    try { await fn(); refresh() } catch (e) { setError(e.message); query.reload() } finally { setBusy(false) }
  }
  const active = data && ACTIVE_ESCALATIONS.includes(data.status)
  const handler = admin && data?.handled_by === auth.username
  const creator = !admin && data?.created_by === auth.username
  return <div className="dash-page"><Link to="/escalations">{admin ? 'Escalations' : 'My escalations'}</Link><Status loading={query.loading} error={query.error}>{data && <>
    <header className="dash-header mt-3"><div><h1>Escalation #{data.id}</h1><div className="d-flex gap-2 align-items-center flex-wrap"><PriorityBadge priority={data.priority} /><EscalationStatus status={data.status} /><span className={data.overdue ? 'badge bg-danger' : 'text-muted'}>{data.age_hours.toFixed(1)} h old{data.overdue ? ' · Overdue' : ''}</span></div></div><div className="text-end"><p className="mb-1">Filed by {data.created_by} · {fmt(data.created_at)}</p><p className="mb-0">Handling admin: {data.handled_by || 'Not acknowledged'}</p></div></header>
    <div className="d-flex gap-3 mb-3 flex-wrap"><Link to={`${admin ? '/alerts' : '/my-cases'}/${data.alert_id}`}>Case #{data.alert_id}</Link><Link to={`/users/${encodeURIComponent(data.user_id)}`}>{admin ? `View user profile and contact details (${data.user_id})` : data.user_id}</Link></div>
    <section className="dash-panel p-3 mb-3"><h2 className="h5">Filing snapshot</h2><div className="d-flex gap-3 flex-wrap"><span>User ID: <Link to={`/users/${encodeURIComponent(data.user_id)}`}>{data.user_id}</Link></span><span>Case status: {STATUS_LABEL[data.case_status_at_filing]}</span><span>Peak score: {data.snapshot.peak_score}</span><CategoryBadge category={data.snapshot.category} /><span>Outcome: {data.snapshot.outcome?.replaceAll('_', ' ') || 'Not recorded'}</span></div><p className="small text-muted mt-2">Filed {fmt(data.snapshot.filed_at)} · Indicators: {data.snapshot.indicators?.join(', ') || 'None'}</p><h3 className="h6">Summary</h3><p className="employee-value text-break">{data.summary}</p><h3 className="h6">Recommendation: {RECOMMENDATIONS[data.recommendation]}</h3>{data.recommendation_note && <p className="employee-value text-break">{data.recommendation_note}</p>}<p className="small text-muted mb-0">Recommendations are advisory. The app cannot disable accounts.</p></section>
    {error && <p role="alert" className="alert alert-danger">{error}</p>}
    <div className="d-flex gap-2 flex-wrap mb-3">
      {admin && data.status === 'submitted' && <button className="btn btn-primary" disabled={busy} onClick={() => act(() => api.acknowledgeEscalation(id))}>Acknowledge</button>}
      {handler && active && data.status !== 'submitted' && <><button className="btn btn-outline-primary" disabled={busy} onClick={() => setAction('info')}>Request more info</button><button className="btn btn-outline-primary" disabled={busy} onClick={() => setAction('contact')}>Log contact</button><button className="btn btn-primary" disabled={busy} onClick={() => setAction('complete')}>Mark as handled</button></>}
      {creator && data.status === 'submitted' && <button className="btn btn-outline-danger" disabled={busy} onClick={() => setAction('withdraw')}>Withdraw</button>}
      {admin && active && data.handled_by && !handler && <p className="text-muted">This request is being handled by {data.handled_by}.</p>}
    </div>
    {data.handling_note && <section className="dash-panel p-3 mb-3"><h2 className="h5">Handling note</h2><p className="employee-value text-break">{data.handling_note}</p><p className="small text-muted mb-0">Handled {fmt(data.completed_at)}</p></section>}
    <div className="row g-3"><section className="col-lg-8"><div className="dash-panel p-3"><h2 className="h5">Messages</h2>{data.messages.length ? data.messages.map(m => <article className="border-bottom py-3" key={m.id}><strong>{m.author}</strong> <span className="small text-muted">({m.role}) · {fmt(m.created_at)}</span><p className="employee-value text-break mb-0">{m.message}</p></article>) : <p className="text-muted">No messages yet.</p>}
      {active && (creator || handler) && <form className="mt-3" onSubmit={e => { e.preventDefault(); act(async () => { await api.replyEscalation(id, reply.trim()); setReply('') }) }}><label className="d-block">Reply<textarea className="form-control" maxLength={4000} required value={reply} onChange={e => setReply(e.target.value)} /></label><p className="small text-muted">Visible to the filing analyst and administrators. Keep contact details in the private contact log.</p><button className="btn btn-primary" disabled={busy || !reply.trim()}>Send reply</button></form>}
    </div></section><section className="col-lg-4"><div className="dash-panel p-3"><h2 className="h5">Status timeline</h2><ol className="list-unstyled mb-0">{data.timeline.map(event => <li key={event.id} className="border-start ps-3 pb-3"><strong>{ESCALATION_STATUS[event.to_status]}</strong><div>{event.actor} · {event.action.replaceAll('_', ' ')}</div><div className="small text-muted">{fmt(event.created_at)}</div></li>)}</ol></div></section></div>
    {action && <ActionDialog action={action} id={id} onClose={() => setAction(null)} onComplete={refresh} />}
  </>}</Status></div>
}

function EscalationList() {
  const { auth } = useAuth()
  const admin = auth.role === 'admin'
  const [statuses, setStatuses] = useState([])
  const [priority, setPriority] = useState('')
  const [analyst, setAnalyst] = useState('')
  const [overdue, setOverdue] = useState(false)
  const [search, setSearch] = useState('')
  const [error, setError] = useState(null)
  const [exporting, setExporting] = useState(false)
  const params = { ...(statuses.length ? { status: statuses.join(',') } : {}), ...(priority ? { priority } : {}), ...(admin && analyst.trim() ? { analyst: analyst.trim() } : {}), ...(overdue ? { overdue: 'true' } : {}), ...(search.trim() ? { search: search.trim() } : {}) }
  const query = useLoad(() => api.escalations(params), [statuses.join(','), priority, analyst.trim(), overdue, admin, search.trim()])
  const rows = (query.data || []).filter(e => e.user_id.toLowerCase().includes(search.trim().toLowerCase()))
  const exportCsv = async () => {
    setExporting(true); setError(null)
    try {
      const blob = await api.escalationsCsv(params)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a'); a.href = url; a.download = 'escalations.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (e) { setError(e.message) } finally { setExporting(false) }
  }
  return <div className="dash-page"><header className="dash-header"><div><h1>{admin ? 'Escalations' : 'My escalations'}</h1><p className="text-muted">Advisory requests, ordered by priority and oldest first</p></div>{admin && <button className="btn btn-outline-primary" disabled={exporting || query.loading} title="Export filtered queue" onClick={exportCsv}>Export CSV</button>}</header>
    <section className="dash-panel p-3 mb-3"><div className="row g-3"><label className="col-md-4">Search user ID<input className="form-control" value={search} onChange={e => setSearch(e.target.value)} /></label><label className="col-md-3">Priority<select className="form-select" value={priority} onChange={e => setPriority(e.target.value)}><option value="">All priorities</option>{['low', 'normal', 'urgent'].map(v => <option key={v}>{v}</option>)}</select></label>{admin && <label className="col-md-3">Analyst<input className="form-control" value={analyst} onChange={e => setAnalyst(e.target.value)} /></label>}<label className="col-md-2 align-self-end"><input type="checkbox" checked={overdue} onChange={e => setOverdue(e.target.checked)} /> Overdue only</label></div><fieldset className="mt-3"><legend className="small">Escalation status</legend><div className="d-flex gap-3 flex-wrap">{Object.entries(ESCALATION_STATUS).map(([value, label]) => <label key={value}><input type="checkbox" checked={statuses.includes(value)} onChange={e => setStatuses(e.target.checked ? [...statuses, value] : statuses.filter(s => s !== value))} /> {label}</label>)}</div></fieldset></section>
    {error && <p role="alert" className="alert alert-danger">{error}</p>}
    <Status loading={query.loading} error={query.error}><section className="dash-panel p-3"><div className="table-responsive"><table className="table align-middle"><thead><tr><th>Escalation</th><th>User ID</th><th>Case</th><th>Priority</th><th>Status</th><th>Analyst</th><th>Age</th></tr></thead><tbody>{rows.map(e => <tr key={e.id}><td><Link to={`/escalations/${e.id}`}>Escalation #{e.id}</Link></td><td><Link to={`/users/${encodeURIComponent(e.user_id)}`}>{e.user_id}</Link></td><td><Link to={`${admin ? '/alerts' : '/my-cases'}/${e.alert_id}`}>Case #{e.alert_id}</Link></td><td><PriorityBadge priority={e.priority} /></td><td><EscalationStatus status={e.status} /></td><td>{e.created_by}</td><td><span className={`badge ${e.overdue ? 'bg-danger' : 'bg-secondary'}`}>{e.age_hours.toFixed(1)} h{e.overdue ? ' · Overdue' : ''}</span></td></tr>)}</tbody></table>{!rows.length && <p className="text-muted">No escalations match these filters.</p>}</div></section></Status>
  </div>
}

export default function Escalations() { const { id } = useParams(); return id ? <EscalationDetail key={id} id={id} /> : <EscalationList /> }
