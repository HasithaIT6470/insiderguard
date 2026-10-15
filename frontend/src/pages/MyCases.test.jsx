import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import MyCases from './MyCases.jsx'
import { api } from '../api'

const auth = vi.hoisted(() => ({ role: 'analyst', username: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth }) }))
vi.mock('../api', () => ({ api: { myCases: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks(); auth.role = 'analyst'
  api.myCases.mockResolvedValue({ summary: { total: 3, open: 2, under_investigation: 1, closed: 0, oldest_open_age_hours: 48 },
    cases: [
      { id: 1, user_id: 'u1', category: 'High', peak_score: 50, status: 'open', age_hours: 48 },
      { id: 2, user_id: 'u2', category: 'Critical', peak_score: 90, status: 'open', age_hours: 20 },
      { id: 3, user_id: 'u3', category: 'Critical', peak_score: 80, status: 'under_investigation', age_hours: 40 },
    ] })
})

it('shows assigned cases, sorts by severity then age, and filters statuses and severity', async () => {
  render(<MemoryRouter><MyCases /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Case #1' })
  expect(screen.getByText('48 h')).toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: /^Case #/ }).map(l => l.textContent)).toEqual(['Case #3', 'Case #2', 'Case #1'])
  expect(screen.getByRole('link', { name: 'u1' })).toHaveAttribute('href', '/users/u1')
  fireEvent.change(screen.getByLabelText('Severity'), { target: { value: 'Critical' } })
  expect(screen.queryByRole('link', { name: 'Case #1' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Case status'), { target: { value: 'closed' } })
  await waitFor(() => expect(api.myCases).toHaveBeenLastCalledWith({ status: 'closed' }))
})

it('redirects administrators out of My cases', async () => {
  auth.role = 'admin'
  render(<MemoryRouter initialEntries={['/my-cases']}><Routes><Route path="/my-cases" element={<MyCases />} /><Route path="/alerts" element={<p>Read-only alerts</p>} /></Routes></MemoryRouter>)
  expect(await screen.findByText('Read-only alerts')).toBeInTheDocument()
  expect(api.myCases).not.toHaveBeenCalled()
})
