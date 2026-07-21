import { describe, it, expect } from 'vitest'
import { STATUS_LABELS, NEXT_STATUS, STATUS_PILL, OFF_PATH_STATUSES } from './changeStatus'
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
})
