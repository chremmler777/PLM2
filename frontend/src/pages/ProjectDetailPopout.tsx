/**
 * ProjectDetailPopout - the detail pane alone, in its own browser window.
 * It follows the selection the project window posts on the project channel
 * and tells that window when it opens and closes.
 */
import { useEffect, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import DetailPane from '../components/project/DetailPane';
import type { DetailTab } from '../components/project/detailTabs';
import { useProject, useProjectParts } from '../hooks/queries/useProjectDetail';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useArticleSelection } from '../hooks/useArticleSelection';
import { useSelectionChannel } from '../hooks/useSelectionChannel';

function toId(value: string | null): number | null {
  const n = value ? parseInt(value, 10) : NaN;
  return Number.isFinite(n) ? n : null;
}

export default function ProjectDetailPopout() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const [searchParams] = useSearchParams();
  const initialPart = toId(searchParams.get('part'));
  const initialRev = toId(searchParams.get('rev'));
  // The main window that opened this one; it only listens to hello and bye carrying its id.
  const owner = searchParams.get('owner') ?? undefined;
  const queryClient = useQueryClient();

  const { data: project } = useProject(id);
  const { data: parts } = useProjectParts(id);
  const { data: structure } = useProjectStructure(id);
  const sel = useArticleSelection(parts, initialPart);
  const { partId, openPart, pickRevision, selectRevision } = sel;
  const [tab, setTab] = useState<DetailTab>('documents');

  useEffect(() => {
    if (initialPart !== null && initialRev !== null) pickRevision(initialPart, initialRev);
  }, [initialPart, initialRev, pickRevision]);

  const post = useSelectionChannel(id, (message) => {
    if (message.type === 'ping') {
      post(owner ? { type: 'hello', owner } : { type: 'hello' });
      return;
    }
    if (message.type !== 'select') return;
    if (message.partId === null) {
      openPart(null);
      return;
    }
    // A part created in the main window after this one loaded: fetch the list again.
    if (!parts?.some((p) => p.id === message.partId)) {
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
    }
    if (message.revisionId === null) openPart(message.partId);
    else if (message.partId === partId) selectRevision(message.revisionId);
    else pickRevision(message.partId, message.revisionId);
  }, owner ? { type: 'bye', owner } : { type: 'bye' });

  useEffect(() => {
    post(owner ? { type: 'hello', owner } : { type: 'hello' });
  }, [post, owner]);

  useEffect(() => {
    if (project) document.title = `${project.code} ${project.name} detail`;
  }, [project]);

  if (!project) {
    return <div className="h-screen bg-slate-900 p-6 text-slate-400">Loading project...</div>;
  }

  return (
    <div data-testid="popout-page" className="h-screen flex flex-col bg-slate-900">
      <div className="flex-shrink-0 px-4 py-1.5 border-b border-slate-800 text-xs text-slate-500">
        <span className="font-mono text-slate-400">{project.code}</span> {project.name} · follows the project window
      </div>
      <div className="flex-1 min-h-0">
        <DetailPane
          projectId={id}
          project={project}
          parts={parts}
          structure={structure}
          sel={sel}
          tab={tab}
          onTabChange={setTab}
          emptyText="Select an item in the main window"
        />
      </div>
    </div>
  );
}
