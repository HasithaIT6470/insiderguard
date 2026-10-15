import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom'
import TopBar, { Breadcrumbs } from './TopBar.jsx'
import { routes, routeLabel, routeTrail } from '../routes'
import { OriginLink, linkState, useOriginNavigate } from '../navigation.jsx'

const cases = [
  ['/', ['Dashboard']], ['/alerts', ['Dashboard', 'Alerts']], ['/alerts/42', ['Dashboard', 'Alerts', 'Case #42']],
  ['/my-cases', ['Dashboard', 'My cases']], ['/my-cases/42', ['Dashboard', 'My cases', 'Case #42']],
  ['/users', ['Dashboard', 'Users']], ['/users/log.user%40test', ['Dashboard', 'Users', 'log.user@test']],
  ['/escalations', ['Dashboard', 'Escalations']], ['/escalations/9', ['Dashboard', 'Escalations', 'Escalation #9']],
  ['/reports', ['Dashboard', 'Reports']], ['/evaluation', ['Dashboard', 'Evaluation']],
  ['/telemetry', ['Dashboard', 'Telemetry & Honeytokens']], ['/accounts', ['Dashboard', 'Accounts']],
  ['/profile', ['Dashboard', 'My profile']], ['/notifications', ['Dashboard', 'Notifications']],
]

afterEach(() => vi.unstubAllGlobals())

it.each(cases)('renders the hierarchy for %s with a non-link current page', (path, expected) => {
  render(<MemoryRouter initialEntries={[path]}><TopBar /></MemoryRouter>)
  const nav = screen.getByRole('navigation', { name: 'Breadcrumb' })
  const items = within(nav).getAllByRole('listitem')
  expect(items.map(item => item.textContent)).toEqual(expected)
  const current = items.at(-1).querySelector('[aria-current="page"]')
  expect(current).toHaveTextContent(expected.at(-1))
  expect(current.tagName).toBe('SPAN')
  expect(current).toHaveAttribute('title', expected.at(-1))
  expect(within(items.at(-1)).queryByRole('link')).not.toBeInTheDocument()
  expect(within(nav).queryAllByRole('link')).toHaveLength(expected.length - 1)
})

it('has one metadata entry for each route and valid, acyclic parents', () => {
  expect(new Set(routes.map(route => route.path)).size).toBe(routes.length)
  for (const route of routes) {
    const seen = new Set([route.path])
    let parent = route.parent
    while (parent) {
      expect(seen.has(parent)).toBe(false)
      seen.add(parent)
      const ancestor = routes.find(entry => entry.path === parent)
      expect(ancestor).toBeDefined()
      parent = ancestor.parent
    }
    if (!['/', '/login'].includes(route.path)) expect(route.parent).toBeTruthy()
  }
  expect(routeTrail('/does-not-exist')).toEqual([])
})

it('uses only route IDs and static labels, without employee names from state', () => {
  render(<MemoryRouter initialEntries={[{ pathname: '/users/log-id', state: { full_name: 'Private Employee Marker', email: 'private@example.test' } }]}><TopBar /></MemoryRouter>)
  expect(screen.getByText('log-id')).toBeInTheDocument()
  expect(screen.queryByText(/Private Employee Marker|private@example.test/)).not.toBeInTheDocument()
  expect(routeLabel('/profile')).toBe('My profile')
})

function Probe() {
  const location = useLocation()
  const navigate = useNavigate()
  return <><output aria-label="Current URL">{location.pathname + location.search}</output><output aria-label="Current state">{JSON.stringify(location.state)}</output><button onClick={() => navigate(-1)}>Browser back</button><button onClick={() => navigate(1)}>Browser forward</button></>
}

it('returns to the exact source pathname and query string supplied in location state', () => {
  const source = { pathname: '/alerts', search: '?status=open&sort_by=peak_score&sort_dir=desc', label: 'Alerts' }
  render(<MemoryRouter initialEntries={[{ pathname: '/users/u1', state: { from: source } }]}><TopBar /><Probe /></MemoryRouter>)
  const back = screen.getByRole('link', { name: 'Back to Alerts' })
  expect(back).toHaveAttribute('href', source.pathname + source.search)
  fireEvent.click(back)
  expect(screen.getByLabelText('Current URL')).toHaveTextContent(source.pathname + source.search)
  expect(screen.getByLabelText('Current state')).toHaveTextContent('null')
})

