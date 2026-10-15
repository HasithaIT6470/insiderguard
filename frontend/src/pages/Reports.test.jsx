import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api } from '../api'
import Reports from './Reports.jsx'

vi.mock('../api', () => ({ api: { summary: vi.fn(), users: vi.fn(), reportIndicators: vi.fn(), reportRange: vi.fn(), report: vi.fn(), reportCsv: vi.fn() } }))
vi.mock('react-chartjs-2', () => ({ Bar: props => <div role="img" aria-label={props['aria-label']} />, Doughnut: props => <div role="img" aria-label={props['aria-label']} /> }))

beforeEach(() => {
  vi.clearAllMocks()
  api.summary.mockResolvedValue({ departments: { 'Research Lab': {}, Finance: {} } })
  api.users.mockResolvedValue([{ user_id: 'u1' }])
  api.reportIndicators.mockResolvedValue(['decoy', 'download'])
  api.reportRange.mockResolvedValue({ first_event: '2026-10-01T12:00:00', last_event: '2026-10-04T12:00:00' })
  api.report.mockImplementation(async params => ({
    generated_at: '2026-10-01T10:00:00', filters: params,
    coverage: { events_analysed: 1200, users_monitored: 10, baselines_established: 8 },
    alerts_by_category: {}, alerts: [],
    summary: { total_alerts: 0, avg_peak_score: 0, max_peak_score: 0, open_count: 0, closed_count: 0, alerts_by_category: {}, alerts_by_day: {}, top_indicators: [], top_users: [] },
  }))
})

it('filters by owner and outcome, showing verdict columns and the outcome chart', async () => {
  api.report.mockImplementation(async filters => ({ generated_at: '2026-10-01T10:00:00', filters,
    coverage: { events_analysed: 1, users_monitored: 1, baselines_established: 0 },
    alerts: [{ alert_id: 7, user_id: 'u1', department: 'Finance', start_time: '2026-10-01T09:00:00', peak_score: 70, category: 'High', status: 'closed', owner: 'viewer', outcome: 'true_positive', indicators: 'bulk_download' }],
    summary: { total_alerts: 1, avg_peak_score: 70, max_peak_score: 70, open_count: 0, closed_count: 1,
      alerts_by_category: { High: 1 }, alerts_by_day: {}, top_indicators: [], top_users: [], alerts_by_outcome: { true_positive: 1, false_positive: 0, benign_explained: 0, no_outcome: 0 } },
  }))
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.change(screen.getByLabelText('Owner'), { target: { value: 'viewer' } })
  fireEvent.click(screen.getByLabelText('True positive'))
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await waitFor(() => expect(api.report).toHaveBeenCalledWith(expect.objectContaining({ owner: 'viewer', outcome: 'true_positive' })))
  expect(await screen.findByRole('img', { name: 'Report outcomes' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Owner' })).toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'Outcome' })).toBeInTheDocument()
  expect(screen.getByRole('cell', { name: 'viewer' })).toBeInTheDocument()
})

it('uses discovered departments and includes the entire final day', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Research Lab' })
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
  fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-03' } })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Research Lab' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await screen.findByText('Insider risk findings')
  expect(api.report).toHaveBeenCalledWith(expect.objectContaining({ start: '2026-09-01', end: '2026-09-03', department: 'Research Lab' }))
  expect(screen.getByText('No alerts were found for this reporting scope.')).toBeInTheDocument()
})

it('rejects a reversed reporting period before requesting a report', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-03' } })
  fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-01' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  expect(screen.getByRole('alert')).toHaveTextContent('From date is after To date')
  expect(api.report).not.toHaveBeenCalled()
})

it('exports the displayed scope after draft edits and surfaces export failures', async () => {
  api.reportCsv.mockRejectedValue(new Error('Export unavailable'))
  render(<MemoryRouter><Reports /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Download CSV' })).toBeDisabled()
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Finance' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await screen.findByText('Insider risk findings')
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Research Lab' } })
  fireEvent.click(screen.getByRole('button', { name: 'Download CSV' }))
  await waitFor(() => expect(api.reportCsv).toHaveBeenCalledWith(expect.objectContaining({ department: 'Finance' })))
  expect(await screen.findByRole('alert')).toHaveTextContent('Export unavailable')
})

it('anchors date presets to the dataset and supports all time', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.click(screen.getByRole('button', { name: 'Last 7 days' }))
  expect(screen.getByLabelText('From')).toHaveValue('2026-09-28')
  expect(screen.getByLabelText('To')).toHaveValue('2026-10-04')
  fireEvent.click(screen.getByRole('button', { name: 'Last 14 days' }))
  expect(screen.getByLabelText('From')).toHaveValue('2026-09-21')
  fireEvent.click(screen.getByRole('button', { name: 'Last 30 days' }))
  expect(screen.getByLabelText('From')).toHaveValue('2026-09-05')
  fireEvent.click(screen.getByRole('button', { name: 'All time' }))
  expect(screen.getByLabelText('From')).toHaveValue('')
  expect(screen.getByLabelText('To')).toHaveValue('')
})

it('combines advanced filters and regenerates when an applied filter chip is removed', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.click(screen.getByLabelText('High'))
  fireEvent.click(screen.getByLabelText('Critical'))
  fireEvent.click(screen.getByLabelText('Open'))
  fireEvent.click(screen.getByText('Advanced filters'))
  fireEvent.change(screen.getByLabelText('Minimum score'), { target: { value: '50' } })
  fireEvent.change(screen.getByLabelText('Maximum score'), { target: { value: '90' } })
  fireEvent.change(screen.getByLabelText('User ID'), { target: { value: 'u1' } })
  fireEvent.change(screen.getByLabelText('Indicator'), { target: { value: 'decoy' } })
  fireEvent.change(screen.getByLabelText('Sort by'), { target: { value: 'category' } })
  fireEvent.change(screen.getByLabelText('Sort direction'), { target: { value: 'asc' } })
  fireEvent.change(screen.getByLabelText('Top N'), { target: { value: '10' } })
  fireEvent.change(screen.getByLabelText('Group by'), { target: { value: 'department' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await screen.findByText('Insider risk findings')
  expect(api.report).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'High,Critical', status: 'open', min_score: '50', max_score: '90', user_id: 'u1', indicator: 'decoy', sort_by: 'category', sort_dir: 'asc', limit: 10, group_by: 'department' }))
  fireEvent.click(screen.getByRole('button', { name: 'Remove High', exact: true }))
  await waitFor(() => expect(api.report).toHaveBeenLastCalledWith(expect.objectContaining({ category: 'Critical' })))
})

