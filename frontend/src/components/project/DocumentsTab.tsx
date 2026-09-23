/**
 * Documents tab: revision strip, document pane (drawing / 3D), grouped files,
 * uploads, and the customer data / customer package entry points.
 */
import { useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import client, { API_BASE_URL } from '../../api/client';
import Viewer3D from '../Viewer3D';
import UploadDialog from '../parts/UploadDialog';
import CustomerDataDialog, { type CustomerDataInput } from '../parts/CustomerDataDialog';
import CustomerPackageDialog from '../parts/CustomerPackageDialog';
import RevisionStrip from '../parts/RevisionStrip';
import DocumentPane, { type PaneDocument, type MirrorNotice } from '../parts/DocumentPane';
import RevisionFilesGrouped, { docKindFor } from '../parts/RevisionFilesGrouped';
import { revisionLabel } from '../parts/RevisionBadge';
import { apiErrorMessage } from '../../lib/apiError';
import { articleOf, type ProjectStructure } from '../../hooks/queries/useProjectStructure';
import { useAssemblyFiles, useRevisionFiles } from '../../hooks/queries/useProjectDetail';
import type { ArticleSelection } from '../../hooks/useArticleSelection';
import { LOCKED_REVISION_STATUSES, type Part, type Project } from './projectTypes';

export default function DocumentsTab({ projectId, project, parts, structure, sel, part }: {
  projectId: number;
  project: Project;
  parts: Part[] | undefined;
  structure: ProjectStructure | undefined;
  sel: ArticleSelection;
  part: Part;
}) {
  const queryClient = useQueryClient();
  const partRevisions = sel.partRevisions;
  const hasRevisions = !!partRevisions && partRevisions.length > 0;
  const { data: revisionFiles } = useRevisionFiles(sel.revisionId || 0);
  const article = articleOf(structure, part.id);
  const mirrorSource = article?.mirror_of ? articleOf(structure, article.mirror_of.part_id) : undefined;
  const mirrorFiles = useRevisionFiles(mirrorSource?.active_revision_id ?? 0);

  const isSubAssembly = part.part_type === 'sub_assembly';
  const { data: assemblyFiles } = useAssemblyFiles(isSubAssembly ? part.id : 0);
  const assemblyAvailable = isSubAssembly && (assemblyFiles?.length ?? 0) > 1;
  const assemblyActive = assemblyAvailable && sel.viewingFileId === null;
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

  const [showCustomerData, setShowCustomerData] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[] | null>(null);
  const [uploadDrag, setUploadDrag] = useState(false);

  const customerDataMutation = useMutation({
    mutationFn: async (v: CustomerDataInput) => {
      const res = await client.post(`/v1/parts/${part.id}/revisions/customer-data`, v);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Recorded ${data.revision_name}`);
      setShowCustomerData(false);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to record customer data'));
    },
  });

  const proposalMutation = useMutation({
    mutationFn: async (parentRevisionId: number) => {
      const res = await client.post(`/v1/parts/${part.id}/revisions/proposals`, { parent_revision_id: parentRevisionId });
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}`);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
      sel.selectRevision(data.id);
    },
    onError: (error: unknown) => {
      toast.error(apiErrorMessage(error, 'Failed to create proposal'));
    },
  });

  const afterUpload = (targetRevisionId: number) => {
    queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
    queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
    queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
    sel.setRevisionId(targetRevisionId);
  };

  const selectedRevision = partRevisions?.find((r) => r.id === sel.revisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const viewableFiles = revisionFiles?.filter((f) => f.has_viewer) ?? [];
  const viewingFile = viewableFiles.find((f) => f.id === sel.viewingFileId) ?? viewableFiles[0] ?? null;
  const viewerUrl = viewingFile
    ? `${API_BASE_URL}/v1/parts/revision-files/${viewingFile.id}/viewer`
    : null;

  const openDoc = revisionFiles?.find((f) => f.id === sel.openDocId) ?? null;
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

  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 overflow-hidden flex flex-col">
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
      {hasRevisions && (
        <div className="border-b border-slate-700 bg-slate-800/60">
          <RevisionStrip
            revisions={partRevisions!}
            selectedId={sel.revisionId}
            activeId={part.active_revision_id}
            onSelect={sel.selectRevision}
            onNewProposal={(majorId) => proposalMutation.mutate(majorId)}
          />
        </div>
      )}

      {showPackage && (
        <CustomerPackageDialog open assemblyId={part.id}
          projectParts={(parts ?? []).map((p) => ({ id: p.id, part_number: p.part_number, name: p.name }))}
          officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
          onClose={() => setShowPackage(false)}
          onDone={(r) => {
            toast.success(`Stored ${r.created.length} new, kept ${r.kept.length}`);
            setShowPackage(false);
            queryClient.invalidateQueries({ queryKey: ['part-revisions', part.id] });
            queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
            queryClient.invalidateQueries({ queryKey: ['bom-tree'] });
            queryClient.invalidateQueries({ queryKey: ['project-assemblies', projectId] });
            queryClient.invalidateQueries({ queryKey: ['project-structure', projectId] });
          }} />
      )}

      {!hasRevisions ? (
        <div className="p-6 text-center">
          {article?.mirror_of && (
            <div className="mb-4 text-left">
              <DocumentPane document={paneDoc} mirror={paneMirror} onOpenPart={sel.openPart}>
                <Viewer3D fileId={paneDoc?.fileId ?? null} viewerUrl={paneViewerUrl} />
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
          <DocumentPane document={paneDoc} mirror={paneMirror} onOpenPart={sel.openPart}>
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
                onClick={() => sel.setViewingFileId(null)}
                className="absolute top-2 right-2 z-10 px-2 py-1 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-200 text-xs font-medium"
              >
                ← Assembly view
              </button>
            )}
          </DocumentPane>
          {/* Files list + uploader */}
          <div className="p-2 bg-slate-700/50 space-y-1">
            <RevisionFilesGrouped
              files={revisionFiles ?? []}
              locked={revisionLocked}
              viewingFileId={viewingFile?.id ?? null}
              revisionName={revName}
              onView={(f) => { sel.setViewingFileId(f.id); sel.setOpenDocId(null); }}
              onOpen={(f) => sel.setOpenDocId(f.id)}
            />
            {!revisionLocked && sel.revisionId && (
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
              partId={part.id}
              currentRevision={{ id: selectedRevision.id, revision_name: selectedRevision.revision_name,
                customer_index: selectedRevision.customer_index, phase: selectedRevision.phase }}
              revisionNames={(partRevisions ?? []).map((r) => r.revision_name)}
              officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
              projectNaming={project.customer_naming ?? null}
              initialFiles={uploadFiles}
              onClose={(targetRevisionId) => {
                setUploadFiles(null);
                if (targetRevisionId != null) afterUpload(targetRevisionId);
              }}
              onDone={(targetRevisionId) => {
                setUploadFiles(null);
                afterUpload(targetRevisionId);
              }}
            />
          )}
        </>
      )}
    </div>
  );
}
