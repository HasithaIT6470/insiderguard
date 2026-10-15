import test from 'node:test'
import assert from 'node:assert/strict'
import { baselineEvents, scenarioEvents, SCENARIOS, resource } from './scenarios.js'
test('Learning history exceeds the window, uses a consistent device and sufficient events', () => {
  const events = baselineEvents('sim-test', '2026-09-18', { baseline_days: 14, baseline_min_events: 50 })
  assert.equal(events.length, 105)
  assert(Date.parse(events.at(-1).timestamp) - Date.parse(events[0].timestamp) > 14 * 86400000)
  assert(events.every(e => e.user_id === 'sim-test' && e.device_id === 'LAPTOP-sim-test'))
  assert(events.filter(e => e.event_type === 'download').every(e => e.volume_mb === 10))
})
test('All activity scenarios have correct event structure except deliberate invalid scenario', () => {
  for (const [name] of SCENARIOS) {
    const events = scenarioEvents(name, 'sim-test', '2026-09-18')
    assert(events.length)
    if (name === 'invalid') { assert.equal(events[0].timestamp, undefined); continue }
    for (const event of events) {
      assert(Number.isFinite(Date.parse(event.timestamp)))
      assert.equal(event.department, 'Simulator Lab')
      assert(event.device_id && event.result)
      assert(event.volume_mb >= 0)
    }
  }
})
test('Combined threat includes night login, unfamiliar device, bulk download, restricted resource and registered decoy', () => {
  const events = scenarioEvents('combined', 'sim-test', '2026-09-18')
  assert.equal(new Date(events[0].timestamp).getUTCHours(), 2)
  assert(events.every(e => e.device_id === 'UNKNOWN-sim-test'))
  assert(events.some(e => e.volume_mb === 900))
  assert(events.some(e => e.resource_type === 'restricted'))
  assert(events.some(e => e.resource === resource('sim-test')))
})
test('Failed login and denial scenarios create bursts with the appropriate results', () => {
  assert(scenarioEvents('failed_logins', 'sim-test', '2026-09-18').every(e => e.result === 'fail'))
  assert.equal(scenarioEvents('failed_logins', 'sim-test', '2026-09-18').length, 6)
  assert(scenarioEvents('denied', 'sim-test', '2026-09-18').every(e => e.event_type === 'denied_access' && e.result === 'denied'))
  assert.throws(() => scenarioEvents('missing', 'sim-test', '2026-09-18'), /Unknown scenario/)
})
test('Large configured learning counts stay inside normal working hours', () => {
  const events = baselineEvents('sim-test', '2026-09-18', { baseline_days: 1, baseline_min_events: 5000 })
  assert.equal(events.length, 10000)
  assert(events.every(e => [9, 10].includes(new Date(e.timestamp).getUTCHours())))
  assert(events.filter(e => e.timestamp.startsWith('2026-09-16')).length >= 5000)
})
