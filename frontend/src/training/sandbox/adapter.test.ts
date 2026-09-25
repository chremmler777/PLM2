import { afterEach, describe, expect, it, vi } from 'vitest'
import type { AxiosRequestConfig } from 'axios'
import { createTrainingAdapter, resolve, SandboxMiss } from './adapter'
import {
  assertContained,
  isPassthrough,
  isTrainingAdapter,
  PASSTHROUGH,
  sandboxClosed,
  sandboxIsOpen,
  sandboxOpened,
} from './containment'
import { createSandbox, FIRST_TRAINEE_ID, SEED, type SandboxState } from './state'

//: The adapter is the guarantee (ported from TWOS adapter.test.ts). If it
//: leaks a request to the network, or silently answers one it does not
//: understand, "training never touches the real database" is worth nothing,
//: so those two properties are tested before any behaviour is.

function network() {
  return vi.fn(async (config: AxiosRequestConfig) => ({
    data: { from: 'network' },
    status: 200,
    statusText: 'OK',
    headers: {},
    config,
  })) as never
}

async function call(s: SandboxState, method: string, url: string, data?: unknown,
  params?: Record<string, unknown>) {
  const adapter = createTrainingAdapter(s, network())
  const res = await adapter({
    method, url, params, data: data === undefined ? undefined : JSON.stringify(data),
  })
  return res.data as Record<string, unknown>
}

async function statusOf(s: SandboxState, method: string, url: string, data?: unknown) {
  try {
    await call(s, method, url, data)
    return 200
  } catch (e) {
    return (e as { response?: { status: number } }).response?.status ?? -1
  }
}

afterEach(() => {
  while (sandboxIsOpen()) sandboxClosed()
})

describe('containment', () => {
  it('never reaches the network for an operational route', async () => {
    const real = network()
    const adapter = createTrainingAdapter(createSandbox(), real)
    await adapter({ method: 'get', url: '/v1/plants/projects' })
    await adapter({ method: 'get', url: `/v1/changes/${SEED.changeCaptured}` })
    await adapter({ method: 'get', url: '/v1/changes/reference/assessment-checklist',
      params: { department_id: 1 } })
    expect(real).not.toHaveBeenCalled()
  })

  it('throws rather than falling through on a route it does not cover', async () => {
    const real = network()
    const s = createSandbox()
    const adapter = createTrainingAdapter(s, real)
    await expect(adapter({ method: 'get', url: '/v1/changes/my-tasks' }))
      .rejects.toBeInstanceOf(SandboxMiss)
    await expect(adapter({ method: 'delete', url: `/v1/changes/${SEED.changeCaptured}` }))
      .rejects.toBeInstanceOf(SandboxMiss)
    expect(real).not.toHaveBeenCalled()
    expect(s.misses).toEqual([
      { method: 'get', url: '/v1/changes/my-tasks' },
      { method: 'delete', url: `/v1/changes/${SEED.changeCaptured}` },
    ])
  })

  it('passes exactly identity and the training record through', async () => {
    expect(PASSTHROUGH).toEqual(['/v1/auth/me'])
    const real = network()
    const adapter = createTrainingAdapter(createSandbox(), real)
    await adapter({ method: 'get', url: '/v1/auth/me' })
    await adapter({ method: 'post', url: '/v1/training/attempts', data: '{}' })
    expect(real).toHaveBeenCalledTimes(2)
    expect(isPassthrough('/v1/trainingish')).toBe(false)
    expect(isPassthrough('/v1/training')).toBe(true)
    expect(isPassthrough('/v1/training/status?x=1')).toBe(true)
    expect(isPassthrough('/v1/changes')).toBe(false)
  })

  it('refuses passthrough to any path that is not literally an allowed one', async () => {
    for (const url of [
      '/v1/training/../changes/1',
      '/v1/training/./../changes/1',
      '/v1/training/%2e%2e/changes/1',
      '/v1/training/%2E%2E/changes/1',
      '/v1/training/.%2e/changes/1',
      '/v1/training/%252e%252e/changes/1',
      '/v1/training/..%2fchanges/1',
      '/v1/training/..\\changes/1',
      '/v1/training//../changes/1',
      '//evil.example/v1/training/status',
      '/v1//training/status',
      '/v1/auth/me/..',
      '/v1/auth/me/../../changes',
      'http://evil.example/v1/training/status',
      '/v1/training/%zz',
    ]) {
      expect(isPassthrough(url), url).toBe(false)
    }
    expect(isPassthrough('/v1/auth/me')).toBe(true)
    expect(isPassthrough('/v1/auth/me/')).toBe(true)
    expect(isPassthrough('/v1/training/attempts')).toBe(true)
    expect(isPassthrough('/v1/training/status?role=a/../b')).toBe(true)

    // And through the adapter: the escape attempt is answered (or missed) by
    // the sandbox, never sent.
    const real = network()
    const s = createSandbox()
    const adapter = createTrainingAdapter(s, real)
    await expect(adapter({ method: 'delete', url: '/v1/training/../changes/1' })).rejects
      .toBeInstanceOf(SandboxMiss)
    expect(real).not.toHaveBeenCalled()
  })

  it('marks its adapter so the client can tell it from the network', () => {
    expect(isTrainingAdapter(createTrainingAdapter(createSandbox(), network()))).toBe(true)
    expect(isTrainingAdapter(['xhr', 'http'])).toBe(false)
    expect(isTrainingAdapter(undefined)).toBe(false)
  })

  it('refuses a request that escapes a live sandbox, and nothing otherwise', () => {
    expect(() => assertContained('/v1/changes')).not.toThrow()
    sandboxOpened()
    expect(() => assertContained('/v1/changes')).toThrow(/Training containment/)
    expect(() => assertContained('/v1/changes', ['xhr'])).toThrow(/Training containment/)
    const adapter = createTrainingAdapter(createSandbox(), network())
    expect(() => assertContained('/v1/changes', adapter)).not.toThrow()
    // On the network client only the passthrough may leave, adapter or not.
    expect(() => assertContained('/v1/changes', adapter, true)).toThrow()
    expect(() => assertContained('/v1/training/attempts', undefined, true)).not.toThrow()
    expect(() => assertContained('/v1/auth/me', undefined, true)).not.toThrow()
    sandboxClosed()
    expect(() => assertContained('/v1/changes')).not.toThrow()
  })

  it('resolves the longest route first', () => {
    expect(resolve('get', `/v1/changes/${SEED.changeInAssessment}/concerns`)?.pattern.source)
      .toContain('concerns')
  })
})

