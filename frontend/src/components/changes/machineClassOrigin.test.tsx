/**
 * The costing line and the costing strip say where the machine class came
 * from: the tool and its source with the tonnage, or that no tool has one.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CostingSheetBar from './CostingSheetBar'
import { machineClassOriginDetail, machineClassOriginText } from './machineClassOrigin'
import { changesApi } from '../../api/changes'
import type { CostingContext, ToolTonnageSourceReport } from '../../types/change'
import { toast } from 'sonner'

vi.mock('sonner', () => ({ toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() } }))
vi.mock('../../api/changes', () => ({
  changesApi: { costingContext: vi.fn(), setMachineClass: vi.fn(), refreshToolTonnage: vi.fn() },
}))

describe('machineClassOriginText', () => {
  it('names the tool, the source and the tonnage', () => {
    expect(machineClassOriginText({ kind: 'tool', tool_number: '3454', source: 'machinedb',
      tonnage: 450, basis: 'assigned', machine: 'KM 450' }))
      .toBe('from tool 3454 (MachineDB, 450 t)')
    expect(machineClassOriginText({ kind: 'tool', tool_number: '668', source: 'twos', tonnage: 1300 }))
      .toBe('from tool 668 (TWOS, 1,300 t)')
    expect(machineClassOriginText({ kind: 'tool', tool_number: '0777', source: 'plm2', tonnage: 650 }))
      .toBe('from tool 0777 (PLM2 tool data, 650 t)')
  })

  it('says the press behind a MachineDB tonnage in the detail', () => {
    expect(machineClassOriginDetail({ kind: 'tool', tool_number: '3454', source: 'machinedb',
      tonnage: 450, basis: 'assigned', machine: 'KM 450' }))
      .toBe('from tool 3454 (MachineDB, 450 t); assigned press KM 450')
    expect(machineClassOriginDetail({ kind: 'tool', tool_number: '3454', source: 'machinedb',
      tonnage: 350, basis: 'qualified_min' }))
      .toBe('from tool 3454 (MachineDB, 350 t); smallest qualified press (none assigned)')
  })

  it('asks for a hand pick when no tool has a tonnage or no class covers it', () => {
    expect(machineClassOriginText({ kind: 'none', tools: ['3454'], without: ['3454'] }))
      .toBe('Tool 3454 has no tonnage: pick a machine class by hand')
    expect(machineClassOriginText({ kind: 'none', tools: ['3454', '3455'], without: ['3454', '3455'] }))
      .toBe('Tools 3454, 3455 have no tonnage: pick a machine class by hand')
    expect(machineClassOriginText({ kind: 'none', tools: [], without: [] }))
      .toBe('No tool on this change: pick a machine class by hand')
    expect(machineClassOriginText({ kind: 'tool', tool_number: '9', source: 'twos', tonnage: 5000,
      class_found: false }))
      .toBe('from tool 9 (TWOS, 5,000 t): no machine class covers 5,000 t, pick one by hand')
  })

  it('says nothing for a class picked on the line or a named press', () => {
    expect(machineClassOriginText({ kind: 'line' })).toBeNull()
    expect(machineClassOriginText({ kind: 'machine' })).toBeNull()
    expect(machineClassOriginText(null)).toBeNull()
    expect(machineClassOriginText({ kind: 'change' })).toBe('change class')
  })
})

const ctx: CostingContext = {
  plant_id: 1, plant_name: 'Toccoa', currency: 'USD', rate_source: 'cost_sheet',
  current_version: { id: 9, version: 2, valid_from: '2026-07-01' }, pricing_date: '2026-08-03',
  latest_version: 2, stale: null,
  machine_classes: [{ id: 3, name: '200-450 t', tonnage_min: 200, tonnage_max: 450 }],
  machine_class_id: null, default_machine_class_id: 3, effective_machine_class_id: 3,
  tonnage: 450, positions_by_department: {}, can_set_machine_class: true,
  tool_class_origin: { kind: 'tool', tool_number: '3454', source: 'machinedb', tonnage: 450,
    basis: 'assigned', machine: 'KM 450', class_found: true },
  tonnage_sources: { machinedb: true, twos: false },
}

const wrap = (ui: React.ReactElement) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    {ui}
  </QueryClientProvider>)

describe('CostingSheetBar tool tonnage', () => {
  afterEach(cleanup)

  it('shows the class with its tool and source, and refreshes the tonnage', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue(ctx as never)
    wrap(<CostingSheetBar changeId={7} editable />)
    const pick = await screen.findByTestId('costing-machine-class') as HTMLSelectElement
    expect(pick.options[0].textContent).toBe('Automatic: 200-450 t, from tool 3454 (MachineDB, 450 t)')
    vi.mocked(changesApi.refreshToolTonnage).mockResolvedValue(ctx as never)
    fireEvent.click(screen.getByTestId('costing-refresh-tonnage'))
    await waitFor(() => expect(changesApi.refreshToolTonnage).toHaveBeenCalledWith(7))
  })

  it('says the tool has no tonnage, and offers no refresh without a source', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue({
      ...ctx, default_machine_class_id: null, effective_machine_class_id: null, tonnage: null,
      tool_class_origin: { kind: 'none', tools: ['3454'], without: ['3454'] },
      tonnage_sources: { machinedb: false, twos: false } } as never)
    wrap(<CostingSheetBar changeId={7} editable />)
    expect((await screen.findByTestId('costing-class-origin')).textContent)
      .toBe('Tool 3454 has no tonnage: pick a machine class by hand')
    expect(screen.queryByTestId('costing-refresh-tonnage')).toBeNull()
  })

  it('offers the refresh to Sales / Finance who may not set the class', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue({
      ...ctx, can_set_machine_class: false, can_refresh_tonnage: true } as never)
    wrap(<CostingSheetBar changeId={7} editable={false} />)
    expect(await screen.findByTestId('costing-refresh-tonnage')).toBeTruthy()
    expect((screen.getByTestId('costing-machine-class') as HTMLSelectElement).disabled).toBe(true)
  })

  it('hides the refresh when the backend says the viewer may not refresh', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue({
      ...ctx, can_set_machine_class: true, can_refresh_tonnage: false } as never)
    wrap(<CostingSheetBar changeId={7} editable />)
    await screen.findByTestId('costing-machine-class')
    expect(screen.queryByTestId('costing-refresh-tonnage')).toBeNull()
  })

  it('says why a source failed (MachineDB route not deployed), not just unreachable', async () => {
    vi.mocked(changesApi.costingContext).mockResolvedValue(ctx as never)
    const ok: ToolTonnageSourceReport = { status: 'not_configured', matched: 0, updated: 0,
      no_tonnage: [], error: null }
    vi.mocked(changesApi.refreshToolTonnage).mockResolvedValue({ ...ctx, tool_tonnage_refresh: {
      tools: 1, without: [], twos: ok,
      machinedb: { ...ok, status: 'failed', error: 'MachineDB has no /v1/im-tools route yet' },
    } } as never)
    wrap(<CostingSheetBar changeId={7} editable />)
    fireEvent.click(await screen.findByTestId('costing-refresh-tonnage'))
    await waitFor(() => expect(toast.warning).toHaveBeenCalledWith(
      'MachineDB: MachineDB has no /v1/im-tools route yet. The stored tonnage stays'))
  })
})
