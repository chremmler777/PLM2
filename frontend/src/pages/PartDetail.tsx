/**
 * PartDetail - Show part and its revisions with full lifecycle support
 */

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

interface Revision {
  id: number;
  revision_name: string;
  phase: string;
  status: string;
  summary?: string;
  parent_revision_id?: number;
  created_by: number;
  created_at: string;
}

interface Part {
  id: number;
  part_number: string;
  name: string;
  part_type: string;
  data_classification: string;
  revisions: Revision[];
}

function getStatusColor(status: string) {
  switch (status) {
    case 'draft':
      return 'bg-gray-100 text-gray-800';
    case 'rejected':
      return 'bg-red-100 text-red-800';
    case 'archived':
      return 'bg-slate-100 text-slate-700';
    case 'approved':
      return 'bg-green-100 text-green-800';
    case 'frozen':
      return 'bg-blue-100 text-blue-800';
    default:
      return 'bg-yellow-100 text-yellow-800';
  }
}

function getPhaseColor(phase: string) {
  switch (phase) {
    case 'rfq_phase':
      return 'bg-blue-100 text-blue-700';
    case 'engineering':
      return 'bg-purple-100 text-purple-700';
    case 'freeze':
      return 'bg-orange-100 text-orange-700';
    case 'ecn':
      return 'bg-pink-100 text-pink-700';
    default:
      return 'bg-gray-100 text-gray-700';
  }
}

function canAdvance(proposal: Revision, allRevisions: Revision[]): boolean {
  // Can promote if: draft, OR approved but newer major version is rejected
  if (proposal.status === 'draft') return true;
  if (proposal.status === 'approved' && proposal.parent_revision_id) {
    // Check if parent's parent (the previous major) exists
    const parent = allRevisions.find((r) => r.id === proposal.parent_revision_id);
    if (!parent) return false;

    // Extract parent major (e.g., "RFQ2" from parent "RFQ2")
    const parentMajor = parent.revision_name.split('.')[0];
    const parentNum = parseInt(parentMajor.replace(/\D/g, ''));
    const phase = parent.phase;

    // Find newer major versions (e.g., RFQ3 when parent is RFQ2)
    const newerMajor = allRevisions.find(
      (r) =>
        r.phase === phase &&
        !r.parent_revision_id &&
        r.revision_name.match(/\D+/)?.[0] === parentMajor.match(/\D+/)?.[0] &&
        parseInt(r.revision_name.replace(/\D/g, '')) > parentNum
    );

    // Can re-promote if newer major is rejected
    return newerMajor ? newerMajor.status === 'rejected' : false;
  }
  return false;
}

function getLatestActiveRFQMajor(revisions: Revision[]): Revision | null {
  // Get the latest RFQ major version that is not rejected
  const rfqMajors = revisions.filter((r) => r.phase === 'rfq_phase' && !r.parent_revision_id);
  return rfqMajors
    .sort((a, b) => {
      const numA = parseInt(a.revision_name.replace(/\D/g, ''));
      const numB = parseInt(b.revision_name.replace(/\D/g, ''));
      return numB - numA;
    })
    .find((r) => r.status !== 'rejected') || null;
}

function getLatestEngineeringMajor(revisions: Revision[]): Revision | null {
  // Get the latest ENG major version
  const engMajors = revisions.filter((r) => r.phase === 'engineering' && !r.parent_revision_id);
  return engMajors
    .sort((a, b) => {
      const numA = parseInt(a.revision_name.replace(/\D/g, ''));
      const numB = parseInt(b.revision_name.replace(/\D/g, ''));
      return numB - numA;
    })[0] || null;
}

function getLatestFreezeMajor(revisions: Revision[]): Revision | null {
  // Get the latest freeze/IND major version
  const freezeMajors = revisions.filter((r) => r.phase === 'freeze' && !r.parent_revision_id);
  return freezeMajors
    .sort((a, b) => {
      const numA = parseInt(a.revision_name.replace(/\D/g, ''));
      const numB = parseInt(b.revision_name.replace(/\D/g, ''));
      return numB - numA;
    })[0] || null;
}

