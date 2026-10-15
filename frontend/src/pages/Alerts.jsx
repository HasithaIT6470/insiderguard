import { useEffect, useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowDown, ArrowRight, ArrowUp, ArrowUpDown, Bell, CheckCheck, ChevronLeft, ChevronRight, RefreshCw, RotateCcw, Search, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import { AttackChips, CategoryBadge, DISCLAIMER, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

const PAGE_SIZE = 20
const LIMIT = 1000
const SORT_COLUMNS = { id: 'Alert ID', user_id: 'User', department: 'Department', start_time: 'Started', peak_score: 'Peak score', category: 'Risk level', status: 'Case status', indicator_count: 'Indicator count' }
const DEFAULT_SORT = { sort_by: 'peak_score', sort_dir: 'desc', then_by: 'start_time', then_dir: 'desc' }

function alertTechniques(alert) {
  const techniques = alert.attack?.techniques || (alert.breakdown || []).flatMap(b => b.attack || [])
  return [...new Map(techniques.map(t => [t.id, t])).values()]
}

function SortHeader({ column, label, sort, onSort }) {
  const primary = sort.sort_by === column
  const secondary = !primary && sort.then_by === column
  const direction = primary ? sort.sort_dir : sort.then_dir
  const Icon = primary || secondary ? (direction === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown
  return <th scope="col" aria-sort={primary ? (direction === 'asc' ? 'ascending' : 'descending') : 'none'}><button className="alerts-sort-header" onClick={() => onSort({ sort_by: column, sort_dir: primary && sort.sort_dir === 'asc' ? 'desc' : 'asc' })}>{label}<Icon size={13} aria-hidden="true" />{secondary && <span title="Secondary sort">2</span>}</button></th>
}

export default function Alerts() {
  const [searchParams, setSearchParams] = useSearchParams()
  const sort = Object.fromEntries(Object.entries(DEFAULT_SORT).map(([key, fallback]) => [key, searchParams.get(key) ?? fallback]))
  const [filters, setFilters] = useState({ query: '', status: '', category: '', department: '', tactic: '' })
  const { data, loading, error, reload } = useLoad(() => api.alerts({ limit: LIMIT, ...sort, ...(filters.status ? { status: filters.status } : {}), ...(filters.category ? { category: filters.category } : {}), ...(filters.department ? { department: filters.department } : {}) }), [sort.sort_by, sort.sort_dir, sort.then_by, sort.then_dir, filters.status, filters.category, filters.department])
  const [page, setPage] = useState(1)
  const [departments, setDepartments] = useState([])
  const alerts = data || []
  const tactics = useMemo(() => [...new Map((data || []).flatMap(a => alertTechniques(a)
    .flatMap(t => t.tactics || [])).map(t => [t.id, t])).values()].sort((a, b) => a.name.localeCompare(b.name)), [data])
  useEffect(() => { if (data) setDepartments(previous => [...new Set([...previous, ...data.map(a => a.department).filter(Boolean)])].sort()) }, [data])
  useEffect(() => { setPage(1) }, [sort.sort_by, sort.sort_dir, sort.then_by, sort.then_dir])
  const changeSort = updates => {
    setSearchParams(previous => { const next = new URLSearchParams(previous); Object.entries({ ...sort, ...updates }).forEach(([key, value]) => next.set(key, value)); return next })
    setPage(1)
  }
  const counts = useMemo(() => ({ open: alerts.filter(a => a.status === 'open').length, investigating: alerts.filter(a => a.status === 'under_investigation').length, closed: alerts.filter(a => a.status === 'closed').length, critical: alerts.filter(a => a.category === 'Critical').length }), [data])
  const filtered = useMemo(() => {
    const search = filters.query.trim().toLowerCase()
    return (data || []).filter(a => {
      const techniques = alertTechniques(a)
      return (!filters.status || a.status === filters.status) && (!filters.category || a.category === filters.category)
        && (!filters.department || a.department === filters.department)
        && (!filters.tactic || techniques.some(t => (t.tactics || []).some(tactic => tactic.id === filters.tactic)))
        && (!search || [a.id, a.user_id, a.department, ...(a.breakdown || []).map(b => b.name),
          ...techniques.flatMap(t => [t.id, t.name, ...(t.tactics || []).map(tactic => tactic.name)])].join(' ').toLowerCase().includes(search))
    })
  }, [data, filters])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages)
  const start = (currentPage - 1) * PAGE_SIZE
  const visible = filtered.slice(start, start + PAGE_SIZE)
  const hasFilters = Object.values(filters).some(Boolean)
  const updateFilter = (key, value) => { setFilters(previous => ({ ...previous, [key]: value })); setPage(1) }
  const clearFilters = () => { setFilters({ query: '', status: '', category: '', department: '', tactic: '' }); setPage(1) }

  return <div className="dash-page alerts-page">
    <header className="dash-header">
      <div><h1>Alerts</h1><p className="text-muted mb-0">Detection evidence and investigation workload</p></div>
      <button className="btn btn-sm btn-outline-light d-inline-flex align-items-center gap-2" onClick={reload} disabled={loading}><RefreshCw size={15} aria-hidden="true" />Refresh</button>
    </header>
    {error && <button className="btn btn-sm btn-outline-light align-self-start" onClick={() => changeSort(DEFAULT_SORT)}>Reset sort</button>}
    <Status loading={loading} error={error}>
      {data && <>
        <section className="dash-metrics" aria-label="Loaded alert summary">
          {[
            ['Open alerts', counts.open, 'Awaiting investigation', Bell, 'dash-metric-warning'],
            ['Under investigation', counts.investigating, 'Active cases', Search, ''],
            ['Critical alerts', counts.critical, 'Across all case statuses', ShieldAlert, 'dash-metric-danger'],
            ['Closed cases', counts.closed, 'Completed investigations', CheckCheck, ''],
          ].map(([label, count, detail, Icon, tone]) => <article key={label} className={`card dash-metric ${tone}`}><div className="dash-metric-label"><span>{label}</span><Icon size={19} aria-hidden="true" /></div><strong className="dash-metric-value">{count.toLocaleString()}</strong><span className="text-muted small">{detail}</span></article>)}
        </section>
        <section className="card dash-panel">
          <div className="dash-panel-heading"><div><h2>Alert queue</h2><p>{alerts.length.toLocaleString()} loaded alerts</p></div>
          </div>
          <div className="dash-filters alerts-filters">
            <select className="form-select form-select-sm" aria-label="ATT&CK tactic" value={filters.tactic} onChange={e => updateFilter('tactic', e.target.value)}><option value="">All ATT&CK tactics</option>{tactics.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
            <div className="dash-search"><Search size={17} aria-hidden="true" /><input className="form-control form-control-sm" aria-label="Search alerts" placeholder="Search alert, user or indicator" value={filters.query} onChange={e => updateFilter('query', e.target.value)} /></div>
            <select className="form-select form-select-sm" aria-label="Risk level" value={filters.category} onChange={e => updateFilter('category', e.target.value)}><option value="">All risk levels</option>{['Low', 'Medium', 'High', 'Critical'].map(c => <option key={c}>{c}</option>)}</select>
            <select className="form-select form-select-sm" aria-label="Case status" value={filters.status} onChange={e => updateFilter('status', e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
            <select className="form-select form-select-sm" aria-label="Department" value={filters.department} onChange={e => updateFilter('department', e.target.value)}><option value="">All departments</option>{departments.map(d => <option key={d}>{d}</option>)}</select>
            {hasFilters && <button className="btn btn-link btn-sm" onClick={clearFilters}>Clear filters</button>}
          </div>
          <div className="alerts-sort-panel" aria-label="Alert sorting">
            <div className="alerts-sort"><label htmlFor="primary-sort">Sort by</label><select id="primary-sort" className="form-select form-select-sm" value={sort.sort_by} onChange={e => changeSort({ sort_by: e.target.value })}>{Object.entries(SORT_COLUMNS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button className="btn btn-sm btn-outline-secondary telemetry-command" aria-label={`Primary sort direction: ${sort.sort_dir === 'asc' ? 'ascending' : 'descending'}`} title="Toggle primary sort direction" onClick={() => changeSort({ sort_dir: sort.sort_dir === 'asc' ? 'desc' : 'asc' })}>{sort.sort_dir === 'asc' ? <ArrowUp size={15} /> : <ArrowDown size={15} />}{sort.sort_dir === 'asc' ? 'Asc' : 'Desc'}</button></div>
            <div className="alerts-sort"><label htmlFor="secondary-sort">Then by</label><select id="secondary-sort" className="form-select form-select-sm" value={sort.then_by} onChange={e => changeSort({ then_by: e.target.value })}><option value="">None</option>{Object.entries(SORT_COLUMNS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select><button className="btn btn-sm btn-outline-secondary telemetry-command" disabled={!sort.then_by} aria-label={`Secondary sort direction: ${sort.then_dir === 'asc' ? 'ascending' : 'descending'}`} title="Toggle secondary sort direction" onClick={() => changeSort({ then_dir: sort.then_dir === 'asc' ? 'desc' : 'asc' })}>{sort.then_dir === 'asc' ? <ArrowUp size={15} /> : <ArrowDown size={15} />}{sort.then_dir === 'asc' ? 'Asc' : 'Desc'}</button></div>
            <button className="btn btn-sm btn-outline-secondary telemetry-command" onClick={() => changeSort(DEFAULT_SORT)}><RotateCcw size={14} aria-hidden="true" />Reset sort</button><span className="alerts-sort-count" aria-live="polite">Showing {filtered.length.toLocaleString()} alerts</span>
          </div>
          {alerts.length >= LIMIT && <p className="alerts-limit" role="status">Summary and search cover the first {LIMIT.toLocaleString()} alerts in the selected sort order.</p>}
          <div className="table-responsive"><table className="table table-hover align-middle mb-0 alerts-table">
            <thead><tr>{[['id', 'Alert'], ['user_id', 'User'], ['department', 'Department'], ['peak_score', 'Peak score'], ['category', 'Risk level'], ['status', 'Case status'], ['start_time', 'Started (UTC)'], ['indicator_count', 'Indicators']].map(([column, label]) => <SortHeader key={column} column={column} label={label} sort={sort} onSort={changeSort} />)}<th scope="col"><span className="visually-hidden">Investigation</span></th></tr></thead>
            <tbody>{visible.map(a => <tr key={a.id}>
              <td><Link className="fw-semibold" to={`/alerts/${a.id}`}>Alert #{a.id}</Link></td><td><Link to={`/users/${encodeURIComponent(a.user_id)}`}>{a.user_id}</Link></td>
              <td>{a.department || 'Unassigned'}</td>
              <td><ScoreBar score={a.peak_score} category={a.category} /></td><td><CategoryBadge category={a.category} /></td>
              <td><span className={`alerts-status alerts-status-${a.status}`}>{STATUS_LABEL[a.status] || a.status}</span></td>
              <td className="alerts-date">{fmt(a.start_time)}</td>
              <td className="alerts-indicators">{(a.breakdown || []).length ? <><span className="text-muted">{a.breakdown.length} indicators</span><ul>{a.breakdown.slice(0, 3).map((b, i) => <li key={i}>{b.name}</li>)}</ul></> : <span className="text-muted">No indicators</span>}{a.breakdown?.length > 3 && <span className="text-muted">+{a.breakdown.length - 3} more</span>}<AttackChips techniques={alertTechniques(a)} /></td>
              <td><Link className="dash-investigate" to={`/alerts/${a.id}`} aria-label={`Investigate alert ${a.id}`} title={`Investigate alert ${a.id}`}><ArrowRight size={18} aria-hidden="true" /></Link></td>
            </tr>)}</tbody>
          </table></div>
          {!filtered.length && <div className="dash-empty"><Bell size={25} aria-hidden="true" /><p className="mt-2 mb-2">{hasFilters ? 'No alerts match these filters.' : 'No alerts recorded.'}</p>{hasFilters && <button className="btn btn-sm btn-outline-primary" onClick={clearFilters}>Clear filters</button>}</div>}
          <footer className="alerts-pagination">
            <span aria-live="polite">{filtered.length ? `${start + 1}-${Math.min(start + PAGE_SIZE, filtered.length)} of ${filtered.length.toLocaleString()} alerts` : '0 alerts'}</span>
            <div><button className="btn btn-sm btn-outline-secondary" aria-label="Previous page" title="Previous page" disabled={currentPage === 1} onClick={() => setPage(currentPage - 1)}><ChevronLeft size={17} /></button><span>Page {currentPage} of {pages}</span><button className="btn btn-sm btn-outline-secondary" aria-label="Next page" title="Next page" disabled={currentPage === pages} onClick={() => setPage(currentPage + 1)}><ChevronRight size={17} /></button></div>
          </footer>
        </section>
        <p className="dash-disclaimer"><ShieldAlert size={15} aria-hidden="true" />{DISCLAIMER}</p>
      </>}
    </Status>
  </div>
}
