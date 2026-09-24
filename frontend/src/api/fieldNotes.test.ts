import { describe, it, expect, vi, beforeEach } from 'vitest'
import { addFieldComment, getFieldNoteThread, listProjectFieldNotes, setFieldFlag } from './fieldNotes'
import { downloadWorksheetXlsx, getWorksheet } from './worksheet'
import { searchMaterials, setPartMaterial, refreshPartMaterial, materialDbUrl } from './materials'

const clientMocks = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }))
vi.mock('./client', () => ({ default: clientMocks, API_BASE_URL: '' }))

describe('field notes, material and worksheet api', () => {
  beforeEach(() => {
    clientMocks.get.mockReset(); clientMocks.post.mockReset(); clientMocks.put.mockReset()
    clientMocks.get.mockResolvedValue({ data: [] })
    clientMocks.post.mockResolvedValue({ data: {} })
    clientMocks.put.mockResolvedValue({ data: {} })
  })

  it('calls the field note routes with the key in the path', async () => {
    await getFieldNoteThread(7, 'tool.cavities')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities')
    await addFieldComment(7, 'tool.cavities', 'Excel says 4')
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/comments', { body: 'Excel says 4' })
    await setFieldFlag(7, 'tool.cavities', null)
    expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/7/field-notes/tool.cavities/flag', { status: null })
    await listProjectFieldNotes(35)
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/35/field-notes')
  })

  it('calls the material and worksheet routes', async () => {
    await searchMaterials('pa6')
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/materials/search', { params: { q: 'pa6' } })
    await setPartMaterial(5, { source: 'new', new_text: 'PP' })
    expect(clientMocks.put).toHaveBeenCalledWith('/v1/parts/5/material', { source: 'new', new_text: 'PP' })
    await refreshPartMaterial(5)
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/parts/5/material/refresh')
    expect(materialDbUrl(11)).toBe('/materialdb/materials/11')
    await getWorksheet(35)
    expect(clientMocks.get).toHaveBeenCalledWith('/v1/projects/35/worksheet')
  })

  it('downloads the export under the server file name', async () => {
    const click = vi.fn()
    const anchor = { click, href: '', download: '' } as unknown as HTMLAnchorElement
    const create = vi.spyOn(document, 'createElement').mockReturnValue(anchor)
    const url = vi.fn(() => 'blob:x')
    const revoke = vi.fn()
    Object.assign(URL, { createObjectURL: url, revokeObjectURL: revoke })
    clientMocks.post.mockResolvedValue({ data: new Blob(['x']), headers: { 'content-disposition': 'attachment; filename="1994-worksheet-2026-09-24.xlsx"' } })
    const payload = { columns: [{ key: 'part.part_number', label: 'KTX no.', type: 'text' as const }], rows: [], frozen_columns: 1 }
    await downloadWorksheetXlsx(35, payload)
    expect(clientMocks.post).toHaveBeenCalledWith('/v1/projects/35/worksheet/export', payload, { responseType: 'blob' })
    expect(anchor.download).toBe('1994-worksheet-2026-09-24.xlsx')
    expect(click).toHaveBeenCalled()
    expect(revoke).toHaveBeenCalledWith('blob:x')
    create.mockRestore()
  })
})
