import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import LifecycleStepper from './LifecycleStepper'
import { t } from '../../i18n/cmLabels'

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

  it('sources the hint from the bilingual cmLabels layer, not a hardcoded string', () => {
    render(<LifecycleStepper status="in_validation" />)
    expect(screen.getByText(t('stepper.hint.in_validation'))).toBeDefined()
  })
})

describe('LifecycleStepper stage responsibility', () => {
  it('tags every stage with its agreed owner along the whole path', () => {
    // Agreed 2026-08-12: Sales owns capture and everything quote-shaped,
    // the team owns assessment/costing/implementation/validation, PM the
    // scoping and the release. Closed states carry no badge.
    render(<LifecycleStepper status="scoping" customerRelevant />)
    const tags = screen.getAllByTestId('stage-responsible')
    expect(tags.length).toBeGreaterThanOrEqual(2)
    expect(tags[0].textContent).toContain(t('role.sales'))
    expect(tags[0].parentElement?.textContent).toContain('Captured')
    expect(tags[1].textContent).toContain(t('role.pmShort'))
    expect(tags[1].parentElement?.textContent).toContain('Scoping')
    const all = tags.map((el) => el.textContent).join('|')
    expect(all).toContain(t('role.team'))
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
