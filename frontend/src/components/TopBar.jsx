import { useEffect, useState } from 'react'
import { ArrowLeft, ChevronRight } from 'lucide-react'
import { Link, useLocation } from 'react-router-dom'
import { routeTrail } from '../routes'

export function BackLink() {
  const location = useLocation()
  const trail = routeTrail(location.pathname)
  const from = location.state?.from
  const validFrom = from && typeof from.pathname === 'string' && from.pathname.startsWith('/') && !from.pathname.startsWith('//') && routeTrail(from.pathname).length && from.pathname !== '/login' && (from.pathname !== location.pathname || (from.search || '') !== location.search)
  const target = validFrom ? { pathname: from.pathname, search: typeof from.search === 'string' ? from.search : '' } : trail.at(-2)
  if (!target) return null
  const label = validFrom && typeof from.label === 'string' ? from.label : (validFrom ? routeTrail(from.pathname).at(-1).label : target.label)
  return <Link className="ig-back-link" to={{ pathname: target.pathname, search: target.search || '' }} title={`Back to ${label}`}><ArrowLeft size={16} aria-hidden="true" /><span>Back to {label}</span></Link>
}

export function Breadcrumbs({ compact = false }) {
  const location = useLocation()
  if (location.pathname === '/login') return null
  const trail = routeTrail(location.pathname)
  if (!trail.length) return null
  return <div className={`ig-breadcrumb-area${compact ? ' is-compact' : ''}`}>
    <BackLink />
    <nav aria-label="Breadcrumb"><ol className="ig-breadcrumb-list">{trail.map((crumb, index) => <li key={crumb.pathname}>
      {index > 0 && <ChevronRight size={14} aria-hidden="true" />}
      {index === trail.length - 1 ? <span aria-current="page" title={crumb.label}>{crumb.label}</span> : <Link to={crumb.pathname} title={crumb.label}>{crumb.label}</Link>}
    </li>)}</ol></nav>
  </div>
}

export default function TopBar({ right }) {
  const location = useLocation()
  const [compact, setCompact] = useState(() => window.matchMedia?.('(max-width: 991.98px)').matches || false)
  useEffect(() => {
    const media = window.matchMedia?.('(max-width: 991.98px)')
    if (!media) return
    const update = () => setCompact(media.matches)
    update(); media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])
  if (location.pathname === '/login') return null
  return <header className={`ig-topbar${compact ? ' is-compact' : ''}`} aria-label="Page navigation">
    <Breadcrumbs compact={compact} /><div className="ig-topbar-right" data-testid="topbar-right">{right}</div>
  </header>
}
