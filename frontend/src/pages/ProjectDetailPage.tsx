/**
 * ProjectDetailPage - the project work surface. A one-line header, the status
 * nav bar (SEP gates, changes, lessons) with its inline panel, the items
 * list on the left and the selected item's detail on the right; the page
 * fills the viewport and each pane scrolls on its own. The detail can pop out
 * into its own window, which follows the selection over the project channel
 * while the list here turns into a table.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useHref, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import StartChangeModal from '../components/changes/StartChangeModal';
import { projectPaintOverview } from '../api/paints';
import type { PartPaintLayer } from '../types/paint';
import { useProjectStructure } from '../hooks/queries/useProjectStructure';
import { useProject, useProjectParts } from '../hooks/queries/useProjectDetail';
import { revisionOfSelectedPart, useArticleSelection } from '../hooks/useArticleSelection';
import { selectionChannelSupported, useSelectionChannel } from '../hooks/useSelectionChannel';
import { windowOwnerId } from '../lib/windowOwner';
import ProjectHeaderBar from '../components/project/ProjectHeaderBar';
import ProjectStatusNav from '../components/project/ProjectStatusNav';
import ItemsPane from '../components/project/ItemsPane';
import DetailPane from '../components/project/DetailPane';
import SplitPane from '../components/project/SplitPane';
import ProjectContextMenu from '../components/project/ProjectContextMenu';
import ChangelogModal from '../components/project/ChangelogModal';
import AddPartModal from '../components/project/AddPartModal';
import type { DetailTab } from '../components/project/detailTabs';
import type { ContextMenuState } from '../components/project/projectTypes';

const SPLIT_KEY = 'plm2.project.splitLeft';
const POPOUT_POLL_MS = 1000;

/**
 * One page instance per project: switching projects on the same route mounts a
 * fresh page, so pop-out state (table mode, the window handle) and the
 * selection never carry over from the previous project.
 */
export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  return <ProjectDetailView key={projectId} />;
}

function ProjectDetailView() {
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
  // What the pop-out gets told: never a revision of the previously selected item.
  const postedRevisionId = revisionOfSelectedPart(sel);

  // Follow ?part= deep links from global search while already on the page
  useEffect(() => {
    if (initialPartId) selectPart(parseInt(initialPartId, 10));
  }, [initialPartId, selectPart]);

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showStartChange, setShowStartChange] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>('documents');

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

  // Pop-out detail window
  const [popoutOpen, setPopoutOpen] = useState(false);
  const popoutRef = useRef<Window | null>(null);
  const popoutHref = useHref(`/projects/${id}/detail`);
  // Another tab on the same project shares the channel; its pop-out carries a different owner.
  const [owner] = useState(windowOwnerId);

  const post = useSelectionChannel(id, (message) => {
    if ((message.type === 'hello' || message.type === 'bye') && message.owner !== owner) return;
    if (message.type === 'hello') {
      setPopoutOpen(true);
      post({ type: 'select', partId: sel.partId, revisionId: postedRevisionId });
    } else if (message.type === 'bye') {
      // A reloading pop-out says bye and then hello again from the same
      // window: keep the handle so the closed-window poll still covers it.
      if (popoutRef.current?.closed) popoutRef.current = null;
      setPopoutOpen(false);
    }
  });

  // On load, ask whether a pop-out of this project is already open; it answers hello.
  useEffect(() => {
    post({ type: 'ping' });
  }, [post]);

  useEffect(() => {
    if (popoutOpen) post({ type: 'select', partId: sel.partId, revisionId: postedRevisionId });
  }, [popoutOpen, sel.partId, postedRevisionId, post]);

  // A window closed by the OS or a crash never says bye: watch the handle we opened.
  useEffect(() => {
    if (!popoutOpen) return;
    const timer = window.setInterval(() => {
      if (popoutRef.current?.closed) {
        popoutRef.current = null;
        setPopoutOpen(false);
      }
    }, POPOUT_POLL_MS);
    return () => window.clearInterval(timer);
  }, [popoutOpen]);

  const openPopout = useCallback(() => {
    const params = new URLSearchParams();
    if (sel.partId !== null) {
      params.set('part', String(sel.partId));
      if (postedRevisionId !== null) params.set('rev', String(postedRevisionId));
    }
    params.set('owner', owner);
    // A fixed name per project: a second click reuses the same window.
    const win = window.open(`${popoutHref}?${params.toString()}`, `plm2-detail-${id}`, 'popup,width=1100,height=900');
    if (!win) {
      toast.error('The browser blocked the new window');
      return;
    }
    popoutRef.current = win;
    setPopoutOpen(true);
  }, [sel.partId, postedRevisionId, popoutHref, id, owner]);

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
    <div data-testid="project-page" className="h-full flex flex-col overflow-hidden bg-slate-900">
      <ProjectHeaderBar
        project={project}
        onStartChange={() => setShowStartChange(true)}
        onAddPart={() => setShowAddModal(true)}
      />
      <ProjectStatusNav projectId={id} />

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <div className="flex-1 min-h-0">
        <SplitPane
          storageKey={SPLIT_KEY}
          rightHidden={popoutOpen}
          left={
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
              mode={popoutOpen ? 'table' : 'list'}
            />
          }
          right={
            <div data-testid="detail-column" className="h-full min-h-0" onClick={() => selectPart(null)}>
              <DetailPane
                projectId={id}
                project={project}
                parts={parts}
                structure={structure}
                sel={sel}
                tab={detailTab}
                onTabChange={setDetailTab}
                onPopOut={selectionChannelSupported() ? openPopout : undefined}
              />
            </div>
          }
        />
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
