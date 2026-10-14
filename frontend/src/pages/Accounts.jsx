import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../App.jsx'
import { api } from '../api'
import { Status, fmt, useLoad } from '../components.jsx'

function AccountManagement() {
  const accounts = useLoad(() => api.accounts())
  const [form, setForm] = useState({ username: '', password: '', role: 'analyst' })
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(null)
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      await api.createAccount(form)
      setMessage({ ok: true, text: `Created account ${form.username}.` })
      setForm({ username: '', password: '', role: 'analyst' })
      accounts.reload()
    } catch (error) {
      setMessage({ ok: false, text: error.message })
    } finally {
      setBusy(false)
    }
  }
  return <>
    <h1 className="h3 mb-3">Accounts</h1>
    <div className="row g-3">
      <section className="col-lg-5">
        <form className="card p-3" onSubmit={submit}>
          <h2 className="h5">Create account</h2>
          <label className="form-label" htmlFor="account-username">Username</label>
          <input id="account-username" className="form-control mb-3" autoComplete="off" required minLength={3} maxLength={64} pattern="[A-Za-z0-9_.\-]+" value={form.username} onChange={e => setForm({ ...form, username: e.target.value })} />
          <label className="form-label" htmlFor="account-password">Password</label>
          <input id="account-password" type="password" className="form-control mb-3" autoComplete="new-password" required minLength={10} maxLength={72} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })} />
          <label className="form-label" htmlFor="account-role">Role</label>
          <select id="account-role" className="form-select mb-3" value={form.role} onChange={e => setForm({ ...form, role: e.target.value })}>
            <option value="analyst">Security analyst</option>
            <option value="admin">Administrator</option>
          </select>
          <button className="btn btn-primary" disabled={busy}>{busy ? 'Creating...' : 'Create account'}</button>
          {message && <div className={`alert mt-3 mb-0 alert-${message.ok ? 'success' : 'danger'}`} role="status">{message.text}</div>}
        </form>
      </section>
      <section className="col-lg-7">
        <h2 className="h5">Login accounts</h2>
        <Status loading={accounts.loading} error={accounts.error}>
          <div className="table-responsive"><table className="table">
            <thead><tr><th>Username</th><th>Role</th><th>Created</th></tr></thead>
            <tbody>{(accounts.data || []).map(a => <tr key={a.username}><td>{a.username}</td><td>{a.role === 'admin' ? 'Administrator' : 'Security analyst'}</td><td>{fmt(a.created_at)}</td></tr>)}</tbody>
          </table></div>
        </Status>
      </section>
    </div>
  </>
}

export default function Accounts() {
  const { auth } = useAuth()
  return auth.role === 'admin' ? <AccountManagement /> : <Navigate to="/" replace />
}
