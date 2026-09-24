import { describe, it, expect } from 'vitest'
import { FIELD_KEY_RE, MAX_COMMENT_LENGTH, fieldKeyAllowed, flagTint, indexByField, localDate, localDateTime, noteKey, popoverPosition } from './fieldNotes'
import type { FieldNoteSummary } from '../api/fieldNotes'

const note = (field_key: string, flag_status: FieldNoteSummary['flag_status'] = null): FieldNoteSummary => ({
  id: 1, part_id: 7, field_key, flag_status, flag_set_by: null, flag_set_by_name: null, flag_set_at: null,
  created_at: '2026-09-24T10:00:00', comment_count: 0, last_comment: null,
})

describe('field note helpers', () => {
  it('indexes notes by field key and builds part keys', () => {
    const idx = indexByField([note('tool.cavities', 'open'), note('part.name')])
    expect(idx.get('tool.cavities')?.flag_status).toBe('open')
    expect(indexByField(undefined).size).toBe(0)
    expect(noteKey(7, 'tool.cavities')).toBe('7:tool.cavities')
  })

  it('tints by flag and nothing without one', () => {
    expect(flagTint('open')).toContain('yellow')
    expect(flagTint('confirmed')).toContain('emerald')
    expect(flagTint('rejected')).toContain('red')
    expect(flagTint(null)).toBe('')
  })

  it('accepts only registry style keys', () => {
    expect(FIELD_KEY_RE.test('tool.cavities')).toBe(true)
    expect(FIELD_KEY_RE.test('Tool.cavities')).toBe(false)
    expect(FIELD_KEY_RE.test('x"]')).toBe(false)
  })

  it('keeps the popover inside the viewport', () => {
    expect(popoverPosition({ top: 100, bottom: 120, left: 50, right: 60 }, { width: 1200, height: 800 })).toEqual({ top: 124, left: 50 })
    // near the bottom: opens above the anchor
    expect(popoverPosition({ top: 700, bottom: 720, left: 50, right: 60 }, { width: 1200, height: 800 }).top).toBe(700 - 360 - 4)
    // near the right edge: shifted left
    expect(popoverPosition({ top: 100, bottom: 120, left: 1150, right: 1160 }, { width: 1200, height: 800 }).left).toBe(1200 - 320 - 8)
  })
})


describe('field keys per item category (same rule as the backend)', () => {
  it('allows tool. and dfm. only on tools, paint. and revision. never on tools', () => {
    expect(fieldKeyAllowed('tool.cavities', 'tool')).toBe(true)
    expect(fieldKeyAllowed('dfm.status', 'tool')).toBe(true)
    expect(fieldKeyAllowed('tool.cavities', 'article')).toBe(false)
    expect(fieldKeyAllowed('dfm.status', 'article')).toBe(false)
    expect(fieldKeyAllowed('paint.painted', 'tool')).toBe(false)
    expect(fieldKeyAllowed('revision.level', 'tool')).toBe(false)
    expect(fieldKeyAllowed('paint.painted', 'article')).toBe(true)
    expect(fieldKeyAllowed('part.name', 'tool')).toBe(true)
    expect(fieldKeyAllowed('part.material', 'article')).toBe(true)
  })

  it('keeps the comment limit of the backend', () => {
    expect(MAX_COMMENT_LENGTH).toBe(4000)
  })
})

describe('note timestamps (backend sends naive UTC, vitest runs in Europe/Berlin)', () => {
  it('shows the viewer local time', () => {
    expect(localDateTime('2026-09-24T14:54:27')).toBe('2026-09-24 16:54')
    expect(localDateTime('2026-09-24T14:54:27.123456')).toBe('2026-09-24 16:54')
    expect(localDateTime('2026-09-24T14:54:27Z')).toBe('2026-09-24 16:54')
    expect(localDateTime('2026-09-24T14:54:27+00:00')).toBe('2026-09-24 16:54')
    expect(localDate('2026-09-24T23:30:00')).toBe('2026-09-25')
    expect(localDateTime('garbage')).toBe('garbage')
  })
})
