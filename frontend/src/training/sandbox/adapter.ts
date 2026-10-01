import type { AxiosRequestConfig, AxiosResponse } from 'axios'
import type { ChangeConcern } from '../../types/change'
import {
  isPassthrough,
  stripQuery,
  TRAINING_ADAPTER,
} from './containment'
import {
  FIRST_TRAINEE_ID,
  SEED,
  TRAINEE_NAME,
  findChange,
  type SandboxChange,
  type SandboxState,
} from './state'

//: The training adapter, ported from TWOS. It is installed on the shared axios
//: client, so every screen, form, validation rule and payload builder in PLM2
//: runs its real code. What does not happen is a network request.
//:
//: A request no handler covers throws (SandboxMiss) and is recorded on
//: state.misses. It never falls through to the network and it never quietly
//: returns an empty object: a task that grades against a screen which failed
//: to load is worse than one that stops and says so.
//:
//: Handlers model the rules a task depends on (a missing reason, an
//: unanswered checklist row, a quote deadline moved without a reason), in the
//: backend's words, so the trainee meets the same refusal the live system
//: gives. They do not model the rest of the change process.

export class SandboxMiss extends Error {
  constructor(readonly method: string, readonly url: string) {
    super(
      `The training copy has no answer for ${method.toUpperCase()} ${url}. ` +
        'This is a gap in the training fixture, not something you did wrong.',
    )
    this.name = 'SandboxMiss'
  }
}

function ok<T>(data: T, config: AxiosRequestConfig, status = 200): AxiosResponse<T> {
  return {
    data,
    status,
    statusText: 'OK',
    headers: {},
    config: config as AxiosResponse<T>['config'],
  }
}

/** An error shaped the way axios delivers a server 4xx, so real error paths run. */
function fail(status: number, detail: string, config: AxiosRequestConfig): never {
  const err = new Error(detail) as Error & {
    response?: unknown
    config?: unknown
    isAxiosError?: boolean
  }
  err.isAxiosError = true
  err.config = config
  err.response = { status, statusText: 'Error', data: { detail }, headers: {}, config }
  throw err
}

function body<T = Record<string, unknown>>(config: AxiosRequestConfig): T {
  const d = config.data
  if (d == null) return {} as T
  if (typeof d === 'string') return JSON.parse(d) as T
  if (typeof FormData !== 'undefined' && d instanceof FormData) {
    const out: Record<string, unknown> = {}
    d.forEach((v, k) => {
      out[k] = typeof v === 'string' ? v : (v as File).name
    })
    return out as T
  }
  return d as T
}

const nowIso = () => new Date().toISOString()

type Handler = (s: SandboxState, config: AxiosRequestConfig, match: RegExpMatchArray) => unknown

interface Route {
  method: string
  pattern: RegExp
  handle: Handler
}

const routes: Route[] = []

function on(method: string, pattern: RegExp, handle: Handler): void {
  routes.push({ method, pattern, handle })
}

function changeOr404(s: SandboxState, id: string, config: AxiosRequestConfig): SandboxChange {
  const c = findChange(s, Number(id))
  if (!c) fail(404, 'Change not found', config)
  return c
}

// ---------------------------------------------------------------------------
// Starting a change
// ---------------------------------------------------------------------------

on('get', /^\/v1\/changes\/permissions$/, () => ({
  can_start_change: true,
  can_start_mother_plant: false,
  mother_plants: [],
}))

on('get', /^\/v1\/plants\/projects$/, (s) => s.projects)

on('get', /^\/v1\/parts\/project\/(\d+)$/, (s, _c, m) => s.parts[Number(m[1])] ?? [])

on('get', /^\/v1\/projects\/(\d+)\/team$/, (s, _c, m) => s.team[Number(m[1])] ?? [])

