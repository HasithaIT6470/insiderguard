import { useState } from 'react'
import { Check, Circle, Eye, EyeOff, KeyRound, UserRound } from 'lucide-react'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { Status, fmt, useLoad } from '../components.jsx'

function PasswordInput({ id, label, value, onChange, disabled, autoComplete }) {
  const [visible, setVisible] = useState(false)
  return <div className="mb-3"><label className="form-label" htmlFor={id}>{label}</label><div className="account-password-field">
    <input id={id} className="form-control" type={visible ? 'text' : 'password'} autoComplete={autoComplete} value={value} onChange={onChange} disabled={disabled} required />
    <button type="button" className="account-password-toggle" disabled={disabled} aria-label={`${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`} title={`${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button>
  </div></div>
}

export default function Profile() {
  const profile = useLoad(() => api.me())
  const { updateToken } = useAuth()
  const [form, setForm] = useState({ current: '', next: '', confirm: '' })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const username = profile.data?.username || ''
  const rules = [
    ['At least 10 characters', [...form.next].length >= 10],
    ['At most 72 UTF-8 bytes', !!form.next && new TextEncoder().encode(form.next).length <= 72],
    ['Contains a letter', /\p{L}/u.test(form.next)],
    ['Contains a digit', /\p{Nd}/u.test(form.next)],
    ['Does not contain your username', !!username && !!form.next && !form.next.toLowerCase().includes(username.toLowerCase())],
    ['Different from current password', !!form.next && form.next !== form.current],
    ['Matches confirmation', !!form.next && form.next === form.confirm],
  ]
  const valid = !!form.current && rules.every(([, passed]) => passed)
  const update = key => event => { setForm(previous => ({ ...previous, [key]: event.target.value })); setSuccess(false) }
  const submit = async event => {
    event.preventDefault()
    if (!valid || busy) return
    setBusy(true)
    setError(null)
    setSuccess(false)
    try {
      const data = await api.changePassword(form.current, form.next)
      updateToken(data.access_token)
      setForm({ current: '', next: '', confirm: '' })
      setSuccess(true)
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return <div className="dash-page profile-page">
    <header className="dash-header"><div><h1>My profile</h1><p className="text-muted mb-0">Account details and password security</p></div></header>
    <Status loading={profile.loading} error={profile.error}>
      {profile.data && <div className="profile-layout">
        <section className="card p-3"><div className="dash-panel-heading"><h2>Account details</h2><UserRound size={20} aria-hidden="true" /></div><dl className="profile-details"><dt>Username</dt><dd>{profile.data.username}</dd><dt>Role</dt><dd><span className={`badge ${profile.data.role === 'admin' ? 'bg-primary' : 'bg-secondary'}`}>{profile.data.role === 'admin' ? 'Admin' : 'Analyst'}</span></dd><dt>Account created</dt><dd>{fmt(profile.data.created_at)}</dd></dl></section>
        <section className="card p-3"><h2 className="h5 mb-3">Change password</h2>
          {success && <div className="alert alert-success" role="status">Password changed. You are still signed in; your other sessions have been signed out.</div>}
          {error && <div className="alert alert-danger" role="alert">{error}</div>}
          <form onSubmit={submit}>
            <PasswordInput id="profile-current" label="Current password" value={form.current} onChange={update('current')} disabled={busy} autoComplete="current-password" />
            <PasswordInput id="profile-new" label="New password" value={form.next} onChange={update('next')} disabled={busy} autoComplete="new-password" />
            <PasswordInput id="profile-confirm" label="Confirm password" value={form.confirm} onChange={update('confirm')} disabled={busy} autoComplete="new-password" />
            <ul className="profile-checklist" aria-label="Password requirements">{rules.map(([label, passed]) => <li key={label} className={passed ? 'is-met' : ''}>{passed ? <Check size={15} aria-hidden="true" /> : <Circle size={13} aria-hidden="true" />}<span>{label}<span className="visually-hidden">: {passed ? 'met' : 'not met'}</span></span></li>)}</ul>
            <button className="btn btn-sm btn-primary telemetry-command" disabled={!valid || busy}><KeyRound size={16} aria-hidden="true" />{busy ? 'Changing password...' : 'Change password'}</button>
          </form>
        </section>
      </div>}
    </Status>
  </div>
}
