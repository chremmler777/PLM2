import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import LifecycleStepper from './LifecycleStepper'
import { t } from '../../i18n/cmLabels'

describe('LifecycleStepper', () => {
  afterEach(cleanup)

  it('marks past, current and future statuses', () => {
    render(<LifecycleStepper status="costing" />)
    expect(screen.getByTestId('step-captured').className).toContain('emerald')
    // Past stages collapse to a check and a muted name.
    expect(screen.getByTestId('step-captured').querySelector('svg')).not.toBeNull()
    expect(screen.getByTestId('step-costing').className).toContain('sky-500')
    expect(screen.getByTestId('step-costing').closest('li')?.getAttribute('aria-current')).toBe('step')
    expect(screen.getByTestId('step-released').className).toContain('text-slate-500')
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

  it('sources the hint from the bilingual cmLabels layer, not a hardcoded string', () => {
    render(<LifecycleStepper status="in_validation" />)
    expect(screen.getByText(t('stepper.hint.in_validation'))).toBeDefined()
  })
})

describe('LifecycleStepper stage responsibility', () => {
  afterEach(cleanup)

  it('names the owner on the running stage only, not on every stage', () => {
    // Agreed 2026-08-12: Sales owns capture and everything quote-shaped,
    // the team owns assessment/costing/implementation/validation, PM the
    // scoping and the release. Only the current stage carries the chip.
    render(<LifecycleStepper status="scoping" customerRelevant />)
    const tags = screen.getAllByTestId('stage-responsible')
    expect(tags).toHaveLength(1)
    expect(tags[0].textContent).toContain(t('role.pmShort'))
    expect(tags[0].parentElement?.textContent).toContain('Scoping')
    cleanup()
    render(<LifecycleStepper status="costing" customerRelevant />)
    expect(screen.getByTestId('stage-responsible').textContent).toContain(t('role.team'))
  })

  it('shows no owner on a closed change', () => {
    render(<LifecycleStepper status="closed" customerRelevant />)
    expect(screen.queryByTestId('stage-responsible')).toBeNull()
    expect(screen.getByTestId('step-closed').className).toContain('emerald')
  })
})

describe('LifecycleStepper engineering review track', () => {
  afterEach(cleanup)

  it('gives the running review stage to Development, never Sales or PM', () => {
    render(<LifecycleStepper status="scoping" origin="engineering_review" />)
    const tag = screen.getByTestId('stage-responsible')
    expect(tag.textContent).toContain('Development')
    expect(tag.parentElement?.querySelector('[data-testid^="step-"]')?.textContent).toBe('Impact and review')
  })
})

describe('LifecycleStepper mother-plant track', () => {
  afterEach(cleanup)

  it('gives the capture to Project Management, who starts it, not Sales', () => {
    render(<LifecycleStepper status="captured" origin="mother_plant" />)
    const tag = screen.getByTestId('stage-responsible')
    expect(tag.textContent).toContain('PM')
    expect(tag.textContent).not.toContain('Sales')
  })
})

describe('LifecycleStepper scoping handoff note', () => {
  afterEach(cleanup)

  it('tells the capture author who takes over at scoping', () => {
    render(<LifecycleStepper status="captured" customerRelevant />)
    expect(screen.getByTitle(t('tab.scopingHandoff')).textContent).toBe('Scoping')
  })

  it('keeps the ordinary scoping hint once scoping is running', () => {
    render(<LifecycleStepper status="scoping" customerRelevant />)
    expect(screen.queryByTitle(t('tab.scopingHandoff'))).toBeNull()
  })
})

describe('LifecycleStepper end states (spec §16)', () => {
  afterEach(cleanup)

  it('ends a rejected change in a red pill, stopped at its stage, later stages greyed', () => {
    render(<LifecycleStepper status="rejected" customerRelevant
      end={{ kind: 'rejected', stoppedAt: 'in_assessment' }} />)
    expect(screen.getByTestId('stepper-end').textContent).toContain('Rejected')
    expect(screen.getByTestId('stepper-end').textContent).toContain('stopped at In Assessment')
    expect(screen.getByTestId('step-captured').className).toContain('emerald')
    expect(screen.getByTestId('step-in_assessment').className).toContain('red')
    expect(screen.getByTestId('step-costing').className).toContain('slate-600')
    // Never "Closed" as the end of a stopped path, and no "Rejected" off-path badge twice.
    expect(screen.queryByTestId('step-closed')).toBeNull()
    expect(screen.getAllByText(/Rejected/)).toHaveLength(1)
  })

  it('names a rejected-then-closed change and a cancelled one distinctly', () => {
    render(<LifecycleStepper status="closed" end={{ kind: 'rejected', stoppedAt: 'scoping', closed: true }} />)
    expect(screen.getByTestId('stepper-end').textContent).toContain('Rejected, closed')
    cleanup()
    render(<LifecycleStepper status="cancelled" end={{ kind: 'cancelled', stoppedAt: 'costing' }} />)
    expect(screen.getByTestId('stepper-end').textContent).toContain('Canceled')
    expect(screen.getByTestId('stepper-stopped-at')).toBeTruthy()
  })
})
