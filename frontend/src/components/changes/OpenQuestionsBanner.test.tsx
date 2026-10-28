import { afterEach, describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, cleanup } from '@testing-library/react'
import OpenQuestionsBanner from './OpenQuestionsBanner'
import type { ChangeConcern } from '../../types/change'

const q = (id: number, extra: Partial<ChangeConcern> = {}) => ({
  id, kind: 'needs_info', flag_type: 'question', is_open: true, note: `Q${id}?`,
  answer_from: 'customer', answered_at: null, raised_by: 1, ...extra,
}) as unknown as ChangeConcern

afterEach(cleanup)

describe('OpenQuestionsBanner', () => {
  it('warns everyone in scoping: count, impact, who answers', () => {
    const onShow = vi.fn()
    render(<OpenQuestionsBanner status="scoping" onShow={onShow} concerns={[
      q(1), q(2, { answer_from: 'our_team', answered_at: '2026-10-28' }),
      q(3, { flag_type: 'check' }), q(4, { is_open: false }), q(6, { answer_from: null, asking_department_name: 'APQP' } as Partial<ChangeConcern>),
      q(5, { kind: 'reject_proposal' } as Partial<ChangeConcern>)]} />)
    const b = screen.getByTestId('open-questions-banner')
    expect(b.textContent).toContain('3 open questions hold this change')
    expect(b.textContent).toContain('no department gets a task')
    expect(screen.getByTestId('open-question-1').textContent).toContain('Customer: Q1?')
    expect(screen.getByTestId('open-question-2').textContent).toContain('Answered, PM closes: Q2?')
    expect(screen.getByTestId('open-question-6').textContent).toContain('APQP: Q6?')
    expect(screen.queryByTestId('open-question-3')).toBeNull()
    fireEvent.click(screen.getByTestId('open-questions-show'))
    expect(onShow).toHaveBeenCalled()
  })

  it('is gone once the change has moved on or nothing is open', () => {
    const { rerender } = render(<OpenQuestionsBanner status="in_assessment" concerns={[q(1)]} />)
    expect(screen.queryByTestId('open-questions-banner')).toBeNull()
    rerender(<OpenQuestionsBanner status="scoping" concerns={[q(1, { is_open: false })]} />)
    expect(screen.queryByTestId('open-questions-banner')).toBeNull()
  })
})
