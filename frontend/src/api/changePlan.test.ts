import { describe, it, expect, vi, beforeEach } from 'vitest'
import { filenameFrom, planApi } from './changePlan'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
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
