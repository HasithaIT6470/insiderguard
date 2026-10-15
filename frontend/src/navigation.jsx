import { forwardRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { routeLabel } from './routes'

export function linkState(location, label = routeLabel(location.pathname)) {
  return { from: { pathname: location.pathname, search: location.search || '', label } }
}

// Use for page-content links. Breadcrumb ancestors and BackLink intentionally use
// plain router Links so returning doesn't create a circular "Back to" trail.
export const OriginLink = forwardRef(function OriginLink({ state, ...props }, ref) {
  const location = useLocation()
  return <Link {...props} ref={ref} state={{ ...state, ...linkState(location) }} />
})

export function useOriginNavigate() {
  const location = useLocation()
  const navigate = useNavigate()
  return (to, options = {}) => typeof to === 'number' ? navigate(to) : navigate(to, { ...options, state: { ...options.state, ...linkState(location) } })
}
