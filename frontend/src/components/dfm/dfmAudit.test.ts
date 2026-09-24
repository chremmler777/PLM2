import { describe, it, expect } from 'vitest'
import type { DfmAuditEvent } from '../../api/dfm'
import { auditFileSize, auditGroupOf, auditLocalTime, auditShaShort, auditSummary, matchesAuditGroup } from './dfmAudit'

const ev = (over: Partial<DfmAuditEvent>): DfmAuditEvent => ({
  id: 1, at: '2026-09-24T09:15:02.113400', action: 'entry_recorded',
  actor: { id: 2, name: 'Engineer' }, topic: { id: 7, title: 'Gate position' },
  entry: { id: 19, kind: 'original', party: 'ktx' }, file: null,
  details: { kind: 'original', party: 'ktx', addressed_to: ['toolmaker'], note: 'hi' }, ...over,
})

describe('dfmAudit helpers', () => {
  it('groups actions into the four filter groups', () => {
    expect(auditGroupOf('topic_opened')).toBe('topic')
    expect(auditGroupOf('topic_closed')).toBe('topic')
    expect(auditGroupOf('topic_reopened')).toBe('topic')
    expect(auditGroupOf('entry_recorded')).toBe('messages')
    expect(auditGroupOf('entry_updated')).toBe('messages')
    expect(auditGroupOf('file_attached')).toBe('files')
    expect(auditGroupOf('file_viewed')).toBe('views')
    expect(auditGroupOf('file_downloaded')).toBe('views')
  })

  it('matches the all group unconditionally, other groups by mapped action', () => {
    expect(matchesAuditGroup('file_attached', 'all')).toBe(true)
    expect(matchesAuditGroup('file_attached', 'files')).toBe(true)
    expect(matchesAuditGroup('file_attached', 'messages')).toBe(false)
    expect(matchesAuditGroup('file_viewed', 'views')).toBe(true)
    expect(matchesAuditGroup('topic_reopened', 'topic')).toBe(true)
  })

  it('formats a UTC-without-offset timestamp as local date and time', () => {
    const s = auditLocalTime('2026-09-24T09:15:02.113400')
    expect(s).toContain('2026')
    expect(s).toContain('Sep')
    expect(s).toMatch(/\d{1,2}:\d{2}/)
  })

  it('formats file sizes in human units', () => {
    expect(auditFileSize(500)).toBe('500 B')
    expect(auditFileSize(482113)).toBe('471 KB')
    expect(auditFileSize(5_242_880)).toBe('5.0 MB')
  })

  it('shortens a sha256 to a 10-char prefix, or null when absent', () => {
    expect(auditShaShort('9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08')).toBe('9f86d08188')
    expect(auditShaShort(null)).toBeNull()
    expect(auditShaShort(undefined)).toBeNull()
  })

  it('builds a plain-word summary per action', () => {
    expect(auditSummary(ev({ action: 'entry_recorded' }))).toContain('Message recorded')
    expect(auditSummary(ev({ action: 'entry_recorded' }))).toContain('KTX')
    expect(auditSummary(ev({ action: 'file_attached', details: { filename: 'a.pdf' } }))).toBe('File attached: a.pdf')
    expect(auditSummary(ev({ action: 'topic_opened', details: { title: 'Gate position' } }))).toBe('Topic opened: Gate position')
  })
})
