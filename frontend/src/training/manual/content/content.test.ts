import { describe, expect, it } from 'vitest'
import { CHAPTERS } from '../chapters'
import { CONTENT_CHAPTERS, PRACTICE_TASKS, PRACTICE_TASKS_BY_ROLE, SHOT_SLOTS } from './index'
import type { Block } from './types'

//: The draft content's house rules, checked so the next writer cannot drift
//: from them without noticing. Pure data checks: nothing is rendered.

const ROLES = ['project_management', 'sales', 'engineering', 'scheduling', 'quality', 'finance']

/** Every string a trainee will read, block by block. */
function textsOf(b: Block): string[] {
  if ('lede' in b) return [b.lede]
  if ('p' in b) return [b.p]
  if ('h3' in b) return [b.h3]
  if ('points' in b) return b.points.flat()
  if ('steps' in b) return b.steps.flatMap((s) => [s.title, s.body])
  if ('callout' in b) return [b.callout, b.title ?? '']
  if ('table' in b) return [...b.table.head, ...b.table.rows.flat()]
  return [b.alt, b.caption ?? '']
}

const allTexts: string[] = [
  ...CONTENT_CHAPTERS.flatMap((c) => [
    c.title,
    c.summary,
    ...c.sections.flatMap((s) => [s.title, ...s.blocks.flatMap(textsOf)]),
  ]),
  ...PRACTICE_TASKS.flatMap((t) => [
    t.title,
    t.brief,
    t.why,
    ...t.fixture,
    ...t.pass.flatMap((p) => [p.assert, p.hint]),
  ]),
]

describe('the draft training content', () => {
  it('uses no em-dash, en-dash or placeholder words', () => {
    const bad = allTexts.filter((t) => /[—–]|\bTBD\b|\bTODO\b|\bXXX\b|lorem/i.test(t))
    expect(bad).toEqual([])
  })

  it('gives every section an id unique across the manual', () => {
    const ids = CONTENT_CHAPTERS.flatMap((c) => c.sections.map((s) => s.id))
    expect(new Set(ids).size).toBe(ids.length)
    for (const c of CONTENT_CHAPTERS) {
      for (const s of c.sections) expect(s.id.startsWith(`${c.id}-`) || s.id.startsWith(prefixOf(c.id))).toBe(true)
    }
  })

  it('has no empty section', () => {
    for (const c of CONTENT_CHAPTERS) {
      for (const s of c.sections) expect(s.blocks.length, s.id).toBeGreaterThan(0)
    }
  })

  it('names every screenshot slot once, in kebab case', () => {
    const shots = SHOT_SLOTS.map((s) => s.shot)
    expect(new Set(shots).size).toBe(shots.length)
    for (const s of shots) expect(s).toMatch(/^[a-z0-9]+(-[a-z0-9]+)*$/)
  })

  it('gives every role two to four practice tasks, within the ceiling of five', () => {
    expect(Object.keys(PRACTICE_TASKS_BY_ROLE).sort()).toEqual([...ROLES].sort())
    for (const r of ROLES) {
      const n = PRACTICE_TASKS_BY_ROLE[r as keyof typeof PRACTICE_TASKS_BY_ROLE].length
      expect(n, r).toBeGreaterThanOrEqual(2)
      expect(n, r).toBeLessThanOrEqual(4)
    }
  })

  it('keys every task uniquely, with its role prefix, and gives it pass criteria', () => {
    const keys = PRACTICE_TASKS.map((t) => t.key)
    expect(new Set(keys).size).toBe(keys.length)
    const prefix: Record<string, string> = {
      project_management: 'pm_',
      sales: 'sales_',
      engineering: 'eng_',
      scheduling: 'sch_',
      quality: 'qa_',
      finance: 'fin_',
    }
    for (const t of PRACTICE_TASKS) {
      expect(t.key.startsWith(prefix[t.role]), t.key).toBe(true)
      expect(t.pass.length, t.key).toBeGreaterThan(0)
      expect(t.fixture.length, t.key).toBeGreaterThan(0)
    }
  })

  it('writes every section still pending in ../chapters.tsx, under the same chapter', () => {
    const written = new Map(CONTENT_CHAPTERS.map((c) => [c.id, new Set(c.sections.map((s) => s.id))]))
    const missing = CHAPTERS.filter((c) => c.id !== 'record').flatMap((c) =>
      c.sections.filter((s) => !written.get(c.id)?.has(s.id)).map((s) => `${c.id}/${s.id}`),
    )
    expect(missing).toEqual([])
  })

  it('keeps the chapter numbers and roles of ../chapters.tsx', () => {
    for (const c of CONTENT_CHAPTERS) {
      const live = CHAPTERS.find((x) => x.id === c.id)
      expect(live, c.id).toBeDefined()
      expect(c.number).toBe(live!.number)
      expect(c.roles ?? null).toEqual(live!.roles ?? null)
    }
  })

  it('tags each role chapter with its role', () => {
    for (const r of ROLES) {
      expect(CONTENT_CHAPTERS.some((c) => c.roles?.includes(r as never)), r).toBe(true)
    }
  })
})

/** Chapter ids whose stub sections use a short prefix (see ../chapters.tsx). */
function prefixOf(chapterId: string): string {
  const short: Record<string, string> = {
    engineering: 'eng-',
    scheduling: 'sch-',
    quality: 'qa-',
    finance: 'fin-',
  }
  return short[chapterId] ?? `${chapterId}-`
}
