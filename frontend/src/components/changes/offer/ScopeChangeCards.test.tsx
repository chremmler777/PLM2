import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ScopeChangeCards, { type ScopeChangeCardsProps } from './ScopeChangeCards'
import { changesApi } from '../../../api/changes'
import type { ScopeChangeCard } from '../../../types/change'

vi.mock('../../../api/changes', () => ({
  changesApi: {
    scopeChanges: vi.fn(), requestScopeChange: vi.fn(), decideScopeChange: vi.fn(),
    scopeRecosted: vi.fn(), scopeTold: vi.fn(),
  },
}))
vi.mock('sonner', () => ({ toast: { error: vi.fn(), success: vi.fn() } }))

const card = (over: Partial<ScopeChangeCard> = {}): ScopeChangeCard => ({
  id: 3, kind: 'customer', status: 'requested', part_number: '886.198', what: 'Second variant grained',
  post_accept: false, requested_by_name: 'Jubei', requested_at: '2026-10-15T09:00:00',
  departments: [], waiting_for: [], ...over,
})

const props = (over: Partial<ScopeChangeCardsProps> = {}): ScopeChangeCardsProps => ({
  changeId: 7, status: 'quoted', canRequest: true, mayDecide: false, isSales: true,
  myDepartmentIds: [], routed: [{ id: 21, name: 'Tool Engineer' }, { id: 22, name: 'Process Engineer' }],
  attachments: [], ...over,
})

const wrap = (p: ScopeChangeCardsProps) => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient()}><ScopeChangeCards {...p} /></QueryClientProvider></MemoryRouter>)

describe('ScopeChangeCards (§6 [R3])', () => {
  afterEach(cleanup)
  beforeEach(() => { vi.clearAllMocks() })

  it('Sales records the request only with what and the customer evidence', async () => {
    vi.mocked(changesApi.scopeChanges).mockResolvedValue([])
    vi.mocked(changesApi.requestScopeChange).mockResolvedValue([card()])
    wrap(props())
    fireEvent.click(await screen.findByTestId('scope-request-open'))
    const save = screen.getByTestId('scope-request-save') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('scope-what'), { target: { value: 'Second variant grained' } })
    expect(save.disabled).toBe(true)          // NEGATIVE: no mail, no reference
    fireEvent.change(screen.getByTestId('scope-ref'), { target: { value: 'ok' } })
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('scope-ref'), { target: { value: 'Mail 15 Oct buyer' } })
    fireEvent.change(screen.getByTestId('scope-part'), { target: { value: '886.198' } })
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.requestScopeChange).toHaveBeenCalledWith(7, {
      what: 'Second variant grained', part_number: '886.198', ref: 'Mail 15 Oct buyer' }))
  })

  it('nobody but Sales or the run team sees the request button', async () => {
    vi.mocked(changesApi.scopeChanges).mockResolvedValue([card()])
    wrap(props({ canRequest: false }))
    expect(await screen.findByTestId('scope-card-3')).toBeDefined()
    expect(screen.queryByTestId('scope-request-open')).toBeNull()
    expect(screen.queryByTestId('scope-decide-3')).toBeNull()   // not the lead either
  })

  it('the lead accepts with the routed departments preticked; refusing needs a note', async () => {
    vi.mocked(changesApi.scopeChanges).mockResolvedValue([card()])
    vi.mocked(changesApi.decideScopeChange).mockResolvedValue([card({ status: 'recosting' })])
    wrap(props({ mayDecide: true }))
    const refuse = await screen.findByTestId('scope-refuse-3') as HTMLButtonElement
    expect(refuse.disabled).toBe(true)        // NEGATIVE: no reason yet
    fireEvent.click(screen.getByTestId('scope-dept-3-22'))      // untick Process
    fireEvent.click(screen.getByTestId('scope-accept-3'))
    await waitFor(() => expect(changesApi.decideScopeChange).toHaveBeenCalledWith(7, 3,
      { decision: 'accept', department_ids: [21] }))
  })

  it('a department marks only its own re-costing done; the card says who it waits for', async () => {
    vi.mocked(changesApi.scopeChanges).mockResolvedValue([card({
      status: 'recosting', recost_due: '2026-10-19', waiting_for: ['Tool Engineer', 'Process Engineer'],
      departments: [{ id: 21, name: 'Tool Engineer', done: false }, { id: 22, name: 'Process Engineer', done: false }] })])
    vi.mocked(changesApi.scopeRecosted).mockResolvedValue([card({ status: 'recosting' })])
    wrap(props({ myDepartmentIds: [21], canRequest: false }))
    expect((await screen.findByTestId('scope-waiting-3')).textContent).toContain('Waiting for: Tool Engineer, Process Engineer')
    expect(screen.queryByTestId('scope-recosted-3-22')).toBeNull()
    fireEvent.click(screen.getByTestId('scope-recosted-3-21'))
    await waitFor(() => expect(changesApi.scopeRecosted).toHaveBeenCalledWith(7, 3, 21, undefined))
  })

  it('no cost impact needs a sentence saying why (R4)', async () => {
    vi.mocked(changesApi.scopeChanges).mockResolvedValue([card({
      status: 'recosting', waiting_for: ['Tool Engineer'],
      departments: [{ id: 21, name: 'Tool Engineer', done: false }] })])
    vi.mocked(changesApi.scopeRecosted).mockResolvedValue([card({ status: 'ready' })])
    wrap(props({ myDepartmentIds: [21], canRequest: false }))
    fireEvent.click(await screen.findByTestId('scope-nocost-open-3-21'))
    const confirm = screen.getByTestId('scope-nocost-3-21') as HTMLButtonElement
    fireEvent.change(screen.getByTestId('scope-nocost-note-3-21'), { target: { value: 'same insert' } })
    expect(confirm.disabled).toBe(true)        // NEGATIVE: too short to say why
    fireEvent.change(screen.getByTestId('scope-nocost-note-3-21'),
      { target: { value: 'Same insert, only the engraving text changes' } })
    fireEvent.click(confirm)
    await waitFor(() => expect(changesApi.scopeRecosted).toHaveBeenCalledWith(
      7, 3, 21, 'Same insert, only the engraving text changes'))
  })

  it('a refused card leaves Sales to tell the customer', async () => {
    vi.mocked(changesApi.scopeChanges).mockResolvedValue([card({ status: 'refused', decision_note: 'Not in this tool' })])
    vi.mocked(changesApi.scopeTold).mockResolvedValue([card({ status: 'refused', told_at: '2026-10-16T00:00:00' })])
    wrap(props())
    const told = await screen.findByTestId('scope-told-3') as HTMLButtonElement
    expect(told.disabled).toBe(true)
    fireEvent.change(screen.getByTestId('scope-told-ref-3'), { target: { value: 'Mail 16 Oct to buyer' } })
    fireEvent.click(told)
    await waitFor(() => expect(changesApi.scopeTold).toHaveBeenCalledWith(7, 3, 'Mail 16 Oct to buyer'))
  })
})
