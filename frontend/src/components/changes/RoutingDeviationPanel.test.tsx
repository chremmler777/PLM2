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
