import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { CategoryBadge, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

export default function Alerts() {
  const [status, setStatus] = useState('')
  const [category, setCategory] = useState('')
  const params = {}
  if (status) params.status = status
  if (category) params.category = category
  const { data, loading, error } = useLoad(() => api.alerts(params), [status, category])
  const nav = useNavigate()

  return (
    <>
      <div className="d-flex justify-content-between align-items-center mb-3">
        <h1 className="h3 mb-0">Alerts</h1>
        <div className="d-flex gap-2">
          <select className="form-select form-select-sm" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Category">
            <option value="">All levels</option>
            {['Medium', 'High', 'Critical'].map((c) => <option key={c}>{c}</option>)}
          </select>
          <select className="form-select form-select-sm" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="">All statuses</option>
            {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
      </div>
      <div className="card p-3">
        <Status loading={loading} error={error}>
          <table className="table table-hover align-middle mb-0">
            <thead><tr><th>#</th><th>User</th><th>Dept</th><th>Started</th><th>Peak score</th><th>Level</th><th>Case status</th><th>Top indicators</th></tr></thead>
            <tbody>
              {(data || []).map((a) => (
                <tr key={a.id} className="clickable" onClick={() => nav(`/alerts/${a.id}`)}>
                  <td>{a.id}</td>
                  <td><Link to={`/users/${a.user_id}`} onClick={(e) => e.stopPropagation()}>{a.user_id}</Link></td>
                  <td>{a.department}</td>
                  <td className="small">{fmt(a.start_time)}</td>
                  <td><ScoreBar score={a.peak_score} category={a.category} /></td>
                  <td><CategoryBadge category={a.category} /></td>
                  <td>{STATUS_LABEL[a.status]}</td>
                  <td className="small">{a.breakdown.slice(0, 3).map((b) => b.name).join(', ')}</td>
                </tr>
              ))}
              {data && data.length === 0 && <tr><td colSpan={8} className="text-muted text-center py-4">No alerts match.</td></tr>}
            </tbody>
          </table>
        </Status>
      </div>
    </>
  )
}
