import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import App, { useAuth } from './App.jsx'
import { api, getAuth, setAuth } from './api'

vi.mock('./api', async importOriginal => ({ ...await importOriginal(), api: { escalationSummary: vi.fn().mockResolvedValue({ open_count: 2, overdue_count: 1 }), me: vi.fn(), changePassword: vi.fn(), myCases: vi.fn().mockResolvedValue({ summary: { open: 0, under_investigation: 0 } }) } }))
vi.mock('./pages/Alerts.jsx', () => ({ default: function AuthProbe() { const { auth } = useAuth(); return <h1>{auth.token}</h1> } }))

afterEach(() => sessionStorage.clear())

it('keeps the current session signed in and updates both storage and React auth state', async () => {
  setAuth({ username: 'viewer', role: 'analyst', token: 'old-token' })
  api.me.mockResolvedValue({ username: 'viewer', role: 'analyst', created_at: '2026-10-01T10:00:00' })
  api.changePassword.mockResolvedValue({ access_token: 'fresh-token', token_type: 'bearer' })
  render(<MemoryRouter initialEntries={['/profile']}><App /></MemoryRouter>)
  await screen.findByLabelText('Current password')
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: 'CurrentPass123' } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: 'Replacement5678' } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: 'Replacement5678' } })
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByRole('status')).toHaveTextContent('You are still signed in')
  expect(getAuth()).toEqual({ username: 'viewer', role: 'analyst', token: 'fresh-token' })
  fireEvent.click(screen.getByRole('link', { name: 'Alerts', exact: true }))
  expect(await screen.findByRole('heading', { name: 'fresh-token' })).toBeInTheDocument()
})
