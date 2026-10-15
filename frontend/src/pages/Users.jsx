import { useState } from 'react'
import { OriginLink as Link, useOriginNavigate as useNavigate } from '../navigation.jsx'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { CategoryBadge, Status, fmt, useLoad } from '../components.jsx'
import { EmployeeDialog } from '../employees.jsx'
import { CaseDialog } from '../cases.jsx'

export default function Users() {
  const { auth } = useAuth()
  const admin = auth.role === 'admin'
  const navigate = useNavigate()
  const users = useLoad(() => api.users())
  const directory = useLoad(() => admin ? api.adminEmployees() : Promise.resolve(null), [admin])
  const [search, setSearch] = useState('')
  const [department, setDepartment] = useState('')
  const [risk, setRisk] = useState('')
  const [missing, setMissing] = useState(false)
  const [add, setAdd] = useState(false)
  const [removing, setRemoving] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const refresh = () => { users.reload(); directory.reload() }
  const rows = [...(users.data || [])]
  if (admin) for (const profile of directory.data?.profiles || []) {
    if (!rows.some(row => row.user_id === profile.user_id)) rows.push({ user_id: profile.user_id, department: '', risk_category: 'Low', open_case_count: 0, has_profile: true, baseline_status: 'pending', pre_registered: true })
  }
  const filtered = rows.filter(row => row.user_id.toLowerCase().includes(search.trim().toLowerCase()) && (!department || row.department === department) && (!risk || row.risk_category === risk) && (!missing || !row.has_profile))
  const remove = async () => {
    setBusy(true); setError(null)
    try { await api.removeUser(removing); setRemoving(null); refresh() }
    catch (e) { setError(e.message) }
    finally { setBusy(false) }
  }
  return <div className="dash-page">
    <header className="dash-header"><div><h1>Users</h1><p className="text-muted">Monitored identities, activity and case history</p></div>{admin && <div className="d-flex gap-2 flex-wrap"><button className="btn btn-primary" onClick={() => setAdd(true)}>Add employee profile</button></div>}</header>
    {admin && <Status loading={directory.loading} error={directory.error}>{directory.data && <button className="dash-panel p-3 my-3 text-start w-100" aria-pressed={missing} onClick={() => setMissing(!missing)}><strong>Profile completeness: {directory.data.stats.completeness_percent}%</strong><span className="d-block">{directory.data.stats.missing_count} users missing contact details</span><span className="small text-muted">{missing ? 'Show all users' : 'Show users without a profile'}</span></button>}</Status>}
    {error && !removing && <div role="alert" className="alert alert-danger">{error}</div>}
    <section className="dash-panel p-3 mt-3"><div className="row g-2 mb-3"><label className="col-md-5">Search user ID<input className="form-control" value={search} onChange={e => setSearch(e.target.value)} /></label><label className="col-md-4">Department<select className="form-select" value={department} onChange={e => setDepartment(e.target.value)}><option value="">All departments</option>{[...new Set(rows.map(r => r.department).filter(Boolean))].sort().map(d => <option key={d}>{d}</option>)}</select></label><label className="col-md-3">Risk<select className="form-select" value={risk} onChange={e => setRisk(e.target.value)}><option value="">All risk levels</option>{['Low', 'Medium', 'High', 'Critical'].map(c => <option key={c}>{c}</option>)}</select></label></div>
      <Status loading={users.loading} error={users.error}><div className="table-responsive"><table className="table table-hover align-middle"><thead><tr><th>User ID</th><th>Department</th><th>Current risk</th><th>Open cases</th><th>Last activity</th><th>Baseline</th>{admin && <><th>Profile</th><th>Actions</th></>}</tr></thead><tbody>{filtered.map(row => <tr key={row.user_id} className="user-tile" tabIndex={0} aria-label={`View user ${row.user_id}`} onClick={e => { if (!e.target.closest('a, button')) navigate(`/users/${encodeURIComponent(row.user_id)}`) }} onKeyDown={e => { if (e.target === e.currentTarget && ['Enter', ' '].includes(e.key)) { e.preventDefault(); navigate(`/users/${encodeURIComponent(row.user_id)}`) } }}><td><Link to={`/users/${encodeURIComponent(row.user_id)}`}>{row.user_id}</Link></td><td>{row.department || 'No activity yet'}</td><td>{row.pre_registered ? 'No activity yet' : <CategoryBadge category={row.risk_category} />}</td><td>{row.open_case_count ?? row.open_alerts}</td><td>{row.last_seen ? fmt(row.last_seen) : 'No activity yet'}</td><td>{row.baseline_status}</td>{admin && <><td><span className={`badge ${row.has_profile ? 'bg-success' : 'bg-secondary'}`}>{row.has_profile ? 'Present' : 'Missing'}</span></td><td><button className="btn btn-sm btn-outline-danger" aria-label={`Remove user ${row.user_id}`} onClick={() => { setError(null); setRemoving(row.user_id) }}>Remove user</button></td></>}</tr>)}</tbody></table>{!filtered.length && <p className="text-muted">No users match these filters.</p>}</div></Status>
    </section>
    {removing && <CaseDialog title={`Remove user ${removing}`} onClose={() => { setRemoving(null); setError(null) }} busy={busy}>
      <p>Remove {removing} from the Users directory? Existing activity and case history will be retained.</p>
      {error && <div role="alert" className="alert alert-danger">{error}</div>}
      <div className="d-flex gap-2"><button className="btn btn-danger" disabled={busy} onClick={remove}>{busy ? 'Removing...' : 'Confirm removal'}</button><button className="btn btn-secondary" disabled={busy} onClick={() => { setRemoving(null); setError(null) }}>Cancel</button></div>
    </CaseDialog>}
    {add && <EmployeeDialog suggestions={directory.data?.missing_profiles} departments={Object.fromEntries((users.data || []).map(u => [u.user_id, u.department]))} onCancel={() => setAdd(false)} onComplete={() => { setAdd(false); refresh() }} />}
  </div>
}
