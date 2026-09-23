/**
 * Tool tab: produced-article chips (open the article via the existing
 * open-part callback) and the tool fields card, fed by the part's own
 * produces relations.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';
import RevisionLabel from '../parts/RevisionLabel';
import ToolFieldsCard from '../tools/ToolFieldsCard';
import { producedArticles, type ToolRelation } from '../tools/toolRelations';
import type { Part } from './projectTypes';

export default function ToolInfoTab({ part, onOpenPart }: { part: Part; onOpenPart(partId: number): void }) {
  const { data: relations, isLoading } = useQuery({
    queryKey: ['part-relations', part.id],
    queryFn: async () => (await client.get(`/v1/parts/${part.id}/relations`)).data as ToolRelation[],
  });
  const produced = producedArticles(relations ?? []);

  return (
    <>
      {!isLoading && (
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
      <ToolFieldsCard
        partId={part.id}
        values={{
          tool_cavities: part.tool_cavities ?? null,
          toolmaker_id: part.toolmaker_id ?? null,
          tool_tonnage_class: part.tool_tonnage_class ?? null,
          tool_cycle_time_s: part.tool_cycle_time_s ?? null,
        }}
        producedNotes={produced.map((a) => a.notes)}
      />
    </>
  );
}
