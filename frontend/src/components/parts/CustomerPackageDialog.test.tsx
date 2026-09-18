import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import CustomerPackageDialog from './CustomerPackageDialog'

const post = vi.fn()
vi.mock('../../api/client', () => ({ default: { post: (...a: unknown[]) => post(...a) } }))

const previewRows = [
  { filename: 'top.stp', part_id: 1, part_number: '1994-100', customer_part_number: '3CR.807.425', customer_index: 'B',
    current_revision: 'E1', current_index: 'A', action: 'new_major', suggested_name: 'E2', major: null, error: null },
  { filename: 'clamp.stp', part_id: 2, part_number: '1994-120', customer_part_number: null, customer_index: 'A',
    current_revision: 'E1', current_index: 'A', action: 'unchanged', suggested_name: null, major: null, error: null },
  { filename: 'x.stp', part_id: null, part_number: null, customer_part_number: null, customer_index: 'B',
    current_revision: null, current_index: null, action: 'unmatched', suggested_name: null, major: null, error: null },
]

describe('CustomerPackageDialog', () => {
  beforeEach(() => post.mockReset())
  afterEach(cleanup)

  it('previews, lets a row change, and confirms with the edited rows', async () => {
    post.mockResolvedValueOnce({ data: { rows: previewRows } })
    post.mockResolvedValueOnce({ data: { created: [{ revision_name: 'E2' }], kept: [{}], skipped: [] } })
    const onDone = vi.fn()
    render(<CustomerPackageDialog open assemblyId={1} projectParts={[{ id: 1, part_number: '1994-100', name: 'Top' }, { id: 3, part_number: '1994-130', name: 'Bracket' }]}
      onClose={() => {}} onDone={onDone} />)
    const input = screen.getByTestId('package-files') as HTMLInputElement
    const file = new File(['x'], 'top.stp')
    fireEvent.change(input, { target: { files: [file] } })
    fireEvent.click(screen.getByText('Check package'))
    await waitFor(() => expect(screen.getByTestId('row-top.stp')).toBeTruthy())
    expect(screen.getByTestId('row-top.stp').textContent).toContain('E1 · A')
    expect(screen.getByTestId('row-top.stp').textContent).toContain('E2')
    expect(screen.getByTestId('row-clamp.stp').textContent).toContain('unchanged')

    fireEvent.change(screen.getByTestId('part-x.stp'), { target: { value: '3' } })
    fireEvent.change(screen.getByTestId('action-x.stp'), { target: { value: 'new_major' } })
    fireEvent.click(screen.getByText('Store package'))
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    const form = post.mock.calls[1][1] as FormData
    const rows = JSON.parse(form.get('rows') as string)
    expect(rows.find((r: { filename: string }) => r.filename === 'x.stp')).toMatchObject({ part_id: 3, action: 'new_major' })
  })

  it('shows row errors from a 409 and keeps the table', async () => {
    post.mockResolvedValueOnce({ data: { rows: previewRows } })
    post.mockRejectedValueOnce({ response: { status: 409, data: { detail: 'x', rows: [{ ...previewRows[0], action: 'error', error: 'Revision number must be above E1' }] } } })
    render(<CustomerPackageDialog open assemblyId={1} projectParts={[]} onClose={() => {}} onDone={() => {}} />)
    fireEvent.change(screen.getByTestId('package-files'), { target: { files: [new File(['x'], 'top.stp')] } })
    fireEvent.click(screen.getByText('Check package'))
    await waitFor(() => screen.getByTestId('row-top.stp'))
    fireEvent.click(screen.getByText('Store package'))
    await waitFor(() => expect(screen.getByTestId('row-top.stp').textContent).toContain('above E1'))
  })
})
