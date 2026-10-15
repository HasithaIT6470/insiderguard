import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import UserProfile from './UserProfile.jsx'
import { api } from '../api'

const auth = vi.hoisted(() => ({ role: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth }) }))
vi.mock('../userCharts.jsx', () => ({ UserChart: ({ title }) => <div>{title}</div> }))
vi.mock('../api', () => ({ api: { userOverview: vi.fn(), adminEmployee: vi.fn(), employeeContacts: vi.fn(), addEmployeeContact: vi.fn(), offboardEmployee: vi.fn(), createEmployee: vi.fn(), updateEmployee: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks(); auth.role = 'analyst'
  HTMLDialogElement.prototype.showModal = vi.fn(function () { this.setAttribute('open', '') })
  HTMLDialogElement.prototype.close = vi.fn(function () { this.removeAttribute('open') })
  api.userOverview.mockResolvedValue({ user_id: 'log.id', department: 'Engineering', current_risk: { score: 60, category: 'High' }, baseline_status: 'established', has_profile: true,
    activity_heatmap: Array.from({ length: 7 }, () => Array(24).fill(0)), activity_window: {}, risk_trend: [], event_type_breakdown: {}, baseline_vs_recent: { download_mb: {}, file_access: {} }, recent_window: {}, devices: [],
    case_history: [{ id: 42, category: 'High', status: 'closed', owner: 'reviewer', outcome: 'true_positive', peak_score: 60 }], case_notes: [{ id: 1, alert_id: 42, author: 'reviewer', note: 'Investigation context' }], escalations: [] })
  api.adminEmployee.mockResolvedValue({ user_id: 'log.id', full_name: 'Private Admin Name', employment_status: 'active' })
  api.employeeContacts.mockResolvedValue([])
})
const mount = () => render(<MemoryRouter initialEntries={['/users/log.id']}><Routes><Route path="/users/:id" element={<UserProfile />} /></Routes></MemoryRouter>)

it('shows activity, cases, notes and escalation tabs, with no personal requests for analysts', async () => {
  mount()
  await screen.findByRole('heading', { name: 'log.id' })
  expect(screen.getByText('Contact details are restricted to administrators')).toBeInTheDocument()
  expect(screen.getByRole('img', { name: /Activity heatmap/ })).toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Personal information' })).not.toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Contact log' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Case history' }))
  expect(screen.getByRole('link', { name: 'Case #42' })).toHaveAttribute('href', '/alerts/42')
  expect(screen.getByText('reviewer')).toBeInTheDocument()
  expect(screen.getByText('True positive')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Analyst notes' }))
  expect(screen.getByText('Investigation context')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Escalations' }))
  expect(screen.getByText('No escalations yet.')).toBeInTheDocument()
  expect(api.adminEmployee).not.toHaveBeenCalled(); expect(api.employeeContacts).not.toHaveBeenCalled()
})

it('loads admin personal information only on its tab and confirms offboarding', async () => {
  auth.role = 'admin'; mount()
  await screen.findByRole('tab', { name: 'Personal information' })
  expect(api.adminEmployee).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('tab', { name: 'Personal information' }))
  expect(await screen.findByText('Private Admin Name')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Offboard' }))
  expect(api.offboardEmployee).not.toHaveBeenCalled()
  api.offboardEmployee.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: 'Confirm offboarding' }))
  await waitFor(() => expect(api.offboardEmployee).toHaveBeenCalledWith('log.id'))
})

it('prefills an immutable log ID when an admin creates a missing profile', async () => {
  auth.role = 'admin'; api.adminEmployee.mockRejectedValue({ status: 404 }); mount()
  fireEvent.click(await screen.findByRole('tab', { name: 'Personal information' }))
  await screen.findByText('No profile yet')
  expect(screen.getByLabelText('Log user ID')).toHaveValue('log.id')
  expect(screen.getByLabelText('Log user ID')).toHaveAttribute('readonly')
  expect(screen.getByLabelText('Department (from logs)')).toHaveValue('Engineering')
})

it('adds a private contact record through the admin tab', async () => {
  auth.role = 'admin'; mount()
  fireEvent.click(await screen.findByRole('tab', { name: 'Contact log' }))
  await screen.findByText('No contact records yet.')
  fireEvent.click(screen.getByRole('button', { name: 'Add contact record' }))
  fireEvent.change(screen.getByLabelText('Summary'), { target: { value: 'Contacted about case context' } })
  api.addEmployeeContact.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: 'Save contact record' }))
  await waitFor(() => expect(api.addEmployeeContact).toHaveBeenCalledWith('log.id', { method: 'email', summary: 'Contacted about case context' }))
})