function getLatestProposalForParent(parentId: number, revisions: Revision[]): Revision | null {
  // Get the latest proposal under a major version
  const proposals = revisions.filter((r) => r.parent_revision_id === parentId);
  return proposals
    .sort((a, b) => {
      const numA = parseInt(a.revision_name.split('.')[1] || '0');
      const numB = parseInt(b.revision_name.split('.')[1] || '0');
      return numB - numA;
    })[0] || null;
}

function getActiveRevisionLevel(revisions: Revision[]): string {
  // Get the latest non-rejected major for current phase
  // Priority: Freeze > Engineering > RFQ
  const byPhase = {
    freeze: revisions.filter((r) => r.phase === 'freeze' && !r.parent_revision_id),
    engineering: revisions.filter((r) => r.phase === 'engineering' && !r.parent_revision_id),
    rfq_phase: revisions.filter((r) => r.phase === 'rfq_phase' && !r.parent_revision_id),
  };

  // Get latest non-rejected in each phase
  const getLatest = (arr: Revision[]) =>
    arr
      .sort((a, b) => parseInt(b.revision_name.replace(/\D/g, '')) - parseInt(a.revision_name.replace(/\D/g, '')))
      .find((r) => r.status !== 'rejected');

  const activeFreeze = getLatest(byPhase.freeze);
  if (activeFreeze) return `${activeFreeze.revision_name} (Active)`;

  const activeEng = getLatest(byPhase.engineering);
  if (activeEng) return `${activeEng.revision_name} (Active)`;

  const activeRfq = getLatest(byPhase.rfq_phase);
  if (activeRfq) return `${activeRfq.revision_name} (Active)`;

  return 'No active revision';
}

