import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import AttachmentDropzone from './AttachmentDropzone'

const upload = vi.fn()
vi.mock('../../api/changes', () => ({
  changesApi: { uploadAttachment: (id: number, f: File) => upload(id, f) },
}))
const toastErr = vi.fn()
vi.mock('sonner', () => ({ toast: { error: (m: string) => toastErr(m), success: vi.fn() } }))

const file = (name: string, size = 10) =>
  new File([new Uint8Array(size)], name, { type: 'application/octet-stream' })

describe('AttachmentDropzone', () => {
  beforeEach(() => { upload.mockReset().mockResolvedValue({ id: 1 }); toastErr.mockReset() })
  afterEach(cleanup)

  it('uploads each dropped file', async () => {
    const onUploaded = vi.fn()
    render(<AttachmentDropzone changeId={7} onUploaded={onUploaded} />)
    const zone = screen.getByRole('button', { name: /drop files/i })
    fireEvent.drop(zone, { dataTransfer: { files: [file('deck.pptx'), file('mail.msg')] } })
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(2))
    expect(upload).toHaveBeenCalledWith(7, expect.objectContaining({ name: 'deck.pptx' }))
    expect(upload).toHaveBeenCalledWith(7, expect.objectContaining({ name: 'mail.msg' }))
    await waitFor(() => expect(onUploaded).toHaveBeenCalled())
  })

  it('guides the user when a drop carries no file (Outlook-direct drag)', async () => {
    render(<AttachmentDropzone changeId={7} onUploaded={vi.fn()} />)
    const zone = screen.getByRole('button', { name: /drop files/i })
    fireEvent.drop(zone, { dataTransfer: { files: [] } })
    await waitFor(() => expect(toastErr).toHaveBeenCalledWith(expect.stringMatching(/save the email as \.msg/i)))
    expect(upload).not.toHaveBeenCalled()
  })

  it('rejects a file over 50 MB without uploading it', async () => {
    render(<AttachmentDropzone changeId={7} onUploaded={vi.fn()} />)
    const zone = screen.getByRole('button', { name: /drop files/i })
    const huge = new File([new Uint8Array(1)], 'big.pdf')
    Object.defineProperty(huge, 'size', { value: 51 * 1024 * 1024 })
    fireEvent.drop(zone, { dataTransfer: { files: [huge] } })
    await waitFor(() => expect(toastErr).toHaveBeenCalledWith(expect.stringMatching(/larger than 50 MB/i)))
    expect(upload).not.toHaveBeenCalled()
  })
})
