import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ArrowRight, Download, FileText, Printer, ShieldAlert, ShieldCheck, Users } from 'lucide-react'
import { api } from '../api'
import { CategoryBadge, DISCLAIMER, ScoreBar, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

const number = value => Number(value || 0).toLocaleString()

export default function Reports() {
  const [filters, setFilters] = useState({ start: '', end: '', department: '' })
  const [report, setReport] = useState(null)
  const [appliedParams, setAppliedParams] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const departments = useLoad(() => api.summary())
  const generate = async event => {
    event.preventDefault()
    setError(null)
    if (filters.start && filters.end && filters.start > filters.end) {
      setError('The end date must be on or after the start date.')
      return
    }
    const params = {
      ...(filters.start ? { start: `${filters.start}T00:00:00Z` } : {}),
      ...(filters.end ? { end: `${filters.end}T23:59:59.999999Z` } : {}),
      ...(filters.department ? { department: filters.department } : {}),
    }
    setBusy(true)
    try {
      const result = await api.report(params)
      setReport(result)
      setAppliedParams(params)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  const download = async () => {
    if (!appliedParams) return
    setExporting(true)
    setError(null)
    try {
      const blob = await api.reportCsv(appliedParams)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = 'insiderguard_risk_report.csv'
      document.body.appendChild(anchor)
      anchor.click()
      anchor.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { setError(err.message) }
    finally { setExporting(false) }
  }

  return <div className="dash-page reports-page">
    <header className="dash-header"><div><h1>Risk reports</h1><p className="text-muted mb-0">Coverage, risk findings and investigation outcomes</p></div><div className="reports-export">
      <button className="btn btn-sm btn-outline-light" onClick={download} disabled={!report || busy || exporting}><Download size={16} aria-hidden="true" />{exporting ? 'Exporting...' : 'Export CSV'}</button>
      <button className="btn btn-sm btn-outline-light" onClick={() => window.print()} disabled={!report || busy}><Printer size={16} aria-hidden="true" />Print</button>
    </div></header>

    <section className="card dash-panel reports-setup" aria-labelledby="report-setup-title">
      <div className="dash-panel-heading"><div><h2 id="report-setup-title">Report scope</h2><p>Reporting dates in UTC</p></div></div>
      <form className="reports-form" onSubmit={generate}>
        <div><label htmlFor="report-start" className="form-label">From</label><input id="report-start" type="date" className="form-control form-control-sm" value={filters.start} onChange={e => setFilters({ ...filters, start: e.target.value })} /></div>
        <div><label htmlFor="report-end" className="form-label">To</label><input id="report-end" type="date" className="form-control form-control-sm" value={filters.end} onChange={e => setFilters({ ...filters, end: e.target.value })} /></div>
        <div><label htmlFor="report-department" className="form-label">Department</label><select id="report-department" className="form-select form-select-sm" value={filters.department} onChange={e => setFilters({ ...filters, department: e.target.value })}><option value="">All departments</option>{Object.keys(departments.data?.departments || {}).sort().map(d => <option key={d}>{d}</option>)}</select></div>
        <button className="btn btn-primary btn-sm" disabled={busy || exporting}><FileText size={16} aria-hidden="true" />{busy ? 'Generating...' : 'Generate report'}</button>
      </form>
      {departments.error && <p className="small text-danger mt-3 mb-0" role="status">Departments could not be loaded. <button className="btn btn-link btn-sm p-0" onClick={departments.reload}>Retry</button></p>}
    </section>
    {error && <div className="alert alert-danger mb-0" role="alert">{error}</div>}
    {!report && !busy && <section className="card dash-panel reports-empty"><FileText size={36} aria-hidden="true" /><h2>No report generated</h2><p>Select a reporting period and department, or generate a report for all available data.</p></section>}
    {busy && <p role="status" className="text-muted mb-0">Generating report...</p>}
    {report && <div className="reports-results" aria-busy={busy}>
      <div className="reports-result-heading"><div><h2>Insider risk findings</h2><p>{report.filters.department || 'All departments'} <span aria-hidden="true">/</span> {report.filters.start?.slice(0, 10) || 'Beginning of records'} to {report.filters.end?.slice(0, 10) || 'Latest available'}</p></div><span>Generated {fmt(report.generated_at)}</span></div>
      <section className="dash-metrics" aria-label="Report coverage">
        {[
          ['Events analysed', report.coverage.events_analysed, 'Within reporting period', Activity],
          ['Monitored users', report.coverage.users_monitored, 'Profiles in selected departments', Users],
          ['Established baselines', report.coverage.baselines_established, 'Profiles with learned behaviour', ShieldCheck],
          ['Report alerts', report.alerts.length, 'Matching the report scope', ShieldAlert],
        ].map(([label, count, detail, Icon]) => <article key={label} className="card dash-metric"><div className="dash-metric-label"><span>{label}</span><Icon size={19} aria-hidden="true" /></div><strong className="dash-metric-value">{number(count)}</strong><span className="text-muted small">{detail}</span></article>)}
      </section>
      <section className="reports-risk-summary" aria-label="Report risk distribution">{['Critical', 'High', 'Medium', 'Low'].map(category => <span key={category}><CategoryBadge category={category} /><strong>{number(report.alerts_by_category?.[category])}</strong></span>)}</section>
      <section className="card dash-panel">
        <div className="dash-panel-heading"><div><h2>Alert findings</h2><p>Evidence and case status for the selected scope</p></div><span className="dash-panel-meta">{number(report.alerts.length)} alerts</span></div>
        <div className="table-responsive"><table className="table table-hover align-middle mb-0 reports-table">
          <thead><tr><th scope="col">Alert / user</th><th scope="col">Department</th><th scope="col">Started (UTC)</th><th scope="col">Peak risk</th><th scope="col">Case status</th><th scope="col">Indicators</th><th scope="col" className="reports-detail-link"><span className="visually-hidden">Investigation</span></th></tr></thead>
          <tbody>{report.alerts.map(a => <tr key={a.alert_id}>
            <td><Link className="fw-semibold" to={`/alerts/${a.alert_id}`}>Alert #{a.alert_id}</Link><Link className="alerts-user-link" to={`/users/${encodeURIComponent(a.user_id)}`}>{a.user_id}</Link></td><td>{a.department || 'Unassigned'}</td><td className="alerts-date">{fmt(a.start_time)}</td>
            <td><div className="alerts-score"><CategoryBadge category={a.category} /><ScoreBar score={a.peak_score} category={a.category} /></div></td><td><span className={`alerts-status alerts-status-${a.status}`}>{STATUS_LABEL[a.status] || a.status}</span></td>
            <td className="alerts-indicators">{a.indicators || 'No indicators'}</td><td className="reports-detail-link"><Link className="dash-investigate" to={`/alerts/${a.alert_id}`} aria-label={`Investigate alert ${a.alert_id}`} title={`Investigate alert ${a.alert_id}`}><ArrowRight size={18} aria-hidden="true" /></Link></td>
          </tr>)}</tbody>
        </table></div>
        {!report.alerts.length && <div className="dash-empty">No alerts were found for this reporting scope.</div>}
      </section>
      <p className="dash-disclaimer"><ShieldAlert size={15} aria-hidden="true" />{report.disclaimer || DISCLAIMER}</p>
    </div>}
  </div>
}
