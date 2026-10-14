import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Download, FileText, Printer, RotateCcw, ShieldAlert, X } from 'lucide-react'
import { ArcElement, BarElement, CategoryScale, Chart as ChartJS, Legend, LinearScale, Tooltip } from 'chart.js'
import { Bar, Doughnut } from 'react-chartjs-2'
import { api } from '../api'
import { CATEGORY_COLOR, CategoryBadge, DISCLAIMER, ScoreBar, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

ChartJS.register(ArcElement, BarElement, CategoryScale, LinearScale, Tooltip, Legend)
const EMPTY = { start: '', end: '', department: '', category: [], status: [], min_score: '', max_score: '', user_id: '', indicator: '', sort_by: 'peak_score', sort_dir: 'desc', limit: '1000', group_by: 'none' }
const SORTS = { peak_score: 'Peak score', start_time: 'Started', user_id: 'User ID', department: 'Department', category: 'Risk level', status: 'Case status' }
const GROUPS = { none: 'None', department: 'Department', user: 'User', indicator: 'Indicator', category: 'Risk level', day: 'Day' }
const number = value => Number(value || 0).toLocaleString()
const dateOf = value => value?.slice(0, 10) || ''
const parameters = filters => Object.fromEntries(Object.entries(filters).map(([key, value]) => [key, Array.isArray(value) ? value.join(',') : key === 'limit' ? Number(value) : value]).filter(([, value]) => value !== ''))

function SelectField({ name, label, value, options, onChange }) {
  return <div><label className="form-label" htmlFor={`report-${name}`}>{label}</label><select id={`report-${name}`} className="form-select form-select-sm" value={value} onChange={e => onChange(name, e.target.value)}>{Object.entries(options).map(([key, text]) => <option value={key} key={key}>{text}</option>)}</select></div>
}

export default function Reports() {
  const navigate = useNavigate()
  const metadata = useLoad(async () => {
    const [summary, users, indicators, range] = await Promise.all([api.summary(), api.users(), api.reportIndicators(), api.reportRange()])
    return { departments: Object.keys(summary.departments || {}).sort(), users, indicators, range }
  })
  const [filters, setFilters] = useState({ ...EMPTY })
  const [report, setReport] = useState(null)
  const [applied, setApplied] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [exporting, setExporting] = useState(false)
  const update = (key, value) => setFilters(previous => ({ ...previous, [key]: value }))
  const toggle = (key, value) => update(key, filters[key].includes(value) ? filters[key].filter(item => item !== value) : [...filters[key], value])
  const execute = async scope => {
    setError(null)
    if (scope.start && scope.end && scope.start > scope.end) { setError('From date is after To date'); return }
    if ([scope.min_score, scope.max_score].some(value => value !== '' && (!Number.isFinite(Number(value)) || Number(value) < 0 || Number(value) > 100))) { setError('Scores must be between 0 and 100'); return }
    if (scope.min_score !== '' && scope.max_score !== '' && Number(scope.min_score) > Number(scope.max_score)) { setError('Minimum score must not exceed maximum score'); return }
    if (!Number.isInteger(Number(scope.limit)) || Number(scope.limit) < 1 || Number(scope.limit) > 1000) { setError('Top N must be an integer between 1 and 1000'); return }
    setBusy(true)
    try { const result = await api.report(parameters(scope)); setReport(result); setApplied({ ...scope }) }
    catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  const preset = days => {
    if (!days) { setFilters(previous => ({ ...previous, start: '', end: '' })); return }
    const end = dateOf(metadata.data?.range.last_event)
    if (!end) return
    const start = new Date(`${end}T00:00:00Z`)
    start.setUTCDate(start.getUTCDate() - days + 1)
    setFilters(previous => ({ ...previous, start: start.toISOString().slice(0, 10), end }))
  }
  const download = async () => {
    if (!applied) return
    setExporting(true); setError(null)
    try {
      const blob = await api.reportCsv(parameters(applied))
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url; anchor.download = `insiderguard_risk_report_${dateOf(report.generated_at)}.csv`
      document.body.appendChild(anchor); anchor.click(); anchor.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (err) { setError(err.message) }
    finally { setExporting(false) }
  }
  const chips = applied ? Object.entries(applied).flatMap(([key, value]) => {
    if (value === '' || value === EMPTY[key]) return []
    if (Array.isArray(value)) return value.map(item => ({ key, value: item, label: key === 'status' ? STATUS_LABEL[item] : item }))
    const labels = { start: 'From', end: 'To', department: 'Department', min_score: 'Min score', max_score: 'Max score', user_id: 'User', indicator: 'Indicator', sort_by: 'Sort', sort_dir: 'Direction', limit: 'Top N', group_by: 'Group' }
    return [{ key, value, label: `${labels[key]}: ${key === 'sort_by' ? SORTS[value] : key === 'group_by' ? GROUPS[value] : value}` }]
  }) : []
  const removeChip = chip => {
    const next = { ...applied, [chip.key]: Array.isArray(applied[chip.key]) ? applied[chip.key].filter(value => value !== chip.value) : EMPTY[chip.key] }
    setFilters(next); execute(next)
  }
  const summary = report?.summary
  const chartOptions = { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { precision: 0 } } } }

  return <div className="dash-page reports-page">
    <header className="dash-header"><div><h1>Risk reports</h1><p className="text-muted mb-0">Filtered evidence, risk patterns and investigation outcomes</p></div></header>
    <section className="card dash-panel reports-setup" aria-labelledby="report-setup-title">
      <div className="dash-panel-heading"><div><h2 id="report-setup-title">Report scope</h2><p>{metadata.data?.range.last_event ? `Dataset: ${dateOf(metadata.data.range.first_event)} to ${dateOf(metadata.data.range.last_event)} / UTC` : 'Reporting dates in UTC'}</p></div></div>
      {metadata.error && <div className="alert alert-warning" role="alert">Report options could not be loaded. <button className="btn btn-sm btn-link" onClick={metadata.reload}>Retry</button></div>}
      <form onSubmit={event => { event.preventDefault(); execute(filters) }} noValidate>
        <fieldset disabled={busy || exporting} className="reports-filter-fields">
          <div className="reports-presets" aria-label="Dataset date presets">{[7, 14, 30].map(days => <button key={days} type="button" className="btn btn-sm btn-outline-primary" disabled={!metadata.data?.range.last_event} onClick={() => preset(days)}>Last {days} days</button>)}<button type="button" className="btn btn-sm btn-outline-secondary" onClick={() => preset(null)}>All time</button></div>
          <div className="reports-filter-grid">
            {['start', 'end'].map(key => <div key={key}><label htmlFor={`report-${key}`} className="form-label">{key === 'start' ? 'From' : 'To'}</label><input id={`report-${key}`} type="date" className="form-control form-control-sm" value={filters[key]} onChange={e => update(key, e.target.value)} /></div>)}
            <SelectField name="department" label="Department" value={filters.department} options={{ '': 'All departments', ...Object.fromEntries((metadata.data?.departments || []).map(value => [value, value])) }} onChange={update} />
          </div>
          <div className="reports-checkbox-grid">
            <fieldset><legend>Risk level</legend><div>{Object.keys(CATEGORY_COLOR).map(category => <label key={category} className="form-check"><input type="checkbox" className="form-check-input" checked={filters.category.includes(category)} onChange={() => toggle('category', category)} /><span>{category}</span></label>)}</div></fieldset>
            <fieldset><legend>Case status</legend><div>{Object.entries(STATUS_LABEL).map(([key, label]) => <label key={key} className="form-check"><input type="checkbox" className="form-check-input" checked={filters.status.includes(key)} onChange={() => toggle('status', key)} /><span>{label}</span></label>)}</div></fieldset>
          </div>
          <details className="reports-advanced"><summary>Advanced filters</summary><div className="reports-filter-grid">
            {['min_score', 'max_score'].map(key => <div key={key}><label className="form-label" htmlFor={`report-${key}`}>{key === 'min_score' ? 'Minimum score' : 'Maximum score'}</label><input id={`report-${key}`} type="number" min="0" max="100" step="any" className="form-control form-control-sm" value={filters[key]} onChange={e => update(key, e.target.value)} /></div>)}
            <div><label className="form-label" htmlFor="report-user">User ID</label><input id="report-user" list="report-users" maxLength={64} className="form-control form-control-sm" value={filters.user_id} onChange={e => update('user_id', e.target.value)} /><datalist id="report-users">{(metadata.data?.users || []).map(user => <option key={user.user_id} value={user.user_id} />)}</datalist></div>
            <SelectField name="indicator" label="Indicator" value={filters.indicator} options={{ '': 'All indicators', ...Object.fromEntries((metadata.data?.indicators || []).map(value => [value, value])) }} onChange={update} />
            <SelectField name="sort_by" label="Sort by" value={filters.sort_by} options={SORTS} onChange={update} />
            <SelectField name="sort_dir" label="Sort direction" value={filters.sort_dir} options={{ desc: 'Descending', asc: 'Ascending' }} onChange={update} />
            <div><label className="form-label" htmlFor="report-limit">Top N</label><input id="report-limit" type="number" min="1" max="1000" step="1" className="form-control form-control-sm" value={filters.limit} onChange={e => update('limit', e.target.value)} /></div>
            <SelectField name="group_by" label="Group by" value={filters.group_by} options={GROUPS} onChange={update} />
          </div></details>
          <div className="reports-filter-actions"><button className="btn btn-primary btn-sm telemetry-command"><FileText size={16} aria-hidden="true" />{busy ? 'Generating...' : 'Generate report'}</button><button type="button" className="btn btn-sm btn-outline-secondary telemetry-command" onClick={() => { setFilters({ ...EMPTY }); setError(null) }}><RotateCcw size={15} aria-hidden="true" />Reset filters</button><button type="button" className="btn btn-sm btn-outline-primary telemetry-command" onClick={download} disabled={!report}><Download size={16} aria-hidden="true" />{exporting ? 'Exporting...' : 'Download CSV'}</button><button type="button" className="btn btn-sm btn-outline-secondary telemetry-command" onClick={() => window.print()} disabled={!report}><Printer size={16} aria-hidden="true" />Print</button></div>
        </fieldset>
      </form>
    </section>
    {error && <div className="alert alert-danger mb-0" role="alert">{error}</div>}
    {!report && !busy && <section className="card dash-panel reports-empty"><FileText size={36} aria-hidden="true" /><h2>No report generated</h2><p>Choose a scope or generate a report for all available data.</p></section>}
    {busy && <p role="status" className="text-muted mb-0">Generating report...</p>}
    {report && <div className="reports-results" aria-busy={busy}>
      <div className="reports-result-heading"><div><h2>Insider risk findings</h2><p>{report.filters.department || 'All departments'} / {report.filters.start || 'Beginning of records'} to {report.filters.end || 'Latest available'}</p></div><span>Generated {fmt(report.generated_at)}</span></div>
      {chips.length > 0 && <div className="reports-chips" aria-label="Active report filters">{chips.map(chip => <span key={`${chip.key}:${chip.value}`}>{chip.label}<button disabled={busy || exporting} aria-label={`Remove ${chip.label}`} title={`Remove ${chip.label}`} onClick={() => removeChip(chip)}><X size={13} /></button></span>)}</div>}
      {summary && <>
        <section className="dash-metrics" aria-label="Report summary">{[['Total alerts', number(summary.total_alerts)], ['Average peak score', number(summary.avg_peak_score)], ['Highest peak score', number(summary.max_peak_score)], ['Open / closed', `${number(summary.open_count)} / ${number(summary.closed_count)}`]].map(([label, value]) => <article className="card dash-metric" key={label}><span className="dash-metric-label">{label}</span><strong className="dash-metric-value">{value}</strong></article>)}</section>
        <p className="reports-coverage">{number(report.coverage.events_analysed)} events analysed / {number(report.coverage.users_monitored)} monitored profiles / {number(report.coverage.baselines_established)} established baselines. Summary covers all {number(summary.total_alerts)} matching alerts; showing the top {number(report.alerts.length)} below.</p>
        <div className="reports-charts">
          <section className="card dash-panel"><div className="dash-panel-heading"><h2>Alerts by risk level</h2></div><div className="reports-chart">{summary.total_alerts ? <Doughnut aria-label="Alerts by risk level" role="img" data={{ labels: Object.keys(summary.alerts_by_category), datasets: [{ data: Object.values(summary.alerts_by_category), backgroundColor: Object.keys(summary.alerts_by_category).map(key => CATEGORY_COLOR[key]), borderWidth: 2, borderColor: '#fff' }] }} options={{ maintainAspectRatio: false, cutout: '65%', plugins: { legend: { position: 'bottom' } } }} /> : <div className="dash-empty">No matching alerts</div>}</div></section>
          <section className="card dash-panel"><div className="dash-panel-heading"><h2>Alerts by day</h2></div><div className="reports-chart">{summary.total_alerts ? <Bar aria-label="Alerts by day" role="img" data={{ labels: Object.keys(summary.alerts_by_day), datasets: [{ label: 'Alerts', data: Object.values(summary.alerts_by_day), backgroundColor: '#2563eb', borderRadius: 3 }] }} options={chartOptions} /> : <div className="dash-empty">No matching alerts</div>}</div></section>
          <section className="card dash-panel"><div className="dash-panel-heading"><h2>Top indicators</h2></div><div className="reports-chart">{summary.top_indicators.length ? <Bar aria-label="Top indicators" role="img" data={{ labels: summary.top_indicators.map(item => item.name), datasets: [{ label: 'Alerts', data: summary.top_indicators.map(item => item.count), backgroundColor: '#269582', borderRadius: 3 }] }} options={{ ...chartOptions, indexAxis: 'y', scales: { x: { beginAtZero: true, ticks: { precision: 0 } }, y: { ticks: { font: { size: 10 } } } } }} /> : <div className="dash-empty">No matching indicators</div>}</div></section>
        </div>
        {summary.top_users.length > 0 && <section className="card dash-panel"><div className="dash-panel-heading"><h2>Top users by alert count</h2></div><div className="table-responsive"><table className="table align-middle mb-0"><thead><tr><th>User</th><th>Alerts</th><th>Highest score</th></tr></thead><tbody>{summary.top_users.map(user => <tr key={user.user_id}><td><Link to={`/users/${encodeURIComponent(user.user_id)}`}>{user.user_id}</Link></td><td>{user.count}</td><td>{user.max_score}</td></tr>)}</tbody></table></div></section>}
      </>}
      {report.groups && <section className="card dash-panel"><div className="dash-panel-heading"><h2>Grouped by {GROUPS[applied.group_by]?.toLowerCase()}</h2></div><div className="table-responsive"><table className="table align-middle mb-0"><thead><tr><th>Group</th><th>Alerts</th><th>Average score</th><th>Highest score</th></tr></thead><tbody>{report.groups.map(group => <tr key={group.key}><td>{group.key}</td><td>{group.count}</td><td>{group.avg_score}</td><td>{group.max_score}</td></tr>)}</tbody></table></div>{!report.groups.length && <div className="dash-empty">No groups in this report.</div>}</section>}
      <section className="card dash-panel"><div className="dash-panel-heading"><div><h2>Alert findings</h2><p>{number(report.alerts.length)} returned alerts</p></div></div><div className="table-responsive"><table className="table table-hover align-middle mb-0 reports-table"><thead><tr><th>Alert / user</th><th>Department</th><th>Started (UTC)</th><th>Peak risk</th><th>Case status</th><th>Indicators</th></tr></thead><tbody>{report.alerts.map(alert => <tr key={alert.alert_id} className="clickable" onClick={event => { if (!event.target.closest('a')) navigate(`/alerts/${alert.alert_id}`) }}><td><Link className="fw-semibold" to={`/alerts/${alert.alert_id}`}>Alert #{alert.alert_id}</Link><Link className="alerts-user-link" to={`/users/${encodeURIComponent(alert.user_id)}`}>{alert.user_id}</Link></td><td>{alert.department}</td><td className="alerts-date">{fmt(alert.start_time)}</td><td><div className="alerts-score"><CategoryBadge category={alert.category} /><ScoreBar score={alert.peak_score} category={alert.category} /></div></td><td><span className={`alerts-status alerts-status-${alert.status}`}>{STATUS_LABEL[alert.status]}</span></td><td className="alerts-indicators">{alert.indicators}</td></tr>)}</tbody></table></div>{!report.alerts.length && <div className="dash-empty">No alerts were found for this reporting scope.</div>}</section>
      <p className="dash-disclaimer"><ShieldAlert size={15} aria-hidden="true" />{report.disclaimer || DISCLAIMER}</p>
    </div>}
  </div>
}
