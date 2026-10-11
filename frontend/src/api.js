// Thin API client. The JWT lives in sessionStorage (cleared when the tab closes).
const KEY = 'ig_auth'

export function getAuth() {
  try {
    return JSON.parse(sessionStorage.getItem(KEY)) || null
  } catch {
    return null
  }
}
export function setAuth(a) {
  if (a) sessionStorage.setItem(KEY, JSON.stringify(a))
  else sessionStorage.removeItem(KEY)
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.message || `Request failed (${status})`)
    this.status = status
    this.detail = detail
  }
}

async function request(path, { method = 'GET', body, form, raw } = {}) {
  const headers = {}
  const auth = getAuth()
  if (auth?.token) headers.Authorization = `Bearer ${auth.token}`
  let payload
  if (form) payload = form
  else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload })
  if (res.status === 401 && auth) {
    setAuth(null)
    window.location.assign('/login')
  }
  if (!res.ok) {
    let detail
    try {
      detail = (await res.json()).detail
    } catch {
      detail = res.statusText
    }
    throw new ApiError(res.status, detail)
  }
  return raw ? res : res.json()
}

export const api = {
  login: async (username, password) => {
    const form = new URLSearchParams({ username, password })
    const res = await fetch('/api/auth/login', { method: 'POST', body: form })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new ApiError(res.status, data.detail || 'Login failed')
    return data
  },
  summary: () => request('/dashboard/summary'),
  users: (department) => request(`/users${department ? `?department=${encodeURIComponent(department)}` : ''}`),
  userRisk: (id) => request(`/users/${encodeURIComponent(id)}/risk`),
  userTimeline: (id) => request(`/users/${encodeURIComponent(id)}/timeline?limit=300`),
  userActivity: (id) => request(`/users/${encodeURIComponent(id)}/activity?days=60`),
  alerts: (params = {}) => request(`/alerts?${new URLSearchParams(params)}`),
  alert: (id) => request(`/alerts/${id}`),
  setStatus: (id, status) => request(`/alerts/${id}`, { method: 'PATCH', body: { status } }),
  addNote: (id, note) => request(`/alerts/${id}/notes`, { method: 'POST', body: { note } }),
  explain: (id) => request(`/alerts/${id}/explain`, { method: 'POST' }),
  honeytokens: () => request('/honeytokens'),
  createHoneytoken: (resource, description) =>
    request('/honeytokens', { method: 'POST', body: { resource, description } }),
  revokeHoneytoken: (id) => request(`/honeytokens/${id}`, { method: 'DELETE' }),
  importEvents: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/events/import', { method: 'POST', form })
  },
  parseErrors: () => request('/parse-errors?limit=50'),
  rules: () => request('/rules'),
  updateRules: (values) => request('/rules', { method: 'PUT', body: { values } }),
  evaluation: () => request('/evaluation/results'),
  runEvaluation: () => request('/evaluation/run', { method: 'POST' }),
  report: (params = {}) => request(`/reports/risk?${new URLSearchParams(params)}`),
  reportCsv: async (params = {}) => (await request(`/reports/risk?${new URLSearchParams({ ...params, format: 'csv' })}`, { raw: true })).blob(),
  audit: () => request('/audit?limit=200'),
}
