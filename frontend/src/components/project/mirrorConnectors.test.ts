import { describe, it, expect } from 'vitest'
import { mirrorConnectors, mirrorGutterWidth } from './mirrorConnectors'
import type { StructureArticle } from '../../hooks/queries/useProjectStructure'

const brief = (id: number) => ({ part_id: id, part_number: `P${id}`, customer_part_number: null, name: `Part ${id}` })
const article = (id: number, over: Partial<StructureArticle> = {}): StructureArticle => ({
  part_id: id, part_number: `P${id}`, customer_part_number: null, name: `Part ${id}`,
  lifecycle_phase: 'nominated', active_revision_id: null, revisions: [], related: [],
  mirror_of: null, mirrored_by: [], ...over,
})

describe('mirrorConnectors', () => {
  it('gives adjacent rows of a pair start and end segments in the same lane', () => {
    const articles = [article(1), article(2, { mirror_of: brief(1) })]
    const result = mirrorConnectors([1, 2], articles)
    expect(result.get(1)).toEqual([{ lane: 0, kind: 'start', pairId: '1-2' }])
    expect(result.get(2)).toEqual([{ lane: 0, kind: 'end', pairId: '1-2' }])
  })

  it('gives rows between the pair a middle segment', () => {
    const articles = [article(1), article(2), article(3, { mirror_of: brief(1) })]
    const result = mirrorConnectors([1, 2, 3], articles)
    expect(result.get(1)).toEqual([{ lane: 0, kind: 'start', pairId: '1-3' }])
    expect(result.get(2)).toEqual([{ lane: 0, kind: 'middle', pairId: '1-3' }])
    expect(result.get(3)).toEqual([{ lane: 0, kind: 'end', pairId: '1-3' }])
  })

  it('gives no connectors when the partner is not visible (filtered out or hidden by search)', () => {
    const articles = [article(1), article(2, { mirror_of: brief(1) })]
    const result = mirrorConnectors([2], articles)
    expect(result.size).toBe(0)
  })

  it('assigns overlapping pairs to different lanes', () => {
    // Pair A: rows 1-4, Pair B: rows 2-3 -> B nests inside A, needs a different lane.
    const articles = [
      article(1),
      article(4, { mirror_of: brief(1) }),
      article(2),
      article(3, { mirror_of: brief(2) }),
    ]
    const result = mirrorConnectors([1, 2, 3, 4], articles)
    const laneOf = (id: number, kind: string) => result.get(id)?.find((s) => s.kind === kind)?.lane
    expect(laneOf(1, 'start')).toBe(0)
    expect(laneOf(4, 'end')).toBe(0)
    expect(laneOf(2, 'start')).toBe(1)
    expect(laneOf(3, 'end')).toBe(1)
  })

  it('reuses the last lane beyond the max', () => {
    // Four pairs that all overlap each other: rows 1..8 pairing 1-8, 2-7, 3-6, 4-5.
    const articles = [
      article(1), article(8, { mirror_of: brief(1) }),
      article(2), article(7, { mirror_of: brief(2) }),
      article(3), article(6, { mirror_of: brief(3) }),
      article(4), article(5, { mirror_of: brief(4) }),
    ]
    const result = mirrorConnectors([1, 2, 3, 4, 5, 6, 7, 8], articles)
    const laneOf = (id: number, kind: string) => result.get(id)?.find((s) => s.kind === kind)?.lane
    expect(laneOf(1, 'start')).toBe(0)
    expect(laneOf(2, 'start')).toBe(1)
    expect(laneOf(3, 'start')).toBe(2)
    expect(laneOf(4, 'start')).toBe(2) // reuses the last lane past MIRROR_MAX_LANES
  })

  it('dedupes a pair even though it appears on both articles (mirror_of / mirrored_by)', () => {
    const articles = [
      article(1, { mirrored_by: [brief(2)] }),
      article(2, { mirror_of: brief(1) }),
    ]
    const result = mirrorConnectors([1, 2], articles)
    expect(result.get(1)?.length).toBe(1)
    expect(result.get(2)?.length).toBe(1)
  })
})

describe('mirrorGutterWidth', () => {
  it('is zero with no connectors and covers the lanes actually used otherwise', () => {
    expect(mirrorGutterWidth(new Map())).toBe(0)
    const connectors = new Map([[1, [{ lane: 1, kind: 'start' as const, pairId: 'a' }]]])
    expect(mirrorGutterWidth(connectors)).toBe(12)
  })
})
