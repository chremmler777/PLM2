import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ProcessMapPage from './ProcessMapPage'
import { t } from '../i18n/cmLabels'

// The ten stages of docs/ECR_PROCESS_MAP.md, in order.
const STAGES = [
  'captured', 'scoping', 'in_assessment', 'costing', 'quoting', 'quoted',
  'scheduling', 'in_implementation', 'in_validation', 'released',
]

const wrap = () => render(<MemoryRouter><ProcessMapPage /></MemoryRouter>)

describe('ProcessMapPage', () => {
  afterEach(cleanup)

  it('lays out all ten stages with their German title and responsible', () => {
    wrap()
    for (const key of STAGES) {
      const card = screen.getByTestId(`procmap-stage-${key}`)
      expect(card.textContent).toContain(t(`procmap.stage.${key}`, 'de'))
      expect(screen.getByTestId(`procmap-role-${key}`).textContent)
        .toBe(t(`procmap.role.${key}`, 'de'))
    }
    // The map's own vocabulary, in the language the team reviews it in.
    expect(screen.getByTestId('procmap-stage-quoting').textContent)
      .toContain('Angebotserstellung')
    expect(screen.getByTestId('procmap-stage-scheduling').textContent)
      .toContain('Terminplanung / Bank-Build')
  })

  it('says of every stage how much of it is built', () => {
    wrap()
    const states = STAGES.map((k) => screen.getByTestId(`procmap-status-${k}`).textContent)
    expect(states).toHaveLength(10)
    expect(states.every((s) => ['BUILT', 'IN BUILD', 'PARTIAL', 'TO BUILD'].includes(s ?? '')))
      .toBe(true)
    expect(screen.getByTestId('procmap-status-captured').textContent).toBe('BUILT')
    expect(screen.getByTestId('procmap-status-costing').textContent).toBe('IN BUILD')
    // The doc calls the negotiation stage partial — acceptance is live, the
    // negotiation loop is not.
    expect(screen.getByTestId('procmap-status-quoted').textContent).toBe('PARTIAL')
    expect(screen.getByTestId('procmap-status-scheduling').textContent).toBe('TO BUILD')
  })

  it('draws the two places the flow leaves the straight line', () => {
    wrap()
    expect(screen.getByTestId('procmap-branch-quoted').textContent).toContain('no deal')
    expect(screen.getByTestId('procmap-branch-quoted').textContent).toContain('rejected')
    const validation = screen.getByTestId('procmap-branch-in_validation').textContent
    expect(validation).toContain('not good')
    expect(validation).toContain('escalation')
  })

  it('carries the cross-cutting rules and the build order', () => {
    wrap()
    const rules = screen.getByTestId('procmap-rules')
    expect(rules.textContent).toContain(t('procmap.rules', 'de'))
    expect(rules.querySelectorAll('li')).toHaveLength(5)
    expect(rules.textContent).toContain('a department sees its own input only')
    const order = screen.getByTestId('procmap-build-order')
    expect(order.querySelectorAll('li')).toHaveLength(7)
    expect(order.textContent).toContain('Weight quote at costing')
  })
})
