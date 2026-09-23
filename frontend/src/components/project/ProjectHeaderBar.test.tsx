import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import ProjectHeaderBar from './ProjectHeaderBar'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), patch: vi.fn() }))
vi.mock('../../api/client', () => ({ default: clientMocks, API_BASE_URL: '' }))
vi.mock('../MilestoneStrip', () => ({ default: () => <div>milestones</div> }))

const project = { id: 2, name: 'Seat Trim', code: '1994', status: 'active', customer_naming: 'vw' as const }

function mount() {
  const props = { onStartChange: vi.fn(), onAddPart: vi.fn() }
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter><ProjectHeaderBar project={project} {...props} /></MemoryRouter>
    </QueryClientProvider>)
  return props
}

describe('ProjectHeaderBar', () => {
  beforeEach(() => {
    clientMocks.get.mockReset()
    clientMocks.get.mockImplementation((url: string) => {
      if (url === '/v1/sep/projects/2') return Promise.resolve({ data: { active: true, gates: [
        { id: 1, code: 'K0/RG1', status: 'in_progress', color: 'green', phase_en: 'Kick-off', progress: { done: 0, open: 5, not_applicable: 0, total: 5, pct: 0 } },
      ] } })
      if (url === '/v1/changes') return Promise.resolve({ data: [{ id: 1, status: 'scoping' }, { id: 2, status: 'closed' }] })
      if (url === '/v1/lessons/projects/2/references') return Promise.resolve({ data: [] })
      return Promise.resolve({ data: [] })
    })
  })
  afterEach(cleanup)

  it('shows code, name and customer on one row, without the old status chips', () => {
    mount()
    const header = screen.getByTestId('project-header')
    expect(header.textContent).toContain('1994')
    expect(header.textContent).toContain('Seat Trim')
    expect(header.textContent).toContain('VW group')
    expect(screen.queryByTestId('chip-sep')).toBeNull()
    expect(screen.queryByTestId('chip-changes')).toBeNull()
    expect(screen.queryByTestId('chip-lessons')).toBeNull()
  })

  it('keeps the project actions in the ⋯ menu', async () => {
    const props = mount()
    expect(screen.queryByText('+ Add Part')).toBeNull()
    fireEvent.click(screen.getByLabelText('Project actions'))
    expect(screen.getByText('Start change request')).toBeTruthy()
    expect(screen.getByLabelText('Customer file naming')).toBeTruthy()
    expect(screen.getByText('milestones')).toBeTruthy()
    fireEvent.click(screen.getByText('+ Add Part'))
    expect(props.onAddPart).toHaveBeenCalled()
    expect(screen.queryByText('+ Add Part')).toBeNull()
  })

  it('closes the menu on Escape', () => {
    mount()
    fireEvent.click(screen.getByLabelText('Project actions'))
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByText('+ Add Part')).toBeNull()
  })
})
