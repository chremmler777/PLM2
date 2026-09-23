/**
 * ToolDetail - the part page for item_category = tool. A tool has no 3D
 * pane, no revision strip and no customer numbers; it shows what it
 * produces, its sold state (Task 10) and the DFM archive (Task 11).
 */
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import RevisionLabel from '../components/parts/RevisionLabel';
import PartThumbnail from '../components/parts/PartThumbnail';
import ToolFieldsCard from '../components/tools/ToolFieldsCard';
import DocumentPane, { type PaneDocument } from '../components/parts/DocumentPane';
import DfmArchive from '../components/dfm/DfmArchive';
import { producedArticles, type ToolRelation } from '../components/tools/toolRelations';

export interface ToolPart {
  id: number;
  part_number: string;
  name: string;
  part_type: string;
  project_id: number;
  item_category: string;
  lifecycle_phase: 'rfq' | 'nominated' | 'series';
  tool_cavities: number | null;
  toolmaker_id: number | null;
  tool_tonnage_class: number | null;
  tool_cycle_time_s: number | null;
  thumbnail_url?: string | null;
}

interface Props {
  part: ToolPart;
  onOpenPart(partId: number): void;
  onBack(): void;
}

export default function ToolDetail({ part, onOpenPart, onBack }: Props) {
  const [showStartChange, setShowStartChange] = useState(false);
  const [openDoc, setOpenDoc] = useState<PaneDocument | null>(null);
  const paneRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (openDoc) paneRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
  }, [openDoc]);

  const { data: relations, isLoading: relationsLoading } = useQuery({
    queryKey: ['part-relations', part.id],
    queryFn: async () => (await client.get(`/v1/parts/${part.id}/relations`)).data as ToolRelation[],
  });
  const produced = producedArticles(relations ?? []);

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-8">
          <button onClick={onBack} className="mb-4 px-3 py-1 bg-slate-700 text-slate-100 rounded hover:bg-slate-600 text-sm">← Back</button>
          <div className="flex justify-between items-start gap-4">
            <div className="flex items-start gap-4 min-w-0">
            <PartThumbnail url={part.thumbnail_url} name={part.name} size="lg" testId="tool-thumbnail" />
            <div className="min-w-0">
              <h1 className="text-4xl font-bold text-slate-100 mb-1">{part.part_number}</h1>
              <p className="text-slate-300 mb-2">{part.name}</p>
              <div className="flex items-center gap-2 flex-wrap mb-3">
                <span className="text-sm text-slate-200 bg-slate-700 px-3 py-1 rounded-md">Tool</span>
                <span data-testid="lifecycle-phase" className="text-sm text-slate-200 bg-slate-700 px-3 py-1 rounded-md capitalize">{part.lifecycle_phase}</span>
              </div>
              {!relationsLoading && (
                <div data-testid="produced-articles" className="flex items-center gap-2 flex-wrap text-sm">
                  <span className="text-slate-400">Produces</span>
                  {produced.length === 0 && <span className="text-slate-500">No produced article linked yet</span>}
                  {produced.map((a) => (
                    <button key={a.part_id} onClick={() => onOpenPart(a.part_id)}
                      className="px-2 py-0.5 rounded bg-slate-700 text-slate-100 hover:bg-slate-600">
                      {a.name}
                      {a.revision_name && <span className="text-slate-400"> · <RevisionLabel name={a.revision_name} index={a.customer_index} /></span>}
                    </button>
                  ))}
                </div>
              )}
            </div>
            </div>
            <StartChangeButton label="Start change request" onClick={() => setShowStartChange(true)}
              className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
          </div>
        </div>

        <ToolFieldsCard partId={part.id}
          values={{ tool_cavities: part.tool_cavities, toolmaker_id: part.toolmaker_id,
            tool_tonnage_class: part.tool_tonnage_class, tool_cycle_time_s: part.tool_cycle_time_s }}
          producedNotes={produced.map((a) => a.notes)} />

        {openDoc && (
          <div ref={paneRef} className="bg-slate-800 rounded-lg border border-slate-700 mb-8 overflow-hidden">
            <DocumentPane document={openDoc} onClose={() => setOpenDoc(null)} />
          </div>
        )}
        <DfmArchive partId={part.id} onOpenPdf={setOpenDoc} />

        {showStartChange && (
          <StartChangeModal open onClose={() => setShowStartChange(false)}
            prefill={{ projectId: part.project_id, part: { id: part.id, part_number: part.part_number, name: part.name, item_category: part.item_category } }} />
        )}
      </div>
    </div>
  );
}