on('post', /^\/v1\/changes$/, (s, config) => {
  const b = body<{
    project_id?: number
    title?: string
    change_type?: string
    reason?: string
    description?: string
    customer_relevant?: boolean
    impacted_part_ids?: number[]
    lead_part_id?: number
  }>(config)
  const project = s.projects.find((p) => p.id === b.project_id)
  if (!project) fail(404, 'Project not found', config)
  if (!b.title?.trim()) fail(422, 'A change needs a title.', config)
  if (!b.reason?.trim()) fail(422, 'Say why the change is needed.', config)
  if (b.customer_relevant === false) {
    fail(422, 'The practice tasks use customer changes: start a customer change.', config)
  }
  const parts = s.parts[project.id] ?? []
  const ids = b.impacted_part_ids ?? []
  const id = s.nextId++
  const leadId = b.lead_part_id ?? ids[0]
  const pm = s.team[project.id]?.find((r) => r.department_name === 'Project Manager')?.responsible
  const created: SandboxChange = {
    ...findChange(s, SEED.changeCaptured)!,
    id,
    change_number: `CR-TRAIN-${String(id - FIRST_TRAINEE_ID + 100).padStart(4, '0')}`,
    project_id: project.id,
    title: b.title.trim(),
    description: b.description?.trim() || null,
    reason: b.reason.trim(),
    change_type: b.change_type ?? 'physical_part',
    priority: 'medium',
    status: 'captured',
    customer_relevant: true,
    lead_id: pm?.id ?? null,
    lead_name: pm?.name ?? null,
    raised_by: FIRST_TRAINEE_ID - 1,
    required_by_date: null,
    required_by_reason: null,
    deadline_state: null,
    impacted_items: ids.map((pid, i) => ({
      id: id * 10 + i,
      part_id: pid,
      is_lead: pid === leadId,
      part_number: parts.find((p) => p.id === pid)?.part_number ?? String(pid),
    })),
    assessments: [],
    attachments: [],
    created_at: nowIso(),
    updated_at: nowIso(),
  }
  s.changes.push(created)
  return created
})

on('get', /^\/v1\/changes\/(\d+)$/, (s, config, m) => changeOr404(s, m[1], config))

//: The patch the status card and the start form both use. Only the fields a
//: task touches are modelled; the quote-deadline pushback rule is, because
//: the backend refuses a moved deadline without a reason once the change has
//: left capture and a trainee must meet that refusal here too.
on('patch', /^\/v1\/changes\/(\d+)$/, (s, config, m) => {
  const c = changeOr404(s, m[1], config)
  const b = body<Record<string, unknown>>(config)
  if ('priority' in b) {
    if (!['low', 'medium', 'high', 'critical'].includes(String(b.priority))) {
      fail(422, 'Unknown priority.', config)
    }
    c.priority = b.priority as SandboxChange['priority']
  }
  if ('required_by_date' in b) {
    const moved = (b.required_by_date ?? null) !== c.required_by_date
    const reason = String(b.required_by_reason ?? '').trim()
    if (moved && c.status !== 'captured' && c.required_by_date && !reason) {
      fail(422, 'Moving the quote deadline after capture needs a reason.', config)
    }
    c.required_by_date = (b.required_by_date as string | null) ?? null
    if ('required_by_reason' in b) c.required_by_reason = reason || null
    c.deadline_state = c.required_by_date ? 'on_track' : null
  }
  c.updated_at = nowIso()
  return c
})

on('post', /^\/v1\/changes\/(\d+)\/impacted-items$/, (s, config, m) => {
  const c = changeOr404(s, m[1], config)
  const b = body<{ part_id: number; is_lead?: boolean }>(config)
  const item = {
    id: c.id * 10 + c.impacted_items.length,
    part_id: b.part_id,
    is_lead: !!b.is_lead,
    part_number: String(b.part_id),
  }
  c.impacted_items.push(item)
  return item
})

on('post', /^\/v1\/changes\/(\d+)\/attachments$/, (s, config, m) => {
  const c = changeOr404(s, m[1], config)
  const b = body<{ file?: string; kind?: string; assessment_id?: string }>(config)
  // Filed against the assessment it was dropped on, as the backend does: the
  // form reads a department's documents by that link.
  const a = {
    id: s.nextId++, filename: b.file ?? 'file', kind: b.kind ?? 'general',
    assessment_id: b.assessment_id ? Number(b.assessment_id) : null,
  }
  c.attachments.push(a)
  return a
})

// ---------------------------------------------------------------------------
// Assessing a change
// ---------------------------------------------------------------------------

on('get', /^\/v1\/changes\/reference\/assessment-checklist$/, (s) => s.checklist)

on('get', /^\/v1\/changes\/reference\/risk-types$/, (s) => ({ items: s.riskTypes }))

on('get', /^\/v1\/changes\/(\d+)\/concerns$/, (s, _c, m) =>
  s.concerns.filter((x) => x.change_id === Number(m[1])))

