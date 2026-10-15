import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Users from './Users.jsx'
import { api } from '../api'

const auth = vi.hoisted(() => ({ role: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth }) }))
vi.mock('../userCharts.jsx', () => ({ UserChart: ({ title }) => <div>{title}</div> }))
vi.mock('../api', () => ({ api: { users: vi.fn(), usersStats: vi.fn(), adminEmployees: vi.fn(), createEmployee: vi.fn(), importEmployees: vi.fn(), removeUser: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks(); auth.role = 'analyst'
  HTMLDialogElement.prototype.showModal = vi.fn(function () { this.setAttribute('open', '') })
  HTMLDialogElement.prototype.close = vi.fn(function () { this.removeAttribute('open') })
  api.users.mockResolvedValue([{ user_id: 'log.id', department: 'Engineering', risk_category: 'High', open_case_count: 2, baseline_status: 'established', has_profile: false }])
  api.usersStats.mockResolvedValue({ users_by_department: { Engineering: 1 }, risk_distribution: { High: 1 }, baseline_status_counts: { established: 1 }, event_volume_by_department: { Engineering: 50 } })
  api.adminEmployees.mockResolvedValue({ profiles: [{ user_id: 'preregistered', pre_registered: true }], missing_profiles: ['log.id'], stats: { completeness_percent: 0, missing_count: 1 } })
})
const mount = () => render(<MemoryRouter><Routes><Route path="/" element={<Users />} /><Route path="/users/:id" element={<p>Opened profile</p>} /></Routes></MemoryRouter>)

it('shows linked IDs without landing charts without requesting directory data for analysts', async () => {
  mount()
  expect(await screen.findByRole('link', { name: 'log.id' })).toHaveAttribute('href', '/users/log.id')
  expect(screen.queryByText('Users by department')).not.toBeInTheDocument()
  expect(api.usersStats).not.toHaveBeenCalled()
  expect(screen.queryByRole('button', { name: /Remove user/ })).not.toBeInTheDocument()
  expect(screen.queryByText('Risk distribution')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add employee profile' })).not.toBeInTheDocument()
  expect(api.adminEmployees).not.toHaveBeenCalled()
  fireEvent.keyDown(screen.getByRole('row', { name: 'View user log.id' }), { key: 'Enter' })
  expect(await screen.findByText('Opened profile')).toBeInTheDocument()
})

it('offers admin controls, includes preregistrations, and filters missing profiles', async () => {
  auth.role = 'admin'; mount()
  expect(await screen.findByRole('link', { name: 'preregistered' })).toHaveAttribute('href', '/users/preregistered')
  expect(screen.queryByText('Download CSV template')).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Import directory (CSV)')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: /1 users missing contact details/ }))
  expect(screen.queryByRole('link', { name: 'preregistered' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Add employee profile' }))
  expect(screen.getByRole('dialog', { name: 'Add employee profile' })).toBeInTheDocument()
  expect(screen.getByLabelText('Department (from logs)')).toHaveAttribute('readonly')
  fireEvent.change(screen.getByLabelText('Log user ID'), { target: { value: 'new.log.id' } })
  api.createEmployee.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: 'Create profile' }))
  await waitFor(() => expect(api.createEmployee).toHaveBeenCalledWith(expect.objectContaining({ user_id: 'new.log.id', employment_status: 'active' })))
})

it('confirms removal without navigating and refreshes the list', async () => {
  auth.role = 'admin'; mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Remove user log.id' }))
  expect(screen.getByRole('dialog', { name: 'Remove user log.id' })).toBeInTheDocument()
  expect(api.removeUser).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Remove user log.id' }))
  api.removeUser.mockRejectedValueOnce(new Error('Removal failed'))
  fireEvent.click(screen.getByRole('button', { name: 'Confirm removal' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Removal failed')
  api.users.mockResolvedValue([])
  api.removeUser.mockResolvedValue({ removed: true })
  fireEvent.click(screen.getByRole('button', { name: 'Confirm removal' }))
  await waitFor(() => expect(screen.queryByRole('link', { name: 'log.id' })).not.toBeInTheDocument())
  expect(api.removeUser).toHaveBeenCalledWith('log.id')
  expect(screen.queryByText('Opened profile')).not.toBeInTheDocument()
})
