/**
 * The change page's five cockpit reads (stage-state, my-actions, gates,
 * transition deviations, concerns) come from one request, GET
 * /changes/{id}/cockpit, whose parts are exactly what the single endpoints
 * return. Each part keeps its own cache key, so every panel that reads
 * ['change', id, 'concerns'] and friends is untouched; only the fetch is
 * shared. Parts asked for in the same tick (the page mounting, an
 * invalidation of ['change', id]) ride one in-flight bundle. A backend
 * without the bundle falls back to the single endpoint.
 */
import { changesApi } from './changes'

type Bundle = Awaited<ReturnType<typeof changesApi.cockpit>>
export type CockpitPart = 'stage_state' | 'my_actions' | 'gates' | 'deviations' | 'concerns'

interface Batch { parts: Set<CockpitPart>; result: Promise<Partial<Bundle>> }
const batches = new Map<number, Batch>()

const single: { [K in CockpitPart]: (id: number) => Promise<Bundle[K]> } = {
  stage_state: (id) => changesApi.stageState(id),
  my_actions: (id) => changesApi.myActions(id),
  gates: (id) => changesApi.getGates(id),
  deviations: (id) => changesApi.listDeviations(id),
  concerns: (id) => changesApi.listConcerns(id),
}

/** Collect the parts asked for in this tick; two or more share the bundle,
 *  a lone part (one panel refreshing its own data) keeps its light endpoint. */
function batchFor(changeId: number, part: CockpitPart): Batch {
  const open = batches.get(changeId)
  if (open) { open.parts.add(part); return open }
  const batch: Batch = { parts: new Set([part]), result: Promise.resolve({}) }
  batch.result = new Promise<void>((r) => queueMicrotask(r)).then(async () => {
    batches.delete(changeId)
    if (batch.parts.size < 2) return {}
    try { return await changesApi.cockpit(changeId) } catch { return {} }
  })
  batches.set(changeId, batch)
  return batch
}

export async function cockpitPart<K extends CockpitPart>(changeId: number, part: K): Promise<Bundle[K]> {
  const b = await batchFor(changeId, part).result
  // Not bundled (a lone part), or an older backend without the bundle.
  if (b && part in b) return b[part] as Bundle[K]
  return single[part](changeId)
}
