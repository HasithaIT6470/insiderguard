import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import Alerts from './Alerts.jsx'

const authState = vi.hoisted(() => ({ role: 'analyst', username: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth: authState }) }))
vi.mock('../api', () => ({ api: { alerts: vi.fn(), teamWorkload: vi.fn(), claimAlert: vi.fn(), assignAlert: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  authState.role = 'analyst'
  authState.username = 'analyst'
  api.teamWorkload.mockResolvedValue([])
  api.claimAlert.mockResolvedValue({})
  api.alerts.mockResolvedValue(Array.from({ length: 21 }, (_, index) => ({
    id: index + 1, user_id: `user-${index + 1}`, department: index ? 'Engineering' : 'Finance',
    peak_score: 100 - index, category: index ? 'High' : 'Critical', status: index ? 'closed' : 'open',
    start_time: '2026-10-01T10:00:00', breakdown: [{ name: index ? 'Bulk download' : 'Decoy access' }],
  })))
})

it('paginates the loaded queue and links to alert investigations', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: 'Case #1', exact: true })).toHaveAttribute('href', '/alerts/1')
  expect(api.alerts).toHaveBeenCalledWith({ limit: 1000, sort_by: 'peak_score', sort_dir: 'desc', then_by: 'start_time', then_dir: 'desc' })
  expect(screen.queryByRole('link', { name: 'Case #21', exact: true })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
  expect(screen.getByRole('link', { name: 'Case #21', exact: true })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Risk level'), { target: { value: 'Critical' } })
  expect(await screen.findByRole('link', { name: 'Case #1', exact: true })).toBeInTheDocument()
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument()
})

it('combines filters and indicator search, then clears an empty result', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  fireEvent.change(screen.getByLabelText('Search alerts'), { target: { value: 'Decoy' } })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Finance' } })
  expect(await screen.findByRole('link', { name: 'Case #1', exact: true })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Case status'), { target: { value: 'closed' } })
  expect(await screen.findByText('No alerts match these filters.')).toBeInTheDocument()
  fireEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  await waitFor(() => expect(screen.getByRole('link', { name: 'Case #1', exact: true })).toBeInTheDocument())
  expect(screen.getByLabelText('Search alerts')).toHaveValue('')
})

function NavigationProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><output aria-label="URL">{location.search}</output><output aria-label="Path">{location.pathname}</output><button onClick={() => navigate(-1)}>Back</button></>
}

it('opens an alert by clicking anywhere on its tile and removes the investigate control', async () => {
  render(<MemoryRouter initialEntries={['/alerts']}><Alerts /><NavigationProbe /></MemoryRouter>)
  const tile = await screen.findByRole('row', { name: 'Open alert 1', exact: true })
  expect(tile).toHaveAttribute('tabindex', '0')
  expect(tile.querySelectorAll('td')).toHaveLength(10)
  expect(screen.queryByRole('link', { name: /Investigate alert/ })).not.toBeInTheDocument()
  fireEvent.click(tile.querySelector('.alerts-indicators'))
  expect(screen.getByLabelText('Path')).toHaveTextContent('/alerts/1')
})

it.each(['Enter', ' '])('opens a focused alert tile with %s', async key => {
  render(<MemoryRouter initialEntries={['/alerts']}><Alerts /><NavigationProbe /></MemoryRouter>)
  const tile = await screen.findByRole('row', { name: 'Open alert 2', exact: true })
  tile.focus()
  fireEvent.keyDown(tile, { key })
  expect(screen.getByLabelText('Path')).toHaveTextContent('/alerts/2')
})

it('preserves direct user-profile navigation inside an alert tile', async () => {
  render(<MemoryRouter initialEntries={['/alerts']}><Alerts /><NavigationProbe /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('link', { name: 'user-1', exact: true }))
  expect(screen.getByLabelText('Path')).toHaveTextContent('/users/user-1')
})

