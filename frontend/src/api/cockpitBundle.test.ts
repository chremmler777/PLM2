import { describe, it, expect, vi, beforeEach } from 'vitest'
import { cockpitPart } from './cockpitBundle'
import { changesApi } from './changes'

vi.mock('./changes', () => ({
  changesApi: {
    cockpit: vi.fn(), stageState: vi.fn(), myActions: vi.fn(), getGates: vi.fn(),
    listDeviations: vi.fn(), listConcerns: vi.fn(),
  },
}))

const bundle = {
  change_id: 7, stage_state: { s: 1 }, my_actions: { items: [] }, gates: [{ gate_key: 'release' }],
  deviations: [], concerns: [{ id: 3 }],
}

describe('cockpitPart', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('parts asked for together ride one bundle request', async () => {
    vi.mocked(changesApi.cockpit).mockResolvedValue(bundle as never)
    const [g, c, s] = await Promise.all([
      cockpitPart(7, 'gates'), cockpitPart(7, 'concerns'), cockpitPart(7, 'stage_state')])
    expect(changesApi.cockpit).toHaveBeenCalledTimes(1)
    expect(g).toEqual(bundle.gates)
    expect(c).toEqual(bundle.concerns)
    expect(s).toEqual(bundle.stage_state)
    expect(changesApi.getGates).not.toHaveBeenCalled()
  })

  it('a lone part keeps its own light endpoint', async () => {
    vi.mocked(changesApi.listConcerns).mockResolvedValue([{ id: 9 }] as never)
    expect(await cockpitPart(7, 'concerns')).toEqual([{ id: 9 }])
    expect(changesApi.cockpit).not.toHaveBeenCalled()
  })

  it('falls back to the single endpoints when the bundle fails (older backend)', async () => {
    vi.mocked(changesApi.cockpit).mockRejectedValue(new Error('404'))
    vi.mocked(changesApi.getGates).mockResolvedValue([] as never)
    vi.mocked(changesApi.listDeviations).mockResolvedValue([] as never)
    await Promise.all([cockpitPart(7, 'gates'), cockpitPart(7, 'deviations')])
    expect(changesApi.getGates).toHaveBeenCalledWith(7)
    expect(changesApi.listDeviations).toHaveBeenCalledWith(7)
  })
})
