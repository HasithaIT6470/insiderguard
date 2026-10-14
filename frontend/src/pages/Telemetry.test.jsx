import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { api } from '../api'
import Telemetry from './Telemetry.jsx'

const authState = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth: authState }) }))
vi.mock('../api', () => ({ api: {
  honeytokens: vi.fn(), rules: vi.fn(), parseErrors: vi.fn(), audit: vi.fn(),
  createHoneytoken: vi.fn(), revokeHoneytoken: vi.fn(), importEvents: vi.fn(), updateRules: vi.fn(), createRule: vi.fn(), deleteRule: vi.fn(),
} }))

beforeEach(() => {
  vi.clearAllMocks()
  authState.role = 'admin'
  api.honeytokens.mockResolvedValue([
    { id: 1, resource: '/finance/decoy.csv', description: 'Payroll', active: true, created_at: '2026-10-01T10:00:00' },
    { id: 2, resource: '/engineering/old.csv', description: 'Archive', active: false, created_at: '2026-10-01T10:00:00' },
  ])
  api.rules.mockResolvedValue([{ key: 'alert_threshold', description: 'Alert threshold', value: 25, built_in: true }])
  api.createRule.mockResolvedValue({ key: 'custom_limit' })
  api.deleteRule.mockResolvedValue({ deleted: 'custom_limit' })
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  api.parseErrors.mockResolvedValue([])
  api.audit.mockResolvedValue([])
  api.createHoneytoken.mockResolvedValue({ id: 3 })
  api.revokeHoneytoken.mockResolvedValue({ active: false })
  api.updateRules.mockResolvedValue({ changed: { alert_threshold: { from: 25, to: 40 } } })
  api.importEvents.mockResolvedValue({ accepted: 2, rejected: 1, affected_users: ['u1'], errors: [{ row: 3, errors: [{ field: 'timestamp', message: 'Invalid' }] }] })
})

it('filters the registry and preserves register and revoke actions', async () => {
  render(<Telemetry />)
  await screen.findByText('/finance/decoy.csv')
  fireEvent.change(screen.getByLabelText('Decoy state'), { target: { value: 'active' } })
  expect(screen.queryByText('/engineering/old.csv')).not.toBeInTheDocument()
  fireEvent.change(screen.getByLabelText('Search decoys'), { target: { value: 'missing' } })
  expect(screen.getByText('No decoys match these filters.')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
  fireEvent.change(screen.getByLabelText('Decoy resource'), { target: { value: '/new/decoy.csv' } })
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: 'New decoy' } })
  fireEvent.click(screen.getByRole('button', { name: 'Register decoy' }))
  await waitFor(() => expect(api.createHoneytoken).toHaveBeenCalledWith('/new/decoy.csv', 'New decoy'))
  await waitFor(() => expect(screen.getByRole('button', { name: 'Revoke /finance/decoy.csv' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'Revoke /finance/decoy.csv' }))
  await waitFor(() => expect(api.revokeHoneytoken).toHaveBeenCalledWith(1))
})

it('imports a file and presents accepted and rejected rows', async () => {
  render(<Telemetry />)
  fireEvent.click(screen.getByRole('tab', { name: 'Telemetry import' }))
  const file = new File(['timestamp,user_id'], 'events.csv', { type: 'text/csv' })
  fireEvent.change(screen.getByLabelText('Event file'), { target: { files: [file] } })
  fireEvent.click(screen.getByRole('button', { name: 'Import events' }))
  expect(await screen.findByText('Import completed')).toBeInTheDocument()
  expect(api.importEvents).toHaveBeenCalledWith(file)
  expect(screen.getByText('Accepted 2 events, rejected 1. Scores updated for 1 users.')).toBeInTheDocument()
  expect(screen.getByText(/Row 3: timestamp/)).toBeInTheDocument()
})

it('discards rule edits and saves numeric changes through the existing API', async () => {
  render(<Telemetry />)
  fireEvent.click(screen.getByRole('tab', { name: 'Detection rules' }))
  const input = await screen.findByLabelText('alert_threshold')
  fireEvent.change(input, { target: { value: '40' } })
  fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
  expect(input).toHaveValue(25)
  fireEvent.change(input, { target: { value: '' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  expect(api.updateRules).not.toHaveBeenCalled()
  expect(screen.getByRole('alert')).toHaveTextContent('Rule values must be numbers')
  fireEvent.change(input, { target: { value: '40' } })
  fireEvent.click(screen.getByRole('button', { name: 'Save changes' }))
  await waitFor(() => expect(api.updateRules).toHaveBeenCalledWith({ alert_threshold: 40 }))
})

it('keeps analyst access read-only and excludes admin-only requests', async () => {
  authState.role = 'analyst'
  render(<Telemetry />)
  await screen.findByText('/finance/decoy.csv')
  expect(screen.queryByRole('tab', { name: 'Telemetry import' })).not.toBeInTheDocument()
  expect(screen.queryByRole('tab', { name: 'Admin logs' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Register decoy' })).not.toBeInTheDocument()
  expect(api.audit).not.toHaveBeenCalled()
  expect(api.parseErrors).not.toHaveBeenCalled()
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Honeytoken registry' }), { key: 'ArrowRight' })
  expect(screen.getByRole('tab', { name: 'Detection rules' })).toHaveAttribute('aria-selected', 'true')
  await waitFor(() => expect(api.rules).toHaveBeenCalled())
  expect(screen.queryByRole('spinbutton')).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Add rule' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Save changes' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /Remove/ })).not.toBeInTheDocument()
  expect(screen.getByText('25')).toBeInTheDocument()
})

it('adds custom parameters through a dialog with parameter, description and value', async () => {
  render(<Telemetry />)
  fireEvent.click(screen.getByRole('tab', { name: 'Detection rules' }))
  await screen.findByLabelText('alert_threshold')
  fireEvent.click(screen.getByRole('button', { name: 'Add rule' }))
  const dialog = within(screen.getByRole('dialog', { name: 'Add detection rule' }))
  fireEvent.change(dialog.getByLabelText('Parameter'), { target: { value: 'custom_limit' } })
  fireEvent.change(dialog.getByLabelText('Description'), { target: { value: 'Custom volume limit' } })
  fireEvent.change(dialog.getByLabelText('Value'), { target: { value: '150' } })
  fireEvent.click(dialog.getByRole('button', { name: 'Add rule' }))
  await waitFor(() => expect(api.createRule).toHaveBeenCalledWith({ key: 'custom_limit', description: 'Custom volume limit', value: 150 }))
  await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
})

it('allows custom parameter removal and protects built-in parameters', async () => {
  api.rules.mockResolvedValue([
    { key: 'alert_threshold', description: 'Built-in', value: 25, built_in: true },
    { key: 'custom_limit', description: 'Custom', value: 150, built_in: false },
  ])
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  render(<Telemetry />)
  fireEvent.click(screen.getByRole('tab', { name: 'Detection rules' }))
  expect(await screen.findByRole('button', { name: 'Remove alert_threshold' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: 'Remove custom_limit' }))
  await waitFor(() => expect(api.deleteRule).toHaveBeenCalledWith('custom_limit'))
  confirm.mockRestore()
})
