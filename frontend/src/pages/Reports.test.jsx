import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api } from '../api'
import Reports from './Reports.jsx'

vi.mock('../api', () => ({ api: { summary: vi.fn(), report: vi.fn(), reportCsv: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  api.summary.mockResolvedValue({ departments: { 'Research Lab': {}, Finance: {} } })
  api.report.mockImplementation(async params => ({
    generated_at: '2026-10-01T10:00:00', filters: params,
    coverage: { events_analysed: 1200, users_monitored: 10, baselines_established: 8 },
    alerts_by_category: {}, alerts: [],
  }))
})

it('uses discovered departments and includes the entire final day', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Research Lab' })
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-01' } })
  fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-03' } })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Research Lab' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await screen.findByText('Insider risk findings')
  expect(api.report).toHaveBeenCalledWith({ start: '2026-09-01T00:00:00Z', end: '2026-09-03T23:59:59.999999Z', department: 'Research Lab' })
  expect(screen.getByText('No alerts were found for this reporting scope.')).toBeInTheDocument()
})

it('rejects a reversed reporting period before requesting a report', async () => {
  render(<MemoryRouter><Reports /></MemoryRouter>)
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-09-03' } })
  fireEvent.change(screen.getByLabelText('To'), { target: { value: '2026-09-01' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  expect(screen.getByRole('alert')).toHaveTextContent('The end date must be on or after the start date.')
  expect(api.report).not.toHaveBeenCalled()
})

it('exports the displayed scope after draft edits and surfaces export failures', async () => {
  api.reportCsv.mockRejectedValue(new Error('Export unavailable'))
  render(<MemoryRouter><Reports /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Export CSV' })).toBeDisabled()
  await screen.findByRole('option', { name: 'Finance' })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Finance' } })
  fireEvent.click(screen.getByRole('button', { name: 'Generate report' }))
  await screen.findByText('Insider risk findings')
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Research Lab' } })
  fireEvent.click(screen.getByRole('button', { name: 'Export CSV' }))
  await waitFor(() => expect(api.reportCsv).toHaveBeenCalledWith({ department: 'Finance' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Export unavailable')
})
