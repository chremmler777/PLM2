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

export default function PartDetail() {
  const { partId } = useParams<{ partId: string }>();
  const navigate = useNavigate();
  const [showProposalForm, setShowProposalForm] = useState<number | null>(null);
  const [proposalSummary, setProposalSummary] = useState('');

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
    mutationFn: async () => {
      const response = await client.post(`/v1/parts/${partId}/revisions/rfq`, {
        summary: 'New RFQ cycle',
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('RFQ created!');
      refetch();
    },
    onError: (error: any) => {
      const message = error.response?.data?.detail || 'Failed to create RFQ';
      toast.error(message);
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

  // Promote revision mutation
  const promoteRevisionMutation = useMutation({
    mutationFn: async (revisionId: number) => {
      const response = await client.post(`/v1/parts/${partId}/revisions/${revisionId}/promote`, {});
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(`Promoted to ${data.revision_name}!`);
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
          <h1 className="text-4xl font-bold text-gray-900 mb-2">{part.part_number}</h1>
          <p className="text-gray-600">{part.name}</p>
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
            <button
              onClick={() => createRfqMutation.mutate()}
              disabled={createRfqMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 text-sm font-medium"
            >
              {createRfqMutation.isPending ? 'Creating...' : '+ New RFQ'}
            </button>
          </div>

          {Object.keys(majorVersions).length === 0 ? (
            <div className="text-center py-8 text-gray-500">
              No revisions yet. Click "New RFQ" to start.
            </div>
          ) : (
            <div className="space-y-6">
              {Object.keys(majorVersions)
                .sort()
                .map((major) => {
                  const revisions = majorVersions[major];
                  const majorRev = revisions.find((r) => !r.parent_revision_id);
                  const proposals = revisions.filter((r) => r.parent_revision_id);

                  return (
                    <div key={major} className="border border-gray-200 rounded-lg p-4">
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
                              <button
                                onClick={() => setShowProposalForm(showProposalForm === majorRev.id ? null : majorRev.id)}
                                className="px-3 py-1 bg-green-100 text-green-700 text-sm rounded hover:bg-green-200"
                              >
                                + Proposal
                              </button>
                              {majorRev.status !== 'rejected' && (
                                <button
                                  onClick={() => rejectRevisionMutation.mutate(majorRev.id)}
                                  disabled={rejectRevisionMutation.isPending}
                                  className="px-3 py-1 bg-red-100 text-red-700 text-sm rounded hover:bg-red-200 disabled:bg-gray-100"
                                >
                                  Reject
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
                                <button
                                  onClick={() => promoteRevisionMutation.mutate(proposal.id)}
                                  disabled={promoteRevisionMutation.isPending}
                                  className="px-3 py-1 bg-purple-100 text-purple-700 text-sm rounded hover:bg-purple-200 disabled:bg-gray-100"
                                  title={proposal.status === 'rejected' ? 'Re-promote this proposal (creates new major version)' : 'Promote to next major version'}
                                >
                                  Promote
                                </button>
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
                              onClick={() => createProposalMutation.mutate(majorRev!.id)}
                              disabled={createProposalMutation.isPending}
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
      </div>
    </div>
  );
}