describe('behaviour the tasks rely on', () => {
  it('starts a change with the items, the lead first, and the project PM as lead', async () => {
    const s = createSandbox()
    const c = await call(s, 'post', '/v1/changes', {
      project_id: SEED.project, title: 'T', change_type: 'physical_part', reason: 'r',
      customer_relevant: true, impacted_part_ids: [SEED.partLead, SEED.partSibling],
      lead_part_id: SEED.partLead,
    })
    expect(c.id).toBe(FIRST_TRAINEE_ID)
    expect(c.lead_id).toBe(SEED.pmUser)
    expect((c.impacted_items as { part_id: number; is_lead: boolean }[])
      .map((i) => [i.part_id, i.is_lead])).toEqual([[SEED.partLead, true], [SEED.partSibling, false]])
  })

  it('refuses a change without a reason, and an internal one', async () => {
    const s = createSandbox()
    const base = { project_id: SEED.project, title: 'T', change_type: 'physical_part' }
    expect(await statusOf(s, 'post', '/v1/changes', base)).toBe(422)
    expect(await statusOf(s, 'post', '/v1/changes', { ...base, reason: 'r', customer_relevant: false }))
      .toBe(422)
  })

  it('holds a submit until every row is answered', async () => {
    const s = createSandbox()
    const dept = SEED.departments['Tool Engineer']
    const url = `/v1/changes/${SEED.changeInAssessment}/assessments`
    expect(await statusOf(s, 'post', url, { department_id: dept, verdict: 'feasible',
      details: { impacts: [{ key: 'threed_change', answer: 'no', impacted: false }] } })).toBe(422)
    const all = s.checklist.map((d) => ({ key: d.key, answer: 'no', impacted: false }))
    expect(await statusOf(s, 'post', url, { department_id: dept, verdict: 'feasible',
      details: { impacts: all } })).toBe(200)
    expect(s.submissions).toHaveLength(1)
  })

  it('refuses a moved quote deadline without a reason after capture', async () => {
    const s = createSandbox()
    const url = `/v1/changes/${SEED.changeInAssessment}`
    expect(await statusOf(s, 'patch', url, { required_by_date: '2030-01-01T23:59:59Z' })).toBe(422)
    expect(await statusOf(s, 'patch', url, { required_by_date: '2030-01-01T23:59:59Z',
      required_by_reason: 'customer moved SOP' })).toBe(200)
  })

  it('starts every attempt from the fixture', async () => {
    const s = createSandbox()
    await call(s, 'patch', `/v1/changes/${SEED.changeCaptured}`, { priority: 'high' })
    expect(createSandbox().changes.find((c) => c.id === SEED.changeCaptured)?.priority)
      .toBe('medium')
  })
})
