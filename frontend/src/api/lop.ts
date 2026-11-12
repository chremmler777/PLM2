/**
 * Project LOP API (backend/app/api/v1/lop.py), all under /v1/lop.
 */
import client from './client'
import type {
  LinePatch, LineCreate, LopHistoryItem, LopLine, LopLineInProject, LopLinesQuery,
  LopMeetingDetail, LopOverview, LopProjectResponse, LopView, MeetingMark, PdbResponse, PinBody, SepCandidateGate, LopMyEscalation, SamplingRequestBody
} from '../types/lop'

/** Every LOP query of a project starts with lopKeys.all(projectId): invalidate that after a write. */
export const lopKeys = {
  all: (projectId: number) => ['lop', projectId] as const,
  project: (projectId: number, view: LopView) => ['lop', projectId, 'project', view] as const,
  /** the nav chip's read without the writing sync (own key: the panel's data comes from the full sync) */
  chip: (projectId: number) => ['lop', projectId, 'chip'] as const,
  pdb: (projectId: number, all: boolean) => ['lop', projectId, 'pdb', all] as const,
  sep: (projectId: number) => ['lop', projectId, 'sep-candidates'] as const,
  meeting: (projectId: number, meetingId: number) => ['lop', projectId, 'meeting', meetingId] as const,
  history: (projectId: number, lineId: number) => ['lop', projectId, 'history', lineId] as const,
}

const isNotFound = (e: unknown) => (e as { response?: { status?: number } })?.response?.status === 404

/** The project's LOP, or null when the project has not switched the LOP on (404).
 * sync false (the nav chip): the server only lets lines follow their sources, no writing sync. */
export async function getProjectLop(projectId: number, view: LopView, sync = true): Promise<LopProjectResponse | null> {
  try {
    const params = sync ? { view } : { view, sync: false }
    const data = (await client.get(`/v1/lop/projects/${projectId}`, { params })).data
    return data && typeof data === 'object' && 'project' in data ? data as LopProjectResponse : null
  } catch (e) {
    if (isNotFound(e)) return null
    throw e
  }
}

/** Cross-project queries (overview, lines behind a number, my lines): not tied to one project. */
export const lopOverviewKeys = {
  overview: ['lop-overview'] as const,
  lines: (q: LopLinesQuery) => ['lop-overview', 'lines', q] as const,
  mine: ['lop-mine'] as const,
  myEscalations: ['lop-mine', 'escalations'] as const,
}

export const lopApi = {
  overview: async (): Promise<LopOverview> => (await client.get('/v1/lop/overview')).data,
  lines: async (q: LopLinesQuery): Promise<LopLineInProject[]> =>
    (await client.get('/v1/lop/lines', { params: q })).data,
  mine: async (): Promise<LopLineInProject[]> => (await client.get('/v1/lop/mine')).data,
  myEscalations: async (): Promise<LopMyEscalation[]> => (await client.get('/v1/lop/escalations/mine')).data,
  pdb: async (projectId: number, all: boolean): Promise<PdbResponse> =>
    (await client.get(`/v1/lop/projects/${projectId}/pdb`, all ? { params: { all: true } } : undefined)).data,
  createLine: async (projectId: number, body: LineCreate): Promise<LopLine> =>
    (await client.post(`/v1/lop/projects/${projectId}/lines`, body)).data,
  patchLine: async (lineId: number, body: LinePatch): Promise<LopLine> =>
    (await client.patch(`/v1/lop/lines/${lineId}`, body)).data,
  comment: async (lineId: number, text: string) =>
    (await client.post(`/v1/lop/lines/${lineId}/comments`, { text })).data,
  history: async (lineId: number): Promise<LopHistoryItem[]> =>
    (await client.get(`/v1/lop/lines/${lineId}/history`)).data,
  sepCandidates: async (projectId: number): Promise<SepCandidateGate[]> =>
    ((await client.get(`/v1/lop/projects/${projectId}/sep-candidates`)).data?.gates ?? []),
  addSepItem: async (projectId: number, itemId: number, dueDate?: string | null) =>
    (await client.post(`/v1/lop/projects/${projectId}/lines/from-sep`,
      dueDate ? { item_id: itemId, due_date: dueDate } : { item_id: itemId })).data,
  addSepGate: async (projectId: number, gateId: number): Promise<{ added: number; lines: LopLine[] }> =>
    (await client.post(`/v1/lop/projects/${projectId}/lines/from-sep`, { gate_id: gateId, only_open: true })).data,
  pin: async (projectId: number, topicId: string, body: PinBody): Promise<LopLine> =>
    (await client.post(`/v1/lop/projects/${projectId}/pdb/${topicId}/pin`, body)).data,
  requestSampling: async (projectId: number, toolNumber: string, body: SamplingRequestBody): Promise<{ created: boolean; preferred_week: string | null }> =>
    (await client.post(`/v1/lop/projects/${projectId}/pdb/tools/${encodeURIComponent(toolNumber)}/request-sampling`, body)).data,
  startMeeting: async (projectId: number): Promise<LopMeetingDetail> =>
    (await client.post(`/v1/lop/projects/${projectId}/meetings`)).data,
  meeting: async (meetingId: number): Promise<LopMeetingDetail> =>
    (await client.get(`/v1/lop/meetings/${meetingId}`)).data,
  setMark: async (meetingId: number, lineId: number, mark: MeetingMark) =>
    (await client.put(`/v1/lop/meetings/${meetingId}/marks/${lineId}`, { mark })).data,
  closeMeeting: async (meetingId: number): Promise<LopMeetingDetail> =>
    (await client.post(`/v1/lop/meetings/${meetingId}/close`)).data,
  sendMinutes: async (meetingId: number): Promise<{ sent_to: number }> =>
    (await client.post(`/v1/lop/meetings/${meetingId}/minutes`)).data,
}

function filenameFrom(disposition: string | undefined, fallback: string): string {
  const m = /filename="?([^";]+)"?/i.exec(disposition ?? '')
  return m ? m[1] : fallback
}

/** With responseType blob an error body is a Blob too: read it back as JSON so apiErrorMessage finds the detail. */
async function withJsonErrorBody(e: unknown): Promise<unknown> {
  const response = (e as { response?: { data?: unknown } })?.response
  if (!(response?.data instanceof Blob)) return e
  try {
    response.data = JSON.parse(await response.data.text())
  } catch {
    // not JSON: keep the Blob, the caller shows its fallback text
  }
  return e
}

const REVOKE_DELAY_MS = 10_000

export async function downloadLopXlsx(projectId: number, view: LopView): Promise<void> {
  let res
  try {
    res = await client.get(`/v1/lop/projects/${projectId}/export.xlsx`, { params: { view }, responseType: 'blob' })
  } catch (e) {
    throw await withJsonErrorBody(e)
  }
  const url = URL.createObjectURL(res.data as Blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filenameFrom(res.headers?.['content-disposition'] as string | undefined, `LOP ${projectId}.xlsx`)
  a.click()
  // Revoking right after click() can cancel the download in some browsers.
  setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS)
}

/** One department row of the project team (GET /v1/projects/{id}/team). */
export interface TeamRow {
  department_id: number
  department_name: string
  responsible: { id: number; name: string } | null
  backup?: { id: number; name: string } | null
}

export const teamQueryKey = (projectId: number) => ['project-team', projectId] as const

export async function getTeam(projectId: number): Promise<TeamRow[]> {
  return (await client.get(`/v1/projects/${projectId}/team`)).data
}
