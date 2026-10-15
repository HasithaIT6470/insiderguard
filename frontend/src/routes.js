import { generatePath, matchPath } from 'react-router-dom'

// Navigation metadata only: labels depend on route IDs, never employee records.
export const routes = [
  { path: '/', label: 'Dashboard', parent: null },
  { path: '/alerts', label: 'Alerts', parent: '/' },
  { path: '/alerts/:id', label: ({ id }) => `Case #${id}`, parent: '/alerts' },
  { path: '/my-cases', label: 'My cases', parent: '/' },
  { path: '/my-cases/:id', label: ({ id }) => `Case #${id}`, parent: '/my-cases' },
  { path: '/users', label: 'Users', parent: '/' },
  { path: '/users/:id', label: ({ id }) => id, parent: '/users' },
  { path: '/escalations', label: 'Escalations', parent: '/' },
  { path: '/escalations/:id', label: ({ id }) => `Escalation #${id}`, parent: '/escalations' },
  { path: '/reports', label: 'Reports', parent: '/' },
  { path: '/evaluation', label: 'Evaluation', parent: '/' },
  { path: '/telemetry', label: 'Telemetry & Honeytokens', parent: '/' },
  { path: '/accounts', label: 'Accounts', parent: '/' },
  { path: '/profile', label: 'My profile', parent: '/' },
  { path: '/notifications', label: 'Notifications', parent: '/' },
  { path: '/login', label: 'Sign in', parent: null },
]

export function routeTrail(pathname) {
  const route = routes.find(entry => matchPath({ path: entry.path, end: true }, pathname))
  if (!route) return []
  const match = matchPath({ path: route.path, end: true }, pathname)
  const params = Object.fromEntries(Object.entries(match.params).map(([key, value]) => {
    try { return [key, decodeURIComponent(value)] } catch { return [key, value] }
  }))
  // Encode IDs when expanding parent paths.
  const pathParams = Object.fromEntries(Object.entries(params).map(([key, value]) => [key, encodeURIComponent(value)]))
  const trail = []
  let entry = route
  while (entry) {
    trail.unshift({ pathname: entry === route ? pathname : generatePath(entry.path, pathParams), label: typeof entry.label === 'function' ? entry.label(params) : entry.label })
    entry = entry.parent ? routes.find(parent => parent.path === entry.parent) : null
  }
  return trail
}

export function routeLabel(pathname) { return routeTrail(pathname).at(-1)?.label || 'Dashboard' }
