import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AddPartModal from './AddPartModal'
import type { Part } from './projectTypes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
const toastMocks = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }))
vi.mock('sonner', () => ({ toast: toastMocks }))

const base = { part_type: 'internal_mfg', active_revision_id: null, parent_part_id: null }
const parts: Part[] = [
  { ...base, id: 1, part_number: '3345', name: 'Tool Cover', item_category: 'tool' },
  { ...base, id: 2, part_number: '3450', name: 'Tool Console', item_category: 'tool' },
  { ...base, id: 3, part_number: '3345-40', name: 'Gauge Cover', item_category: 'gauge' },
  { ...base, id: 4, part_number: '3345-10', name: 'EOAT Cover', item_category: 'assembly_equipment' },
  { ...base, id: 5, part_number: '1748-0012', name: 'Cover LH', item_category: 'article' },
]

const ALL = { can_edit_tools: true, can_edit_gauges: true, can_edit_assembly_equipment: true }

/** What the server answers for the next free number: undefined = no usable answer (the fallback stays), null = family full. */
let serverNumber: string | null | undefined = undefined
const onCreated = vi.fn()

function mount(rights: Record<string, boolean> = ALL) {
  clientMocks.get.mockImplementation((url: string) =>
    Promise.resolve({ data: url === '/v1/auth/me' ? rights
      : url === '/v1/parts/next-equipment-number' ? (serverNumber === undefined ? {} : { number: serverNumber, base: '1748' }) : [] }))
  const onClose = vi.fn()
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <AddPartModal projectId={7} projectCode="1748" parts={parts} isOpen onClose={onClose} onCreated={onCreated} />
    </QueryClientProvider>,
  )
  return onClose
}

const kind = () => screen.getByLabelText('Item Category *') as HTMLSelectElement
const number = () => screen.getByLabelText('Part Number *') as HTMLInputElement
const pick = (label: string, value: string) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const pickTool = (label: string) => fireEvent.click(within(screen.getByTestId('serves-tool-list')).getByText(label))
const submit = () => fireEvent.click(screen.getByRole('button', { name: /Add Part|Create and open BOM/ }))
const kinds = () => Array.from(kind().options).map((o) => o.value)

