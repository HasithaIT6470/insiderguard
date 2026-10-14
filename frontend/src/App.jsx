import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { Activity, BarChart3, ExternalLink, FlaskConical, LayoutDashboard, LogOut, Menu, ShieldCheck, Siren, Users, X } from 'lucide-react'
import { Link, NavLink, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { getAuth, setAuth } from './api'
import Login from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import RiskDetail from './pages/RiskDetail.jsx'
import Alerts from './pages/Alerts.jsx'
import Telemetry from './pages/Telemetry.jsx'
import Evaluation from './pages/Evaluation.jsx'
import Reports from './pages/Reports.jsx'
import Accounts from './pages/Accounts.jsx'

const AuthCtx = createContext(null)
export const useAuth = () => useContext(AuthCtx)

function Shell({ children }) {
  const { auth, logout } = useAuth()
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
            </NavLink>
          ))}
          <a className="ig-nav-link" href="http://localhost:5175" target="_blank" rel="noopener noreferrer" onClick={() => setMenuOpen(false)} aria-label="Simulated Lab (opens in a new tab)">
            <FlaskConical size={20} aria-hidden="true" /><span>Simulated Lab</span><ExternalLink size={14} aria-hidden="true" />
          </a>
        </nav>
        <div className="ig-account">
          <div className="ig-account-details"><span className="ig-avatar" aria-hidden="true">{auth.username.slice(0, 1).toUpperCase()}</span><div><strong>{auth.username}</strong><span className="ig-role">{auth.role}</span></div></div>
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
        <Route path="/accounts" element={<Protected><Accounts /></Protected>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthCtx.Provider>
  )
}
