import { describe, it, expect, afterEach } from 'vitest'
import { render, screen, cleanup, within } from '@testing-library/react'
import PdbStatusBox from './PdbStatusBox'
import { pdbResponse, pdbTopic } from './lopFixtures'

describe('PdbStatusBox', () => {
  afterEach(cleanup)

  it('shows tools per status and one row per tool', () => {
    render(<PdbStatusBox pdb={pdbResponse({ topics: [pdbTopic(), pdbTopic({ ref_key: '502', escalated: false, age_days: 12 })] })} />)
    const box = screen.getByTestId('pdb-status-box')
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