on('post', /^\/v1\/changes\/(\d+)\/concerns$/, (s, config, m) => {
  const c = changeOr404(s, m[1], config)
  const b = body<Partial<ChangeConcern>>(config)
  if (!String(b.note ?? '').trim()) fail(422, 'Say what the risk is.', config)
  const concern = {
    id: s.nextId++,
    change_id: c.id,
    kind: b.kind ?? 'risk',
    note: String(b.note).trim(),
    raised_by: FIRST_TRAINEE_ID - 1,
    raised_by_name: TRAINEE_NAME,
    raised_at: nowIso(),
    is_open: true,
    department_id: b.department_id ?? null,
    risk_type: b.risk_type ?? null,
    severity: b.severity ?? null,
    checklist_key: b.checklist_key ?? null,
  } as ChangeConcern
  s.concerns.push(concern)
  return concern
})

on('put', /^\/v1\/changes\/(\d+)\/assessments\/(\d+)\/draft$/, (s, config, m) => {
  changeOr404(s, m[1], config)
  const b = body<{ draft?: Record<string, unknown> }>(config)
  s.drafts[Number(m[2])] = b.draft ?? {}
  return { ok: true, saved_at: nowIso() }
})

//: Submitting an assessment: the backend holds a submit until every checklist
//: row is answered and a verdict is given, and so does this.
on('post', /^\/v1\/changes\/(\d+)\/assessments$/, (s, config, m) => {
  const c = changeOr404(s, m[1], config)
  const b = body<{
    department_id: number
    verdict?: string
    details?: Record<string, unknown>
    conditions?: string
    notes?: string
  }>(config)
  const row = c.assessments.find((a) => a.department_id === b.department_id)
  if (!row) fail(403, 'Your department has no assessment on this change.', config)
  if (!b.verdict) fail(422, 'Give a verdict.', config)
  const impacts = Array.isArray(b.details?.impacts)
    ? (b.details!.impacts as { key?: string; answer?: string }[])
    : []
  const answered = new Set(impacts.filter((i) => i.key && i.answer).map((i) => i.key))
  const open = s.checklist.filter((d) => !answered.has(d.key))
  if (open.length > 0) {
    fail(422, `${open.length} checklist row(s) still unanswered.`, config)
  }
  if (b.verdict === 'feasible_with_conditions' && !b.conditions?.trim()) {
    fail(422, 'Name the conditions.', config)
  }
  row.verdict = b.verdict
  row.details = b.details ?? {}
  row.submitted_at = nowIso()
  s.submissions.push({
    change_id: c.id,
    department_id: b.department_id,
    verdict: b.verdict,
    details: b.details ?? {},
    conditions: b.conditions,
    notes: b.notes,
  })
  return row
})

// ---------------------------------------------------------------------------
// The adapter
// ---------------------------------------------------------------------------

export function resolve(method: string, path: string): Route | undefined {
  //: Longest pattern first, so /changes/{id}/concerns is never swallowed by
  //: /changes/{id}: the same ordering hazard the FastAPI routers have.
  const candidates = routes.filter((r) => r.method === method && r.pattern.test(path))
  if (candidates.length <= 1) return candidates[0]
  return candidates.sort((a, b) => b.pattern.source.length - a.pattern.source.length)[0]
}

export type TrainingAdapter = (config: AxiosRequestConfig) => Promise<AxiosResponse>

export function createTrainingAdapter(
  state: SandboxState,
  /** How a passthrough request reaches the network. See networkClient. */
  passthrough: (config: AxiosRequestConfig) => Promise<AxiosResponse>,
): TrainingAdapter {
  const adapter: TrainingAdapter = async (config) => {
    const url = config.url ?? ''
    if (isPassthrough(url)) {
      return passthrough({ ...config, adapter: undefined })
    }
    const method = (config.method ?? 'get').toLowerCase()
    const path = stripQuery(url)
    state.calls.push({ method, url: path })

    const route = resolve(method, path)
    if (!route) {
      state.misses.push({ method, url: path })
      throw new SandboxMiss(method, path)
    }
    const match = path.match(route.pattern) as RegExpMatchArray
    // A copy, as a server response is: handing out the live state object
    // lets a refetch return the very reference the cache already holds, so
    // React Query sees nothing new and a screen never shows what a write
    // (an upload, a submit) changed.
    const data = route.handle(state, config, match)
    return ok(data == null ? data : structuredClone(data), config,
      method === 'post' ? 201 : 200)
  }
  ;(adapter as unknown as Record<symbol, unknown>)[TRAINING_ADAPTER] = true
  return adapter
}
