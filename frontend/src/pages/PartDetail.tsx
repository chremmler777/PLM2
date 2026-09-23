/**
 * PartDetail - part header, lifecycle phase, and the revision timeline.
 * Majors come only from customer data (E<n> review, <n> official); minors
 * are our proposals.
 */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import RevisionTimeline, { type Revision } from '../components/parts/RevisionTimeline';
import CustomerDataDialog, { type CustomerDataInput } from '../components/parts/CustomerDataDialog';
import CustomerPackageDialog from '../components/parts/CustomerPackageDialog';
import BomTree, { type BomNode } from '../components/parts/BomTree';
import PartPaintCard from '../components/paint/PartPaintCard';
import { revisionLabel } from '../components/parts/RevisionBadge';
import { useAuth } from '../contexts/AuthContext';
import DocumentPane, { type PaneDocument } from '../components/parts/DocumentPane';
import RevisionFilesGrouped, { docKindFor } from '../components/parts/RevisionFilesGrouped';
import Viewer3D from '../components/Viewer3D';
import { API_BASE_URL } from '../api/client';
import type { RevisionFile } from './ProjectDetailPage';
import ToolDetail from './ToolDetail';

interface Part {
  id: number;
  part_number: string;
  customer_part_number?: string | null;
  tier1_part_number?: string | null;
  name: string;
  part_type: string;
  data_classification: string;
  item_category: string;
  project_id: number;
  active_revision_id?: number | null;
  lifecycle_phase: 'rfq' | 'nominated' | 'series';
  nominated_at?: string | null;
  sop_at?: string | null;
  revisions: Revision[];
  tool_cavities?: number | null;
  toolmaker_id?: number | null;
  tool_tonnage_class?: number | null;
  tool_cycle_time_s?: number | null;
}

interface WhereUsed {
  part_id: number;
  part_number: string;
  name: string;
  revision_name: string;
  customer_index?: string | null;
  quantity: number;
  unit: string;
  parents: WhereUsed[];
}

function flattenUsedIn(list: WhereUsed[], acc: WhereUsed[] = []): WhereUsed[] {
  for (const u of list) {
    if (!acc.some((a) => a.part_id === u.part_id)) acc.push(u);
    flattenUsedIn(u.parents, acc);
  }
  return acc;
}

const NEXT_PHASE: Record<Part['lifecycle_phase'], 'nominated' | 'series' | null> = {
  rfq: 'nominated', nominated: 'series', series: null,
};

