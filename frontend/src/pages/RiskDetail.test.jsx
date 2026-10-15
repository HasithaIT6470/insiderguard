import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { api } from '../api'
import RiskDetail from './RiskDetail.jsx'

const authState = vi.hoisted(() => ({ role: 'analyst', username: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth: authState }) }))
vi.mock('../api', () => ({ api: { alert: vi.fn(), userRisk: vi.fn(), userTimeline: vi.fn(), userActivity: vi.fn(), alertEvents: vi.fn(), claimAlert: vi.fn(), setStatus: vi.fn(), addNote: vi.fn(), explain: vi.fn(), releaseAlert: vi.fn() } }))
vi.mock('react-chartjs-2', () => ({ Bar: () => <div>Chart</div> }))

const attribution = '© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation. MITRE ATT&CK and ATT&CK are registered trademarks of The MITRE Corporation.'
const technique = { id: 'T1110', name: 'Brute Force', tactics: [{ id: 'TA0006', name: 'Credential Access' }],
  url: 'https://attack.mitre.org/techniques/T1110/', confidence: 'high', rationale: 'Burst of failed logons', indicators: ['failed_logon_burst'] }

beforeEach(() => {
  vi.clearAllMocks()
  authState.role = 'analyst'
  authState.username = 'analyst'
  api.alertEvents.mockResolvedValue([])
  api.alert.mockResolvedValue({ id: 1, user_id: 'u1', peak_score: 40, category: 'High', status: 'open',
    breakdown: [{ name: 'failed_logon_burst', category: 'denied', source: 'rule', weight: 15, attack: [technique] }],
    notes: [], attack: { attack_version: '20.0', attribution, techniques: [technique], tactics: [{ id: 'TA0006', name: 'Credential Access', techniques: ['T1110'] }] } })
  api.userRisk.mockResolvedValue({ user_id: 'u1', risk_score: 40, risk_category: 'High', breakdown: [] })
  api.userTimeline.mockResolvedValue([{ time: '2026-08-20T09:00:00', indicator: 'failed_logon_burst', source: 'rule', weight: 15, attack: [technique] }])
  api.userActivity.mockResolvedValue({ days: [] })
})

function renderAlert() {
  render(<MemoryRouter initialEntries={['/alerts/1']}><Routes><Route path="/alerts/:id" element={<RiskDetail mode="alert" />} /></Routes></MemoryRouter>)
}

it('shows technique links, ordered tactic context, confidence and attribution', async () => {
  renderAlert()
  const section = await screen.findByRole('region', { name: 'MITRE ATT&CK mapping' })
  expect(within(section).getByText('Credential Access')).toBeInTheDocument()
  expect(within(section).getByText('Brute Force')).toBeInTheDocument()
  expect(within(section).getByText(/Confidence: high/)).toHaveTextContent('failed_logon_burst')
  expect(within(section).getByText(/ATT&CK v20.0/)).toHaveTextContent(attribution)
  expect(within(section).getByText(/does not affect the score/)).toBeInTheDocument()
  const chips = await screen.findAllByRole('link', { name: 'T1110 · Brute Force · Credential Access · confidence high' })
  expect(chips).toHaveLength(1)
  for (const chip of chips) {
    expect(chip).toHaveAttribute('href', 'https://attack.mitre.org/techniques/T1110/')
    expect(chip).toHaveAttribute('target', '_blank')
    expect(chip).toHaveAttribute('rel', 'noopener noreferrer')
  }
})

it('renders legacy responses without ATT&CK fields', async () => {
  api.alert.mockResolvedValue({ id: 1, user_id: 'u1', peak_score: 40, category: 'High', status: 'open',
    breakdown: [{ name: 'failed_logon_burst', category: 'denied', source: 'rule', weight: 15 }], notes: [] })
  renderAlert()
  expect(await screen.findByText('Score composition (deterministic)')).toBeInTheDocument()
  expect(screen.queryByRole('region', { name: 'MITRE ATT&CK mapping' })).not.toBeInTheDocument()
})

