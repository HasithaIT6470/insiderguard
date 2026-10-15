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
    super(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(error => error.msg).join('; ') : detail?.message || `Request failed (${status})`)
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
  me: () => request('/auth/me'),
  changePassword: (current_password, new_password) => request('/auth/change-password', { method: 'POST', body: { current_password, new_password } }),
  accounts: () => request('/auth/accounts'),
  createAccount: (body) => request('/auth/accounts', { method: 'POST', body }),
  deleteAccount: (id) => request(`/auth/accounts/${id}`, { method: 'DELETE' }),
  resetPassword: (id, new_password) => request(`/auth/accounts/${id}/reset-password`, { method: 'POST', body: { new_password } }),
  login: async (username, password) => {
    const form = new URLSearchParams({ username, password })
    const res = await fetch('/api/auth/login', { method: 'POST', body: form })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) throw new ApiError(res.status, data.detail || 'Login failed')
    return data
  },
  summary: () => request('/dashboard/summary'),
  users: (department) => request(`/users${department ? `?department=${encodeURIComponent(department)}` : ''}`),
  usersStats: () => request('/users/stats'),
  userOverview: (id) => request(`/users/${encodeURIComponent(id)}/overview`),
  adminEmployees: () => request('/admin/employees'),
  adminEmployee: (id) => request(`/admin/employees/${encodeURIComponent(id)}`),
  createEmployee: (body) => request('/admin/employees', { method: 'POST', body }),
  updateEmployee: (id, body) => request(`/admin/employees/${encodeURIComponent(id)}`, { method: 'PUT', body }),
  offboardEmployee: (id) => request(`/admin/employees/${encodeURIComponent(id)}/offboard`, { method: 'POST' }),
  importEmployees: (file) => {
    const form = new FormData()
    form.append('file', file)
    return request('/admin/employees/import', { method: 'POST', form })
  },
  employeeContacts: (id) => request(`/admin/employees/${encodeURIComponent(id)}/contacts`),
  addEmployeeContact: (id, body) => request(`/admin/employees/${encodeURIComponent(id)}/contacts`, { method: 'POST', body }),
  userRisk: (id) => request(`/users/${encodeURIComponent(id)}/risk`),
  userTimeline: (id) => request(`/users/${encodeURIComponent(id)}/timeline?limit=300`),
  userActivity: (id) => request(`/users/${encodeURIComponent(id)}/activity?days=60`),
  alerts: (params = {}) => request(`/alerts?${new URLSearchParams(params)}`),
  alert: (id) => request(`/alerts/${id}`),
  claimAlert: (id) => request(`/alerts/${id}/claim`, { method: 'POST' }),
  releaseAlert: (id, reason) => request(`/alerts/${id}/release`, { method: 'POST', body: { reason } }),
  assignAlert: (id, owner) => request(`/alerts/${id}/assign`, { method: 'POST', body: { owner } }),
  myCases: (params = {}) => request(`/my-cases?${new URLSearchParams(params)}`),
  teamWorkload: () => request('/team/workload'),
  alertEvents: (id) => request(`/alerts/${id}/events`),
  setStatus: (id, status, details = {}) => request(`/alerts/${id}`, { method: 'PATCH', body: { ...details, status } }),
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
  createRule: (body) => request('/rules', { method: 'POST', body }),
  deleteRule: (key) => request(`/rules/${encodeURIComponent(key)}`, { method: 'DELETE' }),
  updateRules: (values) => request('/rules', { method: 'PUT', body: { values } }),
  evaluation: () => request('/evaluation/results'),
  evaluationFeedback: () => request('/evaluation/feedback'),
  runEvaluation: () => request('/evaluation/run', { method: 'POST' }),
  report: (params = {}) => request(`/reports/risk?${new URLSearchParams(params)}`),
  reportIndicators: () => request('/reports/indicators'),
  reportRange: () => request('/reports/range'),
  reportCsv: async (params = {}) => (await request(`/reports/risk?${new URLSearchParams({ ...params, format: 'csv' })}`, { raw: true })).blob(),
  audit: () => request('/audit?limit=200'),
}
