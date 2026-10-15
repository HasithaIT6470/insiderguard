import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { api } from './api'
import { CloseCaseDialog, ReopenCaseDialog } from './resolutions.jsx'
import { CaseHistory } from './cases.jsx'

vi.mock('./api', () => ({ api: { setStatus: vi.fn() } }))

beforeEach(() => {
  vi.clearAllMocks()
  api.setStatus.mockResolvedValue({})
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
})

it('requires an outcome and at least 15 trimmed note characters before closing', async () => {
  const complete = vi.fn()
  render(<CloseCaseDialog alertId={7} onClose={vi.fn()} onComplete={complete} />)
  const button = screen.getByRole('button', { name: 'Close case' })
  expect(button).toBeDisabled()
  fireEvent.click(screen.getByRole('radio', { name: /True positive/ }))
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Closing note'), { target: { value: '   ' + 'x'.repeat(14) + '   ' } })
  expect(screen.getByText(/14 \/ 4000 characters/)).toBeInTheDocument()
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Closing note'), { target: { value: '  Verified synthetic policy violation.  ' } })
  expect(button).toBeEnabled()
  fireEvent.click(button)
  await waitFor(() => expect(api.setStatus).toHaveBeenCalledWith(7, 'closed', { outcome: 'true_positive', note: 'Verified synthetic policy violation.' }))
  expect(complete).toHaveBeenCalledTimes(1)
})

it('keeps the close dialog and note after an API error', async () => {
  const complete = vi.fn()
  api.setStatus.mockRejectedValue(new Error('Only the case owner can change this case'))
  render(<CloseCaseDialog alertId={7} onClose={vi.fn()} onComplete={complete} />)
  fireEvent.click(screen.getByRole('radio', { name: /False positive/ }))
  fireEvent.change(screen.getByLabelText('Closing note'), { target: { value: 'Reviewed all available evidence.' } })
  fireEvent.click(screen.getByRole('button', { name: 'Close case' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('Only the case owner')
  expect(screen.getByLabelText('Closing note')).toHaveValue('Reviewed all available evidence.')
  expect(complete).not.toHaveBeenCalled()
})

it('requires a short reason before reopening into the chosen status', async () => {
  const complete = vi.fn()
  render(<ReopenCaseDialog alertId={7} status="under_investigation" onClose={vi.fn()} onComplete={complete} />)
  const button = screen.getByRole('button', { name: 'Reopen case' })
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Reopen reason'), { target: { value: 'tiny' } })
  expect(button).toBeDisabled()
  fireEvent.change(screen.getByLabelText('Reopen reason'), { target: { value: '  Additional evidence received  ' } })
  fireEvent.click(button)
  await waitFor(() => expect(api.setStatus).toHaveBeenCalledWith(7, 'under_investigation', { reason: 'Additional evidence received' }))
  expect(complete).toHaveBeenCalledTimes(1)
})

it('combines resolution history and case events without duplicating resolved entries', () => {
  render(<CaseHistory resolutions={[{ id: 2, outcome: 'benign_explained', note: 'Explained by an approved synthetic export.', resolved_by: 'analyst', resolved_at: '2026-10-01T09:00:00', reopened_at: '2026-10-02T09:00:00', reopened_by: 'analyst', reopen_reason: 'Additional context' }]}
    events={{ loading: false, data: [
      { id: 1, action: 'resolved', actor: 'analyst', created_at: '2026-10-01T09:00:01', detail: { resolution_id: 2, outcome: 'benign_explained' } },
      { id: 2, action: 'updated_after_closure', actor: 'system', created_at: '2026-10-01T12:00:00', detail: { old_peak_score: 50, new_peak_score: 70 } },
    ] }} />)
  expect(screen.getAllByText('Benign/explained')).toHaveLength(1)
  expect(screen.getByText('Explained by an approved synthetic export.')).toBeInTheDocument()
  expect(screen.getByText('Updated after closure')).toBeInTheDocument()
  expect(screen.getByText('Additional context')).toBeInTheDocument()
})
