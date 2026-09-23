import { describe, it, expect, vi, beforeEach } from 'vitest'
import { buildEntryFormData, createEntry, dfmFileUrl, KINDS, KIND_LABELS, PARTIES, PARTY_LABELS } from './dfm'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }))
vi.mock('./client', () => ({ default: clientMocks, API_BASE_URL: '/plm2/api' }))

describe('dfm api', () => {
  beforeEach(() => { clientMocks.post.mockReset() })

  it('names the three parties in column order', () => {
    expect(PARTIES).toEqual(['toolmaker', 'ktx', 'tier1'])
    expect(PARTY_LABELS).toEqual({ toolmaker: 'Toolmaker', ktx: 'KTX', tier1: 'Tier 1' })
  })

  it('builds file urls under the tool', () => {
    expect(dfmFileUrl(7, 12, 'inline')).toBe('/plm2/api/v1/parts/7/dfm/files/12/inline')
    expect(dfmFileUrl(7, 12, 'download')).toBe('/plm2/api/v1/parts/7/dfm/files/12/download')
  })

  it('serialises an entry as multipart with addressed_to as JSON and repeated files', () => {
    const file = new File([new Uint8Array([1, 2])], 'dfm.pdf', { type: 'application/pdf' })
    const fd = buildEntryFormData({ party: 'ktx', addressed_to: ['toolmaker', 'tier1'], note: 'rev A', sent_at: '2026-09-24', supersedes_id: null, kind: 'original', reply_to_id: null, files: [file] })
    expect(fd.get('party')).toBe('ktx')
    expect(JSON.parse(fd.get('addressed_to') as string)).toEqual(['toolmaker', 'tier1'])
    expect(fd.get('note')).toBe('rev A')
    expect(fd.get('sent_at')).toBe('2026-09-24')
    expect(fd.has('supersedes_id')).toBe(false)
    expect(fd.get('kind')).toBe('original')
    expect(fd.has('reply_to_id')).toBe(false)
    expect(fd.getAll('files')).toHaveLength(1)
  })

  it('posts an update with supersedes_id and no sent date', async () => {
    clientMocks.post.mockResolvedValue({ data: { id: 3 } })
    await createEntry(7, 2, { party: 'ktx', addressed_to: ['toolmaker'], note: '', sent_at: '', supersedes_id: 1, kind: 'answer', reply_to_id: 1, files: [] })
    const [url, body] = clientMocks.post.mock.calls[0]
    expect(url).toBe('/v1/parts/7/dfm/topics/2/entries')
    expect((body as FormData).get('supersedes_id')).toBe('1')
    expect((body as FormData).has('sent_at')).toBe(false)
  })

  it('names the four message kinds', () => {
    expect(KINDS).toEqual(['original', 'forward', 'answer', 'question'])
    expect(KIND_LABELS).toEqual({ original: 'Original', forward: 'Forward', answer: 'Answer', question: 'Question' })
  })

  it('sends kind and reply_to_id for a reply', () => {
    const fd = buildEntryFormData({ party: 'tier1', addressed_to: ['ktx'], note: 'gate ok', sent_at: '', supersedes_id: null, kind: 'answer', reply_to_id: 2, files: [] })
    expect(fd.get('kind')).toBe('answer')
    expect(fd.get('reply_to_id')).toBe('2')
  })
})