it('restores URL sort settings, supports None, and resets to the default order', async () => {
  render(<MemoryRouter initialEntries={['/alerts?sort_by=category&sort_dir=asc&then_by=status&then_dir=asc&keep=yes']}><Alerts /><NavigationProbe /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  expect(screen.getByLabelText('Sort by')).toHaveValue('category')
  expect(screen.getByLabelText('Then by')).toHaveValue('status')
  expect(screen.getByRole('button', { name: 'Risk level', exact: true }).closest('th')).toHaveAttribute('aria-sort', 'ascending')
  fireEvent.change(screen.getByLabelText('Then by'), { target: { value: '' } })
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  expect(screen.getByRole('button', { name: 'Secondary sort direction: ascending' })).toBeDisabled()
  expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ then_by: '' }))
  fireEvent.click(screen.getByRole('button', { name: 'Reset sort' }))
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  expect(screen.getByLabelText('Sort by')).toHaveValue('peak_score')
  expect(screen.getByLabelText('Then by')).toHaveValue('start_time')
  expect(screen.getByLabelText('URL')).toHaveTextContent('keep=yes')
})

it('keeps header sorting, direction toggles, and browser Back synchronized', async () => {
  render(<MemoryRouter><Alerts /><NavigationProbe /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  fireEvent.click(screen.getByRole('button', { name: 'Department', exact: true }))
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  expect(screen.getByLabelText('Sort by')).toHaveValue('department')
  expect(screen.getByRole('button', { name: 'Department', exact: true }).closest('th')).toHaveAttribute('aria-sort', 'ascending')
  fireEvent.click(screen.getByRole('button', { name: 'Department', exact: true }))
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  expect(screen.getByRole('button', { name: 'Department', exact: true }).closest('th')).toHaveAttribute('aria-sort', 'descending')
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ sort_by: 'department', sort_dir: 'asc' })))
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  expect(screen.getByRole('button', { name: 'Primary sort direction: ascending' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Primary sort direction: ascending' }))
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ sort_dir: 'desc' })))
})

it('forwards status and level filters with sorting', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  fireEvent.change(screen.getByLabelText('Case status'), { target: { value: 'open' } })
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  fireEvent.change(screen.getByLabelText('Risk level'), { target: { value: 'Critical' } })
  await screen.findByRole('link', { name: 'Case #1', exact: true })
  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'indicator_count' } })
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'open', category: 'Critical', sort_by: 'indicator_count' })))
})

