import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Users from './Users.jsx'
import { api } from '../api'

const auth = vi.hoisted(() => ({ role: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth }) }))
vi.mock('../userCharts.jsx', () => ({ UserChart: ({ title }) => <div>{title}</div> }))
vi.mock('../api', () => ({ api: { users: vi.fn(), usersStats: vi.fn(), adminEmployees: vi.fn(), createEmployee: vi.fn(), importEmployees: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks(); auth.role = 'analyst'
  HTMLDialogElement.prototype.showModal = vi.fn(function () { this.setAttribute('open', '') })
  HTMLDialogElement.prototype.close = vi.fn(function () { this.removeAttribute('open') })
  api.users.mockResolvedValue([{ user_id: 'log.id', department: 'Engineering', risk_category: 'High', open_case_count: 2, baseline_status: 'established', has_profile: false }])
  api.usersStats.mockResolvedValue({ users_by_department: { Engineering: 1 }, risk_distribution: { High: 1 }, baseline_status_counts: { established: 1 }, event_volume_by_department: { Engineering: 50 } })
  api.adminEmployees.mockResolvedValue({ profiles: [{ user_id: 'preregistered', pre_registered: true }], missing_profiles: ['log.id'], stats: { completeness_percent: 0, missing_count: 1 } })
})
const mount = () => render(<MemoryRouter><Routes><Route path="/" element={<Users />} /><Route path="/users/:id" element={<p>Opened profile</p>} /></Routes></MemoryRouter>)

it('shows staff charts and linked IDs without requesting directory data for analysts', async () => {
  mount()
  expect(await screen.findByRole('link', { name: 'log.id' })).toHaveAttribute('href', '/users/log.id')
  expect(screen.getByText('Users by department')).toBeInTheDocument()
  expect(screen.getByText('Risk distribution')).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add employee profile' })).not.toBeInTheDocument()
  expect(api.adminEmployees).not.toHaveBeenCalled()
  fireEvent.keyDown(screen.getByRole('row', { name: 'View user log.id' }), { key: 'Enter' })
  expect(await screen.findByText('Opened profile')).toBeInTheDocument()
})

it('offers admin controls, includes preregistrations, and filters missing profiles', async () => {
  auth.role = 'admin'; mount()
  expect(await screen.findByRole('link', { name: 'preregistered' })).toHaveAttribute('href', '/users/preregistered')
  expect(screen.getByRole('link', { name: 'Download CSV template' })).toHaveAttribute('download', 'employee-directory-template.csv')
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

it('shows import row errors and refreshes the directory after upload', async () => {
  auth.role = 'admin'; mount()
  api.importEmployees.mockResolvedValue({ accepted: 1, rejected: 1, errors: [{ row: 3, message: 'email: invalid email address' }] })
  fireEvent.change(screen.getByLabelText('Import directory (CSV)'), { target: { files: [new File(['csv'], 'directory.csv', { type: 'text/csv' })] } })
  expect(await screen.findByText('Row 3: email: invalid email address')).toBeInTheDocument()
  expect(api.importEmployees).toHaveBeenCalled()
})
