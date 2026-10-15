import { act, fireEvent, render, renderHook, screen } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import NotificationBell, { useUnreadCount } from './NotificationBell.jsx'
import { api } from '../api'

vi.mock('../api', () => ({ api: { unreadCount: vi.fn() } }))
beforeEach(() => {
  vi.clearAllMocks()
  api.unreadCount.mockResolvedValue({ unread_count: 3 })
  vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('visible')
})
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks() })

function Probe() { const location = useLocation(); return <output aria-label="Destination">{location.pathname}</output> }
it('shows a red dot and an accessible unread count, navigating straight to the page', () => {
  const { rerender } = render(<MemoryRouter><NotificationBell count={3} /><Probe /></MemoryRouter>)
  expect(screen.getByTestId('notification-dot')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('link', { name: 'Notifications, 3 unread' }))
  expect(screen.getByLabelText('Destination')).toHaveTextContent('/notifications')
  expect(screen.queryByRole('menu')).not.toBeInTheDocument()
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  rerender(<MemoryRouter><NotificationBell count={0} /><Probe /></MemoryRouter>)
  expect(screen.queryByTestId('notification-dot')).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Notifications, 0 unread' })).toBeInTheDocument()
})

it('polls every 30 seconds, pauses while hidden, resumes immediately and cleans up', async () => {
  vi.useFakeTimers()
  let visibility = 'visible'
  vi.spyOn(document, 'visibilityState', 'get').mockImplementation(() => visibility)
  const { result, unmount } = renderHook(() => useUnreadCount('analyst'))
  await act(async () => {})
  expect(result.current.count).toBe(3)
  await act(async () => { vi.advanceTimersByTime(30000) })
  expect(api.unreadCount).toHaveBeenCalledTimes(2)
  act(() => { visibility = 'hidden'; document.dispatchEvent(new Event('visibilitychange')) })
  await act(async () => { vi.advanceTimersByTime(90000) })
  expect(api.unreadCount).toHaveBeenCalledTimes(2)
  await act(async () => { visibility = 'visible'; document.dispatchEvent(new Event('visibilitychange')) })
  expect(api.unreadCount).toHaveBeenCalledTimes(3)
  unmount()
  await act(async () => { vi.advanceTimersByTime(60000); window.dispatchEvent(new Event('notifications-updated')) })
  expect(api.unreadCount).toHaveBeenCalledTimes(3)
})

it('refreshes immediately after inbox actions and removes the dot when all are read', async () => {
  function BellWithCount() { const { count } = useUnreadCount('analyst'); return <NotificationBell count={count} /> }
  render(<MemoryRouter><BellWithCount /></MemoryRouter>)
  await screen.findByRole('link', { name: 'Notifications, 3 unread' })
  api.unreadCount.mockResolvedValue({ unread_count: 0 })
  await act(async () => window.dispatchEvent(new Event('notifications-updated')))
  expect(screen.getByRole('link', { name: 'Notifications, 0 unread' })).toBeInTheDocument()
  expect(screen.queryByTestId('notification-dot')).not.toBeInTheDocument()
})
