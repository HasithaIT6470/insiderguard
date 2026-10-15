import { useState } from 'react'
import { OriginLink as Link, useOriginNavigate as useNavigate } from './navigation.jsx'
import { api } from './api'
import { CaseDialog } from './cases.jsx'
import { STATUS_LABEL } from './components.jsx'

export const ESCALATION_STATUS = { submitted: 'Submitted', acknowledged: 'Acknowledged', needs_info: 'Needs information', contacted: 'Contacted', completed: 'Handled', withdrawn: 'Withdrawn' }
export const RECOMMENDATIONS = { contact_user: 'Contact user', contact_supervisor: 'Contact supervisor', access_review: 'Access review', monitor_only: 'Monitor only', training: 'Training', hr_referral: 'HR referral', other: 'Other' }
export const ACTIVE_ESCALATIONS = ['submitted', 'acknowledged', 'needs_info', 'contacted']
export const notifyEscalationsChanged = () => window.dispatchEvent(new Event('escalations-updated'))
export function EscalationStatus({ status }) { return <span className={`badge escalation-status escalation-${status}`}>{ESCALATION_STATUS[status] || status}</span> }
export function PriorityBadge({ priority }) { return <span className={`badge ${priority === 'urgent' ? 'bg-danger' : priority === 'normal' ? 'bg-primary' : 'bg-secondary'}`}>{priority}</span> }

export function EscalateDialog({ alert, onClose, onComplete }) {
  const [summary, setSummary] = useState('')
  const [recommendation, setRecommendation] = useState('contact_user')
  const [recommendationNote, setRecommendationNote] = useState('')
  const [priority, setPriority] = useState('normal')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(null)
    try {
      const result = await api.createEscalation({ alert_id: alert.id, summary: summary.trim(), recommendation, recommendation_note: recommendationNote.trim(), priority })
      notifyEscalationsChanged(); onComplete(result)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <CaseDialog title="Escalate to admin" busy={busy} onClose={onClose}><form onSubmit={submit}>
    <p>Case #{alert.id} · {STATUS_LABEL[alert.status]} · <Link to={`/users/${encodeURIComponent(alert.user_id)}`}>{alert.user_id}</Link></p>
    <label className="d-block mb-3">Summary<textarea className="form-control" maxLength={4000} value={summary} onChange={e => setSummary(e.target.value)} required /></label><p className="small text-muted">{summary.trim().length}/4000 characters (minimum 20). Keep personal contact details in the admin-only contact log.</p>
    <label className="d-block mb-3">Recommendation<select className="form-select" value={recommendation} onChange={e => setRecommendation(e.target.value)}>{Object.entries(RECOMMENDATIONS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
    <label className="d-block mb-3">Recommendation note (optional)<textarea className="form-control" maxLength={4000} value={recommendationNote} onChange={e => setRecommendationNote(e.target.value)} /></label>
    <label className="d-block mb-3">Priority<select className="form-select" value={priority} onChange={e => setPriority(e.target.value)}>{['low', 'normal', 'urgent'].map(value => <option key={value}>{value}</option>)}</select></label>
    <p className="small text-muted">Recommendations are advisory. The app cannot disable accounts.</p>
    {error && <p role="alert" className="alert alert-danger">{error}</p>}
    <div className="d-flex justify-content-end gap-2"><button type="button" className="btn btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy || summary.trim().length < 20}>Submit escalation</button></div>
  </form></CaseDialog>
}

export function EscalateCase({ alert, onComplete }) {
  const [show, setShow] = useState(false)
  const navigate = useNavigate()
  return <div className="mt-3"><button className="btn btn-sm btn-outline-primary" disabled={!!alert.open_escalation_id} onClick={() => setShow(true)}>Escalate to admin</button>{alert.open_escalation_id && <Link className="ms-2" to={`/escalations/${alert.open_escalation_id}`}>View open escalation #{alert.open_escalation_id}</Link>}
    {show && <EscalateDialog alert={alert} onClose={() => setShow(false)} onComplete={result => { setShow(false); onComplete(); navigate(`/escalations/${result.id}`) }} />}
  </div>
}
