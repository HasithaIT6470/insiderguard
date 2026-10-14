import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Bell, CheckCheck, ChevronLeft, ChevronRight, RefreshCw, Search, ShieldAlert } from 'lucide-react'
import { api } from '../api'
import { CategoryBadge, DISCLAIMER, ScoreBar, Status, STATUS_LABEL, fmt, useLoad } from '../components.jsx'

const PAGE_SIZE = 20
const LIMIT = 1000

export default function Alerts() {
  const { data, loading, error, reload } = useLoad(() => api.alerts({ limit: LIMIT }))
  const [filters, setFilters] = useState({ query: '', status: '', category: '', department: '' })
  const [sort, setSort] = useState('risk')
  const [page, setPage] = useState(1)
  const alerts = data || []
  const departments = useMemo(() => [...new Set((data || []).map(a => a.department).filter(Boolean))].sort(), [data])
  const counts = useMemo(() => ({ open: alerts.filter(a => a.status === 'open').length, investigating: alerts.filter(a => a.status === 'under_investigation').length, closed: alerts.filter(a => a.status === 'closed').length, critical: alerts.filter(a => a.category === 'Critical').length }), [data])
  const filtered = useMemo(() => {
    const search = filters.query.trim().toLowerCase()
    return (data || []).filter(a => (!filters.status || a.status === filters.status) && (!filters.category || a.category === filters.category) && (!filters.department || a.department === filters.department) && (!search || [a.id, a.user_id, a.department, ...(a.breakdown || []).map(b => b.name)].join(' ').toLowerCase().includes(search)))
      .sort((a, b) => sort === 'newest' ? new Date(b.start_time) - new Date(a.start_time) : sort === 'oldest' ? new Date(a.start_time) - new Date(b.start_time) : b.peak_score - a.peak_score || new Date(b.start_time) - new Date(a.start_time))
  }, [data, filters, sort])
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, pages)
  const start = (currentPage - 1) * PAGE_SIZE
  const visible = filtered.slice(start, start + PAGE_SIZE)
  const hasFilters = Object.values(filters).some(Boolean)
  const updateFilter = (key, value) => { setFilters(previous => ({ ...previous, [key]: value })); setPage(1) }
  const clearFilters = () => { setFilters({ query: '', status: '', category: '', department: '' }); setPage(1) }

  return <div className="dash-page alerts-page">
    <header className="dash-header">
      <div><h1>Alerts</h1><p className="text-muted mb-0">Detection evidence and investigation workload</p></div>
      <button className="btn btn-sm btn-outline-light d-inline-flex align-items-center gap-2" onClick={reload} disabled={loading}><RefreshCw size={15} aria-hidden="true" />Refresh</button>
    </header>
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
            <div className="alerts-sort"><label htmlFor="alert-sort">Sort by</label><select id="alert-sort" className="form-select form-select-sm" value={sort} onChange={e => { setSort(e.target.value); setPage(1) }}><option value="risk">Highest risk</option><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></div>
          </div>
          <div className="dash-filters alerts-filters">
            <div className="dash-search"><Search size={17} aria-hidden="true" /><input className="form-control form-control-sm" aria-label="Search alerts" placeholder="Search alert, user or indicator" value={filters.query} onChange={e => updateFilter('query', e.target.value)} /></div>
            <select className="form-select form-select-sm" aria-label="Risk level" value={filters.category} onChange={e => updateFilter('category', e.target.value)}><option value="">All risk levels</option>{['Low', 'Medium', 'High', 'Critical'].map(c => <option key={c}>{c}</option>)}</select>
            <select className="form-select form-select-sm" aria-label="Case status" value={filters.status} onChange={e => updateFilter('status', e.target.value)}><option value="">All statuses</option>{Object.entries(STATUS_LABEL).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
            <select className="form-select form-select-sm" aria-label="Department" value={filters.department} onChange={e => updateFilter('department', e.target.value)}><option value="">All departments</option>{departments.map(d => <option key={d}>{d}</option>)}</select>
            {hasFilters && <button className="btn btn-link btn-sm" onClick={clearFilters}>Clear filters</button>}
          </div>
          {alerts.length >= LIMIT && <p className="alerts-limit" role="status">Summary and filters cover the {LIMIT.toLocaleString()} highest-ranked alerts returned by the API.</p>}
          <div className="table-responsive"><table className="table table-hover align-middle mb-0 alerts-table">
            <thead><tr><th scope="col">Alert / user</th><th scope="col">Department</th><th scope="col">Peak risk</th><th scope="col">Case status</th><th scope="col">Started (UTC)</th><th scope="col">Top indicators</th><th scope="col"><span className="visually-hidden">Investigation</span></th></tr></thead>
            <tbody>{visible.map(a => <tr key={a.id}>
              <td><Link className="fw-semibold" to={`/alerts/${a.id}`}>Alert #{a.id}</Link><Link className="alerts-user-link" to={`/users/${encodeURIComponent(a.user_id)}`}>{a.user_id}</Link></td>
              <td>{a.department || 'Unassigned'}</td>
              <td><div className="alerts-score"><CategoryBadge category={a.category} /><ScoreBar score={a.peak_score} category={a.category} /></div></td>
              <td><span className={`alerts-status alerts-status-${a.status}`}>{STATUS_LABEL[a.status] || a.status}</span></td>
              <td className="alerts-date">{fmt(a.start_time)}</td>
              <td className="alerts-indicators">{(a.breakdown || []).length ? <ul>{a.breakdown.slice(0, 3).map((b, i) => <li key={i}>{b.name}</li>)}</ul> : <span className="text-muted">No indicators</span>}{a.breakdown?.length > 3 && <span className="text-muted">+{a.breakdown.length - 3} more</span>}</td>
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
