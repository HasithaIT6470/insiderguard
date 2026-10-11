import { createContext, useContext, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { getAuth, setAuth } from './api'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import RiskDetail from './pages/RiskDetail.jsx'
import Alerts from './pages/Alerts.jsx'
import Telemetry from './pages/Telemetry.jsx'
import Evaluation from './pages/Evaluation.jsx'
import Reports from './pages/Reports.jsx'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

function Shell({ children }) {
  const { auth, logout } = useAuth()
  const links = [
    ['/', 'Dashboard'],
    ['/alerts', 'Alerts'],
    ['/reports', 'Reports'],
    ['/evaluation', 'Evaluation'],
    ['/telemetry', 'Telemetry & Honeytokens'],
  ]
  return (
    <>
      <nav className="navbar navbar-expand-md navbar-dark navbar-ig mb-4">
        <div className="container-fluid px-4">
          <Link className="navbar-brand fw-bold" to="/">🛡 InsiderGuard</Link>
          <div className="navbar-nav me-auto">
            {links.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === '/'} className="nav-link">{label}</NavLink>
            ))}
          </div>
          <span className="navbar-text me-3 small">
            {auth.username} <span className="badge bg-secondary">{auth.role}</span>
          </span>
          <button className="btn btn-sm btn-outline-light" onClick={logout}>Sign out</button>
        </div>
      </nav>
      <main className="container-fluid px-4 pb-5">{children}</main>
    </>
  )
}

function Protected({ children }) {
  const { auth } = useAuth()
  if (!auth) return <Navigate to="/login" replace />
  return <Shell>{children}</Shell>
}

export default function App() {
  const [auth, setAuthState] = useState(getAuth())
  const navigate = useNavigate()
  const value = {
    auth,
    login: (data) => {
      const a = { token: data.access_token, username: data.username, role: data.role }
      setAuth(a)
      setAuthState(a)
      navigate('/')
    },
    logout: () => {
      setAuth(null)
      setAuthState(null)
      navigate('/login')
    },
  }
  return (
    <AuthCtx.Provider value={value}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/" element={<Protected><Dashboard /></Protected>} />
        <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
        <Route path="/alerts/:id" element={<Protected><RiskDetail mode="alert" /></Protected>} />
        <Route path="/users/:id" element={<Protected><RiskDetail mode="user" /></Protected>} />
        <Route path="/reports" element={<Protected><Reports /></Protected>} />
        <Route path="/evaluation" element={<Protected><Evaluation /></Protected>} />
        <Route path="/telemetry" element={<Protected><Telemetry /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthCtx.Provider>
  )
}
