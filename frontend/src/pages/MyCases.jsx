import { useMemo, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { CategoryBadge, OutcomeBadge, caseStatusLabel, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

function MyCasesList() {
  const [status, setStatus] = useState('')
  const [category, setCategory] = useState('')
  const query = useLoad(() => api.myCases(status ? { status } : {}), [status])
  const summary = query.data?.summary
  const cases = useMemo(() => {
    const severity = { Critical: 3, High: 2, Medium: 1, Low: 0 }
    return (query.data?.cases || []).filter(a => !category || a.category === category).slice()
      .sort((a, b) => (severity[b.category] ?? -1) - (severity[a.category] ?? -1) || b.age_hours - a.age_hours || a.id - b.id)
  }, [query.data, category])
  return <div className="dash-page">
    <header className="dash-header"><div><h1>My cases</h1><p className="text-muted mb-0">Your assigned investigations</p></div><button className="btn btn-sm btn-outline-secondary" onClick={query.reload}>Refresh</button></header>
    <Status loading={query.loading} error={query.error}>
      {summary && <section className="dash-metrics" aria-label="My cases summary">
        {[
          ['Total assigned', summary.total], ['Under investigation', summary.under_investigation],
          ['Closed', summary.closed], ['Oldest open case age', summary.oldest_open_age_hours == null ? '—' : `${summary.oldest_open_age_hours} h`],
        ].map(([label, value]) => <article key={label} className="card dash-metric"><span>{label}</span><strong className="dash-metric-value">{value}</strong></article>)}
      </section>}
      <section className="card dash-panel">
        <div className="dash-filters">
          <select className="form-select form-select-sm" aria-label="Case status" value={status} onChange={e => setStatus(e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <select className="form-select form-select-sm" aria-label="Severity" value={category} onChange={e => setCategory(e.target.value)}><option value="">All severities</option>{['Critical', 'High', 'Medium', 'Low'].map(c => <option key={c}>{c}</option>)}</select>
        </div>
        <div className="table-responsive"><table className="table align-middle mb-0"><thead><tr>{['Case', 'User ID', 'Severity', 'Score', 'Status', 'Started', 'Age (hours)'].map(h => <th key={h}>{h}</th>)}</tr></thead>
          <tbody>{cases.map(a => <tr key={a.id}><td><Link to={`/my-cases/${a.id}`}>Case #{a.id}</Link></td><td><Link to={`/users/${encodeURIComponent(a.user_id)}`}>{a.user_id}</Link></td><td><CategoryBadge category={a.category} /></td><td><ScoreBar score={a.peak_score} category={a.category} /></td><td>{caseStatusLabel(a)}{a.status === 'closed' && <div><OutcomeBadge outcome={a.outcome} /></div>}</td><td>{fmt(a.start_time)}</td><td>{a.age_hours}</td></tr>)}</tbody>
        </table></div>
        {!cases.length && <p className="text-muted mt-3 mb-0">No cases match these filters. Claim a case from <Link to="/alerts">Alerts</Link> to get started.</p>}
      </section>
    </Status>
  </div>
}

export default function MyCases() {
  const { auth } = useAuth() || {}
  return auth?.role === 'analyst' ? <MyCasesList /> : <Navigate to="/alerts" replace />
}
