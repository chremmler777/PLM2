import { describe, it, expect } from 'vitest'
import { STATUS_LABELS, NEXT_STATUS, STATUS_PILL, OFF_PATH_STATUSES, STATUS_HINTS, stepPosition } from './changeStatus'
import { CHANGE_STATUS_ORDER } from '../types/change'

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

  describe('stepPosition', () => {
    it('returns index/total for the full (customer-relevant) order', () => {
      expect(stepPosition('costing', true)).toEqual({ index: 3, total: 10 })
      expect(stepPosition('captured', true)).toEqual({ index: 0, total: 10 })
      expect(stepPosition('closed', true)).toEqual({ index: 9, total: 10 })
    })

    it('treats undefined customerRelevant as full order', () => {
      expect(stepPosition('quoted', undefined)).toEqual({ index: 4, total: 10 })
    })

    it('omits quoted from the internal (non-customer-relevant) order', () => {
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
