import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import ProcessMapPage from './ProcessMapPage'

// The ten stages of docs/ECR_PROCESS_MAP.md, in order, as the chart names them.
const STAGES: [string, string][] = [
  ['captured', 'Capture'],
  ['scoping', 'Scoping'],
  ['in_assessment', 'Assessment'],
  ['costing', 'Costing'],
  ['quoting', 'Quote Creation'],
  ['quoted', 'Quote & Negotiation'],
  ['scheduling', 'Scheduling / Bank Build'],
  ['in_implementation', 'Implementation'],
  ['in_validation', 'Validation'],
  ['released', 'Released'],
]

const wrap = () => render(<MemoryRouter><ProcessMapPage /></MemoryRouter>)

describe('ProcessMapPage', () => {
  afterEach(cleanup)

  it('draws a box per stage in the chart, named and badged', () => {
    wrap()
    const chart = screen.getByTestId('procmap-chart')
    for (const [key, name] of STAGES) {
      const node = screen.getByTestId(`procmap-node-${key}`)
      expect(chart.contains(node)).toBe(true)
      expect(node.textContent).toContain(name)
    }
    // Who owns the stage rides inside its box.
    expect(screen.getByTestId('procmap-node-quoting').textContent).toContain('Sales')
    expect(screen.getByTestId('procmap-node-scoping').textContent).toContain('PM')
    expect(screen.getByTestId('procmap-node-costing').textContent).toContain('Team')
  })

  it('runs one arrow from each stage into the next', () => {
    wrap()
    for (let i = 0; i < STAGES.length - 1; i += 1) {
      const edge = screen.getByTestId(`procmap-edge-${STAGES[i][0]}-${STAGES[i + 1][0]}`)
      expect(edge.getAttribute('marker-end')).toBe('url(#arrow)')
    }
  })

  it('branches off to Rejected and to the escalation loop', () => {
    wrap()
    expect(screen.getByTestId('procmap-node-rejected').textContent).toContain('Rejected')
    expect(screen.getByTestId('procmap-edge-quoted-rejected')).toBeTruthy()
    const esc = screen.getByTestId('procmap-node-escalation')
    expect(esc.textContent).toContain('Escalation')
    expect(esc.textContent).toContain('PM + Sales')
    expect(screen.getByTestId('procmap-edge-validation-escalation')).toBeTruthy()
    // And the loop back into implementation, drawn as an edge of its own.
    const loop = screen.getByTestId('procmap-loop-edge')
    expect(loop.getAttribute('marker-end')).toBe('url(#arrow-amber)')
    expect(loop.getAttribute('d')).toBeTruthy()
  })

  it('colours every box by how much of the stage is built', () => {
    wrap()
    const strokeOf = (key: string) =>
      screen.getByTestId(`procmap-node-${key}`).querySelector('rect')?.getAttribute('stroke')
    expect(strokeOf('captured')).toBe('#34d399')   // built
    expect(strokeOf('costing')).toBe('#38bdf8')    // in build
    expect(strokeOf('quoted')).toBe('#fbbf24')     // partial
    expect(strokeOf('scheduling')).toBe('#64748b') // to build
    // And the same reading is spelled out in the table and the legend.
    expect(screen.getByTestId('procmap-status-costing').textContent).toBe('In build')
    expect(screen.getByTestId('procmap-status-quoted').textContent).toBe('Partial')
    expect(screen.getByTestId('procmap-legend').textContent).toContain('To build')
  })

  it('describes every stage under the chart', () => {
    wrap()
    const detail = screen.getByTestId('procmap-detail')
    for (const [key] of STAGES) {
      expect(detail.contains(screen.getByTestId(`procmap-detail-${key}`))).toBe(true)
    }
    // What happens, what it produces, how much of it is built.
    const costing = screen.getByTestId('procmap-detail-costing').textContent ?? ''
    expect(costing).toContain('internal effort (assessment time)')
    expect(costing).toContain('vendor quote docs')
    expect(costing).toContain('In build')
    expect(screen.getByTestId('procmap-detail-in_validation').textContent)
      .toContain('weight validated against the costing guess')
  })

  it('keeps the responsibles and the build order in their own blocks', () => {
    wrap()
    expect(screen.getByTestId('procmap-role-in_assessment').textContent)
      .toBe('Routed departments (Sales exempt)')
    expect(screen.getByTestId('procmap-role-scheduling').textContent)
      .toBe('Scheduling (+ Sales publishes)')
    expect(screen.getByTestId('procmap-table').querySelectorAll('tbody tr')).toHaveLength(10)
    expect(screen.getByTestId('procmap-rules').querySelectorAll('li')).toHaveLength(5)
    expect(screen.getByTestId('procmap-build-order').querySelectorAll('li')).toHaveLength(7)
  })

  it('says nothing in German', () => {
    const { container } = wrap()
    const text = container.textContent ?? ''
    for (const word of ['Angebot', 'Erfassung', 'Bewertung', 'Umsetzung', 'Prozess']) {
      expect(text).not.toContain(word)
    }
  })
})
