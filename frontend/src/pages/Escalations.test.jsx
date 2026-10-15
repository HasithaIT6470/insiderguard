import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import Escalations from './Escalations.jsx'
import { api } from '../api'

const auth = vi.hoisted(() => ({ role: 'analyst', username: 'reviewer' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth }) }))
vi.mock('../api', () => ({ api: { escalations: vi.fn(), escalation: vi.fn(), acknowledgeEscalation: vi.fn(), requestEscalationInfo: vi.fn(), contactEscalation: vi.fn(), completeEscalation: vi.fn(), withdrawEscalation: vi.fn(), replyEscalation: vi.fn(), escalationsCsv: vi.fn() } }))
const row = { id: 7, alert_id: 12, user_id: 'u.id', created_by: 'reviewer', status: 'submitted', priority: 'urgent', age_hours: 25, overdue: true, summary: 'Please review the case evidence', recommendation: 'contact_user', case_status_at_filing: 'under_investigation', snapshot: { peak_score: 70, category: 'High', indicators: ['unusual_download'] }, messages: [], timeline: [{ id: 1, to_status: 'submitted', actor: 'reviewer', action: 'submitted' }] }
beforeEach(() => {
  vi.clearAllMocks(); auth.role = 'analyst'; auth.username = 'reviewer'
  api.escalations.mockResolvedValue([row]); api.escalation.mockResolvedValue(row)
  HTMLDialogElement.prototype.showModal = vi.fn(function () { this.setAttribute('open', '') })
  HTMLDialogElement.prototype.close = vi.fn(function () { this.removeAttribute('open') })
})
const mount = (path = '/escalations') => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/escalations" element={<Escalations />} /><Route path="/escalations/:id" element={<Escalations />} /></Routes></MemoryRouter>)

it('lists own escalations for analysts with ID links, filters and overdue badges', async () => {
  mount()
  expect(await screen.findByRole('link', { name: 'Escalation #7' })).toHaveAttribute('href', '/escalations/7')
  expect(screen.getByRole('heading', { name: 'My escalations' })).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'u.id' })).toHaveAttribute('href', '/users/u.id')
  expect(screen.getByRole('link', { name: 'Case #12' })).toHaveAttribute('href', '/my-cases/12')
  expect(screen.getByText(/25.0 h/)).toHaveClass('bg-danger')
  expect(screen.queryByRole('button', { name: 'Export CSV' })).not.toBeInTheDocument()
  expect(screen.queryByLabelText('Analyst')).not.toBeInTheDocument()
  fireEvent.click(screen.getByLabelText('Overdue only'))
  fireEvent.click(screen.getByLabelText('Needs information'))
  await waitFor(() => expect(api.escalations).toHaveBeenLastCalledWith({ overdue: 'true', status: 'needs_info' }))
})

it('provides admin analyst filtering and CSV export control', async () => {
  auth.role = 'admin'; mount()
  await screen.findByRole('link', { name: 'Escalation #7' })
  expect(screen.getByRole('button', { name: 'Export CSV' })).toBeEnabled()
  expect(screen.getByRole('link', { name: 'Case #12' })).toHaveAttribute('href', '/alerts/12')
  fireEvent.change(screen.getByLabelText('Analyst'), { target: { value: 'reviewer' } })
  await waitFor(() => expect(api.escalations).toHaveBeenLastCalledWith({ analyst: 'reviewer' }))
})

it('shows analyst replies and withdrawal only before acknowledgement', async () => {
  mount('/escalations/7')
  await screen.findByRole('heading', { name: 'Escalation #7' })
  expect(screen.getByRole('button', { name: 'Withdraw' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Send reply' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'Acknowledge' })).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Reply'), { target: { value: 'Additional evidence' } })
  api.replyEscalation.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: 'Send reply' }))
  await waitFor(() => expect(api.replyEscalation).toHaveBeenCalledWith('7', 'Additional evidence'))
})

it('allows an admin to acknowledge a submission before other handling actions', async () => {
  auth.role = 'admin'; auth.username = 'admin'; mount('/escalations/7')
  await screen.findByRole('heading', { name: 'Escalation #7' })
  expect(screen.getByRole('link', { name: /View user profile and contact details/ })).toHaveAttribute('href', '/users/u.id')
  expect(screen.queryByRole('button', { name: 'Mark as handled' })).not.toBeInTheDocument()
  api.acknowledgeEscalation.mockResolvedValue({})
  fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }))
  await waitFor(() => expect(api.acknowledgeEscalation).toHaveBeenCalledWith('7'))
})

it('requires a handling note and keeps contact summaries labelled private for the handler', async () => {
  auth.role = 'admin'; auth.username = 'admin'
  api.escalation.mockResolvedValue({ ...row, status: 'acknowledged', handled_by: 'admin', overdue: false })
  mount('/escalations/7')
  fireEvent.click(await screen.findByRole('button', { name: 'Mark as handled' }))
  const buttons = screen.getAllByRole('button', { name: 'Mark as handled' })
  expect(buttons[1]).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Handling note'), { target: { value: 'Resolved after reviewing context' } })
  api.completeEscalation.mockResolvedValue({})
  fireEvent.click(buttons[1])
  await waitFor(() => expect(api.completeEscalation).toHaveBeenCalledWith('7', 'Resolved after reviewing context'))
})

it('hides actions and reply for completed requests and admins who are not the handler', async () => {
  auth.role = 'admin'; auth.username = 'anotheradmin'
  api.escalation.mockResolvedValue({ ...row, status: 'completed', handled_by: 'admin', handling_note: 'Handled after review', messages: [{ id: 1, author: 'reviewer', role: 'analyst', message: 'Context supplied' }] })
  mount('/escalations/7')
  expect(await screen.findByText('Handled after review')).toBeInTheDocument()
  expect(screen.getByText('Context supplied')).toBeInTheDocument()
  for (const name of ['Acknowledge', 'Mark as handled', 'Log contact', 'Withdraw', 'Send reply']) expect(screen.queryByRole('button', { name })).not.toBeInTheDocument()
})
