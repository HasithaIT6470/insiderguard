import { useState } from 'react'
import { Bell, Check, CheckCheck, Mail, MessageSquare, ShieldAlert, Trash2 } from 'lucide-react'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { fmt, Status, useLoad } from '../components.jsx'
import { useOriginNavigate } from '../navigation.jsx'

const LIMIT = 50
export function dayLabel(timestamp, now = new Date()) {
  const date = new Date(timestamp.endsWith('Z') ? timestamp : timestamp + 'Z')
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
  const day = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  return day.getTime() === today.getTime() ? 'Today' : day.getTime() === yesterday.getTime() ? 'Yesterday' : date.toLocaleDateString(undefined, { dateStyle: 'medium' })
}
export function relativeTime(timestamp, now = new Date()) {
  const seconds = Math.max(0, (now - new Date(timestamp.endsWith('Z') ? timestamp : timestamp + 'Z')) / 1000)
  return seconds < 60 ? 'Just now' : seconds < 3600 ? `${Math.floor(seconds / 60)} min ago` : seconds < 86400 ? `${Math.floor(seconds / 3600)} h ago` : `${Math.floor(seconds / 86400)} days ago`
}

function NotificationList({ params }) {
  const navigate = useOriginNavigate()
  const query = useLoad(() => api.notifications({ ...params, limit: LIMIT }))
  const [more, setMore] = useState([])
  const [hasMore, setHasMore] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [changes, setChanges] = useState({})
  const base = [...(query.data || []), ...more]
  const rows = base.map(row => ({ ...row, ...changes[row.id] })).filter(row => !row.dismissed && (!params.unread || !row.read_at))
  const action = async (row, kind) => {
    setBusy(true); setError(null)
    try {
      if (kind === 'dismiss') { await api.dismissNotification(row.id); setChanges(previous => ({ ...previous, [row.id]: { dismissed: true } })) }
      else if (kind === 'unread') { await api.markUnread(row.id); setChanges(previous => ({ ...previous, [row.id]: { read_at: null } })) }
      else { await api.markRead(row.id); setChanges(previous => ({ ...previous, [row.id]: { read_at: new Date().toISOString() } })); if (kind === 'open') navigate(row.link) }
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const loadMore = async () => {
    setBusy(true); setError(null)
    try {
      const page = await api.notifications({ ...params, limit: LIMIT, before_id: base.at(-1).id })
      setMore(previous => [...previous, ...page]); setHasMore(page.length === LIMIT)
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const groups = new Map()
  for (const row of rows) { const day = dayLabel(row.created_at); if (!groups.has(day)) groups.set(day, []); groups.get(day).push(row) }
  return <Status loading={query.loading} error={query.error}>
    {error && <p role="alert" className="alert alert-danger">{error}</p>}
    {!rows.length && <div className="dash-panel p-4 text-center"><Bell size={28} aria-hidden="true" /><h2 className="h5 mt-2">{params.unread ? 'You’re all caught up' : 'No notifications to show'}</h2><p className="text-muted mb-0">{params.unread ? 'There are no unread updates in this view.' : 'Updates will appear here as work progresses. Try changing your filters.'}</p></div>}
    {[...groups].map(([day, notifications]) => <section key={day} className="mb-4"><h2 className="h6">{day}</h2><ul className="list-unstyled dash-panel mb-0">{notifications.map(row => {
      const Icon = row.type.startsWith('escalation_') ? MessageSquare : row.type.startsWith('alert_') ? ShieldAlert : Mail
      return <li key={row.id} className={`notification-row ${row.read_at ? '' : 'is-unread'}`} onClick={event => { if (!busy && !event.target.closest('button')) action(row, 'open') }}>
        <button className="notification-open" disabled={busy} onClick={() => action(row, 'open')}><Icon size={22} className={row.severity === 'critical' ? 'text-danger' : row.severity === 'warning' ? 'text-warning' : ''} aria-hidden="true" /><span className="notification-copy"><strong>{row.title}</strong><span>{row.message}</span><time dateTime={row.created_at} title={fmt(row.created_at)}>{relativeTime(row.created_at)}</time></span>{!row.read_at && <span className="notification-unread-dot" aria-label="Unread" />}</button>
        <div className="notification-actions"><button className="btn btn-sm btn-outline-secondary" disabled={busy} aria-label={`${row.read_at ? 'Mark unread' : 'Mark read'}: ${row.title}`} title={row.read_at ? 'Mark unread' : 'Mark read'} onClick={() => action(row, row.read_at ? 'unread' : 'read')}>{row.read_at ? <Mail size={16} /> : <Check size={16} />}</button><button className="btn btn-sm btn-outline-secondary" disabled={busy} aria-label={`Dismiss: ${row.title}`} title="Dismiss" onClick={() => action(row, 'dismiss')}><Trash2 size={16} /></button></div>
      </li>
    })}</ul></section>)}
    {(hasMore ?? query.data?.length === LIMIT) && <button className="btn btn-outline-primary" disabled={busy} onClick={loadMore}>Load more</button>}
  </Status>
}

export default function Notifications() {
  const { auth } = useAuth()
  const [unread, setUnread] = useState(false)
  const [type, setType] = useState('')
  const [search, setSearch] = useState('')
  const [version, setVersion] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const params = { ...(unread ? { unread: 'true' } : {}), ...(type ? { type } : {}), ...(search.trim() ? { search: search.trim() } : {}) }
  const readAll = async () => {
    setBusy(true); setError(null)
    try { await api.markAllRead(); setVersion(v => v + 1) } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  return <div className="dash-page"><header className="dash-header"><div><h1>Notifications</h1><p className="text-muted">{auth.role === 'admin' ? 'Case and escalation activity, and alerts awaiting review' : 'Your case ownership and escalation updates'}</p></div><button className="btn btn-outline-primary" disabled={busy} onClick={readAll}><CheckCheck size={16} aria-hidden="true" /> Mark all as read</button></header>
    <div className="dash-panel p-3 mb-3"><div className="nav nav-pills mb-3" role="tablist" aria-label="Notification view">{[[false, 'All'], [true, 'Unread']].map(([value, label]) => <button key={label} role="tab" aria-selected={unread === value} className={`nav-link ${unread === value ? 'active' : ''}`} onClick={() => setUnread(value)}>{label}</button>)}</div><div className="row g-3"><label className="col-md-4">Type<select className="form-select" value={type} onChange={e => setType(e.target.value)}><option value="">All types</option><option value="cases">Cases</option><option value="escalations">Escalations</option><option value="alerts">Alerts</option></select></label><label className="col-md-8">Search notifications<input className="form-control" value={search} onChange={e => setSearch(e.target.value)} /></label></div></div>
    {error && <p role="alert" className="alert alert-danger">{error}</p>}<NotificationList key={JSON.stringify(params) + version} params={params} />
  </div>
}
