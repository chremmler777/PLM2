import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import LifecycleStepper from './LifecycleStepper'

describe('LifecycleStepper', () => {
  afterEach(cleanup)

  it('marks past, current and future statuses', () => {
    render(<LifecycleStepper status="costing" />)
    expect(screen.getByText('Captured').className).toContain('emerald')
    expect(screen.getByText('Costing').className).toContain('sky-600')
    expect(screen.getByText('Released').className).toContain('slate-800')
  })

  it('shows an off-path badge for on_hold', () => {
    render(<LifecycleStepper status="on_hold" />)
    expect(screen.getByText('On Hold')).toBeDefined()
  })

  it('omits Quoted for internal (non-customer-relevant) changes', () => {
    render(<LifecycleStepper status="costing" customerRelevant={false} />)
    expect(screen.queryByText('Quoted')).toBeNull()
  })

  it('keeps Quoted for customer-relevant changes', () => {
    render(<LifecycleStepper status="costing" customerRelevant />)
    expect(screen.getByText('Quoted')).toBeDefined()
  })

  it('shows the plain-language hint under the current step', () => {
    render(<LifecycleStepper status="costing" />)
    expect(screen.getByText('Sum up costs')).toBeDefined()
  })
})
