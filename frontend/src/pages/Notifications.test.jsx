import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import Notifications, { dayLabel } from './Notifications.jsx'
import { api } from '../api'

const auth = vi.hoisted(() => ({ role: 'analyst' }))
vi.mock('../App.jsx', () => ({ useAuth: () => ({ auth }) }))
vi.mock('../api', () => ({ api: { notifications: vi.fn(), markRead: vi.fn(), markUnread: vi.fn(), markAllRead: vi.fn(), dismissNotification: vi.fn() } }))
const row = (id, date = new Date()) => ({ id, type: 'case_assigned', title: `Case #${id} assigned`, message: `You are the owner of Case #${id}.`, link: `/my-cases/${id}`, created_at: date.toISOString(), read_at: null, severity: 'info' })
beforeEach(() => {
  vi.clearAllMocks(); auth.role = 'analyst'
  const yesterday = new Date(); yesterday.setDate(yesterday.getDate() - 1)
  const old = new Date(); old.setDate(old.getDate() - 4)
  api.notifications.mockResolvedValue([row(3), row(2, yesterday), row(1, old)])
  for (const method of ['markRead', 'markUnread', 'markAllRead', 'dismissNotification']) api[method].mockResolvedValue({})
})
function Probe() { const location = useLocation(); return <><output aria-label="Destination">{location.pathname}</output><output aria-label="Origin">{JSON.stringify(location.state?.from)}</output></> }
const mount = () => render(<MemoryRouter initialEntries={['/notifications']}><Notifications /><Probe /></MemoryRouter>)

it('groups by Today, Yesterday and dates with role-appropriate copy and filters', async () => {
  mount()
  await screen.findByText('Case #3 assigned')
  expect(screen.getByRole('heading', { name: 'Today' })).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Yesterday' })).toBeInTheDocument()
  const old = new Date(); old.setDate(old.getDate() - 4)
  expect(screen.getByRole('heading', { name: dayLabel(old.toISOString()) })).toBeInTheDocument()
  expect(screen.getByText('Your case ownership and escalation updates')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('tab', { name: 'Unread', exact: true }))
  await waitFor(() => expect(api.notifications).toHaveBeenLastCalledWith({ unread: 'true', limit: 50 }))
  fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'escalations' } })
  await waitFor(() => expect(api.notifications).toHaveBeenLastCalledWith({ unread: 'true', type: 'escalations', limit: 50 }))
  fireEvent.change(screen.getByLabelText('Search notifications'), { target: { value: 'Case #3' } })
  await waitFor(() => expect(api.notifications).toHaveBeenLastCalledWith({ unread: 'true', type: 'escalations', search: 'Case #3', limit: 50 }))
  await screen.findByText('Case #3 assigned')
})

it('marks a clicked row read before navigating and preserves Notifications as its origin', async () => {
  mount()
  fireEvent.click((await screen.findByText('Case #3 assigned')).closest('li'))
  await waitFor(() => expect(screen.getByLabelText('Destination')).toHaveTextContent('/my-cases/3'))
  expect(api.markRead).toHaveBeenCalledWith(3)
  expect(JSON.parse(screen.getByLabelText('Origin').textContent)).toEqual({ pathname: '/notifications', search: '', label: 'Notifications' })
})

it('supports read, unread and dismiss without navigating', async () => {
  mount(); await screen.findByText('Case #3 assigned')
  fireEvent.click(screen.getByRole('button', { name: 'Mark read: Case #3 assigned' }))
  fireEvent.click(await screen.findByRole('button', { name: 'Mark unread: Case #3 assigned' }))
  await screen.findByRole('button', { name: 'Mark read: Case #3 assigned' })
  fireEvent.click(screen.getByRole('button', { name: 'Dismiss: Case #3 assigned' }))
  await waitFor(() => expect(screen.queryByText('Case #3 assigned')).not.toBeInTheDocument())
  expect(api.markUnread).toHaveBeenCalledWith(3)
  expect(api.dismissNotification).toHaveBeenCalledWith(3)
  expect(screen.getByLabelText('Destination')).toHaveTextContent('/notifications')
})

it('marks all read, shows the friendly empty state and uses admin copy', async () => {
  auth.role = 'admin'; mount()
  await screen.findByText('Case #3 assigned')
  expect(screen.getByText('Case and escalation activity, and alerts awaiting review')).toBeInTheDocument()
  api.notifications.mockResolvedValue([])
  fireEvent.click(screen.getByRole('button', { name: 'Mark all as read' }))
  expect(await screen.findByText('No notifications to show')).toBeInTheDocument()
  expect(api.markAllRead).toHaveBeenCalled()
  fireEvent.click(screen.getByRole('tab', { name: 'Unread', exact: true }))
  expect(await screen.findByText('You’re all caught up')).toBeInTheDocument()
})

it('loads the next page using the oldest ID and displays action failures', async () => {
  api.notifications.mockResolvedValueOnce(Array.from({ length: 50 }, (_, i) => row(100 - i))).mockResolvedValueOnce([row(50)])
  mount()
  fireEvent.click(await screen.findByRole('button', { name: 'Load more' }))
  expect(await screen.findByText('Case #50 assigned')).toBeInTheDocument()
  expect(api.notifications).toHaveBeenLastCalledWith({ limit: 50, before_id: 51 })
  expect(screen.queryByRole('button', { name: 'Load more' })).not.toBeInTheDocument()
  api.markRead.mockRejectedValue(new Error('Could not mark read'))
  fireEvent.click(screen.getByText('Case #50 assigned').closest('button'))
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not mark read')
  expect(screen.getByLabelText('Destination')).toHaveTextContent('/notifications')
})
