import { useState } from 'react'
import { api } from '../api'
import { CategoryBadge, DISCLAIMER, STATUS_LABEL, fmt } from '../components.jsx'

export default function Reports() {
  const [f, setF] = useState({ start: '', end: '', department: '' })
  const [report, setReport] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const params = () => Object.fromEntries(Object.entries(f).filter(([, v]) => v))
  const generate = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try { setReport(await api.report(params())) } catch (err) { setError(err.message) } finally { setBusy(false) }
  }
  const download = async () => {
    const blob = await api.reportCsv(params())
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'insiderguard_risk_report.csv'
    a.click()
    URL.revokeObjectURL(a.href)
  }

  return (
    <>
      <h1 className="h3 mb-3">Risk reports</h1>
      <form className="card p-3 mb-3 row g-2 flex-row align-items-end" onSubmit={generate}>
        <div className="col-md-3"><label className="form-label small mb-1" htmlFor="rs">From</label><input id="rs" type="date" className="form-control form-control-sm" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /></div>
        <div className="col-md-3"><label className="form-label small mb-1" htmlFor="re">To</label><input id="re" type="date" className="form-control form-control-sm" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} /></div>
        <div className="col-md-3">
          <label className="form-label small mb-1" htmlFor="rd">Department</label>
          <select id="rd" className="form-select form-select-sm" value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })}>
            <option value="">All</option>{['Finance', 'HR', 'Engineering', 'Sales', 'IT'].map((d) => <option key={d}>{d}</option>)}
          </select>
        </div>
        <div className="col-md-3 d-flex gap-2">
          <button className="btn btn-sm btn-primary" disabled={busy}>Generate</button>
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={download}>CSV</button>
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => window.print()} disabled={!report}>Print</button>
        </div>
      </form>
      {error && <div className="alert alert-danger">{error}</div>}
      {report && (
        <div className="card p-3">
          <h2 className="h5">Insider risk findings</h2>
          <div className="small text-muted mb-3">Generated {fmt(report.generated_at)} · {report.filters.department || 'all departments'}</div>
          <div className="row mb-3 text-center">
            <div className="col"><div className="kpi">{report.coverage.events_analysed.toLocaleString()}</div><div className="small text-muted">events analysed</div></div>
            <div className="col"><div className="kpi">{report.coverage.users_monitored}</div><div className="small text-muted">users monitored</div></div>
            <div className="col"><div className="kpi">{report.coverage.baselines_established}</div><div className="small text-muted">baselines established</div></div>
            <div className="col"><div className="kpi">{report.alerts.length}</div><div className="small text-muted">alerts</div></div>
          </div>
          <table className="table table-sm">
            <thead><tr><th>#</th><th>User</th><th>Dept</th><th>Started</th><th>Score</th><th>Level</th><th>Status</th><th>Indicators</th></tr></thead>
            <tbody>
              {report.alerts.map((a) => (
                <tr key={a.alert_id}><td>{a.alert_id}</td><td>{a.user_id}</td><td>{a.department}</td><td className="small">{fmt(a.start_time)}</td><td>{a.peak_score}</td><td><CategoryBadge category={a.category} /></td><td>{STATUS_LABEL[a.status]}</td><td className="small">{a.indicators}</td></tr>
              ))}
            </tbody>
          </table>
          <div className="small text-muted">{DISCLAIMER}</div>
        </div>
      )}
    </>
  )
}
