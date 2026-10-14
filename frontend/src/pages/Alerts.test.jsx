import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api } from '../api'
import Alerts from './Alerts.jsx'

vi.mock('../api', () => ({ api: { alerts: vi.fn() } }))

beforeEach(() => {
  api.alerts.mockResolvedValue(Array.from({ length: 21 }, (_, index) => ({
    id: index + 1, user_id: `user-${index + 1}`, department: index ? 'Engineering' : 'Finance',
    peak_score: 100 - index, category: index ? 'High' : 'Critical', status: index ? 'closed' : 'open',
    start_time: '2026-10-01T10:00:00', breakdown: [{ name: index ? 'Bulk download' : 'Decoy access' }],
  })))
})

it('paginates the loaded queue and links to alert investigations', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  expect(await screen.findByRole('link', { name: 'Alert #1', exact: true })).toHaveAttribute('href', '/alerts/1')
  expect(api.alerts).toHaveBeenCalledWith({ limit: 1000 })
  expect(screen.queryByRole('link', { name: 'Alert #21', exact: true })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
  expect(screen.getByRole('link', { name: 'Alert #21', exact: true })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Risk level'), { target: { value: 'Critical' } })
  expect(screen.getByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument()
  expect(screen.getByText('Page 1 of 1')).toBeInTheDocument()
})

it('combines filters and indicator search, then clears an empty result', async () => {
  render(<MemoryRouter><Alerts /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Alert #1', exact: true })
  fireEvent.change(screen.getByLabelText('Search alerts'), { target: { value: 'Decoy' } })
  fireEvent.change(screen.getByLabelText('Department'), { target: { value: 'Finance' } })
  expect(screen.getByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Case status'), { target: { value: 'closed' } })
  expect(screen.getByText('No alerts match these filters.')).toBeInTheDocument()
  fireEvent.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
  await waitFor(() => expect(screen.getByRole('link', { name: 'Alert #1', exact: true })).toBeInTheDocument())
  expect(screen.getByLabelText('Search alerts')).toHaveValue('')
})
