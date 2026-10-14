import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { api } from '../api'
import Accounts from './Accounts.jsx'

const authState = vi.hoisted(() => ({ role: 'admin', username: 'rootadmin' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth: authState }) }))
vi.mock('../api', () => ({ api: { accounts: vi.fn(), createAccount: vi.fn(), deleteAccount: vi.fn(), resetPassword: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  authState.role = 'admin'
  api.accounts.mockResolvedValue([
    { id: 1, username: 'rootadmin', role: 'admin', created_at: '2026-10-01T10:00:00' },
    { id: 2, username: 'viewer', role: 'analyst', created_at: '2026-10-02T10:00:00' },
  ])
  api.createAccount.mockResolvedValue({})
  api.deleteAccount.mockResolvedValue({ deleted: 'viewer' })
  api.resetPassword.mockResolvedValue({ reset: 'viewer' })
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})

it.each(['admin', 'analyst'])('creates an %s account, toggles password visibility, and refreshes the list', async role => {
  render(<MemoryRouter><Accounts /></MemoryRouter>)
  await screen.findByText('viewer')
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
  const password = screen.getByLabelText('Password')
  fireEvent.change(password, { target: { value: 'StrongPass1234' } })
  fireEvent.click(screen.getByRole('button', { name: 'Show password' }))
  expect(password).toHaveAttribute('type', 'text')
  fireEvent.click(screen.getByRole('button', { name: 'Hide password' }))
  expect(password).toHaveAttribute('type', 'password')
  fireEvent.change(screen.getByLabelText('Role'), { target: { value: role } })
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  await waitFor(() => expect(api.createAccount).toHaveBeenCalledWith({ username: 'newuser', password: 'StrongPass1234', role }))
  expect(await screen.findByRole('status')).toHaveTextContent(`Created ${role} account newuser`)
  expect(api.accounts).toHaveBeenCalledTimes(2)
  expect(password).toHaveValue('')
})

it('protects the signed-in admin and confirms a named deletion before sending it', async () => {
  render(<MemoryRouter><Accounts /></MemoryRouter>)
  expect(await screen.findByRole('button', { name: 'Delete rootadmin' })).toBeDisabled()
  expect(screen.getByTitle('You cannot delete your own account')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reset password for rootadmin' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Delete viewer' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Delete account: viewer' }))
  expect(dialog.getByText(/This cannot be undone/)).toBeInTheDocument()
  expect(api.deleteAccount).not.toHaveBeenCalled()
  fireEvent.click(dialog.getByRole('button', { name: 'Delete account' }))
  await waitFor(() => expect(api.deleteAccount).toHaveBeenCalledWith(2))
  await waitFor(() => expect(api.accounts).toHaveBeenCalledTimes(2))
})

it('resets a target password and displays API errors inside the modal', async () => {
  api.resetPassword.mockRejectedValueOnce(new Error('Password must contain at least one letter and one digit'))
  render(<MemoryRouter><Accounts /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button', { name: 'Reset password for viewer' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Reset password: viewer' }))
  fireEvent.change(dialog.getByLabelText('New password'), { target: { value: 'nodigitpassword' } })
  fireEvent.click(dialog.getByRole('button', { name: 'Reset password' }))
  expect(await dialog.findByRole('alert')).toHaveTextContent('Password must contain at least one letter and one digit')
  fireEvent.change(dialog.getByLabelText('New password'), { target: { value: 'Replacement5678' } })
  fireEvent.click(dialog.getByRole('button', { name: 'Reset password' }))
  await waitFor(() => expect(api.resetPassword).toHaveBeenLastCalledWith(2, 'Replacement5678'))
  expect(await screen.findByRole('status')).toHaveTextContent('Existing sessions have been invalidated')
  expect(api.accounts).toHaveBeenCalledTimes(2)
})

it('shows API errors when account creation or deletion fails', async () => {
  api.createAccount.mockRejectedValueOnce(new Error('username already exists'))
  api.deleteAccount.mockRejectedValueOnce(new Error('Cannot delete the last remaining administrator'))
  render(<MemoryRouter><Accounts /></MemoryRouter>)
  await screen.findByText('viewer')
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'newuser' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'StrongPass1234' } })
  fireEvent.click(screen.getByRole('button', { name: 'Create account' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('username already exists')
  fireEvent.click(screen.getByRole('button', { name: 'Delete viewer' }))
  const dialog = within(screen.getByRole('dialog'))
  fireEvent.click(dialog.getByRole('button', { name: 'Delete account' }))
  expect(await dialog.findByRole('alert')).toHaveTextContent('Cannot delete the last remaining administrator')
})

it('redirects analysts and never requests the account list', async () => {
  authState.role = 'analyst'
  render(<MemoryRouter initialEntries={['/accounts']}><Routes><Route path="/accounts" element={<Accounts />} /><Route path="/" element={<h1>Dashboard</h1>} /></Routes></MemoryRouter>)
  expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
  expect(api.accounts).not.toHaveBeenCalled()
})
