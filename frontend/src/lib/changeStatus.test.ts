import { describe, it, expect } from 'vitest'
import { STATUS_LABELS, NEXT_STATUS, STATUS_PILL, OFF_PATH_STATUSES, STATUS_HINTS, stepPosition, decodeLogValue } from './changeStatus'
import { CHANGE_STATUS_ORDER } from '../types/change'
import { t } from '../i18n/cmLabels'

describe('changeStatus', () => {
  it('labels and pills cover every status', () => {
    const all = [...CHANGE_STATUS_ORDER, ...OFF_PATH_STATUSES]
    for (const s of all) {
      expect(STATUS_LABELS[s], s).toBeTruthy()
      expect(STATUS_PILL[s], s).toBeTruthy()
    }
  })
  it('every NEXT_STATUS target is a known status', () => {
    for (const targets of Object.values(NEXT_STATUS))
      for (const t of targets!) expect(STATUS_LABELS[t], t).toBeTruthy()
  })

  it('STATUS_HINTS covers on-path statuses with plain-language text', () => {
    expect(STATUS_HINTS.captured).toBe('Describe what should change')
    expect(STATUS_HINTS.scoping).toBe('Meet, decide, pick departments')
    expect(STATUS_HINTS.in_assessment).toBe('Departments check feasibility & cost')
    expect(STATUS_HINTS.costing).toBe('Sum up costs')
    expect(STATUS_HINTS.quoted).toBe('Offer sent to customer')
    expect(STATUS_HINTS.approved).toBe('Go decision made')
    expect(STATUS_HINTS.in_implementation).toBe('Doing the work')
    expect(STATUS_HINTS.in_validation).toBe('Checking results')
    expect(STATUS_HINTS.released).toBe('Change is live')
    expect(STATUS_HINTS.closed).toBe('Wrapped up')
  })

  it('puts quote creation between costing and the offer going out', () => {
    // Sales' own step: the departments are done, the offer is not out yet.
    expect(CHANGE_STATUS_ORDER.indexOf('quoting'))
      .toBe(CHANGE_STATUS_ORDER.indexOf('costing') + 1)
    expect(CHANGE_STATUS_ORDER.indexOf('quoted'))
      .toBe(CHANGE_STATUS_ORDER.indexOf('quoting') + 1)
    expect(STATUS_LABELS.quoting).toBe('Quote creation')
    expect(t('status.quoting', 'de')).toBe('Angebotserstellung')
  })

  describe('stepPosition', () => {
    it('returns index/total for the full (customer-relevant) order', () => {
      // Customer work carries both quoting steps: Sales builds the offer, then
      // it is out with the customer.
      expect(stepPosition('costing', true)).toEqual({ index: 3, total: 11 })
      expect(stepPosition('quoting', true)).toEqual({ index: 4, total: 11 })
      expect(stepPosition('captured', true)).toEqual({ index: 0, total: 11 })
      expect(stepPosition('closed', true)).toEqual({ index: 10, total: 11 })
    })

    it('treats undefined customerRelevant as internal order (matches backend falsy semantics)', () => {
      // A legacy null-flag change shows the 9-step internal path — it is never
      // offered, so neither quoting step appears for it.
      expect(stepPosition('costing', undefined)).toEqual({ index: 3, total: 9 })
      expect(stepPosition('quoting', undefined)).toBeNull()
      expect(stepPosition('quoted', undefined)).toBeNull()
    })

    it('omits both quoting steps from the internal (non-customer-relevant) order', () => {
      expect(stepPosition('costing', false)).toEqual({ index: 3, total: 9 })
      expect(stepPosition('approved', false)).toEqual({ index: 4, total: 9 })
      expect(stepPosition('closed', false)).toEqual({ index: 8, total: 9 })
    })

    it('returns null for off-path statuses', () => {
      expect(stepPosition('on_hold', true)).toBeNull()
      expect(stepPosition('rejected', false)).toBeNull()
      expect(stepPosition('cancelled', undefined)).toBeNull()
    })
  })
})

