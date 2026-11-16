import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import EquipmentTab, { equipmentKindLabel } from './EquipmentTab'
import type { Part } from './projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast: toastMocks }))

const base = { part_type: 'internal_mfg', active_revision_id: null, parent_part_id: null }
const station: Part = { ...base, id: 10, part_number: '3345-20', name: 'Degate station', item_category: 'assembly_equipment', description: 'Cell 4' }
const gauge: Part = { ...base, id: 11, part_number: '3345-40', name: 'Checking fixture', item_category: 'gauge', calibration_interval_months: 12 }
const tool: Part = { ...base, id: 1, part_number: '3345', name: 'Tool Cover', item_category: 'tool' }
const tool2: Part = { ...base, id: 2, part_number: '3346', name: 'Tool Cover RH', item_category: 'tool' }
const art1: Part = { ...base, id: 20, part_number: '50-2277-001-0', name: 'Cover LH', item_category: 'article', customer_part_number: '206.887.233' }
const art2: Part = { ...base, id: 21, part_number: '50-2277-002-0', name: 'Cover RH', item_category: 'article' }
const parts = [station, gauge, tool, tool2, art1, art2]

const rel = (id: number, type: string, other: Part, quantity: number | null = null) => ({
  id, relation_type: type, direction: 'outgoing', other_part_id: other.id, other_part_number: other.part_number,
  other_part_name: other.name, other_item_category: other.item_category,
  other_customer_part_number: other.customer_part_number ?? null, quantity,
})
const ALL = { can_edit_tools: true, can_edit_gauges: true, can_edit_assembly_equipment: true }

interface Setup { relations?: unknown[]; history?: unknown[]; rights?: Record<string, boolean> }
function mount(part: Part, { relations = [], history = [], rights = ALL }: Setup = {}, draggingPartId: number | null = null) {
  clientMocks.get.mockImplementation((url: string) => Promise.resolve({
    data: url === '/v1/auth/me' ? rights : url.endsWith('/relations') ? relations : url.endsWith('/history') ? history : [],
  }))
  const onOpenPart = vi.fn()
  const ui = (dragging: number | null) => (
    <EquipmentTab projectId={7} part={part} parts={parts} draggingPartId={dragging} onOpenPart={onOpenPart} />
  )
  const view = render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui(draggingPartId)}</QueryClientProvider>,
  )
  return { onOpenPart, view }
}

const card = () => screen.getByTestId('equipment-card')
const dropOnCard = () => {
  const dataTransfer = { effectAllowed: '' }
  fireEvent.dragOver(card(), { dataTransfer })
  const highlighted = card().className.includes('border-green-500')
  fireEvent.drop(card(), { dataTransfer })
  return highlighted
}

