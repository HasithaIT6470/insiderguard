import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App from './App.jsx'
import { api, setAuth } from './api'

vi.mock('./api', async original => ({ ...await original(), api: { escalationSummary: vi.fn().mockResolvedValue({ open_count: 2, overdue_count: 1 }), myCases: vi.fn() } }))
vi.mock('./pages/Alerts.jsx', () => ({ default: () => <h1>Alerts route</h1> }))

afterEach(() => sessionStorage.clear())

it.each(['/my-cases', '/my-cases/1'])('redirects administrators from %s to Alerts', async path => {
  setAuth({ username: 'admin', role: 'admin', token: 'test' })
  render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: 'Alerts route' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'My cases' })).not.toBeInTheDocument()
})

it('shows the analyst My cases link and active case count', async () => {
  setAuth({ username: 'analyst', role: 'analyst', token: 'test' })
  api.myCases.mockResolvedValue({ cases: [], summary: { open: 2, under_investigation: 1, closed: 4 } })
  render(<MemoryRouter initialEntries={['/alerts']}><App /></MemoryRouter>)
  expect(screen.getByRole('link', { name: /My cases/ })).toHaveAttribute('href', '/my-cases')
  expect(await screen.findByLabelText('Active cases')).toHaveTextContent('3')
  expect(screen.getByRole('link', { name: /My escalations/ })).toHaveAttribute('href', '/escalations')
  expect(await screen.findByLabelText('Open escalations')).toHaveTextContent('2')
  expect(screen.getByLabelText('Open escalations')).toHaveClass('bg-danger')
})