function errMsg(error: unknown, fallback: string) {
  return (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || fallback;
}

export default function PartDetail() {
  const { partId } = useParams<{ partId: string }>();
  const navigate = useNavigate();
  const { isAdmin } = useAuth();
  const [showStartChange, setShowStartChange] = useState(false);
  const [showCustomerData, setShowCustomerData] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [promoting, setPromoting] = useState<Revision | null>(null);
  const [proposalParent, setProposalParent] = useState<number | null>(null);
  const [proposalSummary, setProposalSummary] = useState('');
  // null = not editing; '' = editing an empty value
  const [editingCustomerNumber, setEditingCustomerNumber] = useState<string | null>(null);
  const [editingTier1Number, setEditingTier1Number] = useState<string | null>(null);
  const [viewingId, setViewingId] = useState<number | null>(null);
  const [openId, setOpenId] = useState<number | null>(null);
  // PartDetail is routed (/parts/:partId) and React Router does not remount
  // it on param-only changes; in-page navigation (BOM node click, "Used in"
  // chips) keeps this instance alive, so a stale view/open selection would
  // otherwise leak into the newly loaded part's render.
  useEffect(() => {
    setViewingId(null);
    setOpenId(null);
  }, [partId]);

  const { data: part, isLoading, error: partError, refetch: refetchPart } = useQuery({
    queryKey: ['part', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}`)).data as Part,
  });
  const { data: bomTree } = useQuery({
    queryKey: ['bom-tree', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/bom-tree`)).data as BomNode,
    enabled: !!part && part.item_category !== 'tool',
  });
  const queryClient = useQueryClient();
  const refetch = () => {
    refetchPart();
    queryClient.invalidateQueries({ queryKey: ['bom-tree', partId] });
  };
  const { data: usedIn } = useQuery({
    queryKey: ['where-used', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/where-used`)).data as WhereUsed[],
    enabled: !!part && part.item_category !== 'tool',
  });
  const { data: projectParts } = useQuery({
    queryKey: ['parts', part?.project_id],
    queryFn: async () => (await client.get(`/v1/parts/project/${part!.project_id}`)).data as { id: number; part_number: string; name: string }[],
    enabled: !!part?.project_id,
  });
  const activeRevision = part?.revisions.find((r) => r.id === part.active_revision_id);
  const { data: files } = useQuery({
    queryKey: ['revision-files', activeRevision?.id],
    queryFn: async () => (await client.get(`/v1/parts/revisions/${activeRevision!.id}/files`)).data as RevisionFile[],
    enabled: !!activeRevision,
  });

  const customerData = useMutation({
    mutationFn: (v: CustomerDataInput) => client.post(`/v1/parts/${partId}/revisions/customer-data`, v),
    onSuccess: (res) => { toast.success(`Recorded ${res.data.revision_name}`); setShowCustomerData(false); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not record customer data')),
  });
  const saveCustomerNumber = useMutation({
    mutationFn: (v: string) => client.put(`/v1/parts/${partId}`, { customer_part_number: v.trim() || null }),
    onSuccess: () => { toast.success('Customer part number saved'); setEditingCustomerNumber(null); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not save the customer part number')),
  });
  const saveTier1Number = useMutation({
    mutationFn: (v: string) => client.put(`/v1/parts/${partId}`, { tier1_part_number: v.trim() || null }),
    onSuccess: () => { toast.success('Tier 1 part number saved'); setEditingTier1Number(null); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not save the tier 1 part number')),
  });
  const promote = useMutation({
    mutationFn: ({ id, v }: { id: number; v: CustomerDataInput }) =>
      client.post(`/v1/parts/${partId}/revisions/${id}/promote`, { statement: v.statement, received_at: v.received_at, customer_index: v.customer_index, major: v.major }),
    onSuccess: (res) => { toast.success(`Now ${res.data.revision_name}`); setPromoting(null); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not promote')),
  });
  const proposal = useMutation({
    mutationFn: (parent_revision_id: number) =>
      client.post(`/v1/parts/${partId}/revisions/proposals`, { parent_revision_id, summary: proposalSummary || undefined }),
    onSuccess: (res) => { toast.success(`Created ${res.data.revision_name}`); setProposalParent(null); setProposalSummary(''); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not create proposal')),
  });
  const reject = useMutation({
    mutationFn: (id: number) => client.post(`/v1/parts/${partId}/revisions/${id}/reject`, {}),
    onSuccess: () => refetch(), onError: (e) => toast.error(errMsg(e, 'Could not reject')),
  });
  const unreject = useMutation({
    mutationFn: (id: number) => client.post(`/v1/parts/${partId}/revisions/${id}/unreject`, {}),
    onSuccess: () => refetch(), onError: (e) => toast.error(errMsg(e, 'Could not restore')),
  });
  const phase = useMutation({
    mutationFn: (next: 'nominated' | 'series') =>
      client.post(`/v1/parts/${partId}/lifecycle-phase`, { phase: next, effective: new Date().toISOString().slice(0, 10) }),
    onSuccess: (res) => { toast.success(`Part is now ${res.data.lifecycle_phase}`); refetch(); },
    onError: (e) => toast.error(errMsg(e, 'Could not change phase')),
  });

  if (isLoading) return <div className="p-8 text-center">Loading...</div>;
  if (partError || !part) {
    return (
      <div className="min-h-screen bg-slate-900 p-8">
        <div className="max-w-4xl mx-auto bg-red-50 border border-red-200 rounded-lg p-6">
          <h2 className="text-lg font-bold text-red-800 mb-2">Part not found</h2>
          <p className="text-red-700">{(partError as Error | null)?.message || 'The requested part could not be loaded.'}</p>
        </div>
      </div>
    );
  }

  if (part.item_category === 'tool') {
    return (
      <ToolDetail
        part={{
          id: part.id, part_number: part.part_number, name: part.name, part_type: part.part_type,
          project_id: part.project_id, item_category: part.item_category, lifecycle_phase: part.lifecycle_phase,
          tool_cavities: part.tool_cavities ?? null, toolmaker_id: part.toolmaker_id ?? null,
          tool_tonnage_class: part.tool_tonnage_class ?? null, tool_cycle_time_s: part.tool_cycle_time_s ?? null,
        }}
        onOpenPart={(id) => navigate(`/parts/${id}`)}
        onBack={() => navigate('/dashboard')}
      />
    );
  }

  const hasOfficial = part.revisions.some((r) => r.phase === 'official' && !r.parent_revision_id);
  const nextPhase = NEXT_PHASE[part.lifecycle_phase];
  const majorsOf = (revs: { revision_name: string }[]) => revs.filter((r) => !r.revision_name.includes('.'));
  const nextMajor = {
    review: Math.max(0, ...majorsOf(part.revisions).filter((r) => r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name.slice(1), 10))) + 1,
    official: Math.max(0, ...majorsOf(part.revisions).filter((r) => !r.revision_name.startsWith('E')).map((r) => parseInt(r.revision_name, 10))) + 1,
  };

  const viewableFiles = files?.filter((f) => f.has_viewer) ?? [];
  const viewingFile = viewableFiles.find((f) => f.id === viewingId) ?? null;
  const openDoc = files?.find((f) => f.id === openId) ?? null;
  const revName = activeRevision ? revisionLabel(activeRevision.revision_name, activeRevision.customer_index) : '';
  let paneDoc: PaneDocument | null = null;
  if (openDoc) {
    const kind = docKindFor(openDoc);
    if (kind) paneDoc = { fileId: openDoc.id, filename: openDoc.filename, kind, revisionName: revName };
  } else if (viewingFile) paneDoc = { fileId: viewingFile.id, filename: viewingFile.filename, kind: '3d', revisionName: revName };

  return (
    <div className="min-h-screen bg-slate-900 p-8">
      <div className="max-w-5xl mx-auto">
        <div className="mb-8">
          <button onClick={() => navigate('/dashboard')}
            className="mb-4 px-3 py-1 bg-slate-700 text-slate-100 rounded hover:bg-slate-600 text-sm">← Back</button>
          <div className="flex justify-between items-start gap-4">
            <div>
              <h1 className="text-4xl font-bold text-slate-100 mb-1">{part.part_number}</h1>
              {editingCustomerNumber === null ? (
                <button data-testid="edit-customer-part-number" title="Edit the customer part number"
                  onClick={() => setEditingCustomerNumber(part.customer_part_number ?? '')}
                  className="block text-slate-400 font-mono text-sm mb-1 hover:text-slate-200">
                  {part.customer_part_number || '+ customer part number'}
                </button>
              ) : (
                <div className="flex items-center gap-2 mb-1">
                  <input data-testid="customer-part-number-input" autoFocus value={editingCustomerNumber}
                    onChange={(e) => setEditingCustomerNumber(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveCustomerNumber.mutate(editingCustomerNumber);
                      if (e.key === 'Escape') setEditingCustomerNumber(null);
                    }}
                    placeholder="customer part number"
                    className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 font-mono text-sm" />
                  <button data-testid="save-customer-part-number" disabled={saveCustomerNumber.isPending}
                    onClick={() => saveCustomerNumber.mutate(editingCustomerNumber)}
                    className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
                  <button onClick={() => setEditingCustomerNumber(null)}
                    className="text-sm px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
                </div>
              )}
              {editingTier1Number === null ? (
                <button data-testid="edit-tier1-part-number" title="Edit the Tier 1 part number (the Tier 1's own number when we are Tier 2; the customer number stays the OEM number)"
                  onClick={() => setEditingTier1Number(part.tier1_part_number ?? '')}
                  className="block text-slate-400 font-mono text-sm mb-1 hover:text-slate-200">
                  {part.tier1_part_number ? `Tier 1 ${part.tier1_part_number}` : '+ tier 1 part number'}
                </button>
              ) : (
                <div className="flex items-center gap-2 mb-1">
                  <input data-testid="tier1-part-number-input" autoFocus value={editingTier1Number}
                    onChange={(e) => setEditingTier1Number(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveTier1Number.mutate(editingTier1Number);
                      if (e.key === 'Escape') setEditingTier1Number(null);
                    }}
                    placeholder="tier 1 part number"
                    className="bg-slate-800 border border-slate-600 rounded px-2 py-1 text-slate-100 font-mono text-sm" />
                  <button data-testid="save-tier1-part-number" disabled={saveTier1Number.isPending}
                    onClick={() => saveTier1Number.mutate(editingTier1Number)}
                    className="text-sm px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white">Save</button>
                  <button onClick={() => setEditingTier1Number(null)}
                    className="text-sm px-2 py-1 rounded bg-slate-700 hover:bg-slate-600 text-slate-100">Cancel</button>
                </div>
              )}
              <p className="text-slate-300 mb-2">{part.name}</p>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-sm font-semibold text-blue-300 bg-blue-900 px-3 py-1 rounded-md">
                  {activeRevision ? `${revisionLabel(activeRevision.revision_name, activeRevision.customer_index)} (active)` : 'no customer data yet'}
                </span>
                <span data-testid="lifecycle-phase" className="text-sm text-slate-200 bg-slate-700 px-3 py-1 rounded-md capitalize">
                  {part.lifecycle_phase}{part.nominated_at ? ` · nominated ${part.nominated_at}` : ''}{part.sop_at ? ` · SOP ${part.sop_at}` : ''}
                </span>
                {isAdmin && nextPhase && (
                  <button onClick={() => phase.mutate(nextPhase)} disabled={phase.isPending}
                    className="text-sm px-3 py-1 rounded-md bg-slate-700 text-slate-100 hover:bg-slate-600">
                    Mark {nextPhase}
                  </button>
                )}
              </div>
            </div>
            <div className="flex gap-2">
              <button onClick={() => setShowCustomerData(true)}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium">
                + Customer data
              </button>
              <button onClick={() => setShowPackage(true)}
                className="px-4 py-2 rounded-lg bg-blue-700 hover:bg-blue-600 text-white text-sm font-medium">+ Customer package</button>
              <StartChangeButton label="Start change request" onClick={() => setShowStartChange(true)}
                className="px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
            </div>
          </div>
        </div>

        {showStartChange && (
          <StartChangeModal open onClose={() => setShowStartChange(false)}
            prefill={{ projectId: part.project_id, part: { id: part.id, part_number: part.part_number, name: part.name, item_category: part.item_category } }} />
        )}

        {showCustomerData && (
          <CustomerDataDialog open title="Customer data received" officialOnly={hasOfficial} nextMajor={nextMajor}
            pending={customerData.isPending} onClose={() => setShowCustomerData(false)} onSubmit={(v) => customerData.mutate(v)} />
        )}

        {showPackage && (
          <CustomerPackageDialog open assemblyId={part.id} projectParts={projectParts ?? []} officialOnly={hasOfficial}
            onClose={() => setShowPackage(false)}
            onDone={(r) => { toast.success(`Stored ${r.created.length} new, kept ${r.kept.length}`); setShowPackage(false); refetch();
              queryClient.invalidateQueries({ queryKey: ['where-used', partId] }); }} />
        )}

        {promoting && (
          <CustomerDataDialog open title={`Customer adopted ${promoting.revision_name} as…`} officialOnly={hasOfficial} nextMajor={nextMajor}
            pending={promote.isPending} onClose={() => setPromoting(null)} onSubmit={(v) => promote.mutate({ id: promoting.id, v })} />
        )}

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
          <h2 className="text-xl font-bold text-slate-100 mb-4">Part Information</h2>
          <div className="grid grid-cols-2 gap-4">
            <div><div className="text-sm text-slate-400">Type</div><div className="font-medium text-slate-100 capitalize">{part.part_type}</div></div>
            <div><div className="text-sm text-slate-400">Classification</div><div className="font-medium text-slate-100 capitalize">{part.data_classification}</div></div>
          </div>
        </div>

        <PartPaintCard key={part.id} partId={part.id} />

        {usedIn && usedIn.length > 0 && (
          <div data-testid="used-in" className="bg-slate-800 rounded-lg border border-slate-700 p-4 mb-8 flex items-center gap-2 flex-wrap text-sm">
            <span className="text-slate-400">Used in</span>
            {flattenUsedIn(usedIn).map((u) => (
              <button key={u.part_id} onClick={() => navigate(`/parts/${u.part_id}`)}
                className="px-2 py-0.5 rounded bg-slate-700 text-slate-100 hover:bg-slate-600 font-mono">
                {u.part_number} <span className="text-slate-400 font-sans">{revisionLabel(u.revision_name, u.customer_index)}</span>
              </button>
            ))}
          </div>
        )}

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
          <h2 className="text-xl font-bold text-slate-100 mb-4">
            Bill of materials{bomTree?.revision_name ? <span className="text-slate-400 font-normal text-base"> · {revisionLabel(bomTree.revision_name, bomTree.customer_index)}</span> : null}
          </h2>
          {bomTree ? <BomTree tree={bomTree} onOpenPart={(id) => navigate(`/parts/${id}`)} /> : <p className="text-slate-400 text-sm">Loading…</p>}
        </div>

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
          <h2 className="text-lg font-semibold text-slate-100 mb-3">Files · {activeRevision ? revisionLabel(activeRevision.revision_name, activeRevision.customer_index) : 'no active revision'}</h2>
          <DocumentPane document={paneDoc}>
            {paneDoc?.kind === '3d' && <Viewer3D fileId={paneDoc.fileId} viewerUrl={`${API_BASE_URL}/v1/parts/revision-files/${paneDoc.fileId}/viewer`} />}
          </DocumentPane>
          <div className="mt-3">
            <RevisionFilesGrouped files={files ?? []} locked={true} viewingFileId={viewingId} revisionName={activeRevision?.revision_name ?? ''}
              onView={(f) => { setViewingId(f.id); setOpenId(null); }} onOpen={(f) => setOpenId(f.id)} />
          </div>
        </div>

        <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 mb-8">
          <h2 className="text-xl font-bold text-slate-100 mb-6">Revisions</h2>
          <RevisionTimeline revisions={part.revisions} activeRevisionId={part.active_revision_id}
            onNewProposal={(id) => setProposalParent(id)} onPromote={(r) => setPromoting(r)}
            onReject={(id) => reject.mutate(id)} onUnreject={(id) => unreject.mutate(id)} />

          {proposalParent !== null && (
            <div className="mt-4 p-4 bg-slate-900 rounded-lg border border-slate-700">
              <textarea value={proposalSummary} onChange={(e) => setProposalSummary(e.target.value)} rows={3}
                placeholder="What are we changing in this proposal?"
                className="w-full p-2 border border-slate-700 rounded text-sm mb-2 bg-slate-800 text-slate-100" />
              <div className="flex gap-2">
                <button onClick={() => proposal.mutate(proposalParent)} disabled={proposal.isPending}
                  className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:bg-slate-600">Create proposal</button>
                <button onClick={() => { setProposalParent(null); setProposalSummary(''); }}
                  className="px-3 py-1 bg-slate-700 text-slate-100 text-sm rounded hover:bg-slate-600">Cancel</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
