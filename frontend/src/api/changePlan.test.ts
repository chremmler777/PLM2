import { describe, it, expect, vi, beforeEach } from 'vitest'
import { filenameFrom, planApi } from './changePlan'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn(), put: vi.fn() }))
vi.mock('./client', () => ({ default: clientMocks, API_BASE_URL: '/plm2/api' }))

describe('plan api', () => {
  beforeEach(() => {
    Object.values(clientMocks).forEach((m) => m.mockReset())
    Object.values(clientMocks).forEach((m) => m.mockResolvedValue({ data: { ok: 1 }, headers: {} }))
  })

  it('reads a plan by kind', async () => {
    await planApi.get(7, 'quote')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/changes/7/plan', { params: { plan: 'quote' } })
  })

  it('bulk-patches dates with the reason only when given', async () => {
    await planApi.bulkPatch(7, 'detailed', [{ id: 1, start_date: '2026-10-08' }])
    expect(clientMocks.patch).toHaveBeenLastCalledWith('/v1/changes/7/plan/tasks',
      { plan: 'detailed', updates: [{ id: 1, start_date: '2026-10-08' }] })
    await planApi.bulkPatch(7, 'detailed', [{ id: 1, duration_days: 3 }], 'supplier late')
    expect(clientMocks.patch).toHaveBeenLastCalledWith('/v1/changes/7/plan/tasks',
      { plan: 'detailed', updates: [{ id: 1, duration_days: 3 }], reason: 'supplier late' })
  })

  it('hits every task and plan endpoint on the right path', async () => {
    await planApi.seed(7, 'detailed', true)
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/seed', { plan: 'detailed', replace: true })
    await planApi.patchTask(7, 3, { progress_pct: 50 })
    expect(clientMocks.patch).toHaveBeenLastCalledWith('/v1/changes/7/plan/tasks/3', { progress_pct: 50 })
    await planApi.deleteTask(7, 3)
    expect(clientMocks.delete).toHaveBeenLastCalledWith('/v1/changes/7/plan/tasks/3')
    await planApi.schedule(7, 'quote')
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/schedule', { plan: 'quote' })
    await planApi.postFeedback(7, { department_id: 4, verdict: 'concern', note: 'x' })
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/feedback',
      { department_id: 4, verdict: 'concern', note: 'x' })
    await planApi.validateTiming(7)
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/validate-timing')
    await planApi.lockDeviation(7, 9)
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/deviations/9/lock', {})
    await planApi.escalateDeviation(7, 9, 'tell them')
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/deviations/9/escalate', { note: 'tell them' })
    await planApi.publishPlan(7)
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/bank-build/publish')
  })

  it('hits the 088 link, batch, calendar and import endpoints', async () => {
    await planApi.createLink(7, 'quote', { from_task_id: 1, to_task_id: 2, type: 'SS', lag_days: -1 })
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/links',
      { plan: 'quote', from_task_id: 1, to_task_id: 2, type: 'SS', lag_days: -1 })
    await planApi.patchLink(7, 9, { lag_days: 2 })
    expect(clientMocks.patch).toHaveBeenLastCalledWith('/v1/changes/7/plan/links/9', { lag_days: 2 })
    await planApi.deleteLink(7, 9)
    expect(clientMocks.delete).toHaveBeenLastCalledWith('/v1/changes/7/plan/links/9')
    const changes = { tasks_upsert: [{ id: 'tmp-1', name: 'x' }], tasks_delete: [], links_upsert: [], links_delete: [] }
    await planApi.applyChanges(7, 'detailed', changes)
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/changes', { plan: 'detailed', changes })
    await planApi.applyChanges(7, 'detailed', changes, 'late')
    expect(clientMocks.post).toHaveBeenLastCalledWith('/v1/changes/7/plan/changes', { plan: 'detailed', changes, reason: 'late' })
    const cal = { mode: 'working' as const, workdays: [1, 2, 3, 4, 5], holidays: ['2026-12-25'] }
    await planApi.setCalendar(7, 'quote', cal)
    expect(clientMocks.put).toHaveBeenLastCalledWith('/v1/changes/7/plan/calendar', cal, { params: { plan: 'quote' } })
  })

  it('uploads an MS Project file as multipart with plan and replace', async () => {
    const file = new File(['<Project/>'], 'p.xml', { type: 'application/xml' })
    await planApi.importXml(7, 'detailed', file, true)
    const [url, body, config] = clientMocks.post.mock.calls[clientMocks.post.mock.calls.length - 1]
    expect(url).toBe('/v1/changes/7/plan/import')
    // Multipart: the JSON default Content-Type is cleared so the browser adds the boundary.
    expect(config).toEqual({ headers: { 'Content-Type': undefined } })
    expect(body).toBeInstanceOf(FormData)
    expect((body as FormData).get('plan')).toBe('detailed')
    expect((body as FormData).get('replace')).toBe('true')
    expect(((body as FormData).get('file') as File).name).toBe('p.xml')
  })

  it('downloads the MS Project export as a blob under the server filename', async () => {
    const createObjectURL = vi.fn(() => 'blob:x')
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    clientMocks.get.mockResolvedValue({
      data: new Blob(['<Project/>']),
      headers: { 'content-disposition': 'attachment; filename="ECR-12-detailed.xml"' },
    })
    const name = await planApi.exportXml(7, 'detailed')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/changes/7/plan/export.xml',
      { params: { plan: 'detailed' }, responseType: 'blob' })
    expect(name).toBe('ECR-12-detailed.xml')
    expect(click).toHaveBeenCalled()
    click.mockRestore()
  })

  it('falls back to a default filename', () => {
    expect(filenameFrom(undefined, 'a.csv')).toBe('a.csv')
    expect(filenameFrom("attachment; filename*=UTF-8''ECR%2012.csv", 'a.csv')).toBe('ECR 12.csv')
  })
})
