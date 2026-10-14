import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from '../api'
import Profile from './Profile.jsx'

const updateToken = vi.hoisted(() => vi.fn())
vi.mock('../App.jsx', () => ({ useAuth: () => ({ updateToken }) }))
vi.mock('../api', () => ({ api: { me: vi.fn(), changePassword: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  api.me.mockResolvedValue({ username: 'viewer', role: 'analyst', created_at: '2026-10-01T10:00:00' })
  api.changePassword.mockResolvedValue({ access_token: 'fresh-token', token_type: 'bearer' })
})

function fill(current = 'CurrentPass123', next = 'Replacement5678', confirmation = next) {
  fireEvent.change(screen.getByLabelText('Current password'), { target: { value: current } })
  fireEvent.change(screen.getByLabelText('New password'), { target: { value: next } })
  fireEvent.change(screen.getByLabelText('Confirm password'), { target: { value: confirmation } })
}

it.each(['admin', 'analyst'])('shows only the signed-in %s profile and replaces the token after a change', async role => {
  api.me.mockResolvedValue({ username: 'viewer', role, created_at: '2026-10-01T10:00:00' })
  render(<Profile />)
  await screen.findByText('viewer')
  expect(screen.getByText(role === 'admin' ? 'Admin' : 'Analyst')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  fill()
  expect(screen.getByRole('button', { name: 'Change password' })).toBeEnabled()
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByRole('status')).toHaveTextContent('You are still signed in')
  expect(api.changePassword).toHaveBeenCalledWith('CurrentPass123', 'Replacement5678')
  expect(updateToken).toHaveBeenCalledWith('fresh-token')
  for (const label of ['Current password', 'New password', 'Confirm password']) expect(screen.getByLabelText(label)).toHaveValue('')
})

it('requires every policy rule and matching confirmation before enabling submit', async () => {
  render(<Profile />)
  await screen.findByText('viewer')
  for (const next of ['short1', 'nodigitpassword', '12345678901', 'prefixVIEWER12345', 'CurrentPass123', '\u00e9'.repeat(36) + 'A1']) {
    fill('CurrentPass123', next)
    expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  }
  fill('CurrentPass123', 'Replacement5678', 'different')
  expect(screen.getByRole('button', { name: 'Change password' })).toBeDisabled()
  fill()
  expect(screen.getByRole('button', { name: 'Change password' })).toBeEnabled()
  expect(screen.getByText('Matches confirmation').closest('li')).toHaveClass('is-met')
})

it('toggles each password field independently and displays API errors without updating auth', async () => {
  api.changePassword.mockRejectedValueOnce(new Error('Current password is incorrect'))
  render(<Profile />)
  await screen.findByText('viewer')
  for (const label of ['Current password', 'New password', 'Confirm password']) {
    fireEvent.click(screen.getByRole('button', { name: `Show ${label.toLowerCase()}` }))
    expect(screen.getByLabelText(label)).toHaveAttribute('type', 'text')
    fireEvent.click(screen.getByRole('button', { name: `Hide ${label.toLowerCase()}` }))
    expect(screen.getByLabelText(label)).toHaveAttribute('type', 'password')
  }
  fill()
  fireEvent.click(screen.getByRole('button', { name: 'Change password' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Current password is incorrect')
  expect(updateToken).not.toHaveBeenCalled()
  await waitFor(() => expect(screen.getByRole('button', { name: 'Change password' })).toBeEnabled())
})
