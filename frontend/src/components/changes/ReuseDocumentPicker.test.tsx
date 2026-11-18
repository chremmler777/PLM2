import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import ReuseDocumentPicker from './ReuseDocumentPicker'

const reusable = vi.fn()
const reuse = vi.fn()
vi.mock('../../api/changes', () => ({
  changesApi: {
    reusableAttachments: (...a: unknown[]) => reusable(...a),
    reuseAttachment: (...a: unknown[]) => reuse(...a),
  },
}))

const row = (id: number, filename: string, source: string, department_name: string | null = null) => ({
  id, filename, kind: 'general', phase: 'baseline', size_bytes: 1, source,
  department_name, uploaded_by_name: 'Cody', created_at: null,
})

describe('ReuseDocumentPicker', () => {
  beforeEach(() => { cleanup(); reusable.mockReset(); reuse.mockReset() })

  it('lists the documents on the change and files the picked one into the slot', async () => {
    reusable.mockResolvedValue([row(7, 'request.msg', 'initial'), row(9, 'deck.pptx', 'change_ppt', 'Tool Engineer')])
    reuse.mockResolvedValue({ id: 20 })
    const onPicked = vi.fn()
    render(<ReuseDocumentPicker changeId={3} assessmentId={5} caseRef="cA" onPicked={onPicked} />)
    expect(screen.queryByTestId('reuse-row-7')).toBeNull()
    fireEvent.click(screen.getByTestId('reuse-toggle'))
    await screen.findByTestId('reuse-row-7')
    expect(reusable).toHaveBeenCalledWith(3, 5, 'cA')
    expect(screen.getByText('Initial request')).toBeTruthy()
    expect(screen.getByText('Change presentation Tool Engineer')).toBeTruthy()
    fireEvent.click(screen.getByTestId('reuse-pick-9'))
    await waitFor(() => expect(onPicked).toHaveBeenCalled())
    expect(reuse).toHaveBeenCalledWith(3, 9, 5, 'cA')
  })

  it('says so when nothing is on the change yet', async () => {
    reusable.mockResolvedValue([])
    render(<ReuseDocumentPicker changeId={3} assessmentId={5} onPicked={() => {}} />)
    fireEvent.click(screen.getByTestId('reuse-toggle'))
    expect(await screen.findByTestId('reuse-empty')).toBeTruthy()
  })
})