it.each([['/alerts/42', '/alerts', 'Alerts'], ['/my-cases/42', '/my-cases', 'My cases'], ['/users/u1', '/users', 'Users'], ['/escalations/9', '/escalations', 'Escalations'], ['/accounts', '/', 'Dashboard']])('falls back to the parent for direct visits to %s', (path, parent, label) => {
  render(<MemoryRouter initialEntries={[path]}><TopBar /></MemoryRouter>)
  expect(screen.getByRole('link', { name: `Back to ${label}` })).toHaveAttribute('href', parent)
})

it('does not offer Back on Dashboard or show navigation on login', () => {
  const { unmount } = render(<MemoryRouter><TopBar /></MemoryRouter>)
  expect(screen.queryByRole('link', { name: /^Back to/ })).not.toBeInTheDocument()
  unmount()
  render(<MemoryRouter initialEntries={['/login']}><TopBar /><Breadcrumbs compact /></MemoryRouter>)
  expect(screen.queryByRole('navigation', { name: 'Breadcrumb' })).not.toBeInTheDocument()
  expect(screen.queryByRole('banner')).not.toBeInTheDocument()
})

it('renders compact mobile breadcrumbs and responds to viewport changes', () => {
  let listener
  const media = { matches: true, addEventListener: vi.fn((name, fn) => { listener = fn }), removeEventListener: vi.fn() }
  vi.stubGlobal('matchMedia', vi.fn(() => media))
  const { unmount } = render(<MemoryRouter initialEntries={['/alerts/42']}><TopBar /></MemoryRouter>)
  expect(screen.getByRole('banner')).toHaveClass('is-compact')
  expect(screen.getByRole('navigation', { name: 'Breadcrumb' }).parentElement).toHaveClass('is-compact')
  act(() => { media.matches = false; listener() })
  expect(screen.getByRole('banner')).not.toHaveClass('is-compact')
  unmount()
  expect(media.removeEventListener).toHaveBeenCalledWith('change', listener)
})

it('reserves an empty right slot that can accept the future notification control', () => {
  const { unmount } = render(<MemoryRouter><TopBar /></MemoryRouter>)
  expect(screen.getByTestId('topbar-right')).toBeEmptyDOMElement()
  unmount()
  render(<MemoryRouter><TopBar right={<button>Notification slot</button>} /></MemoryRouter>)
  expect(screen.getByRole('button', { name: 'Notification slot' }).parentElement).toBe(screen.getByTestId('topbar-right'))
})

function SourceLinks() {
  const navigate = useOriginNavigate()
  return <><OriginLink to="/users/u1">Open user</OriginLink><button onClick={() => navigate('/alerts/42', { state: { notice: 'Preserved notice' } })}>Open case tile</button></>
}

it.each(['Open user', 'Open case tile'])('captures source state for %s and preserves normal browser Back/Forward', name => {
  const source = '/alerts?status=open&sort_by=category&sort_dir=asc'
  render(<MemoryRouter initialEntries={[source]}><SourceLinks /><TopBar /><Probe /></MemoryRouter>)
  fireEvent.click(screen.getByRole(name === 'Open user' ? 'link' : 'button', { name }))
  const state = JSON.parse(screen.getByLabelText('Current state').textContent)
  expect(state.from).toEqual({ pathname: '/alerts', search: '?status=open&sort_by=category&sort_dir=asc', label: 'Alerts' })
  if (name === 'Open case tile') expect(state.notice).toBe('Preserved notice')
  const destination = screen.getByLabelText('Current URL').textContent
  fireEvent.click(screen.getByRole('button', { name: 'Browser back' }))
  expect(screen.getByLabelText('Current URL')).toHaveTextContent(source)
  fireEvent.click(screen.getByRole('button', { name: 'Browser forward' }))
  expect(screen.getByLabelText('Current URL')).toHaveTextContent(destination)
  expect(screen.getByRole('link', { name: 'Back to Alerts' })).toHaveAttribute('href', source)
})

it('creates ID-only source labels for case and user origins', () => {
  expect(linkState({ pathname: '/my-cases/42', search: '' }).from.label).toBe('Case #42')
  expect(linkState({ pathname: '/users/u1', search: '?tab=cases' })).toEqual({ from: { pathname: '/users/u1', search: '?tab=cases', label: 'u1' } })
})
