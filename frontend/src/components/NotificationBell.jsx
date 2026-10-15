import { useCallback, useEffect, useState } from 'react'
import { Bell } from 'lucide-react'
import { api } from '../api'
import { OriginLink } from '../navigation.jsx'

export function useUnreadCount(identity) {
  const [count, setCount] = useState(0)
  const [revision, setRevision] = useState(0)
  const refresh = useCallback(() => setRevision(value => value + 1), [])
  useEffect(() => setCount(0), [identity])
  useEffect(() => {
    let alive = true
    let timer
    let requestId = 0
    const poll = async () => {
      if (document.visibilityState === 'hidden') return
      const id = ++requestId
      try {
        const result = await api.unreadCount()
        if (alive && id === requestId) setCount(result.unread_count)
      } catch { /* Keep the last known badge during temporary network failures. */ }
    }
    const visibility = () => {
      window.clearInterval(timer)
      if (document.visibilityState !== 'hidden') { poll(); timer = window.setInterval(poll, 30000) }
      else requestId += 1
    }
    const update = () => poll()
    visibility()
    document.addEventListener('visibilitychange', visibility)
    window.addEventListener('notifications-updated', update)
    return () => { alive = false; window.clearInterval(timer); document.removeEventListener('visibilitychange', visibility); window.removeEventListener('notifications-updated', update) }
  }, [identity, revision])
  return { count, refresh }
}

export default function NotificationBell({ count = 0 }) {
  return <OriginLink to="/notifications" className="ig-notification-bell" aria-label={`Notifications, ${count} unread`} title="Notifications">
    <Bell size={21} aria-hidden="true" />{count > 0 && <span className="ig-notification-dot" data-testid="notification-dot" aria-hidden="true" />}
  </OriginLink>
}
