import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { CategoryBadge, Status, fmt, useLoad } from '../components.jsx'
import { DIRECTORY_TEMPLATE, EmployeeDialog } from '../employees.jsx'
import { UserChart } from '../userCharts.jsx'

export default function Users() {
  const { auth } = useAuth()
  const admin = auth.role === 'admin'
  const navigate = useNavigate()
  const users = useLoad(() => api.users())
  const stats = useLoad(() => api.usersStats())
  const directory = useLoad(() => admin ? api.adminEmployees() : Promise.resolve(null), [admin])
  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('')
  const [risk, setRisk] = useState('')
  const [missing, setMissing] = useState(false)
  const [add, setAdd] = useState(false)
  const [importing, setImporting] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const refresh = () => { users.reload(); stats.reload(); directory.reload() }
  const rows = [...(users.data || [])]
  if (admin) for (const profile of directory.data?.profiles || []) {
    if (!rows.some(row => row.user_id === profile.user_id)) rows.push({ user_id: profile.user_id, department: '', risk_category: 'Low', open_case_count: 0, has_profile: true, baseline_status: 'pending', pre_registered: true })
  }
  const filtered = rows.filter(row => row.user_id.toLowerCase().includes(search.trim().toLowerCase()) && (!department || row.department === department) && (!risk || row.risk_category === risk) && (!missing || !row.has_profile))
  const importFile = async event => {
    const file = event.target.files[0]
    if (!file) return
    setImporting(true); setError(null); setResult(null)
    try { setResult(await api.importEmployees(file)); refresh() } catch (e) { setError(e.message) } finally { setImporting(false); event.target.value = '' }
  }
  return <div className="dash-page">
    <header className="dash-header"><div><h1>Users</h1><p className="text-muted">Monitored identities, activity and case history</p></div>{admin && <div className="d-flex gap-2 flex-wrap"><button className="btn btn-primary" onClick={() => setAdd(true)}>Add employee profile</button><label className="btn btn-outline-primary mb-0">{importing ? 'Importing…' : 'Import directory (CSV)'}<input type="file" accept=".csv,text/csv" className="visually-hidden" aria-label="Import directory (CSV)" disabled={importing} onChange={importFile} /></label><a className="btn btn-link" download="employee-directory-template.csv" href={`data:text/csv;charset=utf-8,${encodeURIComponent(DIRECTORY_TEMPLATE)}`}>Download CSV template</a></div>}</header>
    <Status loading={stats.loading} error={stats.error}>{stats.data && <div className="users-chart-grid"><UserChart title="Users by department" values={stats.data.users_by_department} /><UserChart title="Risk distribution" values={stats.data.risk_distribution} kind="doughnut" /><UserChart title="Baseline status" values={stats.data.baseline_status_counts} /><UserChart title="Activity volume by department" values={stats.data.event_volume_by_department} /></div>}</Status>
    {admin && <Status loading={directory.loading} error={directory.error}>{directory.data && <button className="dash-panel p-3 my-3 text-start w-100" aria-pressed={missing} onClick={() => setMissing(!missing)}><strong>Profile completeness: {directory.data.stats.completeness_percent}%</strong><span className="d-block">{directory.data.stats.missing_count} users missing contact details</span><span className="small text-muted">{missing ? 'Show all users' : 'Show users without a profile'}</span></button>}</Status>}
    {error && <div role="alert" className="alert alert-danger">{error}</div>}
    {result && <div role="status" className="alert alert-info">Accepted: {result.accepted}. Rejected: {result.rejected}.{result.errors.map(e => <div key={e.row}>Row {e.row}: {e.message}</div>)}</div>}
    <section className="dash-panel p-3 mt-3"><div className="row g-2 mb-3"><label className="col-md-5">Search user ID<input className="form-control" value={search} onChange={e => setSearch(e.target.value)} /></label><label className="col-md-4">Department<select className="form-select" value={department} onChange={e => setDepartment(e.target.value)}><option value="">All departments</option>{[...new Set(rows.map(r => r.department).filter(Boolean))].sort().map(d => <option key={d}>{d}</option>)}</select></label><label className="col-md-3">Risk<select className="form-select" value={risk} onChange={e => setRisk(e.target.value)}><option value="">All risk levels</option>{['Low', 'Medium', 'High', 'Critical'].map(c => <option key={c}>{c}</option>)}</select></label></div>
      <Status loading={users.loading} error={users.error}><div className="table-responsive"><table className="table table-hover align-middle"><thead><tr><th>User ID</th><th>Department</th><th>Current risk</th><th>Open cases</th><th>Last activity</th><th>Baseline</th>{admin && <th>Profile</th>}</tr></thead><tbody>{filtered.map(row => <tr key={row.user_id} className="user-tile" tabIndex={0} aria-label={`View user ${row.user_id}`} onClick={e => { if (!e.target.closest('a')) navigate(`/users/${encodeURIComponent(row.user_id)}`) }} onKeyDown={e => { if (e.target === e.currentTarget && ['Enter', ' '].includes(e.key)) { e.preventDefault(); navigate(`/users/${encodeURIComponent(row.user_id)}`) } }}><td><Link to={`/users/${encodeURIComponent(row.user_id)}`}>{row.user_id}</Link></td><td>{row.department || 'No activity yet'}</td><td>{row.pre_registered ? 'No activity yet' : <CategoryBadge category={row.risk_category} />}</td><td>{row.open_case_count ?? row.open_alerts}</td><td>{row.last_seen ? fmt(row.last_seen) : 'No activity yet'}</td><td>{row.baseline_status}</td>{admin && <td><span className={`badge ${row.has_profile ? 'bg-success' : 'bg-secondary'}`}>{row.has_profile ? 'Present' : 'Missing'}</span></td>}</tr>)}</tbody></table>{!filtered.length && <p className="text-muted">No users match these filters.</p>}</div></Status>
    </section>
    {add && <EmployeeDialog suggestions={directory.data?.missing_profiles} departments={Object.fromEntries((users.data || []).map(u => [u.user_id, u.department]))} onCancel={() => setAdd(false)} onComplete={() => { setAdd(false); refresh() }} />}
  </div>
}