it('preserves the returned server order instead of re-sorting the loaded subset', async () => {
  api.alerts.mockResolvedValueOnce([2, 1].map(id => ({ id, user_id: `user-${id}`, department: 'Finance', peak_score: id === 2 ? 10 : 100, category: 'High', status: 'open', start_time: '2026-10-01T10:00:00', breakdown: [] })))
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #2', exact: true })
  expect(screen.getAllByRole('link', { name: /^Case #/ }).map(link => link.textContent)).toEqual(['Case #2', 'Case #1'])
})

const bruteForce = { id: 'T1110', name: 'Brute Force', tactics: [{ id: 'TA0006', name: 'Credential Access' }], url: 'https://attack.mitre.org/techniques/T1110/', confidence: 'high' }
const collection = { id: 'T1039', name: 'Data from Network Shared Drive', tactics: [{ id: 'TA0009', name: 'Collection' }], url: 'https://attack.mitre.org/techniques/T1039/', confidence: 'medium' }

function mappedAlerts() {
  return [bruteForce, collection].map((technique, index) => ({ id: index + 1, user_id: `user-${index + 1}`,
    department: 'Finance', peak_score: 50, category: 'High', status: 'open',
    start_time: '2026-10-01T10:00:00', attack: { techniques: [technique] },
    breakdown: [{ name: index ? 'bulk_download' : 'failed_logon_burst', attack: [technique] },
      { name: 'another_indicator', attack: [technique] }] }))
}

it.each(['T1110', 'Brute Force', 'Credential Access'])('searches ATT&CK context by %s', async query => {
  api.alerts.mockResolvedValue(mappedAlerts())
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #2', exact: true })
  fireEvent.change(screen.getByLabelText('Search alerts'), { target: { value: query } })
  expect(screen.getByRole('link', { name: 'Case #1', exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Case #2', exact: true })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /T1110 · Brute Force/ })).not.toBeInTheDocument()
  expect(screen.queryByText('T1110', { exact: true })).not.toBeInTheDocument()
})

it('filters tactics locally and clears the selection without changing API parameters', async () => {
  api.alerts.mockResolvedValue(mappedAlerts())
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #2', exact: true })
  const calls = api.alerts.mock.calls.length
  fireEvent.change(screen.getByLabelText('ATT&CK tactic'), { target: { value: 'TA0006' } })
  expect(screen.getByRole('link', { name: 'Case #1', exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Case #2', exact: true })).not.toBeInTheDocument()
  expect(api.alerts.mock.calls.length).toBe(calls)
  fireEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  expect(screen.getByLabelText('ATT&CK tactic')).toHaveValue('')
  expect(screen.getByRole('link', { name: 'Case #2', exact: true })).toBeInTheDocument()
  expect(api.alerts).toHaveBeenLastCalledWith({ limit: 1000, sort_by: 'peak_score', sort_dir: 'desc', then_by: 'start_time', then_dir: 'desc' })
})

it('shows owners separately and changes the claim action to Investigate after success', async () => {
  const alert = { ...mappedAlerts()[0], owner: null }
  api.alerts.mockResolvedValue([alert])
  api.claimAlert.mockImplementation(async () => { api.alerts.mockResolvedValue([{ ...alert, owner: 'analyst' }]); return {} })
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  const row = await screen.findByRole('row', { name: 'Open alert 1', exact: true })
  expect(within(row).getByText('Unassigned')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Assign to me' }))
  expect(await screen.findByRole('link', { name: 'Investigate' })).toHaveAttribute('href', '/my-cases/1')
  expect(api.claimAlert).toHaveBeenCalledWith(1)
  expect(screen.queryByRole('combobox', { name: 'Status' })).not.toBeInTheDocument()
})

it('offers View only for another analyst\'s cases and closed cases', async () => {
  api.alerts.mockResolvedValue([{ ...mappedAlerts()[0], owner: 'other' }, { ...mappedAlerts()[1], owner: 'analyst', status: 'closed' }])
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1' })
  expect(screen.getAllByRole('link', { name: 'View' })).toHaveLength(2)
  expect(screen.queryByRole('button', { name: 'Assign to me' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Investigate' })).not.toBeInTheDocument()
})

it('lets administrators assign and reassign from a workload-aware dialog', async () => {
  authState.role = 'admin'
  api.alerts.mockResolvedValue([{ ...mappedAlerts()[0], owner: null }, { ...mappedAlerts()[1], owner: 'other', status: 'closed' }])
  api.teamWorkload.mockResolvedValue([{ username: 'other', open: 2, under_investigation: 1, closed_total: 4 }])
  api.assignAlert.mockResolvedValue({})
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  expect(await screen.findByRole('region', { name: 'Team workload' })).toBeInTheDocument()
  fireEvent.click(await screen.findByRole('button', { name: 'Reassign' }))
  await screen.findByRole('option', { name: 'other (3 active cases)' })
  fireEvent.click(screen.getByRole('button', { name: 'Save owner' }))
  await waitFor(() => expect(api.assignAlert).toHaveBeenCalledWith(2, 'other'))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  expect(screen.getByRole('button', { name: 'Assign', exact: true })).toBeInTheDocument()
})

it('restores the owner filter from the URL and forwards owner sorting', async () => {
  render(<MemoryRouter initialEntries={['/alerts?owner=me&sort_by=owner&then_by=']}><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1' })
  expect(screen.getByLabelText('Owner')).toHaveValue('me')
  expect(api.alerts).toHaveBeenCalledWith({ limit: 1000, owner: 'me', sort_by: 'owner', sort_dir: 'desc', then_by: '', then_dir: 'desc' })
})

it('shows closed case outcome badges and filters by outcome', async () => {
  const rows = [
    { ...mappedAlerts()[0], status: 'closed', owner: 'analyst', outcome: 'true_positive' },
    { ...mappedAlerts()[1], status: 'closed', owner: 'another', outcome: null },
  ]
  api.alerts.mockImplementation(async params => params.outcome ? rows.filter(a => a.outcome === params.outcome) : rows)
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  const first = within(await screen.findByRole('row', { name: 'Open alert 1', exact: true }))
  expect(first.getByText('True positive')).toBeInTheDocument()
  expect(first.getByText('analyst')).toBeInTheDocument()
  expect(within(screen.getByRole('row', { name: 'Open alert 2', exact: true })).getByText('No outcome')).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'true_positive' } })
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ outcome: 'true_positive' })))
  expect(await screen.findByRole('link', { name: 'Case #1' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Case #2' })).not.toBeInTheDocument()
})
