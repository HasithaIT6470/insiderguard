import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { api } from '../api'
import RiskDetail from './RiskDetail.jsx'

vi.mock('../api', () => ({ api: { alert: vi.fn(), userRisk: vi.fn(), userTimeline: vi.fn(), userActivity: vi.fn() } }))
vi.mock('react-chartjs-2', () => ({ Bar: () => <div>Chart</div> }))

const attribution = '© 2026 The MITRE Corporation. This work is reproduced and distributed with the permission of The MITRE Corporation. MITRE ATT&CK and ATT&CK are registered trademarks of The MITRE Corporation.'
const technique = { id: 'T1110', name: 'Brute Force', tactics: [{ id: 'TA0006', name: 'Credential Access' }],
  url: 'https://attack.mitre.org/techniques/T1110/', confidence: 'high', rationale: 'Burst of failed logons', indicators: ['failed_logon_burst'] }

beforeEach(() => {
  vi.clearAllMocks()
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
