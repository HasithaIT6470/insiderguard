import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, LineElement, PointElement, Tooltip,
} from 'chart.js'
import { Bar, Doughnut } from 'react-chartjs-2'
import { api } from '../api'
import { CATEGORY_COLOR, CategoryBadge, DISCLAIMER, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, LineElement, PointElement, Tooltip, Legend)
const DEPT_COLORS = ['#14213d', '#3a86ff', '#8338ec', '#fb8500', '#2a9d8f', '#e63946']

function Kpi({ label, value }) {
  return (
    <div className="col-6 col-lg-3">
      <div className="card p-3 h-100">
        <div className="kpi">{value}</div>
        <div className="text-muted small mt-1">{label}</div>
      </div>
    </div>
  )
}

export default function Dashboard() {
  const summary = useLoad(() => api.summary())
  const [dept, setDept] = useState('')
  const users = useLoad(() => api.users(dept), [dept])
  const nav = useNavigate()
  const s = summary.data

  const depts = useMemo(() => (s ? Object.keys(s.departments) : []), [s])
  const trend = useMemo(() => {
    if (!s) return null
    return {
      labels: s.alert_trend.map((t) => t.date.slice(5)),
      datasets: depts.map((d, i) => ({
        label: d,
        data: s.alert_trend.map((t) => t.departments[d] || 0),
        backgroundColor: DEPT_COLORS[i % DEPT_COLORS.length],
      })),
    }
  }, [s, depts])

  return (
    <Status loading={summary.loading} error={summary.error}>
      {s && (
        <>
          <div className="d-flex justify-content-between align-items-end mb-3">
            <div>
              <h1 className="h3 mb-0">Security overview</h1>
              <div className="text-muted small">Data as of {fmt(s.as_of)} · {DISCLAIMER}</div>
            </div>
            <span className={`badge ${s.ai_configured ? 'bg-success' : 'bg-secondary'}`}>
              AI explanations {s.ai_configured ? 'enabled' : 'not configured'}
            </span>
          </div>

          <div className="row g-3 mb-3">
            <Kpi label="Monitored users" value={s.totals.users} />
            <Kpi label="Events analysed" value={s.totals.events.toLocaleString()} />
            <Kpi label="Alerts (all time)" value={s.totals.alerts} />
            <Kpi label="Open alerts" value={s.alerts_by_status.open} />
          </div>

          <div className="row g-3 mb-3">
            <div className="col-lg-4">
              <div className="card p-3 h-100">
                <h2 className="h6">Risk distribution (current)</h2>
                <Doughnut
                  data={{
                    labels: Object.keys(s.risk_distribution),
                    datasets: [{ data: Object.values(s.risk_distribution), backgroundColor: Object.keys(s.risk_distribution).map((k) => CATEGORY_COLOR[k]) }],
                  }}
                  options={{ plugins: { legend: { position: 'bottom' } } }}
                />
              </div>
            </div>
            <div className="col-lg-8">
              <div className="card p-3 h-100">
                <h2 className="h6">Alerts per day by department</h2>
                <Bar
                  data={trend}
                  options={{ scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } }, plugins: { legend: { position: 'bottom' } } }}
                />
              </div>
            </div>
          </div>

          <div className="row g-3 mb-3">
            <div className="col-lg-5">
              <div className="card p-3 h-100">
                <h2 className="h6">Department trends &amp; case status</h2>
                <table className="table table-sm mb-0">
                  <thead><tr><th>Dept</th><th>Avg risk</th><th>Max</th><th title="open / investigating / closed">O / I / C</th></tr></thead>
                  <tbody>
                    {depts.map((d) => {
                      const x = s.departments[d]
                      return (
                        <tr key={d}>
                          <td>{d}</td><td>{x.avg_risk}</td><td>{x.max_risk}</td>
                          <td>{x.open} / {x.under_investigation} / {x.closed}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                <div className="small text-muted mt-2">
                  {Object.entries(s.alerts_by_status).map(([k, v]) => `${STATUS_LABEL[k]}: ${v}`).join(' · ')}
                </div>
              </div>
            </div>
            <div className="col-lg-7">
              <div className="card p-3 h-100">
                <div className="d-flex justify-content-between mb-2">
                  <h2 className="h6 mb-0">Risky users (ranked by current score)</h2>
                  <select className="form-select form-select-sm w-auto" value={dept} onChange={(e) => setDept(e.target.value)} aria-label="Filter by department">
                    <option value="">All departments</option>
                    {depts.map((d) => <option key={d}>{d}</option>)}
                  </select>
                </div>
                <Status loading={users.loading} error={users.error}>
                  <div style={{ maxHeight: 340, overflowY: 'auto' }}>
                    <table className="table table-sm table-hover align-middle mb-0">
                      <thead><tr><th>User</th><th>Dept</th><th>Score</th><th>Level</th><th>Alerts</th></tr></thead>
                      <tbody>
                        {(users.data || []).slice(0, 25).map((u) => (
                          <tr key={u.user_id} className="clickable" onClick={() => nav(`/users/${u.user_id}`)}>
                            <td><Link to={`/users/${u.user_id}`}>{u.user_id}</Link></td>
                            <td>{u.department}</td>
                            <td><ScoreBar score={u.risk_score} category={u.risk_category} /></td>
                            <td><CategoryBadge category={u.risk_category} /></td>
                            <td>{u.open_alerts}{u.baseline_status === 'pending' && <span className="badge bg-light text-dark ms-1">baseline pending</span>}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </Status>
              </div>
            </div>
          </div>
        </>
      )}
    </Status>
  )
}
