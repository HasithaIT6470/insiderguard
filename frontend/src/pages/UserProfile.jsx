import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { CategoryBadge, OutcomeBadge, Status, caseStatusLabel, fmt, useLoad } from '../components.jsx'
import { CaseDialog } from '../cases.jsx'
import { EMPLOYEE_FIELDS, EmployeeDialog, EmployeeForm, employmentLabel } from '../employees.jsx'
import { UserChart } from '../userCharts.jsx'

function ContactLog({ userId, hasProfile }) {
  const log = useLoad(() => hasProfile ? api.employeeContacts(userId) : Promise.resolve([]), [userId, hasProfile])
  const [adding, setAdding] = useState(false)
  const [method, setMethod] = useState('email')
  const [summary, setSummary] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const submit = async event => {
    event.preventDefault(); setBusy(true); setError(null)
    try { await api.addEmployeeContact(userId, { method, summary }); setAdding(false); setSummary(''); log.reload() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <><h2 className="h5">Contact log</h2>{hasProfile ? <button className="btn btn-primary mb-3" onClick={() => setAdding(true)}>Add contact record</button> : <p>Create a profile before recording contact.</p>}<Status loading={log.loading} error={log.error}>{log.data?.length ? log.data.map(row => <article key={row.id} className="border-bottom py-3"><strong>{employmentLabel(row.method)}</strong> · {row.contacted_by} · {fmt(row.created_at)}<p className="mb-0 text-break">{row.summary}</p></article>) : <p className="text-muted">No contact records yet.</p>}</Status>
    {adding && <CaseDialog title="Add contact record" onClose={() => setAdding(false)} busy={busy}><form onSubmit={submit}><label className="d-block mb-3">Method<select className="form-select" value={method} onChange={e => setMethod(e.target.value)}>{['email', 'phone', 'in_person', 'other'].map(m => <option key={m} value={m}>{employmentLabel(m)}</option>)}</select></label><label className="d-block">Summary<textarea className="form-control" value={summary} maxLength={4000} required onChange={e => setSummary(e.target.value)} /></label>{error && <p role="alert" className="alert alert-danger">{error}</p>}<div className="d-flex justify-content-end gap-2 mt-3"><button type="button" className="btn btn-outline-secondary" disabled={busy} onClick={() => setAdding(false)}>Cancel</button><button className="btn btn-primary" disabled={busy || !summary.trim()}>Save contact record</button></div></form></CaseDialog>}
  </>
}

function PersonalInformation({ userId, department, onUpdate }) {
  const profile = useLoad(() => api.adminEmployee(userId).catch(e => { if (e.status === 404) return null; throw e }), [userId])
  const [edit, setEdit] = useState(false)
  const [offboard, setOffboard] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const complete = () => { setEdit(false); profile.reload(); onUpdate() }
  const confirmOffboard = async () => {
    setBusy(true); setError(null)
    try { await api.offboardEmployee(userId); setOffboard(false); complete() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <Status loading={profile.loading} error={profile.error}>{profile.data ? <><div className="d-flex gap-2 justify-content-between"><h2 className="h5">Personal information</h2><div className="d-flex gap-2"><button className="btn btn-outline-primary" onClick={() => setEdit(true)}>Edit</button><button className="btn btn-outline-danger" disabled={profile.data.employment_status === 'offboarded'} onClick={() => setOffboard(true)}>Offboard</button></div></div><p className="text-muted">Department (from logs): {department || 'No activity yet'}</p><dl className="row mt-3">{EMPLOYEE_FIELDS.map(([key, label]) => <div className="col-md-6 mb-3" key={key}><dt>{label}</dt><dd className="text-break employee-value">{profile.data[key] ? key === 'employment_status' ? employmentLabel(profile.data[key]) : profile.data[key] : 'Not recorded'}</dd></div>)}</dl></> : <><h2 className="h5">No profile yet</h2><EmployeeForm userId={userId} department={department} onComplete={complete} onCancel={onUpdate} /></>}
    {edit && <EmployeeDialog profile={profile.data} department={department} onCancel={() => setEdit(false)} onComplete={complete} />}
    {offboard && <CaseDialog title="Offboard employee" busy={busy} onClose={() => setOffboard(false)}><p>Mark {userId} as offboarded? The profile and contact history will be retained.</p>{error && <p role="alert" className="alert alert-danger">{error}</p>}<div className="d-flex justify-content-end gap-2"><button className="btn btn-outline-secondary" disabled={busy} onClick={() => setOffboard(false)}>Cancel</button><button className="btn btn-danger" disabled={busy} onClick={confirmOffboard}>Confirm offboarding</button></div></CaseDialog>}
  </Status>
}

function Activity({ data }) {
  const max = Math.max(1, ...data.activity_heatmap.flat())
  const metricLabels = ['Daily downloaded MB', 'Daily files accessed']
  const metrics = ['download_mb', 'file_access'].map(k => data.baseline_vs_recent[k])
  return <><div className="users-chart-grid two"><UserChart title="Daily maximum risk" kind="line" values={Object.fromEntries(data.risk_trend.map(p => [p.date, p.score]))} /><UserChart title="Event types (all activity)" values={data.event_type_breakdown} kind="doughnut" /></div>
    <section className="dash-panel p-3 my-3"><h2 className="h6">Activity by weekday and hour (UTC)</h2><p className="small text-muted">Last 30 dataset days. Darker cells indicate more events. {fmt(data.activity_window.start)} – {fmt(data.activity_window.end)}</p><div className="table-responsive"><div className="activity-heatmap" role="img" aria-label="Activity heatmap, Monday to Sunday, hours 0 to 23 UTC"><span />{Array.from({ length: 24 }, (_, hour) => <span key={hour}>{hour}</span>)}{['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((day, weekday) => <div className="heatmap-row" key={day}><span>{day}</span>{data.activity_heatmap[weekday].map((count, hour) => <span className="heatmap-cell" key={hour} title={`${day} ${hour}:00 UTC: ${count} events`} aria-label={`${day} ${hour}:00 UTC: ${count} events`} style={{ backgroundColor: `rgba(37,99,235,${count ? 0.18 + 0.82 * count / max : 0.04})` }} />)}</div>)}</div></div></section>
    <UserChart title="Baseline versus recent daily activity" labels={metricLabels} datasets={[{ label: 'Baseline mean', data: metrics.map(m => m.baseline_mean), backgroundColor: '#8290a5' }, { label: 'Recent daily average', data: metrics.map(m => m.recent_daily_average), backgroundColor: '#2563eb' }]} /><p className="small text-muted mt-2">Recent: {data.recent_window.start} to {data.recent_window.end}, including days with no activity. Baseline standard deviation: downloads {metrics[0].baseline_std ?? 'unavailable'} MB; files {metrics[1].baseline_std ?? 'unavailable'}. Missing baseline values are unavailable.</p>
    <h2 className="h5 mt-4">Devices</h2>{data.devices.length ? <div className="table-responsive"><table className="table"><thead><tr><th>Device</th><th>First seen</th><th>Events</th></tr></thead><tbody>{data.devices.map(d => <tr key={d.name}><td>{d.name}</td><td>{fmt(d.first_seen)}</td><td>{d.count}</td></tr>)}</tbody></table></div> : <p className="text-muted">No devices recorded.</p>}
  </>
}

export default function UserProfile() {
  const { id } = useParams()
  const { auth } = useAuth()
  const admin = auth.role === 'admin'
  const overview = useLoad(() => api.userOverview(id), [id])
  const [tab, setTab] = useState('Activity and risk')
  const tabs = ['Activity and risk', 'Case history', 'Analyst notes', 'Escalations', ...(admin ? ['Personal information', 'Contact log'] : [])]
  const data = overview.data
  return <div className="dash-page"><Link to="/users">Users</Link><Status loading={overview.loading} error={overview.error}>{data && <><header className="dash-header mt-2"><div><h1>{data.user_id}</h1><p className="mb-1">{data.department || 'No activity yet'} · <CategoryBadge category={data.current_risk.category} /> <span className="ms-2">Score {data.current_risk.score.toFixed(0)}</span></p><p className="text-muted">Baseline: {data.baseline_status} · Last seen: {data.last_seen ? fmt(data.last_seen) : 'No activity yet'}</p></div></header>
    {!admin && <p className="small text-muted">Contact details are restricted to administrators</p>}
    <div className="nav nav-tabs mb-3" role="tablist" aria-label="User profile sections">{tabs.map(name => <button key={name} className={`nav-link ${tab === name ? 'active' : ''}`} role="tab" aria-selected={tab === name} id={`tab-${name.replaceAll(' ', '-')}`} aria-controls="user-tab-panel" onClick={() => setTab(name)}>{name}</button>)}</div>
    <div className="dash-panel p-3" role="tabpanel" id="user-tab-panel" aria-labelledby={`tab-${tab.replaceAll(' ', '-')}`}>
      {tab === 'Activity and risk' && <Activity data={data} />}
      {tab === 'Case history' && <><h2 className="h5">Case history</h2>{data.case_history.length ? <div className="table-responsive"><table className="table align-middle"><thead><tr><th>Case</th><th>Severity</th><th>Peak score</th><th>Status</th><th>Owner</th><th>Outcome</th></tr></thead><tbody>{data.case_history.map(a => <tr key={a.id}><td><Link to={`/alerts/${a.id}`}>Case #{a.id}</Link></td><td><CategoryBadge category={a.category} /></td><td>{a.peak_score}</td><td>{caseStatusLabel(a)}</td><td>{a.owner || 'Unassigned'}</td><td>{a.status === 'closed' ? <OutcomeBadge outcome={a.outcome} /> : '—'}</td></tr>)}</tbody></table></div> : <p className="text-muted">No cases for this user.</p>}</>}
      {tab === 'Analyst notes' && <><h2 className="h5">Analyst notes</h2>{data.case_notes.length ? data.case_notes.map(n => <article key={n.id} className="border-bottom py-3"><Link to={`/alerts/${n.alert_id}`}>Case #{n.alert_id}</Link> · {n.author} · {fmt(n.created_at)}<p className="employee-value text-break">{n.note}</p></article>) : <p className="text-muted">No analyst notes yet.</p>}</>}
      {tab === 'Escalations' && <><h2 className="h5">Escalations</h2><p className="text-muted">No escalations yet.</p></>}
      {admin && tab === 'Personal information' && <PersonalInformation userId={id} department={data.department} onUpdate={overview.reload} />}
      {admin && tab === 'Contact log' && <ContactLog userId={id} hasProfile={data.has_profile} />}
    </div></>}</Status></div>
}
