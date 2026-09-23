/**
 * ProjectDetailPage - Product-centric project overview with hierarchical tree view of parts
 */
import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client, { API_BASE_URL } from '../api/client';
import Viewer3D from '../components/Viewer3D';
import UploadDialog from '../components/parts/UploadDialog';
import RevisionWorkflowSection from '../components/workflows/RevisionWorkflowSection';
import PartBOMSection from '../components/PartBOMSection';
import PartRelationsSection from '../components/PartRelationsSection';
import ProcessFlowSection from '../components/ProcessFlowSection';
import PPAPSection from '../components/PPAPSection';
import MilestoneStrip from '../components/MilestoneStrip';
import ProjectLessonsSection from '../components/ProjectLessonsSection';
import ProjectSepSection from '../components/ProjectSepSection';
import ProjectChangesSection from '../components/ProjectChangesSection';
import ProjectPaintSection from '../components/paint/ProjectPaintSection';
import { projectPaintOverview } from '../api/paints';
import type { PartPaintLayer } from '../types/paint';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import CustomerDataDialog, { type CustomerDataInput } from '../components/parts/CustomerDataDialog';
import CustomerPackageDialog from '../components/parts/CustomerPackageDialog';
import { revisionLabel } from '../components/parts/RevisionBadge';
import { stripProjectCode } from '../lib/partDisplay';
import { toast } from 'sonner';
import RevisionStrip from '../components/parts/RevisionStrip';
import DocumentPane, { type PaneDocument, type MirrorNotice } from '../components/parts/DocumentPane';
import RevisionFilesGrouped, { docKindFor } from '../components/parts/RevisionFilesGrouped';
import { useProjectStructure, articleOf } from '../hooks/queries/useProjectStructure';
import {
  CATEGORY_META, LOCKED_REVISION_STATUSES,
  phaseColor, statusColor, typeColor,
  type ContextMenuState,
} from '../components/project/projectTypes';
import {
  useAssemblyFiles, usePartRevisions, useProject, useProjectParts, useRevisionFiles,
} from '../hooks/queries/useProjectDetail';
import { BomTreeSection } from '../components/project/BomTreeSection';
import { CustomerNamingSelect } from '../components/project/CustomerNamingSelect';
import ChangelogModal from '../components/project/ChangelogModal';
import ProjectContextMenu from '../components/project/ProjectContextMenu';
import AddPartModal from '../components/project/AddPartModal';
import ItemsPane from '../components/project/ItemsPane';

