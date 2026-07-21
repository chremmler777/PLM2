import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import ImplementationPanel from './ImplementationPanel'
import { changesApi } from '../../api/changes'

vi.mock('../../api/changes', () => ({
  changesApi: {
    getImplementation: vi.fn(),
    signNoGeometryChange: vi.fn(),
  },
}))
vi.mock('../CADUploader', () => ({
  default: () => <div data-testid="cad-uploader" />,
}))
vi.mock('../workflows/RevisionWorkflowSection', () => ({
  default: () => <div data-testid="wf-section" />,
}))

const progress = {
  ready_to_go: false,
  items: [
    {
      item_id: 1, part_id: 10, part_number: 'P-100', part_name: 'Housing',
      item_category: 'article', is_lead: true,
      revision_id: 55, revision_name: 'ECR1.1',
      instance_id: 9, instance_status: 'active',
      current_stage_order: 1, total_stages: 4,
      has_cad_file: false, no_geometry_change: false, ready: false,
    },
  ],
}

function wrap(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

describe('ImplementationPanel', () => {
  beforeEach(() => {
    vi.mocked(changesApi.getImplementation).mockResolvedValue(progress)
    vi.mocked(changesApi.signNoGeometryChange).mockResolvedValue({})
  })
  afterEach(cleanup)

  it('shows per-revision status and missing evidence with resolving actions', async () => {
    wrap(<ImplementationPanel changeId={7} />)
    expect(await screen.findByText(/ECR1\.1/)).toBeDefined()
    expect(screen.getByText(/3D evidence missing/)).toBeDefined()
    expect(screen.getByText(/Not ready to go/)).toBeDefined()
    expect(screen.getByRole('button', { name: /Sign no geometry change/ })).toBeDefined()
  })

  it('signs no-geometry-change with a reason', async () => {
    wrap(<ImplementationPanel changeId={7} />)
    await screen.findByText(/ECR1\.1/)
    fireEvent.click(screen.getByRole('button', { name: /Sign no geometry change/ }))
    const textarea = await screen.findByRole('textbox')
    fireEvent.change(textarea, { target: { value: 'label only' } })
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))
    await waitFor(() =>
      expect(changesApi.signNoGeometryChange).toHaveBeenCalledWith(10, 55, 'label only'))
  })

  it('shows the ready banner when all revisions are ready', async () => {
    vi.mocked(changesApi.getImplementation).mockResolvedValue({
      ready_to_go: true,
      items: [{ ...progress.items[0], instance_status: 'completed',
                has_cad_file: true, ready: true }],
    })
    wrap(<ImplementationPanel changeId={7} />)
    expect(await screen.findByText(/Ready to go/)).toBeDefined()
  })
})
