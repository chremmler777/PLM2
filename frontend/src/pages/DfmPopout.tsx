/**
 * DfmPopout - the DFM archive of one tool in its own browser window
 * (/parts/:partId/dfm, optionally ?topic=<id>). No app sidebar: a small tool
 * header, the archive at full window size, and a document pane beside it for
 * PDFs. It shares the react-query keys of the main window and refetches on
 * window focus, so both windows stay current.
 */
import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import DocumentPane, { type PaneDocument } from '../components/parts/DocumentPane';
import DfmArchive from '../components/dfm/DfmArchive';
import { producedArticles, type ToolRelation } from '../components/tools/toolRelations';

interface ToolHead {
  id: number;
  part_number: string;
  name: string;
}

export default function DfmPopout() {
  const { partId } = useParams<{ partId: string }>();
  const id = partId ? parseInt(partId, 10) : 0;
  const [searchParams] = useSearchParams();
  const topicParam = parseInt(searchParams.get('topic') ?? '', 10);
  const initialTopic = Number.isFinite(topicParam) ? topicParam : null;
  const [openDoc, setOpenDoc] = useState<PaneDocument | null>(null);

  const { data: part } = useQuery({
    queryKey: ['part', id],
    queryFn: async () => (await client.get(`/v1/parts/${id}`)).data as ToolHead,
    enabled: id > 0,
  });
  const { data: relations } = useQuery({
    queryKey: ['part-relations', id],
    queryFn: async () => (await client.get(`/v1/parts/${id}/relations`)).data as ToolRelation[],
    enabled: id > 0,
  });
  const produced = producedArticles(relations ?? []);

  useEffect(() => { if (part) document.title = `DFM ${part.part_number}`; }, [part]);

  return (
    <div className="h-screen flex flex-col bg-slate-900 text-slate-100">
      <header data-testid="dfm-popout-header"
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 border-b border-slate-700 bg-slate-800">
        <span className="text-xs text-slate-400">Tool</span>
        <span className="font-semibold tabular-nums">{part?.part_number ?? '…'}</span>
        <span className="text-slate-300">{part?.name}</span>
        {produced.length > 0 && (
          <span className="text-sm text-slate-400">
            produces{' '}
            {produced.map((a, i) => (
              <span key={a.part_id}>{i > 0 && ', '}<span className="text-slate-200">{a.name}</span></span>
            ))}
          </span>
        )}
      </header>
      <div className="flex-1 min-h-0 flex">
        <main className="flex-1 min-w-0 flex flex-col">
          <DfmArchive partId={id} onOpenPdf={setOpenDoc} initialTopic={initialTopic} inWindow />
        </main>
        {openDoc && (
          <aside className="w-[42%] min-w-[24rem] border-l border-slate-700 bg-slate-800 flex flex-col overflow-auto">
            <DocumentPane document={openDoc} onClose={() => setOpenDoc(null)} />
          </aside>
        )}
      </div>
    </div>
  );
}