it('validates score ranges and row limits before requesting a report', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.click(screen.getByText('Advanced filters'))
  fireEvent.change(screen.getByLabelText('Minimum score'), { target: { value: '90' } })
  fireEvent.change(screen.getByLabelText('Maximum score'), { target: { value: '30' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Minimum score must not exceed maximum score')
  expect(api.report).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Reset filters' }))
  fireEvent.change(screen.getByLabelText('Top N'), { target: { value: '1001' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  expect(screen.getByRole('alert')).toHaveTextContent('Top N must be an integer between 1 and 1000')
  expect(api.report).not.toHaveBeenCalled()
})

it('renders summary charts, groups, and investigation links', async () => {
  api.report.mockImplementation(async params => ({
    generated_at: '2026-10-04T12:00:00', filters: params, coverage: { events_analysed: 20, users_monitored: 1, baselines_established: 1 }, alerts_by_category: { High: 1 },
    alerts: [{ alert_id: 7, user_id: 'u1', department: 'Finance', peak_score: 80, category: 'High', status: 'open', start_time: '2026-10-04T11:00:00', indicators: 'decoy(50)' }],
    summary: { total_alerts: 1, avg_peak_score: 80, max_peak_score: 80, open_count: 1, closed_count: 0, alerts_by_category: { High: 1 }, alerts_by_day: { '2026-10-04': 1 }, top_indicators: [{ name: 'decoy', count: 1 }], top_users: [{ user_id: 'u1', count: 1, max_score: 80 }] },
    groups: [{ key: 'Finance', count: 1, avg_score: 80, max_score: 80 }],
  }))
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.click(screen.getByText('Advanced filters'))
  fireEvent.change(screen.getByLabelText('Group by'), { target: { value: 'department' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  expect(await screen.findByRole('img', { name: 'Alerts by risk level' })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Alerts by day' })).toBeInTheDocument()
  expect(screen.getByRole('img', { name: 'Top indicators' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Grouped by department' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Case #7' })).toHaveAttribute('href', '/alerts/7')
  expect(screen.getAllByRole('link', { name: 'u1' })[0]).toHaveAttribute('href', '/users/u1')
})
