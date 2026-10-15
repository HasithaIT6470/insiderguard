import { useState } from 'react'
import { api } from './api'
import { CaseDialog, notifyCasesChanged } from './cases.jsx'
import { OUTCOME_LABEL } from './components.jsx'

const HELP = {
  true_positive: 'Real threat or policy violation.',
  false_positive: 'The detection was wrong or noisy.',
  benign_explained: 'Unusual but legitimate activity, explained by context.',
}

export function CloseCaseDialog({ alertId, onClose, onComplete }) {
  const [outcome, setOutcome] = useState('')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const length = note.trim().length
  const valid = !!outcome && length >= 15 && length <= 4000
  const submit = async event => {
    event.preventDefault()
    if (!valid) return
    setBusy(true); setError(null)
    try { await api.setStatus(alertId, 'closed', { outcome, note: note.trim() }); notifyCasesChanged(); onComplete() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <CaseDialog title={`Close Case #${alertId}`} busy={busy} onClose={onClose}>
    <form onSubmit={submit}>
      <fieldset disabled={busy}><legend className="h6">Outcome</legend>
        {Object.entries(OUTCOME_LABEL).map(([value, label]) => <label key={value} className="form-check mb-2">
          <input className="form-check-input" type="radio" name="outcome" value={value} checked={outcome === value} onChange={() => setOutcome(value)} required />
          <span>{label}</span><span className="d-block small text-muted">{HELP[value]}</span>
        </label>)}
      </fieldset>
      <label htmlFor="closing-note" className="form-label mt-2">Closing note</label>
      <textarea id="closing-note" className="form-control" rows={4} maxLength={4000} required value={note} disabled={busy}
        aria-describedby="closing-note-count" onChange={e => setNote(e.target.value)} />
      <p id="closing-note-count" className="small text-muted" aria-live="polite">{length} / 4000 characters (minimum 15, excluding surrounding whitespace)</p>
      {error && <p className="alert alert-danger" role="alert">{error}</p>}
      <div className="rule-dialog-actions"><button type="button" className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn btn-sm btn-primary" disabled={busy || !valid}>Close case</button></div>
    </form>
  </CaseDialog>
}

export function ReopenCaseDialog({ alertId, status, onClose, onComplete }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const valid = reason.trim().length >= 5 && reason.trim().length <= 4000
  const submit = async event => {
    event.preventDefault()
    if (!valid) return
    setBusy(true); setError(null)
    try { await api.setStatus(alertId, status, { reason: reason.trim() }); notifyCasesChanged(); onComplete() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <CaseDialog title={`Reopen Case #${alertId}`} busy={busy} onClose={onClose}>
    <form onSubmit={submit}>
      <p>The previous outcome and closing note remain in Case history.</p>
      <label htmlFor="reopen-reason" className="form-label">Reopen reason</label>
      <textarea id="reopen-reason" className="form-control" rows={3} maxLength={4000} required value={reason} disabled={busy} onChange={e => setReason(e.target.value)} />
      <p className="small text-muted" aria-live="polite">{reason.trim().length} characters (minimum 5)</p>
      {error && <p className="alert alert-danger" role="alert">{error}</p>}
      <div className="rule-dialog-actions"><button type="button" className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button>
        <button className="btn btn-sm btn-primary" disabled={busy || !valid}>Reopen case</button></div>
    </form>
  </CaseDialog>
}
