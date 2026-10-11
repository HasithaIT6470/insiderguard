import { render, screen } from '@testing-library/react'
import { CategoryBadge, ScoreBar, fmt } from './components.jsx'

describe('components', () => {
  it('renders the risk category', () => {
    render(<CategoryBadge category="Critical" />)
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })

  it('exposes the score on an accessible progress bar', () => {
    render(<ScoreBar score={72} category="High" />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '72')
  })

  it('formats naive UTC timestamps', () => {
    expect(fmt('2026-08-03T09:30:00')).toContain('UTC')
    expect(fmt(null)).toBe('—')
  })
})