describe('AddPartModal', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.post.mockReset()
    Object.values(toastMocks).forEach((m) => m.mockReset())
    serverNumber = undefined
    onCreated.mockReset()
  })
  afterEach(cleanup)

  it('offers only the kinds the viewer may create', async () => {
    mount({ can_edit_tools: false, can_edit_gauges: true, can_edit_assembly_equipment: false })
    await waitFor(() => expect(kinds()).toEqual(['article', 'gauge']))
    cleanup()
    mount({ can_edit_tools: false, can_edit_gauges: false, can_edit_assembly_equipment: true })
    await waitFor(() => expect(kinds()).toEqual(['article', 'assembly_equipment', 'eoat']))
    cleanup()
    mount({ can_edit_tools: false, can_edit_gauges: false, can_edit_assembly_equipment: false })
    await waitFor(() => expect(kinds()).toEqual(['article']))
  })

  it('an article has no "Serves tool" pick list', () => {
    mount()
    expect(screen.queryByLabelText('Serves tool')).toBeNull()
  })

  it('suggests the next free gauge number of the picked tool and keeps it editable', () => {
    mount()
    pick('Item Category *', 'gauge')
    expect(number().value).toBe('1748-70') // no tool yet: on the project code
    pickTool('3345 - Tool Cover')
    expect(number().value).toBe('3345-41') // 3345-40 exists
    pickTool('3450 - Tool Console')
    expect(number().value).toBe('3450-40')
    fireEvent.change(number(), { target: { value: '3450-45' } })
    expect(number().value).toBe('3450-45')
  })

  it('suggests EOAT and station numbers, and the station type switches the family', () => {
    mount()
    pick('Item Category *', 'eoat')
    pickTool('3345 - Tool Cover')
    expect(number().value).toBe('3345-11') // 3345-10 exists
    pick('Item Category *', 'assembly_equipment')
    expect(number().value).toBe('3345-20')
    pick('Station type', '3')
    expect(number().value).toBe('3345-30')
  })

  it('creates an EOAT as assembly equipment and links it to the tool it serves', async () => {
    clientMocks.post.mockImplementation((url: string) =>
      Promise.resolve({ data: url === '/v1/parts' ? { id: 99 } : {} }))
    const onClose = mount()
    pick('Item Category *', 'eoat')
    pickTool('3345 - Tool Cover')
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'EOAT 2' } })
    submit()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(clientMocks.post).toHaveBeenNthCalledWith(1, '/v1/parts',
      expect.objectContaining({ part_number: '3345-11', item_category: 'assembly_equipment', project_id: 7 }))
    expect(clientMocks.post).toHaveBeenNthCalledWith(2, '/v1/parts/99/relations', { to_part_id: 1, relation_type: 'serves' })
  })

  it('without a tool the number is typed freely and no link is made', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 99 } })
    const onClose = mount()
    pick('Item Category *', 'gauge')
    fireEvent.change(number(), { target: { value: 'G-7' } })
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Free gauge' } })
    submit()
    await waitFor(() => expect(onClose).toHaveBeenCalled())
    expect(clientMocks.post).toHaveBeenCalledTimes(1)
    expect(clientMocks.post.mock.calls[0][1]).toMatchObject({ part_number: 'G-7', item_category: 'gauge' })
  })

  it("shows the server's refusal", async () => {
    clientMocks.post.mockRejectedValue({ response: { status: 403, data: { detail: 'Only APQP, the Project Manager or an admin can change gauges; you can view them.' } } })
    const onClose = mount()
    pick('Item Category *', 'gauge')
    fireEvent.change(number(), { target: { value: 'G-7' } })
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'x' } })
    submit()
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalledWith('Only APQP, the Project Manager or an admin can change gauges; you can view them.'))
    expect(onClose).not.toHaveBeenCalled()
  })

  it('a tool is optional: none is picked by default and the wording fits the kind', () => {
    mount()
    pick('Item Category *', 'gauge')
    const options = () => within(screen.getByTestId('serves-tool-list')).getAllByRole('option')
    expect(options()[0].textContent).toBe('No tool (assembly gauge)')
    expect(options()[0].getAttribute('aria-selected')).toBe('true')
    expect(screen.getByTestId('serves-tool-help').textContent).toContain('No tool is needed. A number on the project code is filled in below')
    expect(number().value).toBe('1748-70')
    pick('Item Category *', 'eoat')
    expect(options()[0].textContent).toBe('No tool (assembly operation)')
    pick('Item Category *', 'assembly_equipment')
    expect(options()[0].textContent).toBe('No tool (assembly operation)')
    expect(screen.queryByLabelText('Station type')).toBeNull() // only numbers by tool have a station family
    expect(number().value).toBe('1748-60')
    pick('Item Category *', 'article') // a number the dialog filled in does not stick to an article
    expect(number().value).toBe('')
  })

  it('asks the server for the number without a tool by project, and says when all ten are used', async () => {
    serverNumber = '1748-63'
    mount()
    pick('Item Category *', 'eoat')
    await waitFor(() => expect(number().value).toBe('1748-63'))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/next-equipment-number', { params: { project_id: 7, family: 6 } })
    cleanup()
    serverNumber = null
    mount()
    pick('Item Category *', 'gauge')
    await waitFor(() => expect(screen.getByTestId('serves-tool-help').textContent)
      .toBe('All numbers 1748-70 to -79 are used, type a number.'))
    expect(number().value).toBe('')
  })

  it('takes the number from the server, which sees other projects, over the local guess', async () => {
    serverNumber = '3345-43'
    mount()
    pick('Item Category *', 'gauge')
    pickTool('3345 - Tool Cover')
    expect(number().value).toBe('3345-41') // the stand-in from this project's list
    await waitFor(() => expect(number().value).toBe('3345-43'))
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/next-equipment-number', { params: { tool_id: 1, family: 4 } })
  })

  it('never replaces a number the user typed with the server answer', async () => {
    serverNumber = '3345-43'
    mount()
    pick('Item Category *', 'gauge')
    pickTool('3345 - Tool Cover')
    fireEvent.change(number(), { target: { value: 'MY-1' } })
    await waitFor(() => expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/next-equipment-number', expect.anything()))
    await new Promise((r) => setTimeout(r, 20))
    expect(number().value).toBe('MY-1')
  })

  it('creates an assembly operation without a tool and hands the new item to the page', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 42 } })
    const onClose = mount()
    pick('Item Category *', 'assembly_equipment')
    expect(number().value).toBe('1748-60')
    fireEvent.change(screen.getByLabelText('Name *'), { target: { value: 'Clip station' } })
    submit()
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(42, true))
    expect(onClose).toHaveBeenCalled()
    expect(clientMocks.post).toHaveBeenCalledTimes(1) // no serves link
    expect(clientMocks.post.mock.calls[0][1]).toMatchObject({ part_number: '1748-60', item_category: 'assembly_equipment' })
  })

  it('the tool list narrows as you type, and equipment shows no article fields', () => {
    mount()
    pick('Item Category *', 'gauge')
    const options = () => within(screen.getByTestId('serves-tool-list')).getAllByRole('option').map((o) => o.textContent)
    expect(options()).toEqual(['No tool (assembly gauge)', '3345 - Tool Cover', '3450 - Tool Console'])
    fireEvent.change(screen.getByLabelText('Serves tool'), { target: { value: 'console' } })
    expect(options()).toEqual(['No tool (assembly gauge)', '3450 - Tool Console']) // the picked one stays visible
    expect(screen.queryByTestId('add-part-customer-number')).toBeNull()
    expect(screen.queryByText('Type *')).toBeNull()
    expect(screen.getByRole('button', { name: 'Create and open BOM' })).toBeTruthy()
    pick('Item Category *', 'article')
    expect(screen.getByTestId('add-part-customer-number')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Add Part' })).toBeTruthy()
  })
})
