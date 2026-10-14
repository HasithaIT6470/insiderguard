import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ArrowRight, Bell, RefreshCw, Search, ShieldAlert, Users } from 'lucide-react'
import { ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar, Doughnut } from 'react-chartjs-2'
import { api } from '../api'
import { CATEGORY_COLOR, CategoryBadge, DISCLAIMER, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend)
const DEPT_COLORS = ['#2563eb', '#0891b2', '#8b5cf6', '#e09a20', '#299970', '#df6274']
const number = value => Number(value || 0).toLocaleString()

function Metric({ label, value, detail, icon: Icon, tone = '' }) {
  return <article className={`card dash-metric ${tone}`}>
    <div className="dash-metric-label"><span>{label}</span><Icon size={19} aria-hidden="true" /></div>
    <strong className="dash-metric-value">{number(value)}</strong><span className="text-muted small">{detail}</span>
  </article>
}

export default function Dashboard() {
  const summary = useLoad(() => api.summary())
  const [dept, setDept] = useState('')
  const [query, setQuery] = useState('')
  const [level, setLevel] = useState('')
  const users = useLoad(() => api.users(dept), [dept])
  const s = summary.data
  const depts = useMemo(() => Object.keys(s?.departments || {}).sort(), [s])
  const rankedUsers = useMemo(() => (users.data || []).filter(u => (!level || u.risk_category === level) && `${u.user_id} ${u.department}`.toLowerCase().includes(query.trim().toLowerCase())).sort((a, b) => b.risk_score - a.risk_score), [users.data, level, query])
  const trend = useMemo(() => ({ labels: (s?.alert_trend || []).map(t => t.date.slice(5)), datasets: depts.map((d, i) => ({ label: d, data: s.alert_trend.map(t => t.departments[d] || 0), backgroundColor: DEPT_COLORS[i % DEPT_COLORS.length], borderRadius: 2, maxBarThickness: 28 })) }), [s, depts])

  return <div className="dash-page">
    <header className="dash-header">
      <div><h1>Security overview</h1><p className="text-muted mb-0">{s ? `Data as of ${fmt(s.as_of)}` : 'InsiderGuard monitoring'}</p></div>
      <div className="dash-header-actions">
        {s && <span className="dash-ai-state"><span className={s.ai_configured ? 'is-enabled' : ''} />AI explanations {s.ai_configured ? 'enabled' : 'off'}</span>}
        <button className="btn btn-outline-light btn-sm d-inline-flex align-items-center gap-2" onClick={() => { summary.reload(); users.reload() }} disabled={summary.loading || users.loading}><RefreshCw size={15} aria-hidden="true" />Refresh</button>
      </div>
    </header>
    <Status loading={summary.loading} error={summary.error}>
      {s && <>
        <section className="dash-metrics" aria-label="Monitoring totals">
          <Metric label="Monitored users" value={s.totals.users} detail="Synthetic employee profiles" icon={Users} />
          <Metric label="Events analysed" value={s.totals.events} detail="Total ingested telemetry" icon={Activity} />
          <Metric label="Open alerts" value={s.alerts_by_status.open} detail="Awaiting investigation" icon={Bell} tone="dash-metric-warning" />
          <Metric label="High / critical users" value={(s.risk_distribution.High || 0) + (s.risk_distribution.Critical || 0)} detail="Current risk classification" icon={ShieldAlert} tone="dash-metric-danger" />
        </section>
        <section className="dash-case-strip" aria-label="Case status">
          <span className="dash-case-title">Case workload</span>
          {Object.entries(STATUS_LABEL).map(([key, label]) => <span key={key} className="dash-case-count">{label}<strong>{number(s.alerts_by_status[key])}</strong></span>)}
          <Link to="/alerts">All {number(s.totals.alerts)} alerts <ArrowRight size={15} aria-hidden="true" /></Link>
        </section>
        <div className="dash-charts">
          <section className="card dash-panel">
            <div className="dash-panel-heading"><div><h2>Alert activity</h2><p>Daily alerts by department</p></div><span className="dash-panel-meta">{number(s.alert_trend.length)} days</span></div>
            <div className="dash-trend-chart">{s.alert_trend.length ? <Bar data={trend} options={{ maintainAspectRatio: false, scales: { x: { stacked: true, grid: { display: false }, ticks: { maxTicksLimit: 12, maxRotation: 0 } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } }, plugins: { legend: { position: 'bottom', labels: { boxWidth: 10, boxHeight: 10, padding: 16 } } } }} /> : <div className="dash-empty">No alert activity recorded.</div>}</div>
          </section>
          <section className="card dash-panel">
            <div className="dash-panel-heading"><div><h2>Current risk</h2><p>Distribution across monitored users</p></div></div>
            <div className="dash-risk-chart">{Object.values(s.risk_distribution).some(v => v > 0) ? <Doughnut data={{ labels: Object.keys(s.risk_distribution), datasets: [{ data: Object.values(s.risk_distribution), backgroundColor: Object.keys(s.risk_distribution).map(k => CATEGORY_COLOR[k]), borderWidth: 3, borderColor: '#fff' }] }} options={{ maintainAspectRatio: false, cutout: '74%', plugins: { legend: { display: false } } }} /> : <div className="dash-empty">No risk data available.</div>}</div>
            <div className="dash-risk-legend">{Object.entries(s.risk_distribution).map(([category, count]) => <div key={category}><span><i style={{ background: CATEGORY_COLOR[category] }} />{category}</span><strong>{number(count)}</strong></div>)}</div>
          </section>
        </div>
        <section className="card dash-panel dash-users">
          <div className="dash-panel-heading"><div><h2>User risk overview</h2><p>Ranked by current risk score</p></div><span className="dash-panel-meta">{rankedUsers.length} matching users</span></div>
          <div className="dash-filters">
            <div className="dash-search"><Search size={17} aria-hidden="true" /><input className="form-control form-control-sm" aria-label="Search users" placeholder="Search user or department" value={query} onChange={e => setQuery(e.target.value)} /></div>
            <select className="form-select form-select-sm" aria-label="Filter by department" value={dept} onChange={e => setDept(e.target.value)}><option value="">All departments</option>{depts.map(d => <option key={d}>{d}</option>)}</select>
            <select className="form-select form-select-sm" aria-label="Filter by risk level" value={level} onChange={e => setLevel(e.target.value)}><option value="">All risk levels</option>{Object.keys(CATEGORY_COLOR).map(c => <option key={c}>{c}</option>)}</select>
            {(query || dept || level) && <button className="btn btn-sm btn-link" onClick={() => { setQuery(''); setDept(''); setLevel('') }}>Clear filters</button>}
          </div>
          <Status loading={users.loading} error={users.error}>
            <div className="dash-table-scroll"><table className="table table-hover align-middle mb-0">
              <thead><tr><th scope="col">User</th><th scope="col">Department</th><th scope="col">Risk score</th><th scope="col">Risk level</th><th scope="col">Open alerts</th><th scope="col">Baseline</th><th scope="col"><span className="visually-hidden">Investigation</span></th></tr></thead>
              <tbody>{rankedUsers.map(u => <tr key={u.user_id}>
                <td><Link className="fw-semibold" to={`/users/${encodeURIComponent(u.user_id)}`}>{u.user_id}</Link></td><td>{u.department}</td><td><ScoreBar score={u.risk_score} category={u.risk_category} /></td><td><CategoryBadge category={u.risk_category} /></td><td>{number(u.open_alerts)}</td>
                <td><span className={`dash-baseline ${u.baseline_status === 'pending' ? 'is-pending' : ''}`}>{u.baseline_status === 'pending' ? 'Pending' : u.baseline_status}</span></td>
                <td><Link className="dash-investigate" to={`/users/${encodeURIComponent(u.user_id)}`} aria-label={`Investigate ${u.user_id}`} title={`Investigate ${u.user_id}`}><ArrowRight size={18} /></Link></td>
              </tr>)}</tbody>
            </table>{!rankedUsers.length && <div className="dash-empty">No users match the selected filters.</div>}</div>
          </Status>
        </section>
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Department summary</h2><p>Current risk and investigation workload</p></div></div>
          <div className="table-responsive"><table className="table align-middle mb-0">
            <thead><tr><th scope="col">Department</th><th scope="col">Average risk</th><th scope="col">Highest risk</th><th scope="col">Open</th><th scope="col">Investigating</th><th scope="col">Closed</th></tr></thead>
            <tbody>{depts.map(d => { const x = s.departments[d]; return <tr key={d}><td className="fw-semibold">{d}</td><td>{x.avg_risk}</td><td>{x.max_risk}</td><td>{number(x.open)}</td><td>{number(x.under_investigation)}</td><td>{number(x.closed)}</td></tr> })}</tbody>
          </table>{!depts.length && <div className="dash-empty">No departments available.</div>}</div>
        </section>
        <p className="dash-disclaimer"><ShieldAlert size={15} aria-hidden="true" />{DISCLAIMER}</p>
      </>}
    </Status>
  </div>
}
