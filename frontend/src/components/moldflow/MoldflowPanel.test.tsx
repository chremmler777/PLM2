import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import MoldflowPanel from './MoldflowPanel'
import type { MoldflowRow, ProjectMoldflow } from '../../api/moldflow'
import { articleIdentity, lastStep, nextVersion } from '../../api/moldflow'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const mfRow = (over: Partial<MoldflowRow> = {}): MoldflowRow => ({
  id: 11, tool_part_id: 90, version: 'V1', cavity_layout: null, geometry_status: 'ready', gate_status: 'ready',
  udb_status: 'open', material_label: null, udb_source: null, mf_requested_on: null, received_on: '2026-10-15',
  ktx_review_on: '2026-10-15', sent_customer_on: '2026-10-15', customer_feedback_on: null, final_on: null,
  customer_feedback: null, status: 'sent_to_customer', derived_status: 'sent_to_customer',
  blockers: 'Clamp force high, bigger machine needed', owner: null, notes: null, source_ref: null, updated_at: null, ...over,
})

const data = (canEdit: boolean): ProjectMoldflow => ({
  project_id: 2, can_edit: canEdit,
  tools: [
    { tool: { part_id: 90, part_number: '199410', name: 'TOOL', cavities: '2' }, latest_id: 11, rows: [mfRow()],
      articles: [{ part_id: 5, part_number: '20-1994-019-0', customer_part_number: '206.881.799',
        tier1_part_number: 'S00HP8-110', name: 'A-bracket outer trim' }] },
    { tool: { part_id: 91, part_number: '199401', name: 'TOOL 2', cavities: '2+2' }, latest_id: null, rows: [],
      articles: [
        { part_id: 6, part_number: '20-1994-001-0', customer_part_number: '206.882.251', tier1_part_number: 'S00H4X-110', name: 'Handle height adj LH' },
        { part_id: 7, part_number: '20-1994-002-0', customer_part_number: '206.882.252', tier1_part_number: 'S00H4W-110', name: 'Handle height adj RH' },
      ] },
  ],
})

function mount() {
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MoldflowPanel projectId={2} />
    </QueryClientProvider>)
}

describe('MoldflowPanel', () => {
  beforeEach(() => {
    for (const m of Object.values(clientMocks)) m.mockReset()
    clientMocks.patch.mockResolvedValue({ data: mfRow() })
    clientMocks.post.mockResolvedValue({ data: mfRow({ id: 12 }) })
  })
  afterEach(cleanup)

  it('leads each tool with the customer identity, then the KTX tool number', async () => {
    clientMocks.get.mockResolvedValue({ data: data(false) })
    mount()
    const t10 = await screen.findByTestId('mf-tool-199410')
    expect(t10.textContent).toContain('206.881.799 / S00HP8-110 A-bracket outer trim')
    expect(t10.textContent).toContain('KTX 199410')
    expect(within(t10).getByTestId('mf-status-chip').textContent).toBe('At customer')
    expect(t10.textContent).toContain('Clamp force high')
    expect(t10.textContent).toContain('2026-10-15')
    const t01 = screen.getByTestId('mf-tool-199401')
    expect(t01.textContent).toContain('206.882.251 / S00H4X-110 Handle height adj LH')
    expect(t01.textContent).toContain('206.882.252 / S00H4W-110 Handle height adj RH')
    expect(t01.textContent).toContain('No Moldflow yet')
    expect(within(t01).getByText(/2\+2 cav/)).toBeTruthy()
  })

  it('is read only without tool rights', async () => {
    clientMocks.get.mockResolvedValue({ data: data(false) })
    mount()
    await screen.findByTestId('mf-tool-199410')
    expect(screen.queryByTestId('mf-status-select')).toBeNull()
    expect(screen.queryByTestId('mf-add-199401')).toBeNull()
    expect(screen.queryByRole('button', { name: /Edit Received/ })).toBeNull()
  })

  it('edits a date in place and saves on Enter', async () => {
    clientMocks.get.mockResolvedValue({ data: data(true) })
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit MF requested' }))
    const input = screen.getByLabelText('MF requested') as HTMLInputElement
    expect(input.type).toBe('date')
    fireEvent.change(input, { target: { value: '2026-10-10' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    await vi.waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/moldflow/11', { mf_requested_on: '2026-10-10' }))
  })

  it('Escape cancels an edit without saving', async () => {
    clientMocks.get.mockResolvedValue({ data: data(true) })
    mount()
    fireEvent.click(await screen.findByRole('button', { name: 'Edit Owner' }))
    const input = screen.getByLabelText('Owner')
    fireEvent.change(input, { target: { value: 'Dale' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    fireEvent.blur(input)
    expect(clientMocks.patch).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Owner')).toBeNull()
  })

  it('changes status and input state with their selects', async () => {
    clientMocks.get.mockResolvedValue({ data: data(true) })
    mount()
    fireEvent.change(await screen.findByTestId('mf-status-select'), { target: { value: 'customer_feedback' } })
    await vi.waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/moldflow/11', { status: 'customer_feedback' }))
    fireEvent.change(screen.getByLabelText('UDB (material data) status'), { target: { value: 'ready' } })
    await vi.waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/moldflow/11', { udb_status: 'ready' }))
  })

  it('adds the next version on a tool', async () => {
    clientMocks.get.mockResolvedValue({ data: data(true) })
    mount()
    fireEvent.click(await screen.findByTestId('mf-add-199410'))
    await vi.waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/90/moldflow', { version: 'V2' }))
    fireEvent.click(screen.getByTestId('mf-add-199401'))
    await vi.waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/91/moldflow', { version: 'V1' }))
  })

  it('says so when the overview cannot load', async () => {
    clientMocks.get.mockRejectedValue({ response: { status: 500, data: { detail: 'boom' } } })
    mount()
    expect((await screen.findByText(/could not be loaded/)).textContent).toContain('boom')
  })
})

describe('moldflow helpers', () => {
  it('next version, last step and identity', () => {
    expect(nextVersion([])).toBe('V1')
    expect(nextVersion([mfRow({ version: 'V2' }), mfRow({ version: 'V10' })])).toBe('V11')
    expect(lastStep(mfRow())).toEqual({ label: 'Sent to customer', on: '2026-10-15' })
    expect(lastStep(mfRow({ received_on: null, ktx_review_on: null, sent_customer_on: null }))).toBeNull()
    expect(articleIdentity({ part_id: 1, part_number: 'X', customer_part_number: '206.881.799', tier1_part_number: null,
      name: '206.881.799 A-bracket outer trim' })).toBe('206.881.799 A-bracket outer trim')
  })
})
