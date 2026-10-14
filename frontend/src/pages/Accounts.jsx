import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Navigate } from 'react-router-dom'
import { Eye, EyeOff, KeyRound, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { Status, fmt, useLoad } from '../components.jsx'

function PasswordField({ id, label, value, onChange, disabled }) {
  const [visible, setVisible] = useState(false)
  return <div className="mb-3">
    <label className="form-label" htmlFor={id}>{label}</label>
    <div className="account-password-field"><input id={id} type={visible ? 'text' : 'password'} className="form-control" autoComplete="new-password" required minLength={10} value={value} onChange={onChange} disabled={disabled} />
      <button type="button" className="account-password-toggle" aria-label={visible ? 'Hide password' : 'Show password'} title={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} disabled={disabled} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
  </div>
}

function AccountDialog({ action, onClose, onComplete }) {
  const dialog = useRef(null)
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const deleting = action.type === 'delete'
  const title = `${deleting ? 'Delete account' : 'Reset password'}: ${action.account.username}`
  useEffect(() => {
    const element = dialog.current
    const previousFocus = document.activeElement
    element.showModal()
    return () => { element.close(); previousFocus?.focus() }
  }, [])
  const submit = async event => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      if (deleting) await api.deleteAccount(action.account.id)
      else await api.resetPassword(action.account.id, password)
      onComplete(deleting ? `Deleted account ${action.account.username}.` : `Password reset for ${action.account.username}. Existing sessions have been invalidated.`)
      onClose()
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }
  return createPortal(<dialog className="rule-dialog" ref={dialog} aria-labelledby="account-dialog-title" onCancel={event => { event.preventDefault(); if (!busy) onClose() }}>
    <div className="dash-panel-heading"><h2 id="account-dialog-title">{title}</h2><button className="btn btn-sm btn-outline-secondary telemetry-icon-button" aria-label="Close dialog" title="Close dialog" disabled={busy} onClick={onClose}><X size={17} /></button></div>
    <form onSubmit={submit}>
      {deleting ? <p>Delete <strong>{action.account.username}</strong>? This cannot be undone. Their existing sessions will stop working.</p> : <><PasswordField id="reset-account-password" label="New password" value={password} onChange={e => setPassword(e.target.value)} disabled={busy} /><p className="small text-muted">Resetting this password signs the user out of all existing sessions.</p></>}
      {error && <div className="alert alert-danger" role="alert">{error}</div>}
      <div className="rule-dialog-actions"><button type="button" className="btn btn-sm btn-outline-secondary" disabled={busy} onClick={onClose}>Cancel</button><button className={`btn btn-sm ${deleting ? 'btn-danger' : 'btn-primary'} telemetry-command`} disabled={busy}>{deleting ? <Trash2 size={15} aria-hidden="true" /> : <KeyRound size={15} aria-hidden="true" />}{busy ? 'Working...' : deleting ? 'Delete account' : 'Reset password'}</button></div>
    </form>
  </dialog>, document.body)
}

function AccountManagement() {
  const { auth } = useAuth()
  const accounts = useLoad(() => api.accounts())
  const [form, setForm] = useState({ username: '', password: '', role: 'analyst' })
  const [busy, setBusy] = useState(false)
  const [createError, setCreateError] = useState(null)
  const [message, setMessage] = useState(null)
  const [action, setAction] = useState(null)
  const complete = text => { setMessage(text); accounts.reload() }
  const submit = async event => {
    event.preventDefault()
    setBusy(true)
    setCreateError(null)
    setMessage(null)
    try {
      await api.createAccount(form)
      complete(`Created ${form.role} account ${form.username}.`)
      setForm({ username: '', password: '', role: 'analyst' })
    } catch (error) { setCreateError(error.message) }
    finally { setBusy(false) }
  }
  return <div className="dash-page accounts-page">
    <header className="dash-header"><div><h1>Accounts</h1><p className="text-muted mb-0">Administrator and analyst access management</p></div></header>
    {message && <div className="alert alert-success mb-0" role="status">{message}</div>}
    <div className="accounts-layout">
      <section>
        <form className="card p-3" onSubmit={submit}>
          <h2 className="h5 mb-3">Create account</h2>
          <label className="form-label" htmlFor="account-username">Username</label>
          <input id="account-username" className="form-control mb-3" autoComplete="off" required minLength={3} maxLength={64} pattern="[A-Za-z0-9_.\-]+" value={form.username} disabled={busy} onChange={e => setForm({ ...form, username: e.target.value })} />
          <PasswordField id="account-password" label="Password" value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} disabled={busy} />
          <p className="small text-muted">At least 10 characters, at most 72 UTF-8 bytes, including a letter and a digit. Must not contain the username.</p>
          <label className="form-label" htmlFor="account-role">Role</label>
          <select id="account-role" className="form-select mb-3" value={form.role} disabled={busy} onChange={e => setForm({ ...form, role: e.target.value })}><option value="analyst">Analyst</option><option value="admin">Admin</option></select>
          <button className="btn btn-sm btn-primary telemetry-command" disabled={busy}><Plus size={16} aria-hidden="true" />{busy ? 'Creating...' : 'Create account'}</button>
          {createError && <div className="alert alert-danger mt-3 mb-0" role="alert">{createError}</div>}
        </form>
      </section>
      <section className="card p-3">
        <div className="dash-panel-heading"><div><h2>Login accounts</h2><p>{accounts.data?.length || 0} accounts</p></div><button className="btn btn-sm btn-outline-secondary telemetry-icon-button" aria-label="Refresh accounts" title="Refresh accounts" disabled={accounts.loading} onClick={accounts.reload}><RefreshCw size={16} /></button></div>
        <Status loading={accounts.loading} error={accounts.error}>
          <div className="table-responsive"><table className="table table-hover align-middle mb-0 accounts-table">
            <thead><tr><th scope="col">Username</th><th scope="col">Role</th><th scope="col">Created (UTC)</th><th scope="col">Actions</th></tr></thead>
            <tbody>{(accounts.data || []).map(account => {
              const self = account.username === auth.username
              return <tr key={account.id}><td><strong>{account.username}</strong>{self && <span className="accounts-self">You</span>}</td><td><span className={`badge ${account.role === 'admin' ? 'bg-primary' : 'bg-secondary'}`}>{account.role === 'admin' ? 'Admin' : 'Analyst'}</span></td><td className="small">{fmt(account.created_at)}</td><td><div className="accounts-actions">
                <span title={self ? 'Use self-service to change your own password' : `Reset password for ${account.username}`}><button className="btn btn-sm btn-outline-primary telemetry-command" disabled={self || busy} aria-label={`Reset password for ${account.username}`} onClick={() => { setMessage(null); setAction({ type: 'reset', account }) }}><KeyRound size={14} aria-hidden="true" />Reset password</button></span>
                <span title={self ? 'You cannot delete your own account' : `Delete ${account.username}`}><button className="btn btn-sm btn-outline-danger telemetry-icon-button" disabled={self || busy} aria-label={`Delete ${account.username}`} onClick={() => { setMessage(null); setAction({ type: 'delete', account }) }}><Trash2 size={16} /></button></span>
              </div></td></tr>
            })}</tbody>
          </table></div>
          {accounts.data?.length === 0 && <div className="dash-empty">No accounts found.</div>}
        </Status>
      </section>
    </div>
    {action && <AccountDialog action={action} onClose={() => setAction(null)} onComplete={complete} />}
  </div>
}

export default function Accounts() {
  const { auth } = useAuth()
  return auth?.role === 'admin' ? <AccountManagement /> : <Navigate to="/" replace />
}