describe('activeTabsFor', () => {
  it('marks Approval (offer) active next to costing for an internal change at costing', async () => {
    const { activeTabsFor } = await import('./changeStatus')
    expect(activeTabsFor('costing', false)).toEqual(['costing', 'offer'])
    expect(activeTabsFor('costing', null)).toEqual(['costing', 'offer'])
    expect(activeTabsFor('costing', true)).toEqual(['costing'])
    expect(activeTabsFor('quoted', true)).toEqual(['offer'])
    expect(activeTabsFor('approved', false)).toEqual(['timing'])
    expect(activeTabsFor('on_hold', true)).toEqual([])
  })
})

describe('decodeLogValue', () => {
  it('decodes a JSON string and keeps everything else', () => {
    expect(decodeLogValue('"on_hold"')).toBe('on_hold')
    expect(decodeLogValue('on_hold')).toBe('on_hold')
    expect(decodeLogValue('{"mode": "x"}')).toBe('{"mode": "x"}')
    expect(decodeLogValue('"unterminated')).toBe('"unterminated')
    expect(decodeLogValue(null)).toBeNull()
    expect(decodeLogValue(undefined)).toBeNull()
  })
})

describe('engineering review track (spec §17)', () => {
  it('shows its own stages, tabs and next statuses', async () => {
    const m = await import('./changeStatus')
    expect(m.branchStepOrder(false, 'engineering_review')).toEqual(['captured', 'scoping', 'released', 'closed'])
    expect(m.everydayTabsFor('engineering_review')).toEqual(['overview', 'impacted', 'review'])
    expect(m.everydayTabsFor('customer', true)).toContain('review')
    expect(m.everydayTabsFor('customer')).not.toContain('review')
    expect(m.nextStatusesFor('scoping', 'engineering_review')).toEqual(['rejected'])
    expect(m.activeTabsFor('scoping', false, 'engineering_review')).toEqual(['review'])
    expect(m.resolveChangeTab('costing', 'scoping', 'engineering_review')).toBe('review')
    expect(m.resolveChangeTab('review', 'scoping', 'customer')).toBe('review')
    expect(m.changeTabLabel('review')).toBe('Review')
  })
})

describe('one verb per step (UI polish 2.4)', () => {
  it('names every forward step the same way everywhere', async () => {
    const { transitionLabel, TRANSITION_LABELS } = await import('./changeStatus')
    expect(transitionLabel('scoping', 'captured')).toBe('Hand over to scoping')
    expect(transitionLabel('in_assessment', 'scoping')).toBe('Start assessment')
    expect(transitionLabel('costing', 'in_assessment')).toBe('Close assessment')
    expect(transitionLabel('quoting', 'costing')).toBe('Close costing')
    expect(transitionLabel('approved', 'quoted')).toBe('Record approval')
    expect(transitionLabel('in_implementation', 'approved')).toBe('Start implementation')
    expect(transitionLabel('in_validation', 'in_implementation')).toBe('Finish implementation')
    expect(transitionLabel('released', 'in_validation')).toBe('Release change')
    expect(transitionLabel('closed', 'released')).toBe('Close change')
    expect(transitionLabel('rejected', 'scoping')).toBe('Reject change')
    // Where the change comes from changes the verb.
    expect(transitionLabel('scoping', 'in_assessment')).toBe('Back to scoping')
    expect(transitionLabel('scoping', 'rejected')).toBe('Reopen change')
    expect(transitionLabel('in_assessment', 'on_hold')).toBe('Resume')
    // Every status has a verb, and none is an arrow.
    for (const v of Object.values(TRANSITION_LABELS)) expect(v).not.toMatch(/→/)
  })

  it('spells statuses en-US', () => {
    expect(STATUS_LABELS.cancelled).toBe('Canceled')
  })
})
