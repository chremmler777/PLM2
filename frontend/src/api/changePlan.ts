/**
 * Change plan API (spec 2026-09-25 §4). Every mutation answers with the full
 * PlanOut, so callers replace their cached plan with the server's copy.
 */
import client from './client'
import type {
  BulkDateUpdate, FeedbackVerdict, PlanCalendar, PlanChangeSet, PlanChangesOut, PlanDeviation, PlanFeedback,
  PlanKind, PlanLinkType, PlanOut, TaskCreate, TaskPatch,
} from '../types/changePlan'

const base = (id: number) => `/v1/changes/${id}/plan`

/** Hand a blob to the browser as a file download. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Filename from a Content-Disposition header, if the server named one. */
export function filenameFrom(disposition: unknown, fallback: string): string {
  if (typeof disposition !== 'string') return fallback
  const star = /filename\*=(?:UTF-8'')?([^;]+)/i.exec(disposition)
  if (star) return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''))
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain ? plain[1].trim() : fallback
}

async function download(id: number, plan: PlanKind, ext: 'xml' | 'csv'): Promise<string> {
  const r = await client.get<Blob>(`${base(id)}/export.${ext}`, {
    params: { plan }, responseType: 'blob',
  })
  const name = filenameFrom(
    (r.headers as Record<string, unknown> | undefined)?.['content-disposition'],
    `change-${id}-${plan}.${ext}`)
  saveBlob(r.data, name)
  return name
}

export const planApi = {
  get: (id: number, plan: PlanKind) =>
    client.get<PlanOut>(base(id), { params: { plan } }).then((r) => r.data),

  seed: (id: number, plan: PlanKind, replace = false) =>
    client.post<PlanOut>(`${base(id)}/seed`, { plan, replace }).then((r) => r.data),

  createTask: (id: number, body: TaskCreate) =>
    client.post<PlanOut>(`${base(id)}/tasks`, body).then((r) => r.data),

  patchTask: (id: number, taskId: number, body: TaskPatch) =>
    client.patch<PlanOut>(`${base(id)}/tasks/${taskId}`, body).then((r) => r.data),

  bulkPatch: (id: number, plan: PlanKind, updates: BulkDateUpdate[], reason?: string) =>
    client.patch<PlanOut>(`${base(id)}/tasks`, {
      plan, updates, ...(reason ? { reason } : {}),
    }).then((r) => r.data),

  deleteTask: (id: number, taskId: number) =>
    client.delete<PlanOut>(`${base(id)}/tasks/${taskId}`).then((r) => r.data),

  /** Migration 088: typed links. */
  createLink: (id: number, plan: PlanKind, body: { from_task_id: number; to_task_id: number; type: PlanLinkType; lag_days: number }) =>
    client.post<PlanOut>(`${base(id)}/links`, { plan, ...body }).then((r) => r.data),

  patchLink: (id: number, linkId: number, body: { type?: PlanLinkType; lag_days?: number }) =>
    client.patch<PlanOut>(`${base(id)}/links/${linkId}`, body).then((r) => r.data),

  deleteLink: (id: number, linkId: number) =>
    client.delete<PlanOut>(`${base(id)}/links/${linkId}`).then((r) => r.data),

  /** One ChangeSet, applied atomically by the server (temp ids allowed). */
  applyChanges: (id: number, plan: PlanKind, changes: PlanChangeSet, reason?: string) =>
    client.post<PlanChangesOut>(`${base(id)}/changes`, {
      plan, changes, ...(reason ? { reason } : {}),
    }).then((r) => r.data),

  /** Plan calendar (one per change); answers the PlanOut of `plan`. */
  /** `convert`: on a mode switch, convert durations and lags (calendar d x 5/7 -> working d, and back). */
  setCalendar: (id: number, plan: PlanKind, calendar: Partial<PlanCalendar>, convert = false) =>
    client.put<PlanOut>(`${base(id)}/calendar`, { ...calendar, ...(convert ? { convert: true } : {}) }, { params: { plan } }).then((r) => r.data),

  /** MS Project XML into a plan (multipart). */
  importXml: (id: number, plan: PlanKind, file: File | Blob, replace = false) => {
    const fd = new FormData()
    fd.append('file', file, (file as File).name ?? 'plan.xml')
    fd.append('plan', plan)
    fd.append('replace', replace ? 'true' : 'false')
    // The client's JSON Content-Type default must go: the browser sets
    // multipart/form-data with its boundary itself (else the server sees no file).
    return client.post<PlanOut & { import_warnings?: string[] }>(`${base(id)}/import`, fd, {
      headers: { 'Content-Type': undefined },
    }).then((r) => r.data)
  },

  /** Forward pass on the server. On a baselined detailed plan it needs a reason and records deviations. */
  schedule: (id: number, plan: PlanKind, reason?: string) =>
    client.post<PlanOut>(`${base(id)}/schedule`, { plan, ...(reason ? { reason } : {}) }).then((r) => r.data),

  /** Downloads the MS Project XML; resolves with the filename used. */
  exportXml: (id: number, plan: PlanKind) => download(id, plan, 'xml'),
  /** Downloads the CSV; resolves with the filename used. */
  exportCsv: (id: number, plan: PlanKind) => download(id, plan, 'csv'),

  feedback: (id: number) =>
    client.get<PlanFeedback>(`${base(id)}/feedback`).then((r) => r.data),

  postFeedback: (id: number, body: {
    department_id: number; verdict: FeedbackVerdict; note?: string
  }) => client.post(`${base(id)}/feedback`, body).then((r) => r.data),

  validateTiming: (id: number) =>
    client.post(`${base(id)}/validate-timing`).then((r) => r.data),

  deviations: (id: number) =>
    client.get<PlanDeviation[]>(`${base(id)}/deviations`).then((r) => r.data),

  lockDeviation: (id: number, deviationId: number, note?: string) =>
    client.post(`${base(id)}/deviations/${deviationId}/lock`,
      note ? { note } : {}).then((r) => r.data),

  escalateDeviation: (id: number, deviationId: number, note: string) =>
    client.post(`${base(id)}/deviations/${deviationId}/escalate`, { note })
      .then((r) => r.data),

  /** Sales puts the validated plan in front of the customer (existing endpoint). */
  publishPlan: (id: number) =>
    client.post(`/v1/changes/${id}/bank-build/publish`).then((r) => r.data),
}

export default planApi
