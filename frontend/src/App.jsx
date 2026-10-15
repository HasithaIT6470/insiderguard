import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Activity, BarChart3, ExternalLink, FlaskConical, LayoutDashboard, LogOut, Menu, ShieldCheck, Siren, Users, X } from 'lucide-react'
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { api, getAuth, setAuth } from './api'
import { useLoad } from './components.jsx'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import RiskDetail from './pages/RiskDetail.jsx'
import Alerts from './pages/Alerts.jsx'
import Telemetry from './pages/Telemetry.jsx'
import Evaluation from './pages/Evaluation.jsx'
import Reports from './pages/Reports.jsx'
import Accounts from './pages/Accounts.jsx'
import Profile from './pages/Profile.jsx'
import MyCases from './pages/MyCases.jsx'
import UsersPage from './pages/Users.jsx'
import UserProfile from './pages/UserProfile.jsx'
import Escalations from './pages/Escalations.jsx'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

function Shell({ children }) {
  const { auth, logout } = useAuth()
  const location = useLocation()
  const escalations = useLoad(() => api.escalationSummary(), [auth.username, auth.role, location.pathname])
  useEffect(() => {
    const update = () => escalations.reload()
    window.addEventListener('escalations-updated', update)
    window.addEventListener('focus', update)
    const timer = window.setInterval(update, 30000)
    return () => { window.removeEventListener('escalations-updated', update); window.removeEventListener('focus', update); window.clearInterval(timer) }
  }, [auth.username, auth.role])
  const mine = useLoad(() => auth.role === 'analyst' ? api.myCases() : Promise.resolve(null), [auth.username, auth.role, location.pathname])
  useEffect(() => {
    if (auth.role !== 'analyst') return
    const update = () => mine.reload()
    window.addEventListener('cases-updated', update)
    window.addEventListener('focus', update)
    const timer = window.setInterval(update, 30000)
    return () => { window.removeEventListener('cases-updated', update); window.removeEventListener('focus', update); window.clearInterval(timer) }
  }, [auth.role])
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef(null)
  const sidebar = useRef(null)
  useEffect(() => {
    if (!menuOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    sidebar.current?.querySelector('a')?.focus()
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setMenuOpen(false)
        menuButton.current?.focus()
      }
      if (event.key === 'Tab') {
        const controls = [menuButton.current, ...sidebar.current.querySelectorAll('a, button')]
        const first = controls[0]
        const last = controls[controls.length - 1]
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault()
          last.focus()
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault()
          first.focus()
        }
      }
    }
    const onResize = () => { if (window.innerWidth >= 992) setMenuOpen(false) }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('resize', onResize)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('resize', onResize)
    }
  }, [menuOpen])
  const links = [
    ['/', 'Dashboard', LayoutDashboard],
    ['/alerts', 'Alerts', Siren],
    ['/users', 'Users', Users],
    ['/escalations', auth.role === 'admin' ? 'Escalations' : 'My escalations', Siren],
    ...(auth.role === 'analyst' ? [['/my-cases', 'My cases', Users]] : []),
    ['/reports', 'Reports', BarChart3],
    ['/evaluation', 'Evaluation', FlaskConical],
    ['/telemetry', 'Telemetry & Honeytokens', Activity],
    ...(auth.role === 'admin' ? [['/accounts', 'Accounts', Users]] : []),
  ]
  return (
    <>
      <a className="ig-skip-link" href="#main-content">Skip to content</a>
      <header className="ig-mobile-header">
        <span className="ig-brand"><ShieldCheck size={24} aria-hidden="true" />InsiderGuard</span>
        <button ref={menuButton} className="ig-menu-button" aria-label={menuOpen ? 'Close navigation' : 'Open navigation'} title={menuOpen ? 'Close navigation' : 'Open navigation'} aria-expanded={menuOpen} aria-controls="sidebar-navigation" onClick={() => setMenuOpen(!menuOpen)}>
          {menuOpen ? <X size={22} /> : <Menu size={22} />}
        </button>
      </header>
      {menuOpen && <div className="ig-sidebar-backdrop" onClick={() => { setMenuOpen(false); menuButton.current?.focus() }} aria-hidden="true" />}
      <aside ref={sidebar} id="sidebar-navigation" className={`ig-sidebar${menuOpen ? ' is-open' : ''}`}>
        <Link className="ig-brand ig-sidebar-brand" to="/" onClick={() => setMenuOpen(false)}><ShieldCheck size={28} aria-hidden="true" />InsiderGuard</Link>
        <nav className="ig-navigation" aria-label="Main navigation">
          {links.map(([to, label, Icon]) => (
            <NavLink key={to} to={to} end={to === '/'} className="ig-nav-link" onClick={() => setMenuOpen(false)}>
              <Icon size={20} aria-hidden="true" /><span>{label}</span>
              {to === '/my-cases' && <span className="badge bg-secondary" aria-label="Active cases">{(mine.data?.summary?.open || 0) + (mine.data?.summary?.under_investigation || 0)}</span>}
              {to === '/escalations' && <span className={`badge ${escalations.data?.overdue_count ? 'bg-danger' : 'bg-secondary'}`} aria-label="Open escalations" title={`${escalations.data?.overdue_count || 0} overdue`}>{escalations.data?.open_count ?? '–'}</span>}
            </NavLink>
          ))}
          <a className="ig-nav-link" href="http://localhost:5175" target="_blank" rel="noopener noreferrer" onClick={() => setMenuOpen(false)} aria-label="Simulated Lab (opens in a new tab)">
            <FlaskConical size={20} aria-hidden="true" /><span>Simulated Lab</span><ExternalLink size={14} aria-hidden="true" />
          </a>
        </nav>
        <div className="ig-account">
          <div className="ig-account-details"><span className="ig-avatar" aria-hidden="true">{auth.username.slice(0, 1).toUpperCase()}</span><div><Link className="ig-profile-link" to="/profile" onClick={() => setMenuOpen(false)}>{auth.username}</Link><span className="badge bg-secondary mt-1">{auth.role}</span></div></div>
          <button className="ig-sign-out" onClick={logout}><LogOut size={18} aria-hidden="true" />Sign out</button>
        </div>
      </aside>
      <main id="main-content" className="ig-main" tabIndex={-1}>{children}</main>
    </>
  )
}

