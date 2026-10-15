/**
 * DfmPopout - the DFM archive of one tool (/parts/:partId/dfm) or the general
 * tooling DFM of a project (/projects/:projectId/dfm) in its own browser
 * window, optionally ?topic=<id>. No app sidebar: a small tool or project
 * header and the archive at full window size; PDFs open in their own window.
 * It shares the react-query keys of the main window and refetches on
 * window focus, so both windows stay current.
 */
import { useEffect } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import client from '../api/client';
import DfmArchive from '../components/dfm/DfmArchive';
import { projectScope, toolScope } from '../api/dfm';
import { useProject } from '../hooks/queries/useProjectDetail';
import { producedArticles, type ToolRelation } from '../components/tools/toolRelations';

interface ToolHead {
  id: number;
  part_number: string;
  name: string;
  project_id?: number | null;
}

export default function DfmPopout() {
  const { partId, projectId } = useParams<{ partId?: string; projectId?: string }>();
  const isProject = projectId != null;
  const id = !isProject && partId ? parseInt(partId, 10) : 0;
  const pid = isProject ? parseInt(projectId, 10) : 0;
  const [searchParams] = useSearchParams();
  const topicParam = parseInt(searchParams.get('topic') ?? '', 10);
  const initialTopic = Number.isFinite(topicParam) ? topicParam : null;

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
  const { data: project } = useProject(pid);
  const produced = producedArticles(relations ?? []);

  useEffect(() => { if (part) document.title = `DFM ${part.part_number}`; }, [part]);
  useEffect(() => { if (project) document.title = `General tooling DFM ${project.code}`; }, [project]);

  return (
    <div className="h-screen flex flex-col bg-slate-900 text-slate-100">
      <header data-testid="dfm-popout-header"
        className="flex flex-wrap items-baseline gap-x-3 gap-y-1 px-4 py-2 border-b border-slate-700 bg-slate-800">
        {isProject ? (
          <>
            <span className="font-semibold">General tooling DFM</span>
            <span className="text-xs text-slate-400">Project</span>
            <span className="font-semibold tabular-nums">{project?.code ?? '…'}</span>
            <span className="text-slate-300">{project?.name}</span>
          </>
        ) : (
          <>
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
          </>
        )}
      </header>
      <div className="flex-1 min-h-0 flex">
        <main className="flex-1 min-w-0 flex flex-col">
          <DfmArchive key={isProject ? `p${pid}` : `t${id}`} scope={isProject ? projectScope(pid) : toolScope(id)}
            projectId={isProject ? null : part?.project_id ?? null} initialTopic={initialTopic} inWindow />
        </main>
      </div>
    </div>
  );
}
