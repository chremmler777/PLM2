import { describe, it, expect, afterEach, beforeEach, vi } from 'vitest'
import { render, screen, cleanup, within, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PdbStatusBox from './PdbStatusBox'
import { lopApi } from '../../api/lop'
import { pdbResponse, pdbTopic } from './lop.fixtures'

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('PdbStatusBox', () => {
  beforeEach(() => window.localStorage.clear())
  afterEach(() => { cleanup(); vi.restoreAllMocks() })

  it('opens small: the numbers, no tool table, until "Show tools"', () => {
    render(<PdbStatusBox pdb={pdbResponse()} />)
    const box = screen.getByTestId('pdb-status-box')
    expect(within(box).getByTestId('pdb-step-tools').textContent).toContain('2')
    expect(within(box).queryByRole('table')).toBeNull()
    const toggle = within(box).getByTestId('pdb-box-toggle')
    expect(toggle.textContent).toContain('Show tools')
    fireEvent.click(toggle)
    expect(within(box).getAllByTestId('pdb-tool-row')).toHaveLength(2)
    expect(toggle.textContent).toContain('Hide tools')
    // the choice is kept for the next visit
    cleanup()
    render(<PdbStatusBox pdb={pdbResponse()} />)
    expect(screen.getAllByTestId('pdb-tool-row')).toHaveLength(2)
    fireEvent.click(screen.getByTestId('pdb-box-toggle'))
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('counts tools that are not A/A and have no sampling planned, in red', () => {
    const status = {
      tool_count: 4, funnel: {},
      tools: [
        { tool_number: '1', ps: 'B', ts: 'C', open_topics: 0, next_sampling: null },
        { tool_number: '2', ps: 'A', ts: 'B', open_topics: 0, next_sampling: null, sampling_requested_week: '2026-11-16' },
        { tool_number: '3', ps: 'C', ts: 'C', open_topics: 0,
          next_sampling: { id: 9, start_date: '2026-11-17', machine: 'KM 900', state: 'requested' } },
        { tool_number: '4', ps: 'A', ts: 'A', open_topics: 0, next_sampling: null },
      ],
    }
    render(<PdbStatusBox pdb={pdbResponse({ status, topics: [] })} />)
    const step = screen.getByTestId('pdb-step-unplanned')
    expect(step.textContent).toMatch(/2.*of 3 not A\/A without planned sampling/)
    expect(step.innerHTML).toContain('text-red-300')
    fireEvent.click(step)                       // the number opens the tools
    const rows = screen.getAllByTestId('pdb-tool-row')
    expect(within(rows[0]).getByTestId('pdb-next-sampling').textContent).toBe('none planned')
    expect(within(rows[0]).getByTestId('pdb-next-sampling').className).toContain('text-red-300')
    expect(rows[1].textContent).toContain('none planned · requested for week of Nov 16, no slot yet')
    expect(within(rows[2]).getByTestId('pdb-next-sampling').textContent).toContain('Nov 17 · KM 900')
    expect(rows[2].textContent).toContain('not confirmed')
    expect(within(rows[2]).getByTestId('pdb-next-sampling').className).not.toContain('text-red-300')
    expect(within(rows[3]).queryByTestId('pdb-next-sampling')).toBeNull()   // A/A needs none
  })

  it('the topics number opens what is open; a tool number opens that tool only', () => {
    const topics = [pdbTopic(), pdbTopic({ ref_key: '502', tool_number: '227702', escalated: false, escalation_level: 0,
      age_days: 12, text: 'Sink mark at rib', handover_impact: false })]
    const pdb = pdbResponse({ topics })
    pdb.status!.tools[1].open_topics = 1
    wrap(<PdbStatusBox pdb={pdb} />)
    fireEvent.click(screen.getByTestId('pdb-step-topics'))
    let dialog = screen.getByTestId('pdb-topics-dialog')
    let rows = within(dialog).getAllByTestId('pdb-topic-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('227701')
    expect(rows[0].textContent).toContain('Warpage on clip towers after T1')
    expect(rows[0].textContent).toContain('To do: adjust cooling circuit 4')
    expect(rows[0].textContent).toContain('41 d')
    expect(rows[0].textContent).toContain('escalated')
    expect(rows[0].textContent).toContain('blocks handover')
    expect(rows[0].textContent).toContain('not pinned')
    fireEvent.click(within(dialog).getByRole('button', { name: /close/i }))
    fireEvent.click(screen.getByTestId('pdb-box-toggle'))
    fireEvent.click(within(screen.getAllByTestId('pdb-tool-row')[1]).getByTestId('pdb-tool-topics'))
    dialog = screen.getByTestId('pdb-topics-dialog')
    rows = within(dialog).getAllByTestId('pdb-topic-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].textContent).toContain('Sink mark at rib')
    expect(dialog.textContent).toContain('tool 227702')
  })

  it('reads every open topic for the list when the box holds only the first ones', async () => {
    const more = [pdbTopic(), pdbTopic({ ref_key: '777', text: 'Hidden topic', escalated: false })]
    const spy = vi.spyOn(lopApi, 'pdb').mockResolvedValue(pdbResponse({ topics: more }))
    wrap(<PdbStatusBox projectId={34} pdb={pdbResponse({ hidden: 1 })} />)
    expect(screen.getByTestId('pdb-step-topics').textContent).toMatch(/^2/)
    fireEvent.click(screen.getByTestId('pdb-step-topics'))
    expect(await screen.findByText('Hidden topic')).toBeDefined()
    expect(spy).toHaveBeenCalledWith(34, true)
  })

  it('shows tools per status and one row per tool', () => {
    render(<PdbStatusBox pdb={pdbResponse({ topics: [pdbTopic(), pdbTopic({ ref_key: '502', escalated: false, age_days: 12 })] })} />)
    const box = screen.getByTestId('pdb-status-box')
    fireEvent.click(within(box).getByTestId('pdb-box-toggle'))
    expect(within(box).getByTestId('pdb-step-tools').textContent).toContain('2')
    expect(within(box).getByTestId('pdb-step-sampling').textContent).toMatch(/1.*Sampling/)
    expect(within(box).getByTestId('pdb-step-qualifying').textContent).toMatch(/1.*Qualifying/)
    expect(within(box).getByTestId('pdb-step-topics').textContent).toMatch(/2.*open topics.*1 escalated/)
    const rows = within(box).getAllByTestId('pdb-tool-row')
    expect(rows).toHaveLength(2)
    expect(rows[0].textContent).toContain('227701')
    expect(rows[0].textContent).toContain('Backpanel LH')
    expect(rows[0].textContent).toContain('1 escalated')
    expect(rows[0].textContent).toContain('41 d')
    expect(rows[1].textContent).toContain('227702')
  })

  it('says PDB cannot be reached instead of an empty table', () => {
    render(<PdbStatusBox pdb={pdbResponse({ available: false, reason: 'PDB answered 502', status: null, topics: [] })} />)
    const box = screen.getByTestId('pdb-status-box')
    expect(box.textContent).toContain('PDB cannot be reached')
    expect(box.textContent).toContain('PDB answered 502')
    expect(within(box).queryByRole('table')).toBeNull()
  })

  it('says "No tools in TWOS/PDB yet" when the project has none', () => {
    render(<PdbStatusBox pdb={pdbResponse({ status: { tool_count: 0, funnel: {}, tools: [] }, topics: [] })} />)
    const box = screen.getByTestId('pdb-status-box')
    expect(box.textContent).toContain('No tools in TWOS/PDB yet')
    expect(within(box).queryByRole('table')).toBeNull()
  })

  it('shows the topics count but says the status could not be read', () => {
    render(<PdbStatusBox pdb={pdbResponse({ status: null, status_reason: 'timeout', topics: [pdbTopic()] })} />)
    const box = screen.getByTestId('pdb-status-box')
    expect(box.textContent).toContain('The PDB status could not be read')
    expect(box.textContent).toContain('timeout')
    expect(within(box).getByTestId('pdb-step-topics').textContent).toMatch(/1.*open topic/)
  })
})