describe('EquipmentTab', () => {
  beforeEach(() => {
    Object.values(clientMocks).forEach((m) => m.mockReset())
    Object.values(toastMocks).forEach((m) => m.mockReset())
    for (const m of [clientMocks.post, clientMocks.put, clientMocks.patch, clientMocks.delete]) m.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('names the kind from category and number', () => {
    expect(equipmentKindLabel(gauge)).toBe('Gauge')
    expect(equipmentKindLabel(station)).toBe('Assembly equipment')
    expect(equipmentKindLabel({ item_category: 'assembly_equipment', part_number: '3345-10' })).toBe('EOAT')
    expect(equipmentKindLabel({ item_category: 'assembly_equipment', part_number: 'ASSY-OP-10' })).toBe('Assembly equipment')
  })

  it('shows the header, and without a tool says so in the words of the kind', async () => {
    mount(station)
    expect(within(card()).getByText('Assembly equipment')).toBeTruthy()
    expect(within(card()).getByText('3345-20')).toBeTruthy()
    expect(screen.getByText('No tool: assembly operation')).toBeTruthy()
    expect(screen.getByText('No article linked yet')).toBeTruthy()
    cleanup()
    mount(gauge)
    expect(screen.getByText('No tool: assembly gauge')).toBeTruthy()
  })

  it('lists served tools and articles, customer number first, with the amount', async () => {
    mount(station, { relations: [rel(1, 'serves', tool), rel(2, 'serves', tool2), rel(3, 'assembles', art1, 2), rel(4, 'assembles', art2, 1)] })
    const tools = await screen.findByTestId('equipment-tools')
    await within(tools).findByText('3345')
    expect(within(tools).getByText('3346')).toBeTruthy()
    const rows = within(screen.getByTestId('equipment-articles')).getAllByRole('listitem')
    expect(rows[0].textContent).toContain('206.887.233 50-2277-001-0 Cover LH')
    expect((screen.getByLabelText('Amount of 50-2277-001-0') as HTMLInputElement).value).toBe('2')
    expect((screen.getByLabelText('Amount of 50-2277-002-0') as HTMLInputElement).value).toBe('1')
  })

  it('saves a changed amount on blur and on Enter, and refuses 0', async () => {
    mount(station, { relations: [rel(3, 'assembles', art1, 2)] })
    const input = await screen.findByLabelText('Amount of 50-2277-001-0') as HTMLInputElement
    fireEvent.change(input, { target: { value: '4' } })
    fireEvent.blur(input)
    await waitFor(() => expect(clientMocks.patch).toHaveBeenCalledWith('/v1/parts/relations/3', { quantity: 4 }))
    clientMocks.patch.mockClear()
    fireEvent.change(input, { target: { value: '0' } })
    fireEvent.blur(input)
    expect(toastMocks.error).toHaveBeenCalledWith('The amount must be greater than 0.')
    expect(clientMocks.patch).not.toHaveBeenCalled()
    expect(input.value).toBe('2')
  })

  it('a gauge lists checked articles without an amount', async () => {
    mount(gauge, { relations: [rel(5, 'checks', art1)] })
    await screen.findByLabelText('Remove article 50-2277-001-0')
    expect(screen.queryByLabelText('Amount of 50-2277-001-0')).toBeNull()
  })

  it('removes an article and a served tool', async () => {
    mount(station, { relations: [rel(1, 'serves', tool), rel(3, 'assembles', art1, 2)] })
    fireEvent.click(await screen.findByLabelText('Remove article 50-2277-001-0'))
    await waitFor(() => expect(clientMocks.delete).toHaveBeenCalledWith('/v1/parts/relations/3'))
    fireEvent.click(screen.getByLabelText('Remove tool 3345'))
    await waitFor(() => expect(clientMocks.delete).toHaveBeenCalledWith('/v1/parts/relations/1'))
  })

  it('an article dropped on the card is linked: assembles for equipment, checks for a gauge', async () => {
    mount(station, {}, art1.id)
    expect(dropOnCard()).toBe(true)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/10/relations', { to_part_id: 20, relation_type: 'assembles' }))
    expect(toastMocks.success).toHaveBeenCalledWith('Linked: 3345-20 assembles 50-2277-001-0')
    cleanup()
    clientMocks.post.mockClear()
    mount(gauge, {}, art1.id)
    expect(dropOnCard()).toBe(true)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/11/relations', { to_part_id: 20, relation_type: 'checks' }))
  })

  it('a tool dropped on the card becomes a served tool, also a second one', async () => {
    mount(station, { relations: [rel(1, 'serves', tool)] }, tool2.id)
    await within(screen.getByTestId('equipment-tools')).findByText('3345')
    expect(dropOnCard()).toBe(true)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/10/relations', { to_part_id: 2, relation_type: 'serves' }))
    expect(toastMocks.success).toHaveBeenCalledWith('Linked: 3345-20 serves tool 3346')
  })

  it('does not take what is already linked, another gauge, or anything without the right', async () => {
    mount(station, { relations: [rel(1, 'serves', tool)] }, tool.id)
    await within(screen.getByTestId('equipment-tools')).findByText('3345')
    expect(dropOnCard()).toBe(false)
    cleanup()
    mount(station, {}, gauge.id)
    expect(dropOnCard()).toBe(false)
    cleanup()
    mount(station, { rights: { ...ALL, can_edit_assembly_equipment: false } }, art1.id)
    await waitFor(() => expect(screen.queryByText('Change')).toBeNull())
    expect(dropOnCard()).toBe(false)
    expect(clientMocks.post).not.toHaveBeenCalled()
  })

  it('the change dialog needs Correction or Change, and a note for a change', async () => {
    mount(gauge)
    fireEvent.click(screen.getByText('Change'))
    const dialog = screen.getByRole('dialog', { name: 'Change 3345-40' })
    const save = within(dialog).getByText('Save') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(within(dialog).getByLabelText('Name *'), { target: { value: 'CMM fixture' } })
    expect(save.disabled).toBe(true)
    expect(within(dialog).getByText('Say whether this is a correction or a change.')).toBeTruthy()
    fireEvent.click(within(dialog).getByLabelText(/^Change/))
    expect(save.disabled).toBe(true)
    expect(within(dialog).getByText('A change needs a short note.')).toBeTruthy()
    fireEvent.change(within(dialog).getByLabelText('Note *'), { target: { value: 'rebuilt' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/11', {
      change_kind: 'change', change_note: 'rebuilt', name: 'CMM fixture' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('a correction needs no note and sends only the changed fields', async () => {
    mount(gauge)
    fireEvent.click(screen.getByText('Change'))
    fireEvent.change(screen.getByLabelText('Number *'), { target: { value: '3345-41' } })
    fireEvent.change(screen.getByLabelText('Calibration Interval (months)'), { target: { value: '6' } })
    fireEvent.click(screen.getByLabelText(/^Correction/))
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/11', {
      change_kind: 'correction', change_note: null, part_number: '3345-41', calibration_interval_months: 6 }))
  })

  it('marking obsolete asks for the note', async () => {
    mount(station)
    fireEvent.click(screen.getByText('Mark obsolete'))
    const dialog = screen.getByRole('dialog', { name: 'Mark 3345-20 obsolete' })
    const save = within(dialog).getByRole('button', { name: 'Mark obsolete' }) as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(within(dialog).getByLabelText('Why is it obsolete? *'), { target: { value: 'replaced by 3345-21' } })
    fireEvent.click(save)
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/10/obsolete', { note: 'replaced by 3345-21' }))
  })

  it('an obsolete item shows the marker, only Reactivate, and takes no drop', async () => {
    mount({ ...station, obsolete_at: '2026-11-01T10:00:00' }, { relations: [rel(3, 'assembles', art1, 2)] }, art2.id)
    expect(screen.getByTestId('equipment-obsolete').textContent).toContain('obsolete since')
    expect(screen.queryByText('Change')).toBeNull()
    expect(screen.queryByText('Mark obsolete')).toBeNull()
    const amount = await screen.findByLabelText('Amount of 50-2277-001-0') as HTMLInputElement
    expect(amount.disabled).toBe(true)
    expect(screen.queryByLabelText('Remove article 50-2277-001-0')).toBeNull()
    expect(dropOnCard()).toBe(false)
    fireEvent.click(screen.getByText('Reactivate'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/10/reactivate', {}))
  })

  it('shows the history newest first with the kind as a tag', async () => {
    mount(station, { history: [
      { id: 3, at: '2026-11-16T10:00:00', by_name: 'Russ', kind: 'obsolete', description: 'Marked obsolete: replaced', note: 'replaced' },
      { id: 2, at: '2026-11-15T10:00:00', by_name: 'Cory', kind: 'change', description: 'Article 50-2277-001-0 added, quantity 2', note: null },
      { id: 1, at: '2026-11-14T10:00:00', by_name: 'Cory', kind: 'correction', description: 'Name: Degate -> Degate station', note: 'typo' },
    ] })
    const rows = within(await screen.findByTestId('equipment-history')).getAllByRole('listitem')
    expect(rows.map((r) => within(r).getByText(/Obsolete|Change|Correction/).textContent)).toEqual(['Obsolete', 'Change', 'Correction'])
    expect(rows[1].textContent).toContain('Cory')
    expect(rows[1].textContent).toContain('Article 50-2277-001-0 added, quantity 2')
    expect(rows[2].textContent).toContain('typo')
  })
})
