import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { EscalateCase, EscalateDialog } from './escalations.jsx'
import { api } from './api'

vi.mock('./api', () => ({ api: { createEscalation: vi.fn() } }))
vi.mock('./App.jsx', () => ({ useAuth: () => ({ auth: { role: 'analyst' } }) }))
beforeEach(() => {
  vi.clearAllMocks()
  HTMLDialogElement.prototype.showModal = vi.fn(function () { this.setAttribute('open', '') })
  HTMLDialogElement.prototype.close = vi.fn(function () { this.removeAttribute('open') })
})

it('requires a trimmed summary of 20 characters and submits advisory filing details', async () => {
  const complete = vi.fn()
  api.createEscalation.mockResolvedValue({ id: 7 })
  render(<MemoryRouter><EscalateDialog alert={{ id: 12, user_id: 'u.id', status: 'closed' }} onClose={vi.fn()} onComplete={complete} /></MemoryRouter>)
  const submit = screen.getByRole('button', { name: 'Submit escalation' })
  expect(submit).toBeDisabled()
  expect(screen.getByText(/Case #12/)).toHaveTextContent('Closed')
  expect(screen.getByRole('link', { name: 'u.id' })).toHaveAttribute('href', '/users/u.id')
  expect(screen.getByText(/Recommendations are advisory/)).toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Summary'), { target: { value: ' ' + 'x'.repeat(19) + ' ' } })
  expect(submit).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Summary'), { target: { value: '  Please review the case evidence.  ' } })
  fireEvent.change(screen.getByLabelText('Recommendation'), { target: { value: 'access_review' } })
  fireEvent.change(screen.getByLabelText('Priority'), { target: { value: 'urgent' } })
  expect(submit).toBeEnabled(); fireEvent.click(submit)
  await waitFor(() => expect(complete).toHaveBeenCalledWith({ id: 7 }))
  expect(api.createEscalation).toHaveBeenCalledWith({ alert_id: 12, summary: 'Please review the case evidence.', recommendation: 'access_review', recommendation_note: '', priority: 'urgent' })
})

it('disables filing and links to an existing open escalation', () => {
  render(<MemoryRouter><EscalateCase alert={{ id: 12, open_escalation_id: 7 }} onComplete={vi.fn()} /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Escalate to admin' })).toBeDisabled()
  expect(screen.getByRole('link', { name: /View open escalation #7/ })).toHaveAttribute('href', '/escalations/7')
})
