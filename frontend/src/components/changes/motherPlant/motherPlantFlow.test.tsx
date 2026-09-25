/**
 * Mother-plant side track (spec 2026-09-25 §14) in the shared flow helpers:
 * stepper order, next statuses, tabs, tab aliases, cockpit next steps and
 * Blocked by.
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  branchStepOrder, stepPosition, nextStatusesFor, everydayTabsFor, resolveChangeTab,
  activeTabsFor, changeTabLabel,
} from '../../../lib/changeStatus'
import { resolveWaitStates } from '../../../lib/waitStates'
import CockpitSummary, { nextStepFor } from '../CockpitSummary'
import LifecycleStepper from '../LifecycleStepper'
import type { ChangeDetail } from '../../../types/change'

const change = (over: Partial<ChangeDetail> = {}): ChangeDetail => ({
  id: 9, change_number: 'CR-2026-0009', project_id: 1, title: 'WUG bracket',
  change_type: 'physical_part', priority: 'medium', status: 'scoping',
  raised_by: 1, customer_response: 'pending', lead_id: 5, lead_name: 'Paula PM',
  created_at: '2026-09-01T00:00:00', updated_at: '2026-09-01T00:00:00',
  customer_relevant: false, origin: 'mother_plant',
  mother_plant_name: 'KTX Weissenburg (WUG)', mother_plant_ref: 'WUG-4711',
  mother_plant_sop: '2026-12-01', info_sent_at: null, info_open_department_ids: [],
  quoted_on_time: null, active_deadline: null,
  impacted_items: [], assessments: [], attachments: [], ...over,
} as ChangeDetail)

const deptName = (id: number) => ({ 2: 'Development', 4: 'Tool Engineer' }[id] ?? `#${id}`)

describe('mother-plant flow helpers', () => {
  afterEach(cleanup)

  it('shows only the stages the side track uses', () => {
    expect(branchStepOrder(false, 'mother_plant')).toEqual([
      'captured', 'scoping', 'approved', 'in_implementation', 'in_validation', 'released', 'closed'])
    expect(stepPosition('approved', false, 'mother_plant')).toEqual({ index: 2, total: 7 })
    render(<LifecycleStepper status="scoping" origin="mother_plant" />)
    expect(screen.queryByText('In Assessment')).toBeNull()
    expect(screen.queryByText('Costing')).toBeNull()
    expect(screen.queryByText('Quoted')).toBeNull()
    expect(screen.getByText('Scoping')).toBeDefined()
  })

  it('leaves scoping for approved, never for assessment', () => {
    expect(nextStatusesFor('scoping', 'mother_plant')).toEqual(['approved', 'rejected'])
    expect(nextStatusesFor('scoping', 'customer')).toEqual(['in_assessment', 'rejected'])
  })

  it('replaces Assessments, Costing and Offer with one Mother plant tab', () => {
    expect(everydayTabsFor('mother_plant')).toEqual(
      ['overview', 'scoping', 'impacted', 'mother', 'timing', 'release'])
    expect(everydayTabsFor('customer')).not.toContain('mother')
    expect(changeTabLabel('mother')).toBe('Mother plant')
    for (const old of ['assessments', 'costing', 'offer', 'commercial']) {
      expect(resolveChangeTab(old, 'approved', 'mother_plant')).toBe('mother')
    }
    expect(resolveChangeTab('mother', 'scoping', 'customer')).toBeNull()
    expect(activeTabsFor('scoping', false, 'mother_plant')).toEqual(['mother'])
    expect(activeTabsFor('approved', false, 'mother_plant')).toEqual(['timing'])
  })

  it('cockpit: send the information first, then -> Approved', () => {
    expect(nextStepFor(change())).toEqual([
      { kind: 'go', key: 'info-send', label: 'Send information to the team', tab: 'mother' }])
    expect(nextStepFor(change({ info_sent_at: '2026-09-02T08:00:00' }))).toEqual([
      { kind: 'advance', to: 'approved' }])
  })

  it('cockpit: after the baseline, inform the mother plant (no customer publish)', () => {
    const steps = nextStepFor(change({ status: 'approved', timing_validated_at: '2026-09-10T00:00:00' }))
    expect(steps[0]).toMatchObject({ kind: 'go', key: 'inform-mother', tab: 'timing' })
    expect(steps[1]).toMatchObject({ kind: 'advance', to: 'in_implementation' })
    expect(nextStepFor(change({
      status: 'approved', timing_validated_at: '2026-09-10T00:00:00', plan_published_at: '2026-09-11T00:00:00',
    }))).toEqual([{ kind: 'advance', to: 'in_implementation' }])
  })

  it('cockpit renders the step button (not "decide in the meeting"), the SOP and the origin', () => {
    const onGo = vi.fn()
    render(<QueryClientProvider client={new QueryClient()}>
      <CockpitSummary change={change()} gates={[]} pendingDeviations={0}
        onAdvance={() => {}} advancing={false} onGo={onGo} />
    </QueryClientProvider>)
    fireEvent.click(screen.getByTestId('next-info-send'))
    expect(onGo).toHaveBeenCalledWith('mother')
    expect(screen.getByTestId('mother-plant-sop').textContent).toBe('SOP 01.12.2026')
    expect(screen.getByTestId('mother-plant-origin').textContent).toContain('KTX Weissenburg (WUG) · WUG-4711')
  })

  it('Blocked by: team not informed (a gate), open receipts (info), timing not told', () => {
    const w1 = resolveWaitStates(change(), [], deptName)
    expect(w1.map((w) => [w.key, w.tab, !!w.info])).toEqual([['mother-inform-team', 'mother', false]])
    const w2 = resolveWaitStates(change({
      status: 'approved', info_sent_at: '2026-09-02T08:00:00', info_open_department_ids: [4],
      bank_build_mode: 'running_change', timing_validated_at: '2026-09-10T00:00:00',
    }), [], deptName)
    const receipts = w2.find((w) => w.key === 'mother-receipts')!
    expect(receipts.text).toBe('Read and understood open: Tool Engineer')
    expect(receipts.info).toBe(true)
    expect(w2.find((w) => w.key === 'mother-inform-timing')?.info).toBe(true)
    // never the customer publish wait
    expect(w2.some((w) => w.key === 'plan-publish')).toBe(false)
  })
})
