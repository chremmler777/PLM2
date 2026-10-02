/**
 * DFM tab for a tool (or, with a project scope, the general tooling DFM in
 * the project status panel): the DFM archive plus a document pane for the
 * PDF opened from the ledger. Rendered keyed by part id so switching tools
 * resets the open document. Opening a document scrolls the pane into view,
 * since the archive can be long and the pane would otherwise open off screen.
 */
import { useEffect, useRef, useState } from 'react';
import DocumentPane, { type PaneDocument } from '../parts/DocumentPane';
import DfmArchive from '../dfm/DfmArchive';
import { toolScope, type DfmScope } from '../../api/dfm';

type Props =
  | { partId: number; scope?: never; projectId?: number | null }
  | { scope: DfmScope; partId?: never; projectId?: number | null };

export default function ToolDfmTab({ partId, scope, projectId = null }: Props) {
  const [openDoc, setOpenDoc] = useState<PaneDocument | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);
  const archiveScope = scope ?? toolScope(partId!);

  useEffect(() => {
    if (openDoc) paneRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [openDoc]);

  return (
    <>
      {openDoc && (
        <div ref={paneRef} className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <DocumentPane document={openDoc} onClose={() => setOpenDoc(null)} />
        </div>
      )}
      <DfmArchive scope={archiveScope} projectId={projectId} onOpenPdf={setOpenDoc} />
    </>
  );
}
