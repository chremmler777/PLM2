import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import FieldNoteMarker from './FieldNoteMarker'
import type { FieldNoteSummary } from '../../api/fieldNotes'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const comment = { id: 1, body: 'Excel BOM says 4 cavities', author_id: 2, author_name: 'Engineer', created_at: '2026-09-24T10:12:00' }
const note: FieldNoteSummary = {
  id: 3, part_id: 7, field_key: 'tool.cavities', flag_status: 'open', flag_set_by: 2, flag_set_by_name: 'Engineer',
  flag_set_at: '2026-09-24T10:12:00', created_at: '2026-09-24T10:11:00', comment_count: 1, last_comment: comment,
}

function mount(props: Partial<React.ComponentProps<typeof FieldNoteMarker>> = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(qc, 'invalidateQueries')
  render(<QueryClientProvider client={qc}><FieldNoteMarker partId={7} fieldKey="tool.cavities" label="Cavities" {...props} /></QueryClientProvider>)
  return { invalidate }
}

describe('FieldNoteMarker', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockResolvedValue({ data: { ...note, comments: [comment] } })
    clientMocks.post.mockResolvedValue({ data: {} })
    clientMocks.put.mockResolvedValue({ data: {} })
  })
  afterEach(cleanup)

  it('shows the flag colour and the comment count', () => {
    mount({ note })
    expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('bg-yellow-400')
    expect(screen.getByTestId('note-count-tool.cavities').textContent).toBe('1')
  })

  it('shows an empty ring and no count without a note', () => {
    mount()
    expect(screen.getByTestId('note-dot-tool.cavities').className).toContain('border')
    expect(screen.queryByTestId('note-count-tool.cavities')).toBeNull()
  })

  it('opens the thread, adds a comment and refreshes every field note query', async () => {
    const { invalidate } = mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    expect(await screen.findByText('Excel BOM says 4 cavities')).toBeTruthy()
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities')
    expect(screen.getByText('Engineer, 2026-09-24 12:12')).toBeTruthy() // 10:12 UTC in Europe/Berlin
    expect(screen.getByText(/Open by Engineer, 2026-09-24/)).toBeTruthy()
    expect((screen.getByTestId('note-comment-input') as HTMLTextAreaElement).maxLength).toBe(4000)
    fireEvent.change(screen.getByTestId('note-comment-input'), { target: { value: '  PLM 2 is the sold state  ' } })
    fireEvent.click(screen.getByTestId('note-comment-add'))
    await waitFor(() => expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/comments', { body: 'PLM 2 is the sold state' }))
    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ['field-notes'] }))
  })

  it('sets and clears the flag', async () => {
    mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    await screen.findByText('Excel BOM says 4 cavities')
    expect(screen.getByTestId('flag-open').getAttribute('aria-pressed')).toBe('true')
    fireEvent.click(screen.getByTestId('flag-confirmed'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/flag', { status: 'confirmed' }))
    fireEvent.click(screen.getByTestId('flag-clear'))
    await waitFor(() => expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/flag', { status: null }))
  })

  it('can be opened from outside and closes on Escape', async () => {
    const onOpenChange = vi.fn()
    mount({ note, open: true, onOpenChange })
    expect(await screen.findByTestId('note-popover-tool.cavities')).toBeTruthy()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it('does not send an empty comment', async () => {
    mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    await screen.findByText('Excel BOM says 4 cavities')
    fireEvent.change(screen.getByTestId('note-comment-input'), { target: { value: '   ' } })
    expect((screen.getByTestId('note-comment-add') as HTMLButtonElement).disabled).toBe(true)
  })

  it('lists the field history from the audit log when opened in a project', async () => {
    const history = { entries: [
      { id: 12, at: '2026-09-24T14:56:37', actor: { id: 2, name: 'Engineer' }, part: { id: 7, part_number: '199401', customer_part_number: null, item_category: 'tool' },
        action: 'field_flag_set', action_group: 'flags', field_key: 'tool.cavities', old_value: null, new_value: 'open', description: 'Flag on tool.cavities: none to open' },
      { id: 11, at: '2026-09-23T08:00:00', actor: { id: 2, name: 'Engineer' }, part: { id: 7, part_number: '199401', customer_part_number: null, item_category: 'tool' },
        action: 'metadata_updated', action_group: 'values', field_key: 'tool.cavities', old_value: '4', new_value: '2', description: 'Cavities 4 -> 2' },
    ], has_more: false }
    clientMocks.get.mockImplementation((url: string) => Promise.resolve(
      { data: url === '/v1/projects/35/worksheet/audit' ? history : { ...note, comments: [comment] } }))
    mount({ note, projectId: 35 })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    const toggle = await screen.findByTestId('note-history-toggle')
    expect(toggle.getAttribute('aria-expanded')).toBe('false')
    expect(clientMocks.get).not.toHaveBeenCalledWith('/v1/projects/35/worksheet/audit', expect.anything())
    fireEvent.click(toggle)
    const list = await screen.findByTestId('note-history')
    await waitFor(() => expect(list.textContent).toContain('Flag set to Open'))
    expect(list.textContent).toContain('4 -> 2')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/35/worksheet/audit',
      { params: { part_id: 7, field_key: 'tool.cavities', limit: 50 } })
  })

  it('has no history section outside a project', async () => {
    mount({ note })
    fireEvent.click(screen.getByTestId('note-marker-tool.cavities'))
    await screen.findByTestId('note-comments')
    expect(screen.queryByTestId('note-history-toggle')).toBeNull()
  })
})
