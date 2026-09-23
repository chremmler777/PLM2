/**
 * ProjectDetailPage - the project work surface: header, items list and the
 * selected item's detail. Data hooks and selection state live here; the
 * panes live in components/project.
 */
import { useState, useEffect, useMemo } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import ProjectLessonsSection from '../components/ProjectLessonsSection';
import ProjectSepSection from '../components/ProjectSepSection';
import ProjectChangesSection from '../components/ProjectChangesSection';
import ProjectPaintSection from '../components/paint/ProjectPaintSection';
import StartChangeModal from '../components/changes/StartChangeModal';
import { projectPaintOverview } from '../api/paints';
import type { PartPaintLayer } from '../types/paint';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useProject, useProjectParts } from '../hooks/queries/useProjectDetail';
import { useArticleSelection } from '../hooks/useArticleSelection';
import ProjectHeaderBar from '../components/project/ProjectHeaderBar';
import ItemsPane from '../components/project/ItemsPane';
import DetailPane from '../components/project/DetailPane';
import ProjectContextMenu from '../components/project/ProjectContextMenu';
import ChangelogModal from '../components/project/ChangelogModal';
import AddPartModal from '../components/project/AddPartModal';
import type { ContextMenuState } from '../components/project/projectTypes';

export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const navigate = useNavigate();

  const [searchParams] = useSearchParams();
  const initialPartId = searchParams.get('part');

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: structure } = useProjectStructure(id);
  const sel = useArticleSelection(parts, initialPartId ? parseInt(initialPartId, 10) : null);
  const { selectPart, openPart, pickRevision } = sel;

  // Follow ?part= deep links from global search while already on the page
  useEffect(() => {
    if (initialPartId) selectPart(parseInt(initialPartId, 10));
  }, [initialPartId, selectPart]);

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showStartChange, setShowStartChange] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);

  const { data: paintOverview } = useQuery({
    queryKey: ['project-paint-overview', id],
    queryFn: () => projectPaintOverview(id),
    enabled: !!id,
  });
  // Top layer (layer_order 1) per painted part, for the swatch on the item row.
  const paintByPartId = useMemo(() => {
    const map = new Map<number, PartPaintLayer>();
    for (const part of paintOverview ?? []) {
      const top = part.layers.find((l) => l.layer_order === 1) ?? part.layers[0];
      if (top) map.set(part.part_id, top);
    }
    return map;
  }, [paintOverview]);
  // Every part that requires paint, layer or not: the Painted chip counts
  // these, so the filter must select the same set (a part marked required
  // with no layer yet was counted but filtered out, 2026-09-21).
  const paintedIds = useMemo(
    () => new Set((paintOverview ?? []).map((part) => part.part_id)),
    [paintOverview],
  );

  if (projectLoading) {
    return <div className="p-6 text-slate-400">Loading project...</div>;
  }

  if (!project) {
    return (
      <div className="p-6 text-center">
        <p className="text-red-400 mb-4">Project not found</p>
        <button onClick={() => navigate('/projects')} className="text-blue-400 hover:text-blue-300">
          Back to projects
        </button>
      </div>
    );
  }

  const handleContextMenu = (e: React.MouseEvent, partId: number) => {
    e.preventDefault();
    setContextMenu({ partId, x: e.clientX, y: e.clientY });
  };

  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      <ProjectHeaderBar
        project={project}
        onStartChange={() => setShowStartChange(true)}
        onAddPart={() => setShowAddModal(true)}
      />

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <ProjectSepSection projectId={id} />

      <ProjectChangesSection projectId={id} />

      <ProjectPaintSection projectId={id} />

      <ProjectLessonsSection projectId={id} />

      {/* Two-column layout */}
      <div className="grid grid-cols-3 gap-6">
        <ItemsPane
          projectId={id}
          projectCode={project.code}
          parts={parts}
          partsLoading={partsLoading}
          structure={structure}
          paintByPartId={paintByPartId}
          paintedIds={paintedIds}
          paintedCount={paintOverview?.length ?? 0}
          selectedPartId={sel.partId}
          onSelect={selectPart}
          onOpenPart={openPart}
          onPickRevision={pickRevision}
          onContextMenu={handleContextMenu}
        />

        {/* Right: Part Detail */}
        <div className="col-span-2 space-y-4 min-h-96" onClick={() => selectPart(null)}>
          <DetailPane
            projectId={id}
            project={project}
            parts={parts}
            structure={structure}
            sel={sel}
            onShowChangelog={setChangelogPartId}
          />
        </div>
      </div>

      <ProjectContextMenu
        menu={contextMenu}
        onClose={() => setContextMenu(null)}
        onOpenDetails={(partId) => navigate(`/parts/${partId}`)}
        onViewChangelog={(partId) => setChangelogPartId(partId)}
      />

      {changelogPartId && <ChangelogModal partId={changelogPartId} onClose={() => setChangelogPartId(null)} />}

      <AddPartModal projectId={id} parts={parts} isOpen={showAddModal} onClose={() => setShowAddModal(false)} />
    </div>
  );
}
