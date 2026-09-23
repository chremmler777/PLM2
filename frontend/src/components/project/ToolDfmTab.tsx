/**
 * DFM tab for a tool: the DFM archive plus a document pane for the PDF
 * opened from the ledger. Rendered keyed by part id so switching tools
 * resets the open document. Opening a document scrolls the pane into view,
 * since the archive can be long and the pane would otherwise open off screen.
 */
import { useEffect, useRef, useState } from 'react';
import DocumentPane, { type PaneDocument } from '../parts/DocumentPane';
import DfmArchive from '../dfm/DfmArchive';

export default function ToolDfmTab({ partId }: { partId: number }) {
  const [openDoc, setOpenDoc] = useState<PaneDocument | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);

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
      <DfmArchive partId={partId} onOpenPdf={setOpenDoc} />
    </>
  );
}
