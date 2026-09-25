import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, fireEvent, cleanup, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import LeadPicker from './LeadPicker'
import { DescriptionEditor } from './DescriptionEditor'

const setLead = vi.fn().mockResolvedValue({})
const leadCandidates = vi.fn()
vi.mock('../../api/changes', () => ({
  changesApi: {
    setLead: (...a: unknown[]) => setLead(...a),
    leadCandidates: (...a: unknown[]) => leadCandidates(...a),
    update: vi.fn().mockResolvedValue({}),
  },
}))
vi.mock('../../api/client', () => ({ default: { get: vi.fn().mockRejectedValue(new Error('403')) } }))

const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>
)

describe('LeadPicker (spec §16 P1 5)', () => {
  afterEach(cleanup)

  it('says "No lead assigned" and lets the PM pick one, the project PM first', async () => {
    leadCandidates.mockResolvedValue([
      { id: 3, name: 'Petra PM', department: 'Project Manager', is_default: true },
      { id: 4, name: 'Lars Lead' },
    ])
    render(wrap(<LeadPicker change={{ id: 7, lead_id: null, lead_name: null }} canEdit />))
    expect(screen.getByTestId('lead-name').textContent).toBe('No lead assigned')
    fireEvent.click(screen.getByTestId('lead-edit'))
    const select = await screen.findByTestId('lead-select') as HTMLSelectElement
    await waitFor(() => expect(select.options.length).toBe(3))
    expect(select.options[1].text).toBe('Petra PM (Project Manager)')
    fireEvent.change(select, { target: { value: '3' } })
    await waitFor(() => expect(setLead).toHaveBeenCalledWith(7, 3))
  })

  it('falls back to the current lead and the viewer when there is no candidate list', async () => {
    leadCandidates.mockRejectedValue(new Error('404'))
    render(wrap(<LeadPicker change={{ id: 7, lead_id: 5, lead_name: 'Eva' }} canEdit
      viewer={{ id: 9, name: 'Me' }} />))
    fireEvent.click(screen.getByTestId('lead-edit'))
    const select = await screen.findByTestId('lead-select') as HTMLSelectElement
    await waitFor(() => expect([...select.options].map((o) => o.text)).toEqual(['Pick a lead', 'Eva', 'Me (Me)']))
  })

  it('is read only for everyone else', () => {
    render(wrap(<LeadPicker change={{ id: 7, lead_id: 5, lead_name: 'Eva' }} canEdit={false} />))
    expect(screen.getByTestId('lead-name').textContent).toBe('Eva')
    expect(screen.queryByTestId('lead-edit')).toBeNull()
  })
})

describe('DescriptionEditor state (spec §16 P3)', () => {
  afterEach(cleanup)
  const c = { id: 7, status: 'captured', description: 'Wall' } as never

  it('says when an edit is unsaved and can discard it', () => {
    render(wrap(<DescriptionEditor change={c} />))
    expect(screen.getByTestId('description-state').textContent).toBe('Saved')
    fireEvent.change(screen.getByTestId('description-input'), { target: { value: 'Wall 1.8' } })
    expect(screen.getByTestId('description-state').textContent).toBe('Unsaved changes')
    fireEvent.click(screen.getByTestId('description-discard'))
    expect((screen.getByTestId('description-input') as HTMLTextAreaElement).value).toBe('Wall')
  })

  it('explains why it is read only after kickoff', () => {
    render(wrap(<DescriptionEditor change={{ id: 7, status: 'scoping', description: '' } as never} />))
    expect(screen.getByText('No description')).toBeDefined()
    expect(screen.getByTestId('description-state').textContent).toContain('Fixed at the hand-over to scoping')
  })
})
