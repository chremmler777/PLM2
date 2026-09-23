/**
 * DetailPane - the selected item. A pinned header and tab bar; only the tab
 * content below them scrolls. Used by the project page and the pop-out
 * detail window.
 */
import RevisionWorkflowSection from '../workflows/RevisionWorkflowSection';
import PartBOMSection from '../PartBOMSection';
import PartRelationsSection from '../PartRelationsSection';
import ProcessFlowSection from '../ProcessFlowSection';
import PPAPSection from '../PPAPSection';
import { revisionLabel } from '../parts/RevisionBadge';
import { stripProjectCode } from '../../lib/partDisplay';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useRevisionFiles } from '../../hooks/queries/useProjectDetail';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { BomTreeSection } from './BomTreeSection';
import { ChangelogList } from './ChangelogModal';
import DetailHeader from './DetailHeader';
import DocumentsTab from './DocumentsTab';
import { DETAIL_TABS, type DetailTab } from './detailTabs';
import {
  CATEGORY_META, LOCKED_REVISION_STATUSES, phaseColor, statusColor, type Part, type Project,
} from './projectTypes';

export interface DetailPaneProps {
  projectId: number;
  project: Project;
  parts: Part[] | undefined;
  structure: ProjectStructure | undefined;
  sel: ArticleSelection;
  tab: DetailTab;
  onTabChange(tab: DetailTab): void;
  onPopOut?: () => void;
  emptyText?: string;
}

export default function DetailPane({
  projectId, project, parts, structure, sel, tab, onTabChange, onPopOut,
  emptyText = 'Select an item from the list',
}: DetailPaneProps) {
  const { data: revisionFiles } = useRevisionFiles(sel.revisionId || 0);
  const part = parts?.find((p) => p.id === sel.partId);

  if (!part) {
    return (
      <div className="h-full flex items-center justify-center text-sm text-slate-500" data-testid="detail-empty">
        {emptyText}
      </div>
    );
  }

  const article = articleOf(structure, part.id);
  const selectedRevision = sel.partRevisions?.find((r) => r.id === sel.revisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const revName = revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index);
  const hasLinks = !!article && (article.related.length > 0 || !!article.mirror_of || article.mirrored_by.length > 0);

  return (
    <div data-testid="detail-pane" className="h-full min-h-0 flex flex-col bg-slate-900" onClick={(e) => e.stopPropagation()}>
      <DetailHeader projectId={projectId} part={part} article={article} sel={sel} onPopOut={onPopOut} />

      <div role="tablist" aria-label="Detail sections" className="flex-shrink-0 flex gap-1 px-3 border-b border-slate-700 bg-slate-800/60">
        {DETAIL_TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            type="button"
            data-testid={`detail-tab-${t.key}`}
            aria-selected={tab === t.key}
            onClick={() => onTabChange(t.key)}
            className={`px-3 py-2 text-xs font-medium border-b-2 -mb-px ${
              tab === t.key ? 'border-sky-400 text-sky-300' : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div role="tabpanel" data-testid="detail-scroll" className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
        {tab === 'documents' && (
          // Keyed by part: open dialogs and their state never carry over to another item.
          <DocumentsTab key={part.id} projectId={projectId} project={project} parts={parts} structure={structure} sel={sel} part={part} />
        )}

        {tab === 'links' && (
          <>
            {hasLinks && (
              <div className="flex flex-wrap gap-1">
                {article!.related.map((r) => (
                  <button key={`${r.relation_type}-${r.part_id}`} data-testid={`relation-chip-${r.part_id}`}
                    onClick={() => sel.openPart(r.part_id)}
                    className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-xs text-slate-200">
                    <span className="text-slate-400">{r.label}</span> {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, project.code)}
                  </button>
                ))}
                {article!.mirrored_by.map((m) => (
                  <button key={m.part_id} onClick={() => sel.openPart(m.part_id)}
                    className="px-2 py-0.5 rounded border border-red-700 text-xs text-red-300">
                    ⇄ mirrored by {m.part_number}
                  </button>
                ))}
              </div>
            )}
            <PartRelationsSection
              partId={part.id}
              itemCategory={part.item_category}
              projectParts={parts ?? []}
              onSelectPart={sel.selectPart}
            />
          </>
        )}

        {tab === 'bom' && (
          sel.revisionId ? (
            <>
              <BomTreeSection partId={part.id} revisionId={sel.revisionId} revisionName={revName} onOpenPart={sel.openPart} />
              {part.part_type !== 'purchased' && (
                <PartBOMSection
                  partId={part.id}
                  revisionId={sel.revisionId}
                  revisionName={revName}
                  locked={revisionLocked}
                  projectParts={parts ?? []}
                />
              )}
            </>
          ) : (
            <p className="text-slate-500 text-sm">No revision yet, so no BOM.</p>
          )
        )}

        {tab === 'workflow' && (
          <>
            <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
              <h3 className="text-sm font-semibold text-slate-200 mb-3">Revisions</h3>
              {!sel.partRevisions || sel.partRevisions.length === 0 ? (
                <p className="text-slate-500 text-sm">No revisions yet</p>
              ) : (
                <div className="space-y-2">
                  {sel.partRevisions.map((rev) => (
                    <div
                      key={rev.id}
                      onClick={() => sel.selectRevision(rev.id)}
                      className={`p-3 rounded border cursor-pointer transition ${
                        rev.id === sel.revisionId
                          ? 'bg-blue-900/30 border-blue-600'
                          : 'bg-slate-700/50 border-slate-600 hover:bg-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-mono font-semibold text-slate-100 text-sm">{revisionLabel(rev.revision_name, rev.customer_index)}</span>
                        <span className={`px-2 py-0.5 rounded text-xs font-medium ${phaseColor(rev.phase)}`}>
                          {rev.phase}{rev.part_phase_at_receipt ? ` · ${rev.part_phase_at_receipt}` : ''}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className={statusColor(rev.status)}>{rev.status.replace(/_/g, ' ')}</span>
                        <span className="text-slate-500">{new Date(rev.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {sel.revisionId && <RevisionWorkflowSection revisionId={sel.revisionId} revisionName={revName} />}
            {part.item_category !== 'article' && (
              <ProcessFlowSection partId={part.id} onSelectPart={sel.selectPart} />
            )}
            {sel.revisionId && part.item_category === 'article' && (
              <PPAPSection
                revisionId={sel.revisionId}
                revisionName={revName}
                revisionFiles={(revisionFiles ?? []).map((f) => ({ id: f.id, filename: f.filename }))}
              />
            )}
          </>
        )}

        {tab === 'changelog' && <ChangelogList partId={part.id} />}
      </div>
    </div>
  );
}
