import { describe, it, expect, vi, beforeEach } from 'vitest'

const toastErrorSpy = vi.fn()
vi.mock('sonner', () => ({ toast: { error: (...a: unknown[]) => toastErrorSpy(...a) } }))

import { apiErrorMessage, toastError } from './apiError'

describe('apiErrorMessage', () => {
  it('returns a plain string detail (HTTPException)', () => {
    expect(apiErrorMessage({ response: { data: { detail: 'Change not found' } } }))
      .toBe('Change not found')
  })

  it('joins a 422 validation array into a string instead of returning the objects', () => {
    const e = { response: { data: { detail: [
      { type: 'missing', loc: ['body', 'file'], msg: 'Field required', input: null },
      { type: 'string', loc: ['body', 'x'], msg: 'Bad value' },
    ] } } }
    const msg = apiErrorMessage(e)
    expect(typeof msg).toBe('string')
    expect(msg).toBe('Field required; Bad value')
  })

  it('falls back when there is no usable detail', () => {
    expect(apiErrorMessage({ response: { data: {} } }, 'Upload failed')).toBe('Upload failed')
    expect(apiErrorMessage(new Error('network'), 'Upload failed')).toBe('Upload failed')
    expect(apiErrorMessage(undefined)).toBe('Request failed')
  })

  it('handles a single object detail with a msg field', () => {
    expect(apiErrorMessage({ response: { data: { detail: { msg: 'Too large' } } } }))
      .toBe('Too large')
  })

  it('reads a structured detail with a message field', () => {
    expect(apiErrorMessage({ response: { data: { detail: { code: 'blocked', message: 'Offer not approved' } } } }))
      .toBe('Offer not approved')
  })

  it('falls back on an object detail without msg or message', () => {
    expect(apiErrorMessage({ response: { data: { detail: { code: 'x' } } } }, 'Could not save')).toBe('Could not save')
    expect(apiErrorMessage({ response: { data: { detail: { message: '  ' } } } }, 'Could not save')).toBe('Could not save')
  })
})

describe('toastError', () => {
  beforeEach(() => toastErrorSpy.mockReset())

  it('toasts the backend reason as a string and returns it', () => {
    const msg = toastError({ response: { data: { detail: 'Quote is locked' } } }, 'Could not save the quote')
    expect(msg).toBe('Quote is locked')
    expect(toastErrorSpy).toHaveBeenCalledWith('Quote is locked')
  })

  it('never passes a 422 array to the toast', () => {
    toastError({ response: { data: { detail: [{ msg: 'Field required' }] } } }, 'Could not save')
    expect(toastErrorSpy).toHaveBeenCalledWith('Field required')
    expect(typeof toastErrorSpy.mock.calls[0][0]).toBe('string')
  })

  it('uses the specific fallback when the backend says nothing', () => {
    expect(toastError(new Error('Network Error'), 'Could not send the offer')).toBe('Could not send the offer')
    expect(toastErrorSpy).toHaveBeenCalledWith('Could not send the offer')
  })
})
