import { describe, it, expect } from 'vitest'
import { apiErrorMessage } from './apiError'

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
})
