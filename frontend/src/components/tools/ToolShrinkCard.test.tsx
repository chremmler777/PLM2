import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ToolShrinkCard from './ToolShrinkCard'
import type { ShrinkDecision, ToolShrinkage } from '../../api/toolShrink'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../../hooks/queries/useFieldNotes', () => ({ usePartFieldNoteIndex: () => new Map() }))
vi.mock('../fieldNotes/FieldNoteMarker', () => ({ default: () => null }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() } }))

const SUPPLIER = {
  key: 'm19-doc6', kind: 'supplier' as const, materialdb_id: 19, material_label: '40-0223 Hostacom TRC 352N',
  parallel_pct: 0.8, normal_pct: 1.1, parallel_text: '0.8', normal_text: '1.1',
  method: 'LyondellBasell internal method', condition: 'plaque 2.5 mm',
  source_label: 'LyondellBasell: processing shrinkage (Mail K. Reinert 2026-10-02)', doc_date: '2026-10-02', origin: 'upload',
}

const base: ToolShrinkage = {
  tool: { parallel_pct: null, normal_pct: null }, decisions: [],
  materials: [{ materialdb_id: 19, label: '40-0223 Hostacom TRC 352N', articles: ['5A65DF8'], filler_type: 'TD', notes: null }],
  candidates: [SUPPLIER], error: null, no_material: false, no_article: false,
}

const decision: ShrinkDecision = {
  id: 4, status: 'current', parallel_pct: 0.8, normal_pct: 1.1, source_kind: 'supplier',
  source_label: SUPPLIER.source_label, materialdb_id: 19, material_label: SUPPLIER.material_label, candidates: [SUPPLIER],
  rationale: 'Supplier measured along/across', decided_by: 'C. Demmler', decided_at: '2026-10-05T10:00:00',
  measured_parallel_pct: null, measured_normal_pct: null, measured_ref: null, verdict: null, next_time_note: null,
  verified_by: null, verified_at: null, feedback_status: null, feedback_error: null, feedback_at: null,
}

function wrap(data: ToolShrinkage) {
  clientMocks.get.mockResolvedValue({ data })
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={qc}><ToolShrinkCard partId={7} /></QueryClientProvider>)
}

describe('ToolShrinkCard', () => {
  beforeEach(() => { clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.post.mockResolvedValue({ data: { decisions: [] } }) })
  afterEach(cleanup)

  it('shows each value with its source and records a decision with a reason', async () => {
    wrap(base)
    const row = await screen.findByTestId('shrink-candidate')
    expect(row.textContent).toContain('Supplier statement')
    expect(row.textContent).toContain('Mail K. Reinert')
    expect(row.textContent).toContain('plaque 2.5 mm')
    fireEvent.click(within(row).getByText('Use this'))
    const save = screen.getByTestId('shrink-decide-save')
    expect(save).toHaveProperty('disabled', true)  // no reason yet
    fireEvent.change(screen.getByTestId('shrink-rationale'), { target: { value: 'Same wall as the plaque' } })
    fireEvent.click(save)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/shrinkage/decisions', expect.objectContaining({
      parallel_pct: 0.8, normal_pct: 1.1, source_kind: 'supplier', source_label: SUPPLIER.source_label,
      rationale: 'Same wall as the plaque', materialdb_id: 19,
    })))
  })

  it('records one combined value for both directions', async () => {
    wrap(base)
    fireEvent.click(await screen.findByTestId('shrink-own'))
    // unfilled resin (no glass or carbon fibre): one combined value is the default
    expect(screen.getByTestId('shrink-combined')).toHaveProperty('checked', true)
    expect(screen.queryByTestId('shrink-normal')).toBeNull()
    fireEvent.change(screen.getByTestId('shrink-parallel'), { target: { value: '0.65' } })
    fireEvent.change(screen.getByTestId('shrink-rationale'), { target: { value: 'Painted Bayblend, KTX tooling note' } })
    fireEvent.click(screen.getByTestId('shrink-decide-save'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/shrinkage/decisions', expect.objectContaining({
      parallel_pct: 0.65, normal_pct: 0.65, source_kind: 'own',
    })))
  })

  it('offers parallel and normal when the combined box is cleared', async () => {
    wrap(base)
    fireEvent.click(await screen.findByTestId('shrink-own'))
    fireEvent.click(screen.getByTestId('shrink-combined'))
    expect(screen.getByTestId('shrink-normal')).toBeTruthy()
  })

  it('flags values that were entered without a decision', async () => {
    wrap({ ...base, tool: { parallel_pct: 0.9, normal_pct: 0.9 } })
    expect(await screen.findByTestId('shrink-unrecorded')).toBeTruthy()
    // equal in both directions: one combined value
    expect(screen.getByTestId('shrink-current-parallel').textContent).toBe('0.9 %')
    expect(screen.getByText('Combined')).toBeTruthy()
    expect(screen.queryByTestId('shrink-current-normal')).toBeNull()
  })

  it('verifies after the trial and asks for a next-tool note unless correct', async () => {
    wrap({ ...base, tool: { parallel_pct: 0.8, normal_pct: 1.1 }, decisions: [decision] })
    fireEvent.click(await screen.findByTestId('shrink-verify-open'))
    fireEvent.change(screen.getByTestId('shrink-measured-parallel'), { target: { value: '0.86' } })
    fireEvent.change(screen.getByTestId('shrink-measured-normal'), { target: { value: '1.15' } })
    fireEvent.change(screen.getByTestId('shrink-measured-ref'), { target: { value: 'TH1 6-pc CMM' } })
    fireEvent.click(screen.getByText('Needs offset'))
    expect(screen.getByTestId('shrink-verify-save')).toHaveProperty('disabled', true)
    fireEvent.change(screen.getByTestId('shrink-next-note'), { target: { value: 'Use 0.85 / 1.15' } })
    fireEvent.click(screen.getByTestId('shrink-verify-save'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/shrinkage/decisions/4/verify', {
      measured_parallel_pct: 0.86, measured_normal_pct: 1.15, measured_ref: 'TH1 6-pc CMM', verdict: 'offset',
      next_time_note: 'Use 0.85 / 1.15',
    }))
  })

  it('offers to send a failed report again', async () => {
    wrap({ ...base, tool: { parallel_pct: 0.8, normal_pct: 1.1 }, decisions: [{
      ...decision, verified_at: '2026-10-22T10:00:00', verified_by: 'C. Demmler', verdict: 'correct',
      measured_parallel_pct: 0.8, measured_normal_pct: 1.1, measured_ref: 'TH1', feedback_status: 'failed',
      feedback_error: 'MaterialDB is unreachable',
    }] })
    const fb = await screen.findByTestId('shrink-feedback')
    fireEvent.click(within(fb).getByText('Send again'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/shrinkage/decisions/4/report'))
  })
})