it('shows a technique once even when it belongs to multiple tactics and evidence rows', async () => {
  const shared = { ...technique, id: 'T1078', name: 'Valid Accounts',
    tactics: [{ id: 'TA0001', name: 'Initial Access' }, { id: 'TA0003', name: 'Persistence' }] }
  api.alert.mockResolvedValue({ id: 1, user_id: 'u1', peak_score: 40, category: 'High', status: 'open',
    breakdown: [{ name: 'off_hours_activity', category: 'time', source: 'rule', weight: 10, attack: [shared] }], notes: [],
    attack: { attack_version: '20.0', attribution, techniques: [shared, shared],
      tactics: shared.tactics.map(t => ({ ...t, techniques: ['T1078'] })) } })
  api.userRisk.mockResolvedValue({ user_id: 'u1', risk_score: 40, risk_category: 'High',
    breakdown: [{ name: 'off_hours_activity', category: 'time', source: 'rule', weight: 10, attack: [shared] }] })
  api.userTimeline.mockResolvedValue([1, 2].map(() => ({ indicator: 'off_hours_activity', source: 'rule', weight: 10, attack: [shared] })))
  renderAlert()
  await screen.findByRole('region', { name: 'MITRE ATT&CK mapping' })
  expect(screen.getAllByText('T1078', { exact: true })).toHaveLength(1)
  expect(screen.getByText('Initial Access, Persistence')).toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'ATT&CK' })).not.toBeInTheDocument()
})

it.each(['admin', 'analyst'])('keeps alert details read-only for %s', async role => {
  authState.role = role
  renderAlert()
  await screen.findByText('Case #1', { exact: false })
  expect(screen.queryByLabelText('Status')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Investigation note')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Request AI explanation' })).not.toBeInTheDocument()
  expect(screen.getByRole('region', { name: 'Case history' })).toBeInTheDocument()
})

