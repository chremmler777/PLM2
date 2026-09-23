/**
 * DFM tab for a tool: the DFM archive plus a document pane for the PDF
 * opened from the ledger. Rendered keyed by part id so switching tools
 * resets the open document.
 */
import { useState } from 'react';
import DocumentPane, { type PaneDocument } from '../parts/DocumentPane';
import DfmArchive from '../dfm/DfmArchive';

export default function ToolDfmTab({ partId }: { partId: number }) {
  const [openDoc, setOpenDoc] = useState<PaneDocument | null>(null);

  return (
    <>
      {openDoc && (
        <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden">
          <div className="flex justify-end px-3 py-1">
            <button onClick={() => setOpenDoc(null)} className="text-xs text-slate-400 hover:text-slate-200">close</button>
          </div>
          <DocumentPane document={openDoc} />
        </div>
      )}
      <DfmArchive partId={partId} onOpenPdf={setOpenDoc} />
    </>
  );
}
