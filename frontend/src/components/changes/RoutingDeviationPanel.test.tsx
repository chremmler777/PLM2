import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import RoutingDeviationPanel from './RoutingDeviationPanel'
import { deviationWaitKey } from '../../lib/scopingRules'
import { t } from '../../i18n/cmLabels'
import type { ChangeRouting } from '../../types/change'

vi.mock('../../api/changes', () => ({ changesApi: {} }))
const auth = vi.hoisted(() => ({ current: { userId: 5 as number | null } }))
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => auth.current }))

const routing = (over: Partial<ChangeRouting> = {}): ChangeRouting => ({
  change_id: 7, template_id: 1, template_version: 1, has_deviation: true,
  deviation_status: 'pending_approval', deviation_note: 'Quality owns the sink-mark check',
  deviation_proposed_by: 3, stages: [], ...over,
})

const panel = (r: ChangeRouting, leadId?: number | null) => render(
  <QueryClientProvider client={new QueryClient()}>
    <RoutingDeviationPanel changeId={7} routing={r} departments={[]} routedIds={[]}
      stageOrder={1} canAdd={false} canDecide={false} leadId={leadId} />
  </QueryClientProvider>)

describe('deviationWaitKey', () => {
  it('names the lead for a non-lead proposal', () => {
    expect(deviationWaitKey(3, 9, 5)).toBe('routingDev.waitingForLead')
  })
  it('names the Project Manager when the lead proposed it', () => {
    expect(deviationWaitKey(9, 9, 5)).toBe('routingDev.waitingForPm')
  })
  it('tells the proposer someone else decides', () => {
    expect(deviationWaitKey(5, 9, 5)).toBe('routingDev.waitingYou')
  })
  it('names anyone but the proposer when there is no lead', () => {
    expect(deviationWaitKey(3, null, 5)).toBe('routingDev.waitingForAnyone')
  })
})

describe('RoutingDeviationPanel wait line', () => {
  afterEach(cleanup)

  it('does not say "the change lead" when the lead proposed the change', () => {
    auth.current = { userId: 5 }
    panel(routing({ deviation_proposed_by: 9 }), 9)
    expect(screen.getByTestId('routing-deviation-waiting').textContent).toBe(t('routingDev.waitingForPm'))
  })

  it('keeps the lead wording for someone else\'s proposal', () => {
    auth.current = { userId: 5 }
    panel(routing({ deviation_proposed_by: 3 }), 9)
    expect(screen.getByTestId('routing-deviation-waiting').textContent).toBe(t('routingDev.waitingForLead'))
  })
})

describe('RoutingDeviationPanel add dialog', () => {
  afterEach(cleanup)

  it('offers I (Informed) next to R, A, S and C', async () => {
    auth.current = { userId: 5 }
    const { fireEvent } = await import('@testing-library/react')
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RoutingDeviationPanel changeId={7} routing={routing({ deviation_status: 'none', has_deviation: false })}
          departments={[{ id: 4, name: 'Quality' } as never]} routedIds={[]}
          stageOrder={1} canAdd canDecide={false} leadId={9} />
      </QueryClientProvider>)
    fireEvent.click(screen.getByTestId('add-department-button'))
    const values = Array.from(document.querySelectorAll('input[name="rasic"]'))
      .map((i) => (i as HTMLInputElement).value)
    expect(values).toEqual(['R', 'A', 'S', 'C', 'I'])
    expect(screen.getByText(t('routingDev.letter.I'))).toBeTruthy()
    expect(t('routingDev.letter.I')).toMatch(/Informed|Informiert/)
  })
})

describe('RoutingDeviationPanel pending removal', () => {
  afterEach(cleanup)

  it('names the department a pending deviation asks to take off, marked as awaiting decision', () => {
    auth.current = { userId: 5 }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RoutingDeviationPanel changeId={7} departments={[{ id: 4, name: 'Quality' } as never]}
          routing={routing({ stages: [{ stage_order: 1, departments: [
            { department_id: 4, rasic_letter: 'R', tier: 'blocking', status: 'active',
              verdict: 'pending', assessment_id: 40, pending_removal: true },
            { department_id: 2, rasic_letter: 'R', tier: 'blocking', status: 'active',
              verdict: 'pending', assessment_id: 20 },
          ] }] })}
          routedIds={[4, 2]} stageOrder={1} canAdd={false} canDecide={false} leadId={9} />
      </QueryClientProvider>)
    const row = screen.getByTestId('routing-removal-4-1')
    expect(row.textContent).toContain('Quality')
    expect(row.textContent).toContain(t('routingDev.removalPending'))
    expect(screen.queryByTestId('routing-removal-2-1')).toBeNull()
  })

  it('lists no removal once the deviation is decided', () => {
    auth.current = { userId: 5 }
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RoutingDeviationPanel changeId={7} departments={[]} canAdd canDecide={false}
          routing={routing({ deviation_status: 'approved', stages: [{ stage_order: 1, departments: [
            { department_id: 4, rasic_letter: 'R', tier: 'blocking', status: 'active',
              verdict: 'pending', assessment_id: 40, pending_removal: true },
          ] }] })}
          routedIds={[4]} stageOrder={1} />
      </QueryClientProvider>)
    expect(screen.queryByTestId('routing-deviation-removals')).toBeNull()
  })
})

describe('RoutingDeviationPanel: the lead acting as a department', () => {
  afterEach(() => { cleanup(); sessionStorage.clear() })

  it('says "you are acting as" with a way back, not "waiting for the change lead"', () => {
    auth.current = { userId: 9 }
    sessionStorage.setItem('plm2.actsAsDepartmentId', '4')
    render(
      <QueryClientProvider client={new QueryClient()}>
        <RoutingDeviationPanel changeId={7} routing={routing({ deviation_proposed_by: 3 })}
          departments={[{ id: 4, name: 'Tool Engineer' }]} routedIds={[]}
          stageOrder={1} canAdd={false} canDecide={false} leadId={9} />
      </QueryClientProvider>)
    expect(screen.queryByTestId('routing-deviation-waiting')).toBeNull()
    expect(screen.getByTestId('routing-deviation-acting-lead').textContent)
      .toContain('You are acting as Tool Engineer: switch back to decide as change lead')
    expect(screen.getByTestId('routing-deviation-switch-back')).toBeDefined()
  })

  it('someone else acting as a department still reads the lead wait', () => {
    auth.current = { userId: 5 }
    sessionStorage.setItem('plm2.actsAsDepartmentId', '4')
    panel(routing({ deviation_proposed_by: 3 }), 9)
    expect(screen.getByTestId('routing-deviation-waiting').textContent).toBe(t('routingDev.waitingForLead'))
  })
})