function Protected({ children }) {
  const { auth } = useAuth()
  if (!auth) return <Navigate to="/login" replace />
  return <Shell>{children}</Shell>
}

function AdminOnly({ children }) {
  const { auth } = useAuth()
  return auth?.role === 'admin' ? children : <Navigate to="/" replace />
}

export function AnalystOnly({ children }) {
  const { auth } = useAuth()
  return auth?.role === 'analyst' ? children : <Navigate to="/alerts" replace />
}

export default function App() {
  const [auth, setAuthState] = useState(getAuth())
  const navigate = useNavigate()
  const value = {
    auth,
    updateToken: (token) => {
      const updated = { ...getAuth(), token }
      setAuth(updated)
      setAuthState(updated)
    },
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
        <Route path="/profile" element={<Protected><Profile /></Protected>} />
        <Route path="/" element={<Protected><Dashboard /></Protected>} />
        <Route path="/alerts" element={<Protected><Alerts /></Protected>} />
        <Route path="/alerts/:id" element={<Protected><RiskDetail mode="alert" /></Protected>} />
        <Route path="/my-cases" element={<Protected><AnalystOnly><MyCases /></AnalystOnly></Protected>} />
        <Route path="/my-cases/:id" element={<Protected><AnalystOnly><RiskDetail mode="alert" editable /></AnalystOnly></Protected>} />
        <Route path="/users" element={<Protected><UsersPage /></Protected>} />
        <Route path="/users/:id" element={<Protected><UserProfile /></Protected>} />
        <Route path="/escalations" element={<Protected><Escalations /></Protected>} />
        <Route path="/escalations/:id" element={<Protected><Escalations /></Protected>} />
        <Route path="/reports" element={<Protected><Reports /></Protected>} />
        <Route path="/evaluation" element={<Protected><Evaluation /></Protected>} />
        <Route path="/telemetry" element={<Protected><Telemetry /></Protected>} />
        <Route path="/accounts" element={<Protected><AdminOnly><Accounts /></AdminOnly></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthCtx.Provider>
  )
}
