import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, cleanup, fireEvent } from '@testing-library/react'
import CustomerDataDialog from './CustomerDataDialog'

describe('CustomerDataDialog', () => {
  afterEach(cleanup)

  it('submits the chosen major number and omits it when blank', () => {
    const onSubmit = vi.fn()
    render(<CustomerDataDialog open title="t" onClose={() => {}} onSubmit={onSubmit} nextMajor={{ review: 1, official: 1 }} />)
    const major = screen.getByTestId('major-input') as HTMLInputElement
    expect(major.placeholder).toBe('1')
    fireEvent.click(screen.getByText('Save'))
    expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ statement: 'review' }))
    expect(onSubmit.mock.calls[0][0].major).toBeUndefined()

    fireEvent.change(major, { target: { value: '3' } })
    fireEvent.click(screen.getByText('Save'))
    expect(onSubmit.mock.calls[1][0].major).toBe(3)
  })

  it('placeholder follows the statement', () => {
    render(<CustomerDataDialog open title="t" onClose={() => {}} onSubmit={() => {}} nextMajor={{ review: 3, official: 1 }} />)
    expect((screen.getByTestId('major-input') as HTMLInputElement).placeholder).toBe('3')
    fireEvent.click(screen.getByLabelText(/official/i))
    expect((screen.getByTestId('major-input') as HTMLInputElement).placeholder).toBe('1')
  })
})