// Main Component
export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const navigate = useNavigate();

  const [searchParams] = useSearchParams();
  const initialPartId = searchParams.get('part');
  const [selectedPartId, setSelectedPartId] = useState<number | null>(
    initialPartId ? parseInt(initialPartId, 10) : null
  );
  const [selectedRevisionId, setSelectedRevisionId] = useState<number | null>(null);

  // Follow ?part= deep links from global search while already on the page
  useEffect(() => {
    if (initialPartId) setSelectedPartId(parseInt(initialPartId, 10));
  }, [initialPartId]);
  const [viewingFileId, setViewingFileId] = useState<number | null>(null);
  const [openDocId, setOpenDocId] = useState<number | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showStartChange, setShowStartChange] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: paintOverview } = useQuery({
    queryKey: ['project-paint-overview', id],
    queryFn: () => projectPaintOverview(id),
    enabled: !!id,
  });
  // Top layer (layer_order 1) per painted part, for the swatch on the tree row.
  const paintByPartId = useMemo(() => {
    const map = new Map<number, PartPaintLayer>();
    for (const part of paintOverview ?? []) {
      const top = part.layers.find((l) => l.layer_order === 1) ?? part.layers[0];
      if (top) map.set(part.part_id, top);
    }
    return map;
  }, [paintOverview]);
  // Every part that requires paint, layer or not - the Painted chip counts
  // these, so the filter must select the same set (a part marked required
  // with no layer yet was counted but filtered out, 2026-09-21).
  const paintedIds = useMemo(
    () => new Set((paintOverview ?? []).map((part) => part.part_id)),
    [paintOverview],
  );
  const { data: partRevisions } = usePartRevisions(selectedPartId || 0);
  const { data: revisionFiles } = useRevisionFiles(selectedRevisionId || 0);
  const { data: structure } = useProjectStructure(id);
  const article = articleOf(structure, selectedPartId);
  const mirrorSource = article?.mirror_of ? articleOf(structure, article.mirror_of.part_id) : undefined;
  const mirrorFiles = useRevisionFiles(mirrorSource?.active_revision_id ?? 0);
  const queryClient = useQueryClient();

  const isSubAssembly = parts?.find((p) => p.id === selectedPartId)?.part_type === 'sub_assembly';
  const { data: assemblyFiles } = useAssemblyFiles(isSubAssembly && selectedPartId ? selectedPartId : 0);
  const assemblyAvailable = isSubAssembly && (assemblyFiles?.length ?? 0) > 1;
  const assemblyActive = assemblyAvailable && viewingFileId === null;
  const assemblyModels = useMemo(
    () =>
      assemblyFiles?.map((f) => ({
        id: f.file_id,
        url: `${API_BASE_URL}/v1/parts/revision-files/${f.file_id}/viewer`,
        label: f.uploaded_by_name
          ? `${f.part_name} (${f.revision_name}) · ${f.uploaded_by_name}`
          : `${f.part_name} (${f.revision_name})`,
      })),
    [assemblyFiles]
  );

  // Explicit revision request (e.g. clicking a revision chip in the tree) wins over
  // the default-revision effect below, which otherwise resets to active/latest
  // whenever selectedPartId changes.
  const pendingRevisionRef = useRef<{ partId: number; revisionId: number } | null>(null);

  // Default revision selection: active revision if known, otherwise the latest
  useEffect(() => {
    setViewingFileId(null);
    setOpenDocId(null);
    // A pending pick only guards the part change it was made for — once
    // selectedPartId has moved on to something else, the ref must not
    // outlive that change, or a later re-select of the original part
    // (with revisions already cached) would wrongly reapply the stale pick.
    if (pendingRevisionRef.current && pendingRevisionRef.current.partId !== selectedPartId) {
      pendingRevisionRef.current = null;
    }
    if (pendingRevisionRef.current?.partId === selectedPartId) {
      const pending = pendingRevisionRef.current;
      if (partRevisions?.some((r) => r.id === pending.revisionId)) {
        pendingRevisionRef.current = null;
        setSelectedRevisionId(pending.revisionId);
        return;
      }
      if (!partRevisions || partRevisions.length === 0) {
        // Revisions for this part haven't loaded yet — wait for the next
        // effect run instead of falling through to the default selection.
        return;
      }
      pendingRevisionRef.current = null;
    }
    if (!partRevisions || partRevisions.length === 0) {
      setSelectedRevisionId(null);
      return;
    }
    const activeId = parts?.find((p) => p.id === selectedPartId)?.active_revision_id;
    const fallback = partRevisions[partRevisions.length - 1].id;
    setSelectedRevisionId(partRevisions.some((r) => r.id === activeId) ? activeId! : fallback);
  }, [selectedPartId, partRevisions, parts]);

  const markCalibratedMutation = useMutation({
    mutationFn: async (partId: number) => {
      await client.put(`/v1/parts/${partId}`, { last_calibrated_at: new Date().toISOString() });
    },
    onSuccess: () => {
      toast.success('Calibration recorded');
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to record calibration');
    },
  });

  const [showCustomerData, setShowCustomerData] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[] | null>(null);
  const [uploadDrag, setUploadDrag] = useState(false);
  const customerDataMutation = useMutation({
    mutationFn: async (v: CustomerDataInput) => {
      const res = await client.post(`/v1/parts/${selectedPartId}/revisions/customer-data`, v);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Recorded ${data.revision_name}`);
      setShowCustomerData(false);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to record customer data');
    },
  });

  const proposalMutation = useMutation({
    mutationFn: async (parentRevisionId: number) => {
      const res = await client.post(`/v1/parts/${selectedPartId}/revisions/proposals`, { parent_revision_id: parentRevisionId });
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}`);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
      setSelectedRevisionId(data.id);
      setViewingFileId(null);
      setOpenDocId(null);
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create proposal');
    },
  });

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

  const selectedPart = parts?.find((p) => p.id === selectedPartId);

  const selectedRevision = partRevisions?.find((r) => r.id === selectedRevisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const viewableFiles = revisionFiles?.filter((f) => f.has_viewer) ?? [];
  const viewingFile = viewableFiles.find((f) => f.id === viewingFileId) ?? viewableFiles[0] ?? null;
  const viewerUrl = viewingFile
    ? `${API_BASE_URL}/v1/parts/revision-files/${viewingFile.id}/viewer`
    : null;

  const openDoc = revisionFiles?.find((f) => f.id === openDocId) ?? null;
  const revName = selectedRevision ? revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index) : '';
  let paneDoc: PaneDocument | null = null;
  let paneMirror: MirrorNotice | null = null;
  if (openDoc) {
    const kind = docKindFor(openDoc);
    if (kind) paneDoc = { fileId: openDoc.id, filename: openDoc.filename, kind, revisionName: revName };
  } else if (viewingFile || assemblyActive) paneDoc = { fileId: viewingFile?.id ?? 0, filename: assemblyActive ? 'Assembly' : viewingFile!.filename, kind: '3d', revisionName: revName };
  else if (article?.mirror_of && mirrorSource) {
    const src = mirrorFiles.data ?? [];
    const pick = src.find((f) => f.has_viewer) ?? src.find((f) => f.file_type === 'drawing' && docKindFor(f)) ?? null;
    const sourceActiveRev = mirrorSource.revisions.find((r) => r.is_active);
    const sourceRevName = sourceActiveRev
      ? revisionLabel(sourceActiveRev.revision_name, sourceActiveRev.customer_index)
      : mirrorSource.part_number;
    if (pick) {
      const kind = pick.has_viewer ? '3d' : docKindFor(pick);
      if (kind) paneDoc = { fileId: pick.id, filename: pick.filename, kind, revisionName: sourceRevName };
    }
    paneMirror = { sourcePartId: mirrorSource.part_id, sourceNumber: mirrorSource.customer_part_number ?? mirrorSource.part_number, sourceName: mirrorSource.name };
  }
  const paneViewerUrl = paneMirror && paneDoc?.kind === '3d' ? `${API_BASE_URL}/v1/parts/revision-files/${paneDoc.fileId}/viewer` : viewerUrl;

  const handleContextMenu = (e: React.MouseEvent, partId: number) => {
    e.preventDefault();
    setContextMenu({ partId, x: e.clientX, y: e.clientY });
  };

  return (
    <div className="p-6 bg-slate-900 min-h-screen">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <button
            onClick={() => navigate('/projects')}
            className="text-sm text-blue-400 hover:text-blue-300 mb-3"
          >
            ← Back
          </button>
          <h1 className="text-3xl font-semibold tracking-tight text-slate-100">
            {project.name} <span className="text-slate-400 text-sm">({project.code})</span>
          </h1>
          <div className="mt-2">
            <MilestoneStrip projectId={id} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <CustomerNamingSelect projectId={id} value={project.customer_naming ?? null} />
          <StartChangeButton label="Start change request"
            onClick={() => setShowStartChange(true)}
            className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
          <button
            onClick={() => setShowAddModal(true)}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
          >
            + Add Part
          </button>
        </div>
      </div>

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
        {/* Left: Parts Tree */}
        <ItemsPane
          projectId={id}
          projectCode={project.code}
          parts={parts}
          partsLoading={partsLoading}
          structure={structure}
          paintByPartId={paintByPartId}
          paintedIds={paintedIds}
          paintedCount={paintOverview?.length ?? 0}
          selectedPartId={selectedPartId}
          onSelect={setSelectedPartId}
          onOpenPart={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }}
          onPickRevision={(pid, rid) => { pendingRevisionRef.current = { partId: pid, revisionId: rid }; setSelectedPartId(pid); setSelectedRevisionId(rid); setViewingFileId(null); setOpenDocId(null); }}
          onContextMenu={handleContextMenu}
        />

        {/* Right: Part Detail */}
        <div
          className="col-span-2 space-y-4 min-h-96"
          onClick={() => setSelectedPartId(null)}
        >
          {selectedPart ? (
            <div onClick={(e) => e.stopPropagation()} className="space-y-4">
              {/* Part Info Card */}
              <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
                <div className="flex items-start justify-between">
                  <h2 className="text-lg font-bold text-slate-100">{selectedPart.name}</h2>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setChangelogPartId(selectedPart.id)}
                      className="px-3 py-1 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-xs font-medium"
                    >
                      Changelog
                    </button>
                    <button
                      onClick={() => navigate(`/parts/${selectedPart.id}`)}
                      className="px-3 py-1 rounded bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium"
                    >
                      Revisions & Lifecycle →
                    </button>
                  </div>
                </div>
                <div className="text-slate-400 text-sm mt-1 flex items-center gap-2">
                  <span className="font-mono">{selectedPart.part_number}</span>
                  {selectedPart.customer_part_number && <span className="font-mono" title="Customer (OEM) part number">{selectedPart.customer_part_number}</span>}
                  {selectedPart.tier1_part_number && <span className="font-mono" data-testid="selected-tier1-number" title="Tier 1 part number">Tier 1 {selectedPart.tier1_part_number}</span>}
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${typeColor(selectedPart.part_type)}`}>
                    {selectedPart.part_type.replace(/_/g, ' ')}
                  </span>
                  {CATEGORY_META[selectedPart.item_category] && (
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${CATEGORY_META[selectedPart.item_category].badge}`}>
                      {CATEGORY_META[selectedPart.item_category].icon} {CATEGORY_META[selectedPart.item_category].label}
                    </span>
                  )}
                  {article?.mirror_of && (
                    <button data-testid="mirror-chip" onClick={() => { setSelectedPartId(article.mirror_of!.part_id); setViewingFileId(null); setOpenDocId(null); }}
                      className="px-2 py-0.5 rounded border border-red-500 text-red-300 text-xs">
                      ⇄ Mirror of {article.mirror_of.customer_part_number ?? article.mirror_of.part_number} · data on that part
                    </button>
                  )}
                </div>
                {selectedPart.item_category === 'gauge' && (
                  <div className="mt-2 flex items-center gap-3 text-sm">
                    {selectedPart.next_calibration_due ? (
                      <span
                        className={
                          new Date(selectedPart.next_calibration_due) < new Date()
                            ? 'text-red-400 font-medium'
                            : 'text-slate-300'
                        }
                      >
                        📏 Calibration due {new Date(selectedPart.next_calibration_due).toLocaleDateString()}
                        {new Date(selectedPart.next_calibration_due) < new Date() && ' — OVERDUE'}
                      </span>
                    ) : (
                      <span className="text-amber-400">📏 No calibration recorded</span>
                    )}
                    <button
                      onClick={() => markCalibratedMutation.mutate(selectedPart.id)}
                      disabled={markCalibratedMutation.isPending}
                      className="px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-200 text-xs font-medium"
                    >
                      {markCalibratedMutation.isPending ? 'Saving...' : 'Mark calibrated today'}
                    </button>
                  </div>
                )}
                {selectedPart.supplier && <p className="text-slate-400 text-sm mt-2">Supplier: {selectedPart.supplier}</p>}
                {selectedPart.data_classification && (
                  <p className="text-slate-400 text-sm">Classification: {selectedPart.data_classification}</p>
                )}
              </div>

              {/* Revision Files & CAD Viewer */}
              <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden flex flex-col">
                {/* Revision selector header */}
                <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700 bg-slate-700/30">
                  <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">
                    {article ? `${article.part_number} · ${article.name} · ${article.lifecycle_phase}` : 'Files & 3D Model'}
                  </h3>
                  <div className="flex items-center gap-2">
                    {revisionLocked && (
                      <span className="text-xs text-amber-400" title="This revision is locked; files are read-only">🔒 {selectedRevision?.status}</span>
                    )}
                    <button onClick={() => setShowPackage(true)}
                      className="bg-blue-700 hover:bg-blue-600 border border-blue-600 rounded px-2 py-1 text-white text-xs font-medium">+ Customer package</button>
                  </div>
                </div>
                {partRevisions && partRevisions.length > 0 && (
                  <div className="border-b border-slate-700 bg-slate-800/60">
                    <RevisionStrip
                      revisions={partRevisions}
                      selectedId={selectedRevisionId}
                      activeId={selectedPart.active_revision_id}
                      onSelect={(revId) => { setSelectedRevisionId(revId); setViewingFileId(null); setOpenDocId(null); }}
                      onNewProposal={(majorId) => proposalMutation.mutate(majorId)}
                    />
                  </div>
                )}

                {showPackage && selectedPartId && (
                  <CustomerPackageDialog open assemblyId={selectedPartId}
                    projectParts={(parts ?? []).map((p) => ({ id: p.id, part_number: p.part_number, name: p.name }))}
                    officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
                    onClose={() => setShowPackage(false)}
                    onDone={(r) => {
                      toast.success(`Stored ${r.created.length} new, kept ${r.kept.length}`);
                      setShowPackage(false);
                      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                      queryClient.invalidateQueries({ queryKey: ['parts', id] });
                      queryClient.invalidateQueries({ queryKey: ['bom-tree'] });
                      queryClient.invalidateQueries({ queryKey: ['project-assemblies', id] });
                      queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
                    }} />
                )}

                {!partRevisions || partRevisions.length === 0 ? (
                  <div className="p-6 text-center">
                    {article?.mirror_of && (
                      <div className="mb-4 text-left">
                        <DocumentPane document={paneDoc} mirror={paneMirror}
                          onOpenPart={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }}>
                          <Viewer3D
                            fileId={paneDoc?.fileId ?? null}
                            viewerUrl={paneViewerUrl}
                          />
                        </DocumentPane>
                      </div>
                    )}
                    <p className="text-slate-400 text-sm mb-3">
                      Files are managed per revision. Record the first customer data to upload files.
                    </p>
                    <button
                      onClick={() => setShowCustomerData(true)}
                      className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
                    >
                      + Customer data
                    </button>
                    {showCustomerData && (() => {
                      const majorsOf = (revs: { revision_name: string }[]) => revs.filter((r) => !r.revision_name.includes('.'));
                      const revs = partRevisions || [];
                      const nextMajor = {
                        review: Math.max(0, ...majorsOf(revs).filter((r) => r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name.slice(1), 10))) + 1,
                        official: Math.max(0, ...majorsOf(revs).filter((r) => !r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name, 10))) + 1,
                      };
                      return (
                        <CustomerDataDialog open title="Customer data received" nextMajor={nextMajor}
                          pending={customerDataMutation.isPending} onClose={() => setShowCustomerData(false)}
                          onSubmit={(v) => customerDataMutation.mutate(v)} />
                      );
                    })()}
                  </div>
                ) : (
                  <>
                    {/* Document pane: openDoc (Open) -> 3D viewer -> mirror fallback -> none */}
                    <DocumentPane document={paneDoc} mirror={paneMirror}
                      onOpenPart={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }}>
                      <Viewer3D
                        fileId={assemblyActive ? null : paneDoc?.fileId ?? null}
                        viewerUrl={assemblyActive ? null : paneViewerUrl}
                        models={assemblyActive ? assemblyModels : undefined}
                      />
                      {assemblyActive && (
                        <div className="absolute top-2 right-2 z-10 px-2 py-1 rounded bg-blue-900/70 text-blue-200 text-xs font-medium">
                          Assembly · {assemblyFiles?.length} components
                        </div>
                      )}
                      {assemblyAvailable && !assemblyActive && (
                        <button
                          onClick={() => setViewingFileId(null)}
                          className="absolute top-2 right-2 z-10 px-2 py-1 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-200 text-xs font-medium"
                        >
                          ← Assembly view
                        </button>
                      )}
                    </DocumentPane>
                    {/* Files list + uploader */}
                    <div className="p-2 bg-slate-700/50 max-h-56 overflow-y-auto space-y-1">
                      <RevisionFilesGrouped
                        files={revisionFiles ?? []}
                        locked={revisionLocked}
                        viewingFileId={viewingFile?.id ?? null}
                        revisionName={selectedRevision ? revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index) : ''}
                        onView={(f) => { setViewingFileId(f.id); setOpenDocId(null); }}
                        onOpen={(f) => setOpenDocId(f.id)}
                      />
                      {!revisionLocked && selectedRevisionId && (
                        <div
                          data-testid="upload-dropzone"
                          className={`border-2 border-dashed rounded-lg p-2 text-center text-xs cursor-pointer transition-colors ${uploadDrag ? 'border-blue-500 bg-blue-50/10' : 'border-slate-600 hover:border-slate-500 bg-slate-800/50'}`}
                          onDragEnter={(e) => { e.preventDefault(); setUploadDrag(true); }}
                          onDragOver={(e) => { e.preventDefault(); setUploadDrag(true); }}
                          onDragLeave={(e) => { e.preventDefault(); setUploadDrag(false); }}
                          onDrop={(e) => { e.preventDefault(); setUploadDrag(false); setUploadFiles(Array.from(e.dataTransfer.files)); }}
                          onClick={() => document.getElementById('upload-dropzone-input')?.click()}
                        >
                          <input id="upload-dropzone-input" type="file" multiple className="hidden"
                            onChange={(e) => { if (e.target.files?.length) setUploadFiles(Array.from(e.target.files)); e.target.value = ''; }} />
                          <p className="text-slate-400">+ Drop files here or click to upload (CAD, drawing, picture, document)</p>
                        </div>
                      )}
                    </div>
                    {uploadFiles && selectedRevision && (
                      <UploadDialog
                        open
                        partId={selectedPart.id}
                        currentRevision={{ id: selectedRevision.id, revision_name: selectedRevision.revision_name,
                          customer_index: selectedRevision.customer_index, phase: selectedRevision.phase }}
                        revisionNames={(partRevisions ?? []).map((r) => r.revision_name)}
                        officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
                        projectNaming={project?.customer_naming ?? null}
                        initialFiles={uploadFiles}
                        onClose={(targetRevisionId) => {
                          setUploadFiles(null);
                          if (targetRevisionId != null) {
                            queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                            queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
                            queryClient.invalidateQueries({ queryKey: ['parts', id] });
                            queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
                            setSelectedRevisionId(targetRevisionId);
                          }
                        }}
                        onDone={(targetRevisionId) => {
                          setUploadFiles(null);
                          queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                          queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
                          queryClient.invalidateQueries({ queryKey: ['parts', id] });
                          queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
                          setSelectedRevisionId(targetRevisionId);
                        }}
                      />
                    )}
                  </>
                )}
              </div>

              {/* Relation chips: article's related items and mirror links */}
              {article && (article.related.length > 0 || article.mirror_of || article.mirrored_by.length > 0) && (
                <div className="flex flex-wrap gap-1 px-2 py-1 border-t border-slate-700">
                  {article.related.map((r) => (
                    <button key={`${r.relation_type}-${r.part_id}`} data-testid={`relation-chip-${r.part_id}`}
                      onClick={() => { setSelectedPartId(r.part_id); setViewingFileId(null); setOpenDocId(null); }}
                      className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-xs text-slate-200">
                      <span className="text-slate-400">{r.label}</span> {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, project?.code)}
                    </button>
                  ))}
                  {article.mirrored_by.map((m) => (
                    <button key={m.part_id} onClick={() => { setSelectedPartId(m.part_id); setViewingFileId(null); setOpenDocId(null); }}
                      className="px-2 py-0.5 rounded border border-red-700 text-xs text-red-300">
                      ⇄ mirrored by {m.part_number}
                    </button>
                  ))}
                </div>
              )}

              {/* Process route, derived from serves/feeds (tools and equipment only) */}
              {selectedPart.item_category !== 'article' && (
                <ProcessFlowSection
                  partId={selectedPart.id}
                  onSelectPart={setSelectedPartId}
                />
              )}

              {/* Item Relations (tool produces / gauge checks / equipment assembles) */}
              <PartRelationsSection
                partId={selectedPart.id}
                itemCategory={selectedPart.item_category}
                projectParts={parts ?? []}
                onSelectPart={setSelectedPartId}
              />

              {/* Workflow (RASIC approval flow for the selected revision) */}
              {selectedRevisionId && (
                <RevisionWorkflowSection
                  revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                />
              )}

              {/* Quality / PPAP (articles only) */}
              {selectedRevisionId && selectedPart.item_category === 'article' && (
                <PPAPSection
                  revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                  revisionFiles={(revisionFiles ?? []).map((f) => ({ id: f.id, filename: f.filename }))}
                />
              )}

              {/* Multi-level BOM tree from the selected revision, plus where this part is used */}
              {selectedRevisionId && (
                <BomTreeSection partId={selectedPart.id} revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                  onOpenPart={(id) => { setSelectedPartId(id); setViewingFileId(null); setOpenDocId(null); }} />
              )}

              {/* BOM editor (anything we build ourselves, revision-scoped) */}
              {selectedPart.part_type !== 'purchased' && selectedRevisionId && (
                <PartBOMSection
                  partId={selectedPart.id}
                  revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                  locked={revisionLocked}
                  projectParts={parts ?? []}
                />
              )}

              {/* Revisions Section */}
              <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
                <h3 className="text-sm font-semibold text-slate-200 mb-3">Revisions</h3>
                {!partRevisions || partRevisions.length === 0 ? (
                  <p className="text-slate-500 text-sm">No revisions yet</p>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {partRevisions.map((rev) => (
                      <div
                        key={rev.id}
                        onClick={() => {
                          setSelectedRevisionId(rev.id);
                          setViewingFileId(null);
                          setOpenDocId(null);
                        }}
                        className={`p-3 rounded border cursor-pointer transition ${
                          rev.id === selectedRevisionId
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
            </div>
          ) : null}
        </div>
      </div>

      {/* Context Menu */}
      <ProjectContextMenu
        menu={contextMenu}
        onClose={() => setContextMenu(null)}
        onOpenDetails={(partId) => navigate(`/parts/${partId}`)}
        onViewChangelog={(partId) => setChangelogPartId(partId)}
      />

      {/* Changelog Modal */}
      {changelogPartId && <ChangelogModal partId={changelogPartId} onClose={() => setChangelogPartId(null)} />}

      {/* Add Part Modal */}
      <AddPartModal projectId={id} parts={parts} isOpen={showAddModal} onClose={() => setShowAddModal(false)} />
    </div>
  );
}