it('moves directly to under investigation in My cases and records notes', async () => {
  const alert = await api.alert()
  api.alert.mockResolvedValue({ ...alert, owner: 'analyst' })
  api.setStatus.mockResolvedValue({})
  api.addNote.mockResolvedValue({})
  render(<MemoryRouter initialEntries={['/my-cases/1']}><Routes><Route path="/my-cases/:id" element={<RiskDetail mode="alert" editable />} /></Routes></MemoryRouter>)
  fireEvent.change(await screen.findByLabelText('Status'), { target: { value: 'under_investigation' } })
  await waitFor(() => expect(api.setStatus).toHaveBeenCalledWith(1, 'under_investigation'))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.change(await screen.findByLabelText('Investigation note'), { target: { value: 'Reviewed synthetic evidence' } })
  fireEvent.click(screen.getByRole('button', { name: 'Add', exact: true }))
  await waitFor(() => expect(api.addNote).toHaveBeenCalledWith(1, 'Reviewed synthetic evidence'))
  expect(await screen.findByRole('button', { name: 'Request AI explanation' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Release case' })).toBeInTheDocument()
})

it('redirects non-owners to read-only details with a message', async () => {
  const alert = await api.alert()
  api.alert.mockResolvedValue({ ...alert, owner: 'another-analyst' })
  render(<MemoryRouter initialEntries={['/my-cases/1']}><Routes>
    <Route path="/my-cases/:id" element={<RiskDetail mode="alert" editable />} />
    <Route path="/alerts/:id" element={<RiskDetail mode="alert" />} />
  </Routes></MemoryRouter>)
  expect(await screen.findByText(/Only the case owner can work this case/)).toBeInTheDocument()
  expect(screen.queryByLabelText('Investigation note')).not.toBeInTheDocument()
})

it('shows a lifecycle warning even if a later event is a status change', async () => {
  api.alertEvents.mockResolvedValue([
    { id: 1, action: 'no_longer_detected', actor: 'system', detail: {} },
    { id: 2, action: 'status_changed', actor: 'analyst', detail: { from: 'open', to: 'closed' } },
  ])
  renderAlert()
  expect(await screen.findByText('No longer detected by current rules')).toBeInTheDocument()
})

it('releases an owned case with a reason and returns to read-only details', async () => {
  const alert = await api.alert()
  api.alert.mockResolvedValue({ ...alert, owner: 'analyst' })
  api.releaseAlert.mockResolvedValue({})
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  render(<MemoryRouter initialEntries={['/my-cases/1']}><Routes>
    <Route path="/my-cases/:id" element={<RiskDetail mode="alert" editable />} />
    <Route path="/alerts/:id" element={<RiskDetail mode="alert" />} />
  </Routes></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Release case' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Release Case #1' }))
  expect(dialog.getByRole('button', { name: 'Release case' })).toBeDisabled()
  fireEvent.change(dialog.getByLabelText('Reason'), { target: { value: 'End of shift handoff' } })
  fireEvent.click(dialog.getByRole('button', { name: 'Release case' }))
  await waitFor(() => expect(api.releaseAlert).toHaveBeenCalledWith(1, 'End of shift handoff'))
  expect(await screen.findByText('Case released back to the queue.')).toBeInTheDocument()
  expect(screen.queryByLabelText('Investigation note')).not.toBeInTheDocument()
})

it('labels legacy closed details without inventing an outcome', async () => {
  const alert = await api.alert()
  api.alert.mockResolvedValue({ ...alert, status: 'closed', resolution: null, outcome: null })
  renderAlert()
  expect(await screen.findByText('Closed (no outcome recorded)')).toBeInTheDocument()
  expect(screen.getByText('No outcome')).toBeInTheDocument()
})

it('uses close and reopen dialogs in the owner workspace and retains the closing note', async () => {
  const initial = { ...await api.alert(), owner: 'analyst' }
  const verdict = { id: 3, outcome: 'true_positive', note: 'Confirmed synthetic policy violation.', resolved_by: 'analyst', resolved_at: '2026-10-01T09:00:00' }
  api.alert.mockResolvedValue(initial)
  api.setStatus.mockImplementation(async (_id, status) => {
    api.alert.mockResolvedValue({ ...initial, status, outcome: status === 'closed' ? verdict.outcome : null,
      resolution: status === 'closed' ? verdict : null, resolution_history: [verdict] })
    return {}
  })
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  render(<MemoryRouter initialEntries={['/my-cases/1']}><Routes><Route path="/my-cases/:id" element={<RiskDetail mode="alert" editable />} /></Routes></MemoryRouter>)
  fireEvent.change(await screen.findByLabelText('Status'), { target: { value: 'closed' } })
  expect(screen.getByRole('dialog', { name: 'Close Case #1' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('radio', { name: /True positive/ }))
  fireEvent.change(screen.getByLabelText('Closing note'), { target: { value: verdict.note } })
  fireEvent.click(screen.getByRole('button', { name: 'Close case' }))
  await waitFor(() => expect(api.setStatus).toHaveBeenCalledWith(1, 'closed', { outcome: 'true_positive', note: verdict.note }))
  expect(await screen.findByText(verdict.note)).toBeInTheDocument()
  expect(screen.getByLabelText('Status')).toHaveValue('closed')
  fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'under_investigation' } })
  expect(screen.getByRole('dialog', { name: 'Reopen Case #1' })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Reopen reason'), { target: { value: 'New evidence needs review' } })
  fireEvent.click(screen.getByRole('button', { name: 'Reopen case' }))
  await waitFor(() => expect(api.setStatus).toHaveBeenCalledWith(1, 'under_investigation', { reason: 'New evidence needs review' }))
  expect(await screen.findByText(verdict.note)).toBeInTheDocument()
})
