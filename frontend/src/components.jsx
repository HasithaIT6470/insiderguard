import { useEffect, useState } from 'react'

export const CATEGORY_COLOR = { Low: '#2e7d32', Medium: '#b7791f', High: '#d9480f', Critical: '#b00020' }

export function CategoryBadge({ category }) {
  return <span className={`badge badge-${category}`}>{category}</span>
}

export function ScoreBar({ score, category }) {
  return (
    <div className="d-flex align-items-center gap-2" style={{ minWidth: 140 }}>
      <div className="score-bar flex-grow-1" role="progressbar" aria-valuenow={score} aria-valuemin={0} aria-valuemax={100}>
        <div style={{ width: `${Math.min(100, score)}%`, background: CATEGORY_COLOR[category] || '#888' }} />
      </div>
      <span className="fw-semibold">{Number(score).toFixed(0)}</span>
    </div>
  )
}

export function fmt(ts) {
  if (!ts) return '—'
  const d = new Date(ts.endsWith('Z') ? ts : ts + 'Z')
  return d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC'
}

export function useLoad(fn, deps = []) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true }))
    fn()
      .then((data) => alive && setState({ data, error: null, loading: false }))
      .catch((error) => alive && setState({ data: null, error, loading: false }))
    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { ...state, reload: () => setTick((t) => t + 1) }
}

export function Status({ loading, error, children }) {
  if (loading) return <div className="text-muted py-4">Loading…</div>
  if (error) return <div className="alert alert-danger">{error.message}</div>
  return children
}

export const STATUS_LABEL = { open: 'Open', under_investigation: 'Under investigation', closed: 'Closed' }
export const OUTCOME_LABEL = { true_positive: 'True positive', false_positive: 'False positive', benign_explained: 'Benign/explained' }
export const OUTCOME_COLOR = { true_positive: '#2e7d32', false_positive: '#d29b24', benign_explained: '#657084', no_outcome: '#adb5bd' }

export function OutcomeBadge({ outcome }) {
  return OUTCOME_LABEL[outcome]
    ? <span className={`badge outcome-badge outcome-${outcome}`}>{OUTCOME_LABEL[outcome]}</span>
    : <span className="small text-muted">No outcome</span>
}

export function caseStatusLabel(alert) {
  return alert.status === 'closed' && !(alert.outcome || alert.resolution?.outcome)
    ? 'Closed (no outcome recorded)' : STATUS_LABEL[alert.status]
}

export const DISCLAIMER = 'Risk scores are investigative leads only and are not proof of malicious intent.'

export function AttackChip({ technique }) {
  if (!technique?.id) return null
  const label = [technique.id, technique.name, ...(technique.tactics || []).map(t => t.name),
    `confidence ${technique.confidence || 'unknown'}`].filter(Boolean).join(' · ')
  return technique.url
    ? <a className="attack-chip" href={technique.url} target="_blank" rel="noopener noreferrer" title={label} aria-label={label}>{technique.id}</a>
    : <span className="attack-chip" title={label} aria-label={label}>{technique.id}</span>
}

export function AttackChips({ techniques }) {
  return techniques?.length
    ? <span className="attack-chips">{techniques.map(t => <AttackChip key={t.id} technique={t} />)}</span>
    : <span className="text-muted">—</span>
}