export default function PartDetail() {
  const { partId } = useParams<{ partId: string }>();
  const navigate = useNavigate();
  const [showProposalForm, setShowProposalForm] = useState<number | null>(null);
  const [proposalSummary, setProposalSummary] = useState('');
  const [showRejectDraftsModal, setShowRejectDraftsModal] = useState(false);
  const [showRejectFreezeDraftsModal, setShowRejectFreezeDraftsModal] = useState(false);

  // Fetch part
  const { data: part, isLoading, error: partError, refetch } = useQuery({
    queryKey: ['part', partId],
    queryFn: async () => {
      try {
        const response = await client.get(`/v1/parts/${partId}`);
        return response.data as Part;
      } catch (error) {
        console.error('Failed to load part:', error);
        return null;
      }
    },
  });

  // Create major RFQ mutation
  const createRfqMutation = useMutation({
    mutationFn: async (rejectDrafts: boolean = false) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/rfq`, {
        summary: 'New RFQ cycle',
        reject_drafts: rejectDrafts,
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('RFQ created!');
      setShowRejectDraftsModal(false);
      refetch();
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to create RFQ';

      // Check if error is due to draft proposals
      if (message.includes('draft proposals')) {
        setShowRejectDraftsModal(true);
      } else {
        toast.error(message);
      }
    },
  });

  // Create RFQ proposal mutation
  const createProposalMutation = useMutation({
    mutationFn: async (parentId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/rfq-proposal`, {
        parent_revision_id: parentId,
        summary: proposalSummary || 'RFQ proposal',
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('Proposal created!');
      setShowProposalForm(null);
      setProposalSummary('');
      refetch();
    },
    onError: () => {
      toast.error('Failed to create proposal');
    },
  });

  // Advance revision mutation
  const promoteRevisionMutation = useMutation({
    mutationFn: async (revisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${revisionId}/promote`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Advanced to ${data.revision_name}!`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to promote revision');
    },
  });

  // Reject revision mutation
  const rejectRevisionMutation = useMutation({
    mutationFn: async (revisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${revisionId}/reject`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Rejected ${data.revision_name}`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to reject revision');
    },
  });

  // Unreject revision mutation
  const unrejectRevisionMutation = useMutation({
    mutationFn: async (revisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${revisionId}/unreject`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Restored ${data.revision_name} to available`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to restore revision');
    },
  });

  // Transition to Engineering mutation
  const transitionToEngineeringMutation = useMutation({
    mutationFn: async (rfqRevisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${rfqRevisionId}/to-engineering`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}!`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to transition to engineering');
    },
  });

  // Create engineering proposal mutation
  const createEngineeringProposalMutation = useMutation({
    mutationFn: async (parentId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/engineering-proposal`, {
        parent_revision_id: parentId,
        summary: proposalSummary || 'Engineering proposal',
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('Engineering proposal created!');
      setShowProposalForm(null);
      setProposalSummary('');
      refetch();
    },
    onError: () => {
      toast.error('Failed to create engineering proposal');
    },
  });

  // Advance engineering proposal mutation
  const advanceEngineeringMutation = useMutation({
    mutationFn: async (revisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${revisionId}/advance-engineering`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Advanced to ${data.revision_name}!`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to advance engineering proposal');
    },
  });

  // Create engineering major mutation
  const createEngineeringMajorMutation = useMutation({
    mutationFn: async () => {
      const response = await client.post(`/v1/parts/${partId}/revisions/engineering`, {
        summary: 'New Engineering version',
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('Engineering version created!');
      refetch();
    },
    onError: () => {
      toast.error('Failed to create engineering version');
    },
  });

  // Transition to Freeze mutation
  const transitionToFreezeMutation = useMutation({
    mutationFn: async (engRevisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${engRevisionId}/to-freeze`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}!`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to transition to design freeze');
    },
  });

  // Create freeze proposal mutation
  const createFreezeProposalMutation = useMutation({
    mutationFn: async (parentId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/freeze-proposal`, {
        parent_revision_id: parentId,
        summary: 'New ECR',
      });
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}!`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to create freeze proposal');
    },
  });

  // Advance freeze proposal mutation
  const advanceFreezeMutation = useMutation({
    mutationFn: async (revisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${revisionId}/advance-freeze`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Advanced to ${data.revision_name}!`);
      refetch();
    },
    onError: () => {
      toast.error('Failed to advance freeze proposal');
    },
  });

  // Create freeze major mutation
  const createFreezeMajorMutation = useMutation({
    mutationFn: async (rejectDrafts: boolean = false) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/freeze`, {
        summary: 'New Freeze version',
        reject_drafts: rejectDrafts,
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('Freeze version created!');
      setShowRejectFreezeDraftsModal(false);
      refetch();
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to create freeze version';

      // Check if error is due to draft proposals
      if (message.includes('draft proposals')) {
        setShowRejectFreezeDraftsModal(true);
      } else {
        toast.error(message);
      }
    },
  });

  if (isLoading) {
    return <div className="p-8 text-center">Loading...</div>;
  }

  if (partError) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-50 border border-red-200 rounded-lg p-6">
            <h2 className="text-lg font-bold text-red-800 mb-2">Error loading part</h2>
            <p className="text-red-700">{(partError as any)?.message || 'Unknown error'}</p>
          </div>
        </div>
      </div>
    );
  }

  if (!part) {
    return (
      <div className="min-h-screen bg-gray-50 p-8">
        <div className="max-w-4xl mx-auto">
          <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-6">
            <h2 className="text-lg font-bold text-yellow-800">Part not found</h2>
            <p className="text-yellow-700">The requested part could not be loaded.</p>
          </div>
        </div>
      </div>
    );
  }

  // Group revisions by major version
  const majorVersions = part.revisions.reduce((acc: Record<string, Revision[]>, rev) => {
    const major = rev.revision_name.split('.')[0];
    if (!acc[major]) acc[major] = [];
    acc[major].push(rev);
    return acc;
  }, {});

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="mb-8">
          <button
            onClick={() => navigate('/dashboard')}
            className="mb-4 px-3 py-1 bg-gray-200 text-gray-900 rounded hover:bg-gray-300 text-sm"
          >
            ← Back
          </button>
          <div className="flex justify-between items-start">
            <div>
              <h1 className="text-4xl font-bold text-gray-900 mb-2">{part.part_number}</h1>
              <p className="text-gray-600 mb-2">{part.name}</p>
              <p className="text-sm font-semibold text-blue-700 bg-blue-50 px-3 py-1 rounded-md w-fit">
                {getActiveRevisionLevel(part.revisions)}
              </p>
            </div>
          </div>
        </div>

        {/* Part Info */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Part Information</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-sm text-gray-600">Type</div>
              <div className="font-medium text-gray-900 capitalize">{part.part_type}</div>
            </div>
            <div>
              <div className="text-sm text-gray-600">Classification</div>
              <div className="font-medium text-gray-900 capitalize">{part.data_classification}</div>
            </div>
          </div>
        </div>

        {/* Revisions */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
          <div className="flex justify-between items-center mb-6">
            <h2 className="text-xl font-bold text-gray-900">Revision History</h2>
          </div>

          {Object.keys(majorVersions).length === 0 ? (
            <div className="text-center py-12">
              <p className="text-gray-500 mb-4">No revisions yet.</p>
              <button
                onClick={() => createRfqMutation.mutate()}
                disabled={createRfqMutation.isPending}
                className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 font-medium"
              >
                {createRfqMutation.isPending ? 'Creating...' : '+ New RFQ'}
              </button>
            </div>
          ) : (
            <div className="space-y-6">
              {Object.keys(majorVersions)
                .sort((a, b) => {
                  // Get first revision to determine phase
                  const aRev = majorVersions[a][0];
                  const bRev = majorVersions[b][0];

                  // Phase priority: RFQ → ENG → IND
                  const phaseOrder = { rfq_phase: 0, engineering: 1, freeze: 2 };
                  const aPhase = phaseOrder[aRev.phase as keyof typeof phaseOrder] ?? 3;
                  const bPhase = phaseOrder[bRev.phase as keyof typeof phaseOrder] ?? 3;

                  if (aPhase !== bPhase) return aPhase - bPhase;

                  // Within same phase, sort by version number
                  const aNum = parseInt(a.replace(/\D/g, '')) || 0;
                  const bNum = parseInt(b.replace(/\D/g, '')) || 0;
                  return aNum - bNum;
                })
                .map((major) => {
                  const revisions = majorVersions[major];
                  const majorRev = revisions.find((r) => !r.parent_revision_id);
                  const proposals = revisions.filter((r) => r.parent_revision_id);

                  return (
                    <div
                      key={major}
                      className={`border rounded-lg p-4 ${
                        majorRev && majorRev.status !== 'rejected' && majorRev === getLatestActiveRFQMajor(part.revisions)
                          ? 'border-blue-400 bg-blue-50 shadow-md'
                          : majorRev && majorRev.phase === 'engineering' && majorRev === getLatestEngineeringMajor(part.revisions) && majorRev.status !== 'rejected'
                          ? 'border-purple-400 bg-purple-50 shadow-md'
                          : majorRev && majorRev.phase === 'freeze' && majorRev === getLatestFreezeMajor(part.revisions) && majorRev.status !== 'rejected'
                          ? 'border-orange-400 bg-orange-50 shadow-md'
                          : 'border-gray-200'
                      }`}
                    >
                      {/* Major Version */}
                      {majorRev && (
                        <div className="mb-4 pb-4 border-b border-gray-200">
                          <div className="flex justify-between items-start mb-2">
                            <div>
                              <div className="flex items-center gap-2 mb-1">
                                <div className="font-bold text-lg text-gray-900">{majorRev.revision_name}</div>
                                <span className={`text-xs px-2 py-1 rounded-full ${getPhaseColor(majorRev.phase)}`}>
                                  {majorRev.phase.replace('_phase', '').replace('_', ' ')}
                                </span>
                                <span className={`text-xs px-2 py-1 rounded-full ${getStatusColor(majorRev.status)}`}>
                                  {majorRev.status}
                                </span>
                              </div>
                              {majorRev.summary && <p className="text-sm text-gray-600">{majorRev.summary}</p>}
                              <p className="text-xs text-gray-500 mt-1">
                                Created at {new Date(majorRev.created_at).toLocaleString()}
                              </p>
                            </div>
                            <div className="flex gap-2">
                              {majorRev.status !== 'rejected' && majorRev === getLatestActiveRFQMajor(part.revisions) && majorRev.phase === 'rfq_phase' && (
                                <button
                                  onClick={() => setShowProposalForm(showProposalForm === majorRev.id ? null : majorRev.id)}
                                  className="px-3 py-1 bg-green-100 text-green-700 text-sm rounded hover:bg-green-200"
                                >
                                  + Sub
                                </button>
                              )}
                              {majorRev.status !== 'rejected' && majorRev === getLatestEngineeringMajor(part.revisions) && majorRev.phase === 'engineering' && (
                                <button
                                  onClick={() => setShowProposalForm(showProposalForm === majorRev.id ? null : majorRev.id)}
                                  className="px-3 py-1 bg-green-100 text-green-700 text-sm rounded hover:bg-green-200"
                                >
                                  + Sub
                                </button>
                              )}
                              {majorRev.status !== 'rejected' && majorRev === getLatestFreezeMajor(part.revisions) && majorRev.phase === 'freeze' && (
                                <button
                                  onClick={() => setShowProposalForm(showProposalForm === majorRev.id ? null : majorRev.id)}
                                  className="px-3 py-1 bg-green-100 text-green-700 text-sm rounded hover:bg-green-200"
                                >
                                  + Sub
                                </button>
                              )}
                              {majorRev.status !== 'rejected' &&
                                majorRev === getLatestActiveRFQMajor(part.revisions) &&
                                majorRev.phase === 'rfq_phase' && (
                                <button
                                  onClick={() => rejectRevisionMutation.mutate(majorRev.id)}
                                  disabled={rejectRevisionMutation.isPending}
                                  className="px-3 py-1 bg-red-100 text-red-700 text-sm rounded hover:bg-red-200 disabled:bg-gray-100"
                                >
                                  Reject
                                </button>
                              )}
                              {majorRev.status !== 'rejected' &&
                                majorRev === getLatestEngineeringMajor(part.revisions) &&
                                majorRev.phase === 'engineering' && (
                                <button
                                  onClick={() => rejectRevisionMutation.mutate(majorRev.id)}
                                  disabled={rejectRevisionMutation.isPending}
                                  className="px-3 py-1 bg-red-100 text-red-700 text-sm rounded hover:bg-red-200 disabled:bg-gray-100"
                                >
                                  Reject
                                </button>
                              )}
                              {majorRev.status !== 'rejected' &&
                                majorRev === getLatestFreezeMajor(part.revisions) &&
                                majorRev.phase === 'freeze' && (
                                <button
                                  onClick={() => rejectRevisionMutation.mutate(majorRev.id)}
                                  disabled={rejectRevisionMutation.isPending}
                                  className="px-3 py-1 bg-red-100 text-red-700 text-sm rounded hover:bg-red-200 disabled:bg-gray-100"
                                >
                                  Reject
                                </button>
                              )}
                              {majorRev.phase === 'rfq_phase' && majorRev === getLatestActiveRFQMajor(part.revisions) && majorRev.status === 'in_progress' && (
                                <button
                                  onClick={() => transitionToEngineeringMutation.mutate(majorRev.id)}
                                  disabled={transitionToEngineeringMutation.isPending}
                                  className="px-3 py-1 bg-blue-100 text-blue-700 text-sm rounded hover:bg-blue-200 disabled:bg-gray-100"
                                >
                                  {transitionToEngineeringMutation.isPending ? 'Awarding...' : '→ Engineering'}
                                </button>
                              )}
                              {majorRev.phase === 'engineering' && majorRev === getLatestEngineeringMajor(part.revisions) && majorRev.status === 'in_progress' && (
                                <button
                                  onClick={() => transitionToFreezeMutation.mutate(majorRev.id)}
                                  disabled={transitionToFreezeMutation.isPending}
                                  className="px-3 py-1 bg-purple-100 text-purple-700 text-sm rounded hover:bg-purple-200 disabled:bg-gray-100"
                                >
                                  {transitionToFreezeMutation.isPending ? 'Freezing...' : '→ Freeze'}
                                </button>
                              )}
                              {majorRev.phase === 'rfq_phase' && majorRev === getLatestActiveRFQMajor(part.revisions) && majorRev.status === 'in_progress' && (
                                <button
                                  onClick={() => createRfqMutation.mutate()}
                                  disabled={createRfqMutation.isPending}
                                  className="px-3 py-1 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:bg-gray-400"
                                >
                                  {createRfqMutation.isPending ? 'Creating...' : '+ New RFQ'}
                                </button>
                              )}
                              {majorRev.phase === 'engineering' && majorRev === getLatestEngineeringMajor(part.revisions) && majorRev.status === 'in_progress' && (
                                <button
                                  onClick={() => createEngineeringMajorMutation.mutate()}
                                  disabled={createEngineeringMajorMutation.isPending}
                                  className="px-3 py-1 bg-purple-600 text-white text-sm rounded hover:bg-purple-700 disabled:bg-gray-400"
                                >
                                  {createEngineeringMajorMutation.isPending ? 'Creating...' : '+ New ENG'}
                                </button>
                              )}
                              {majorRev.phase === 'freeze' && majorRev === getLatestFreezeMajor(part.revisions) && majorRev.status === 'in_progress' && (
                                <button
                                  onClick={() => createFreezeMajorMutation.mutate()}
                                  disabled={createFreezeMajorMutation.isPending}
                                  className="px-3 py-1 bg-orange-600 text-white text-sm rounded hover:bg-orange-700 disabled:bg-gray-400"
                                >
                                  {createFreezeMajorMutation.isPending ? 'Creating...' : '+ New IND'}
                                </button>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Proposals */}
                      {proposals.length > 0 && (
                        <div className="space-y-3 mb-4">
                          {proposals.map((proposal) => (
                            <div key={proposal.id} className="pl-4 border-l-2 border-gray-300">
                              <div className="flex justify-between items-start">
                                <div>
                                  <div className="flex items-center gap-2 mb-1">
                                    <div className="font-medium text-gray-900">{proposal.revision_name}</div>
                                    <span className={`text-xs px-2 py-1 rounded-full ${getStatusColor(proposal.status)}`}>
                                      {proposal.status}
                                    </span>
                                  </div>
                                  {proposal.summary && <p className="text-sm text-gray-600">{proposal.summary}</p>}
                                  <p className="text-xs text-gray-500 mt-1">
                                    Created at {new Date(proposal.created_at).toLocaleString()}
                                  </p>
                                </div>
                                <div className="flex gap-2">
                                  {canAdvance(proposal, part.revisions) && (
                                    <button
                                      onClick={() => {
                                        if (proposal.phase === 'engineering') {
                                          advanceEngineeringMutation.mutate(proposal.id);
                                        } else if (proposal.phase === 'freeze') {
                                          advanceFreezeMutation.mutate(proposal.id);
                                        } else {
                                          promoteRevisionMutation.mutate(proposal.id);
                                        }
                                      }}
                                      disabled={promoteRevisionMutation.isPending || advanceEngineeringMutation.isPending || advanceFreezeMutation.isPending}
                                      className="px-3 py-1 bg-purple-100 text-purple-700 text-sm rounded hover:bg-purple-200 disabled:bg-gray-100"
                                      title={proposal.status === 'approved' ? 'Re-advance this proposal (if newer version is rejected)' : 'Advance to next major version'}
                                    >
                                      Advance
                                    </button>
                                  )}
                                  {proposal.status !== 'rejected' && proposal.status !== 'archived' && (
                                    <button
                                      onClick={() => rejectRevisionMutation.mutate(proposal.id)}
                                      disabled={rejectRevisionMutation.isPending}
                                      className="px-3 py-1 bg-red-100 text-red-700 text-sm rounded hover:bg-red-200 disabled:bg-gray-100"
                                    >
                                      Reject
                                    </button>
                                  )}
                                  {(proposal.status === 'rejected' || proposal.status === 'archived') && (
                                    <button
                                      onClick={() => unrejectRevisionMutation.mutate(proposal.id)}
                                      disabled={unrejectRevisionMutation.isPending}
                                      className="px-3 py-1 bg-yellow-100 text-yellow-700 text-sm rounded hover:bg-yellow-200 disabled:bg-gray-100"
                                    >
                                      Unreject
                                    </button>
                                  )}
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Create Proposal Form */}
                      {showProposalForm === majorRev?.id && (
                        <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-200">
                          <textarea
                            value={proposalSummary}
                            onChange={(e) => setProposalSummary(e.target.value)}
                            placeholder="Proposal notes..."
                            className="w-full p-2 border border-gray-300 rounded text-sm mb-2"
                            rows={3}
                          />
                          <div className="flex gap-2">
                            <button
                              onClick={() => {
                                if (majorRev?.phase === 'engineering') {
                                  createEngineeringProposalMutation.mutate(majorRev!.id);
                                } else if (majorRev?.phase === 'freeze') {
                                  createFreezeProposalMutation.mutate(majorRev!.id);
                                } else {
                                  createProposalMutation.mutate(majorRev!.id);
                                }
                              }}
                              disabled={createProposalMutation.isPending || createEngineeringProposalMutation.isPending || createFreezeProposalMutation.isPending}
                              className="px-3 py-1 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:bg-gray-400"
                            >
                              Create Proposal
                            </button>
                            <button
                              onClick={() => {
                                setShowProposalForm(null);
                                setProposalSummary('');
                              }}
                              className="px-3 py-1 bg-gray-300 text-gray-900 text-sm rounded hover:bg-gray-400"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
            </div>
          )}
        </div>

        {/* Reject Drafts Confirmation Modal */}
        {showRejectDraftsModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-lg max-w-md w-full mx-4">
              <div className="p-6">
                <h3 className="text-lg font-bold text-gray-900 mb-2">
                  Reject Draft Proposals?
                </h3>
                <p className="text-gray-700 mb-6">
                  There are active draft proposals. Would you like to reject them and create a new RFQ cycle?
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setShowRejectDraftsModal(false)}
                    className="px-4 py-2 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => createRfqMutation.mutate(true)}
                    disabled={createRfqMutation.isPending}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 font-medium"
                  >
                    {createRfqMutation.isPending ? 'Creating...' : 'Reject & Create RFQ'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Reject Freeze Drafts Confirmation Modal */}
        {showRejectFreezeDraftsModal && (
          <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
            <div className="bg-white rounded-lg shadow-lg max-w-md w-full mx-4">
              <div className="p-6">
                <h3 className="text-lg font-bold text-gray-900 mb-2">
                  Reject Draft Proposals?
                </h3>
                <p className="text-gray-700 mb-6">
                  There are active draft proposals. Would you like to reject them and create a new IND cycle?
                </p>
                <div className="flex gap-3 justify-end">
                  <button
                    onClick={() => setShowRejectFreezeDraftsModal(false)}
                    className="px-4 py-2 bg-gray-200 text-gray-900 rounded-lg hover:bg-gray-300 font-medium"
                  >
                    Cancel
                  </button>
                  <button
                    onClick={() => createFreezeMajorMutation.mutate(true)}
                    disabled={createFreezeMajorMutation.isPending}
                    className="px-4 py-2 bg-orange-600 text-white rounded-lg hover:bg-orange-700 disabled:bg-gray-400 font-medium"
                  >
                    {createFreezeMajorMutation.isPending ? 'Creating...' : 'Reject & Create IND'}
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
