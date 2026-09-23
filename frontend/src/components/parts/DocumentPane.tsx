/**
 * DocumentPane - the one area on the article panel that shows what you are
 * looking at: the 3D viewer (passed in as children so assembly mode keeps
 * working), a drawing PDF, or a picture. A mirror part with no own data shows
 * the source part's document under a red warning.
 */
import type { ReactNode } from 'react';
import { API_BASE_URL } from '../../api/client';

export interface PaneDocument {
  fileId: number;
  filename: string;
  kind: '3d' | 'pdf' | 'image';
  revisionName: string;
  /** Override for documents that are not revision files (DFM archive). */
  inlineUrl?: string;
  /** What the document came from, shown in the title bar instead of revisionName (e.g. "Answer #8 · KTX to Toolmaker"). */
  sourceLabel?: string;
}

export interface MirrorNotice {
  sourcePartId: number;
  sourceNumber: string;
  sourceName: string;
}

interface Props {
  document: PaneDocument | null;
  mirror?: MirrorNotice | null;
  onOpenPart?(partId: number): void;
  onClose?(): void;
  children?: ReactNode;
}

export default function DocumentPane({ document, mirror, onOpenPart, onClose, children }: Props) {
  const inlineUrl = document
    ? (document.inlineUrl ?? `${API_BASE_URL}/v1/parts/revision-files/${document.fileId}/inline`)
    : null;
  return (
    <div className="relative border-b border-slate-700">
      {mirror && (
        <div data-testid="mirror-banner"
          className="flex items-center justify-between gap-2 px-3 py-1.5 bg-red-900/60 border-b border-red-600 text-red-100 text-xs">
          <span>
            Mirrored part. Showing {mirror.sourceNumber} ({mirror.sourceName}). Geometry is the mirror image, RPS and references differ.
          </span>
          {onOpenPart && (
            <button onClick={() => onOpenPart(mirror.sourcePartId)}
              className="px-2 py-0.5 rounded bg-red-800 hover:bg-red-700 text-white font-medium flex-shrink-0">
              Open source part
            </button>
          )}
        </div>
      )}
      {document ? (
        <>
          <div data-testid="doc-header" className="flex items-center justify-between gap-2 px-3 py-1 text-xs text-slate-400 bg-slate-800/60">
            <span className="font-mono truncate">{document.filename} · {document.sourceLabel ?? document.revisionName}</span>
            {onClose && (
              <button data-testid="doc-close" onClick={onClose} className="flex-shrink-0 text-slate-400 hover:text-slate-200">
                ✕ Close
              </button>
            )}
          </div>
          {document.kind === '3d' && <div className="h-80 overflow-hidden relative">{children}</div>}
          {document.kind === 'pdf' && (
            <iframe data-testid="doc-iframe" title={document.filename} src={inlineUrl ?? undefined} className="w-full h-[32rem] bg-white" />
          )}
          {document.kind === 'image' && (
            <div className="h-80 flex items-center justify-center bg-slate-900">
              <img src={inlineUrl ?? undefined} alt={document.filename} className="max-h-full max-w-full object-contain" />
            </div>
          )}
        </>
      ) : (
        <div className="h-24 flex items-center justify-center text-xs text-slate-500">No document to show on this revision</div>
      )}
    </div>
  );
}
