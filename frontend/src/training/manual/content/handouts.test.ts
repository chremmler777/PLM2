import { describe, expect, it } from 'vitest'
import { TASKS_BY_ROLE } from '../../tasks'
import { HANDOUTS, handoutMarkdown, practiceOf } from './handouts'
import { PRACTICE_TASKS_BY_ROLE } from './index'

//: The one-page handouts: house rules, one per role, and the markdown files
//: in docs/training/handouts/ generated from them. WRITE_HANDOUTS=1 rewrites
//: the files instead of comparing (see WIRING.md, section 1).

// A plain path: jsdom's URL would resolve a relative URL against its page.
const HERE = decodeURIComponent(import.meta.url.replace(/^file:\/\//, '').replace(/[^/]*$/, ''))
const DOCS = `${HERE}../../../../../docs/training/handouts/`

/** Node's fs, typed here: the app's tsconfig carries no Node types. */
type Fs = {
  existsSync(p: string): boolean
  readFileSync(p: string, enc: 'utf8'): string
  writeFileSync(p: string, data: string): void
}
const NODE_FS = 'node:fs'
const ROLES = Object.keys(PRACTICE_TASKS_BY_ROLE)

function textsOf(h: (typeof HANDOUTS)[number]): string[] {
  return [
    h.title,
    h.audience,
    h.job,
    ...h.blocks.flatMap((b) => [
      b.h2,
      ...('table' in b ? [...b.table.head, ...b.table.rows.flat()] : 'points' in b ? b.points.flat() : [b.p]),
    ]),
  ]
}

describe('the one-page handouts', () => {
  it('has one per training role', () => {
    expect(HANDOUTS.map((h) => h.role).sort()).toEqual([...ROLES].sort())
  })

  it('uses no em-dash, en-dash or placeholder words', () => {
    const bad = HANDOUTS.flatMap(textsOf).filter((t) => /[—–]|\bTBD\b|\bTODO\b|\bXXX\b|lorem/i.test(t))
    expect(bad).toEqual([])
  })

  it('gives every table row as many cells as its head', () => {
    for (const h of HANDOUTS) {
      for (const b of h.blocks) {
        if ('table' in b) for (const r of b.table.rows) expect(r.length, `${h.role}: ${r[0]}`).toBe(b.table.head.length)
      }
    }
  })

  it('splits the practical check into what runs today and what is coming', () => {
    for (const r of ROLES) {
      const { active, coming } = practiceOf(r)
      expect(active.map((t) => t.key)).toEqual(TASKS_BY_ROLE[r].map((t) => t.key))
      for (const t of coming) expect(active.some((a) => a.key === t.key), t.key).toBe(false)
    }
    // The written specs that run today are not listed as coming.
    expect(practiceOf('engineering').coming.map((t) => t.key)).toEqual([
      'eng_costing_vendor_quotes',
      'eng_contain_issue',
    ])
  })

  it('matches docs/training/handouts/*.md', async () => {
    const fs = (await import(/* @vite-ignore */ NODE_FS)) as Fs
    if (!fs.existsSync(DOCS)) return // a checkout without docs (container build)
    for (const h of HANDOUTS) {
      const path = DOCS + h.file
      const md = handoutMarkdown(h)
      if (import.meta.env.WRITE_HANDOUTS === '1') fs.writeFileSync(path, md)
      expect(fs.readFileSync(path, 'utf8'), h.file).toBe(md)
    }
  })
})
