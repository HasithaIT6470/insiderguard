import { SCENARIOS, newIdentity, resource, baselineEvents, scenarioEvents } from './scenarios.js'
const $ = id => document.getElementById(id)
const KEY = 'ig_activity_simulator'
let state = { token: null, username: '', id: null, day: null, sequence: 0, ready: false, registered: false, history: [] }
try { Object.assign(state, JSON.parse(sessionStorage.getItem(KEY)) || {}) } catch { /* Start a clean session. */ }
let busy = false
let refreshing = false
let refreshTask = Promise.resolve()
let cfg = null
const save = () => sessionStorage.setItem(KEY, JSON.stringify(state))
function message(text, error = false) { $('message').hidden = !text; $('message').textContent = text; $('message').className = error ? 'error' : '' }
function controls() {
  $('login').hidden = !!state.token
  $('workspace').hidden = !state.token
  $('connection').textContent = state.token ? 'Connected to InsiderGuard' : 'Disconnected'
  $('connection').className = state.token ? 'pill connected' : 'pill'
  $('operator').textContent = `Operator: ${state.username} · administrator`
  $('employee-id').textContent = state.id || 'No demo employee yet'
  $('device').textContent = state.id ? `LAPTOP-${state.id}` : '—'
  $('date').textContent = state.day || '—'
  $('decoy-resource').textContent = state.id ? resource(state.id) : 'Prepare an employee first'
  $('decoy-status').textContent = state.registered ? 'Active in InsiderGuard' : 'Not registered'
  $('register').textContent = state.registered ? 'Decoy registered' : 'Register demo decoy'
  for (const button of document.querySelectorAll('button')) button.disabled = busy
  $('register').disabled = busy || !state.ready || state.registered
  $('refresh').disabled = busy || !state.ready
  for (const button of document.querySelectorAll('[data-scenario]')) button.disabled = busy || !state.ready || (['honeytoken', 'combined'].includes(button.dataset.scenario) && !state.registered)
}
async function request(path, { method = 'GET', body, form, publicRequest = false } = {}) {
  const headers = {}
  if (state.token && !publicRequest) headers.Authorization = `Bearer ${state.token}`
  let payload = form
  if (body !== undefined) { headers['Content-Type'] = 'application/json'; payload = JSON.stringify(body) }
  const response = await fetch(`/api${path}`, { method, headers, body: payload })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401 && !publicRequest) { state.token = null; save(); controls() }
    const detail = data.detail
    const error = new Error(typeof detail === 'string' ? detail : detail?.message || `Request failed (${response.status})`)
    error.status = response.status; error.detail = detail
    throw error
  }
  return data
}
function element(tag, text, className) { const node = document.createElement(tag); node.textContent = text; if (className) node.className = className; return node }
function renderHistory() {
  $('history').replaceChildren()
  if (!state.history.length) $('history').append(element('p', 'No transmissions yet.', 'muted'))
  for (const item of state.history) {
    const row = element('div', '', 'history-row')
    row.append(element('strong', `${item.title} · ${item.status}`))
    row.append(element('p', `${new Date(item.time).toLocaleTimeString()} · ${item.summary}`))
    const details = document.createElement('details')
    details.append(element('summary', 'View sent events and API response'))
    details.append(element('pre', JSON.stringify({ events: item.events, response: item.response }, null, 2)))
    row.append(details); $('history').append(row)
  }
}
function log(title, status, summary, events, response) {
  state.history.unshift({ title, status, summary, events, response, time: new Date().toISOString() })
  state.history = state.history.slice(0, 25)
  save(); renderHistory()
}
async function refresh() {
  if (!state.token || !state.ready || refreshing) return
  refreshing = true
  const id = state.id, token = state.token
  try {
    const [risk, users, alerts, honeytokens] = await Promise.all([
      request(`/users/${encodeURIComponent(id)}/risk`), request('/users?department=Simulator%20Lab'),
      request(`/alerts?user_id=${encodeURIComponent(id)}`), request('/honeytokens')])
    if (state.id !== id || state.token !== token) return
    $('score').textContent = risk.risk_score
    $('category').textContent = risk.risk_category
    $('category').className = `pill ${risk.risk_category}`
    $('baseline').textContent = risk.baseline_status
    $('event-count').textContent = users.find(u => u.user_id === id)?.event_count ?? 0
    $('alert-count').textContent = alerts.length
    state.registered = honeytokens.some(h => h.resource === resource(id) && h.active)
    save(); controls()
    $('detector-link').replaceChildren()
    const link = element('a', 'Open employee evidence ↗')
    link.href = `http://localhost:5173/users/${encodeURIComponent(id)}`; link.target = '_blank'; link.rel = 'noopener'
    $('detector-link').append(link)
    if (alerts.length) {
      const alertLink = element('a', `Open highest-risk alert (${alerts[0].category}) ↗`)
      alertLink.href = `http://localhost:5173/alerts/${alerts[0].id}`; alertLink.target = '_blank'; alertLink.rel = 'noopener'
      $('detector-link').append(alertLink)
    }
    $('evidence').replaceChildren()
    if (!risk.breakdown.length) $('evidence').append(element('p', 'No contributing indicators in the current risk window.', 'muted'))
    for (const item of risk.breakdown) {
      const row = element('div', '', 'evidence-row')
      row.append(element('strong', `${item.name.replaceAll('_', ' ')} +${item.weight}`))
      row.append(element('span', `${item.source} · ${item.category}`)); $('evidence').append(row)
    }
  } finally { refreshing = false }
}
async function act(fn) {
  if (busy) return
  busy = true; controls(); message('')
  try { await refreshTask; await fn() } catch (error) { message(error.message, true) }
  finally { busy = false; controls() }
}
async function connect(username, password) {
  const auth = await request('/auth/login', { method: 'POST', form: new URLSearchParams({ username, password }), publicRequest: true })
  if (auth.role !== 'admin') throw new Error('Telemetry submission requires an administrator account. Analysts can inspect results in InsiderGuard.')
  state.token = auth.access_token; state.username = auth.username; save(); controls()
  $('password').value = ''
  const rules = await request('/rules'); cfg = Object.fromEntries(rules.map(r => [r.key, r.value]))
  await refresh()
  message('Connected. Prepare a new employee, then send a scenario.')
}
$('connect-form').addEventListener('submit', event => { event.preventDefault(); act(() => connect($('username').value, $('password').value)) })
$('disconnect').addEventListener('click', () => { state.token = null; save(); controls(); message('Disconnected. Saved events and cases remain in InsiderGuard.') })
$('prepare').addEventListener('click', () => act(async () => {
  const [summary, rules] = await Promise.all([request('/dashboard/summary'), request('/rules')])
  cfg = Object.fromEntries(rules.map(r => [r.key, r.value]))
  const id = newIdentity(), day = (summary.as_of || new Date().toISOString()).slice(0, 10)
  const events = baselineEvents(id, day, cfg)
  const result = await request('/events', { method: 'POST', body: { events } })
  state.id = id; state.day = day; state.ready = true; state.registered = false; state.sequence = 0
  save(); controls()
  log('Prepare normal employee history', 'Accepted', `${result.accepted} stored events, ${result.rejected} rejected.`, events, result)
  await refresh()
  message('Employee prepared. Normal history and baseline are now stored in InsiderGuard.')
}))
$('register').addEventListener('click', () => act(async () => {
  const body = { resource: resource(state.id), description: 'Synthetic decoy for the separate activity simulator' }
  const result = await request('/honeytokens', { method: 'POST', body })
  state.registered = true; save()
  log('Register synthetic decoy', 'Registered', body.resource, [], result)
  await refresh(); message('Decoy registered in InsiderGuard. Honeytoken scenarios are enabled.')
}))
for (const [name, title, description, tag] of SCENARIOS) {
  const button = element('button', '', 'scenario'); button.dataset.scenario = name
  button.append(element('span', tag, 'scenario-tag'), element('strong', title), element('small', description))
  button.addEventListener('click', () => act(async () => {
    const events = scenarioEvents(name, state.id, state.day, state.sequence++)
    const before = $('score').textContent
    try {
      const result = await request('/events', { method: 'POST', body: { events } })
      await refresh()
      log(title, 'Accepted', `${result.accepted} stored, ${result.rejected} rejected. Risk ${before} → ${$('score').textContent}; ${$('alert-count').textContent} employee alert(s).`, events, result)
      message(`${title}: events accepted by InsiderGuard. Risk and alerts above come from the detector.`)
    } catch (error) {
      log(title, error.status === 422 ? 'Rejected by validation' : 'Failed', error.message, events, error.detail || { error: error.message })
      if (error.status === 422) { message('Invalid event correctly rejected. Review the validation response below and the parsing-error notification in InsiderGuard.'); await refresh() }
      else throw error
    }
  }))
  $('scenarios').append(button)
}
$('refresh').addEventListener('click', () => act(refresh))
$('clear-log').addEventListener('click', () => { state.history = []; save(); renderHistory() })
controls(); renderHistory()
if (state.token) act(async () => {
  const me = await request('/auth/me')
  if (me.role !== 'admin') { state.token = null; save(); throw new Error('Connect using an administrator account.') }
  await refresh(); message('Restored the simulator connection.')
})
setInterval(() => { if (!busy && !document.hidden) refreshTask = refresh().catch(error => message(error.message, true)) }, 5000)
