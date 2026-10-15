import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import Alerts from './Alerts.jsx'

vi.mock('../api', () => ({ api: { alerts: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  api.alerts.mockResolvedValue(Array.from({ length: 21 }, (_, index) => ({
    id: index + 1, user_id: `user-${index + 1}`, department: index ? 'Engineering' : 'Finance',
    peak_score: 100 - index, category: index ? 'High' : 'Critical', status: index ? 'closed' : 'open',
    start_time: '2026-10-01T10:00:00', breakdown: [{ name: index ? 'Bulk download' : 'Decoy access' }],
  })))
})

it('paginates the loaded queue and links to alert investigations', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: 'Alert #1', exact: true })).toHaveAttribute('href', '/alerts/1')
  expect(api.alerts).toHaveBeenCalledWith({ limit: 1000, sort_by: 'peak_score', sort_dir: 'desc', then_by: 'start_time', then_dir: 'desc' })
  expect(screen.queryByRole('link', { name: 'Alert #21', exact: true })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
  expect(screen.getByRole('link', { name: 'Alert #21', exact: true })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Risk level'), { target: { value: 'Critical' } })
  expect(await screen.findByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument()
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument()
})

it('combines filters and indicator search, then clears an empty result', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  fireEvent.change(screen.getByLabelText('Search alerts'), { target: { value: 'Decoy' } })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Finance' } })
  expect(await screen.findByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Case status'), { target: { value: 'closed' } })
  expect(await screen.findByText('No alerts match these filters.')).toBeInTheDocument()
  fireEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  await waitFor(() => expect(screen.getByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument())
  expect(screen.getByLabelText('Search alerts')).toHaveValue('')
})

function NavigationProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><output aria-label="URL">{location.search}</output><button onClick={() => navigate(-1)}>Back</button></>
}

it('restores URL sort settings, supports None, and resets to the default order', async () => {
  render(<MemoryRouter initialEntries={['/alerts?sort_by=category&sort_dir=asc&then_by=status&then_dir=asc&keep=yes']}><Alerts /><NavigationProbe /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  expect(screen.getByLabelText('Sort by')).toHaveValue('category')
  expect(screen.getByLabelText('Then by')).toHaveValue('status')
  expect(screen.getByRole('button', { name: 'Risk level', exact: true }).closest('th')).toHaveAttribute('aria-sort', 'ascending')
  fireEvent.change(screen.getByLabelText('Then by'), { target: { value: '' } })
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  expect(screen.getByRole('button', { name: 'Secondary sort direction: ascending' })).toBeDisabled()
  expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ then_by: '' }))
  fireEvent.click(screen.getByRole('button', { name: 'Reset sort' }))
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  expect(screen.getByLabelText('Sort by')).toHaveValue('peak_score')
  expect(screen.getByLabelText('Then by')).toHaveValue('start_time')
  expect(screen.getByLabelText('URL')).toHaveTextContent('keep=yes')
})

it('keeps header sorting, direction toggles, and browser Back synchronized', async () => {
  render(<MemoryRouter><Alerts /><NavigationProbe /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  fireEvent.click(screen.getByRole('button', { name: 'Department', exact: true }))
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  expect(screen.getByLabelText('Sort by')).toHaveValue('department')
  expect(screen.getByRole('button', { name: 'Department', exact: true }).closest('th')).toHaveAttribute('aria-sort', 'ascending')
  fireEvent.click(screen.getByRole('button', { name: 'Department', exact: true }))
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  expect(screen.getByRole('button', { name: 'Department', exact: true }).closest('th')).toHaveAttribute('aria-sort', 'descending')
  fireEvent.click(screen.getByRole('button', { name: 'Back' }))
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ sort_by: 'department', sort_dir: 'asc' })))
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  expect(screen.getByRole('button', { name: 'Primary sort direction: ascending' })).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Primary sort direction: ascending' }))
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ sort_dir: 'desc' })))
})

it('forwards status and level filters with sorting', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  fireEvent.change(screen.getByLabelText('Case status'), { target: { value: 'open' } })
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  fireEvent.change(screen.getByLabelText('Risk level'), { target: { value: 'Critical' } })
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'indicator_count' } })
  await waitFor(() => expect(api.alerts).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'open', category: 'Critical', sort_by: 'indicator_count' })))
})

it('preserves the returned server order instead of re-sorting the loaded subset', async () => {
  api.alerts.mockResolvedValueOnce([2, 1].map(id => ({ id, user_id: `user-${id}`, department: 'Finance', peak_score: id === 2 ? 10 : 100, category: 'High', status: 'open', start_time: '2026-10-01T10:00:00', breakdown: [] })))
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #2', exact: true })
  expect(screen.getAllByRole('link', { name: /^Alert #/ }).map(link => link.textContent)).toEqual(['Alert #2', 'Alert #1'])
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
  await screen.findByRole('link', { name: 'Alert #2', exact: true })
  fireEvent.change(screen.getByLabelText('Search alerts'), { target: { value: query } })
  expect(screen.getByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Alert #2', exact: true })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: /T1110 · Brute Force/ })).not.toBeInTheDocument()
  expect(screen.queryByText('T1110', { exact: true })).not.toBeInTheDocument()
})

it('filters tactics locally and clears the selection without changing API parameters', async () => {
  api.alerts.mockResolvedValue(mappedAlerts())
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #2', exact: true })
  const calls = api.alerts.mock.calls.length
  fireEvent.change(screen.getByLabelText('ATT&CK tactic'), { target: { value: 'TA0006' } })
  expect(screen.getByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Alert #2', exact: true })).not.toBeInTheDocument()
  expect(api.alerts.mock.calls.length).toBe(calls)
  fireEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  expect(screen.getByLabelText('ATT&CK tactic')).toHaveValue('')
  expect(screen.getByRole('link', { name: 'Alert #2', exact: true })).toBeInTheDocument()
  expect(api.alerts).toHaveBeenLastCalledWith({ limit: 1000, sort_by: 'peak_score', sort_dir: 'desc', then_by: 'start_time', then_dir: 'desc' })
})
