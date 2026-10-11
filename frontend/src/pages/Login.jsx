import { useState } from 'react'
import { Navigate } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../App.jsx'

export default function Login() {
  const { auth, login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  if (auth) return <Navigate to="/" replace />

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      login(await api.login(username, password))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="d-flex align-items-center justify-content-center" style={{ minHeight: '100vh' }}>
      <form className="card p-4" style={{ width: 380 }} onSubmit={submit}>
        <h1 className="h4 mb-1">🛡 InsiderGuard</h1>
        <p className="text-muted small">Insider threat detection &amp; data-exfiltration prevention (prototype, synthetic data only)</p>
        {error && <div className="alert alert-danger py-2">{error}</div>}
        <label className="form-label" htmlFor="u">Username</label>
        <input id="u" className="form-control mb-3" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        <label className="form-label" htmlFor="p">Password</label>
        <input id="p" type="password" className="form-control mb-3" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
        <button className="btn btn-primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
    </div>
  )
}
