import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AnswerForm from './AnswerForm'
import { changesApi } from '../../../api/changes'
import type { ChangeConcern } from '../../../types/change'

vi.mock('../../../api/changes', () => ({ changesApi: { answerConcernForm: vi.fn().mockResolvedValue({}) } }))
vi.mock('../AttachmentDropzone', () => ({ default: () => <div data-testid="dropzone" /> }))

afterEach(() => cleanup())

const q = { id: 11, change_id: 7, kind: 'needs_info', note: 'Both variants?', raised_by: 5,
  raised_at: '2026-10-28T10:00:00Z', is_open: true, flag_type: 'question',
  answer_from: 'customer' } as unknown as ChangeConcern
const wrap = (ui: React.ReactElement) => (
  <QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>)

describe('Confirmed without proof: a warning, not a must (2026-10-28)', () => {
  it('warns, asks for the answer in words, then saves', async () => {
    render(wrap(<AnswerForm changeId={7} concern={q} attachments={[]} onDone={() => {}} />))
    fireEvent.click(screen.getByTestId('answer-kind-confirmed-11'))
    expect(screen.getByTestId('answer-no-proof-11').textContent).toContain('Forgot something?')
    const save = screen.getByTestId('answer-save-11') as HTMLButtonElement
    expect(save.disabled).toBe(true)
    fireEvent.change(screen.getByPlaceholderText('The answer in words'), { target: { value: 'Yes, LH and RH' } })
    expect(save.disabled).toBe(false)
    fireEvent.click(save)
    await waitFor(() => expect(changesApi.answerConcernForm).toHaveBeenCalledWith(
      7, 11, { answer_kind: 'confirmed', note: 'Yes, LH and RH' }))
  })

  it('Assumed takes attachments too', () => {
    render(wrap(<AnswerForm changeId={7} concern={q} attachments={[]} onDone={() => {}} />))
    fireEvent.click(screen.getByTestId('answer-kind-assumed-11'))
    expect(screen.getByTestId('dropzone')).toBeTruthy()
    expect(screen.queryByTestId('answer-no-proof-11')).toBeNull()
  })
})
