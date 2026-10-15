export const SCENARIOS = [
  ['normal', 'Normal work', 'A usual login, file read and 10 MB download.', 'Routine'],
  ['unusual_download', 'Unusual download', '120 MB: below the default bulk rule, above the personal baseline.', 'Anomaly'],
  ['off_hours', 'Late-night login', 'Successful login at 2 a.m. on the known laptop.', 'Time'],
  ['bulk', 'Large download', 'A 900 MB export from the employee workspace.', 'Volume'],
  ['failed_logins', 'Failed login burst', 'Six failed authentication attempts within a minute.', 'Denied'],
  ['denied', 'Repeated denied access', 'Four attempts to read a restricted resource.', 'Denied'],
  ['unknown_device', 'Unfamiliar device', 'Activity from a device absent from the learning history.', 'Device'],
  ['restricted', 'Restricted file access', 'Read a synthetic restricted document.', 'Resource'],
  ['honeytoken', 'Open the decoy', 'Access the registered synthetic payroll honeytoken.', 'Honeytoken'],
  ['combined', 'Correlated threat', 'Night login + unfamiliar device + restricted file + large export + decoy.', 'Hybrid'],
  ['invalid', 'Invalid event', 'Send an incomplete record to demonstrate validation and error logging.', 'Validation'],
]

export function newIdentity() {
  return `sim-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
}
export function resource(id) { return `/simulator/${id}/decoy-payroll.xlsx` }
function event(id, time, type, extra = {}) {
  return { timestamp: new Date(time).toISOString(), user_id: id, department: 'Simulator Lab', event_type: type,
    resource: `/simulator/${id}/project-notes.txt`, resource_type: 'general', device_id: `LAPTOP-${id}`,
    result: 'success', volume_mb: 0, ...extra }
}
export function baselineEvents(id, day, cfg) {
  const days = Math.ceil(cfg.baseline_days)
  if (!Number.isFinite(days) || days < 1 || days > 60 || cfg.baseline_min_events > 5000) throw new Error('This demo supports learning windows of 1–60 days and at most 5,000 required learning events.')
  const perDay = Math.max(5, Math.ceil(cfg.baseline_min_events / days) - 2)
  const end = Date.parse(`${day}T09:00:00Z`) - 86400000
  const start = end - days * 86400000
  const out = []
  for (let d = 0; d <= days; d++) {
    const t = start + d * 86400000
    out.push(event(id, t, 'auth', { resource: null }))
    for (let n = 0; n < perDay; n++) out.push(event(id, t + 600000 + Math.floor(n * 2400000 / perDay), 'file_access'))
    out.push(event(id, t + 3600000, 'download', { volume_mb: 10 }))
  }
  return out
}
export function scenarioEvents(name, id, day, sequence = 0) {
  if (!SCENARIOS.some(([key]) => key === name)) throw new Error('Unknown scenario')
  if (name === 'invalid') return [{ user_id: id, event_type: 'unsupported_event' }]
  const night = ['off_hours', 'combined'].includes(name)
  const t = Date.parse(`${day}T${night ? '02' : '09'}:00:00Z`) + (sequence % 60) * 60000
  const e = (offset, type, changes) => event(id, t + offset * 1000, type, changes)
  switch (name) {
    case 'normal': return [e(0, 'auth', { resource: null }), e(10, 'file_access'), e(20, 'download', { volume_mb: 10 })]
    case 'unusual_download': return [e(0, 'download', { volume_mb: 120 })]
    case 'off_hours': return [e(0, 'auth', { resource: null })]
    case 'bulk': return [e(0, 'download', { volume_mb: 900 })]
    case 'failed_logins': return Array.from({ length: 6 }, (_, n) => e(n * 10, 'auth', { result: 'fail', resource: null }))
    case 'denied': return Array.from({ length: 4 }, (_, n) => e(n * 10, 'denied_access', { result: 'denied', resource: `/simulator/${id}/restricted.xlsx`, resource_type: 'restricted' }))
    case 'unknown_device': return [e(0, 'device', { device_id: `UNKNOWN-${id}`, resource: null })]
    case 'restricted': return [e(0, 'file_access', { resource: `/simulator/${id}/restricted.xlsx`, resource_type: 'restricted' })]
    case 'honeytoken': return [e(0, 'file_access', { resource: resource(id) })]
    case 'combined': {
      const device_id = `UNKNOWN-${id}`
      return [e(0, 'auth', { resource: null, device_id }),
        e(10, 'file_access', { resource: `/simulator/${id}/restricted.xlsx`, resource_type: 'restricted', device_id }),
        e(20, 'download', { volume_mb: 900, device_id }),
        e(30, 'file_access', { resource: resource(id), device_id })]
    }
  }
}
