/**
 * 2D drawings and PDFs open in their own browser window, like other PLMs do,
 * never in the preview pane: the pane keeps the 3D model. One window name per
 * file, so opening the same file again focuses the window it is already in.
 * The URL is the same inline URL the pane used; it is authorized by the
 * shared SSO cookie, so a new window works without any header.
 */
import { toast } from 'sonner';
import { API_BASE_URL } from '../../api/client';
import { docKindFor } from './RevisionFilesGrouped';

export interface WindowDocument {
  fileId: number;
  filename: string;
  /** Override for documents that are not revision files (DFM archive). */
  inlineUrl?: string;
}

export const documentInlineUrl = (doc: WindowDocument) =>
  doc.inlineUrl ?? `${API_BASE_URL}/v1/parts/revision-files/${doc.fileId}/inline`;

/** DFM files live in another table than revision files, so their ids get their own name space. */
export const documentWindowName = (doc: WindowDocument) =>
  doc.inlineUrl ? `plm2-doc-dfm-${doc.fileId}` : `plm2-doc-${doc.fileId}`;

/** A PDF, or any picture filed as a drawing, opens in a window; other pictures stay in the pane. */
export function opensInWindow(file: { mime_type: string; filename: string; file_type?: string }): boolean {
  const kind = docKindFor(file);
  return kind === 'pdf' || (kind === 'image' && file.file_type === 'drawing');
}

export function openDocumentWindow(doc: WindowDocument): boolean {
  const url = documentInlineUrl(doc);
  const win = window.open(url, documentWindowName(doc), 'popup,width=1200,height=900');
  if (!win) {
    toast.error('The browser blocked the new window', {
      description: (
        <a href={url} target="_blank" rel="noopener" className="underline">Open {doc.filename} in a new tab</a>
      ),
    });
    return false;
  }
  win.focus?.();
  return true;
}
