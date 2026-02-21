/**
 * PartDetail - Show part and its revisions
 */

import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation } from '@tanstack/react-query';
import client from '../api/client';
import { toast } from 'sonner';

export default function PartDetail() {
  const { partId } = useParams<{ partId: string }>();
  const navigate = useNavigate();

  console.log('PartDetail rendering with partId:', partId);

  // Fetch part
  const { data: part, isLoading, error: partError } = useQuery({
    queryKey: ['part', partId],
    queryFn: async () => {
      try {
        console.log(`Fetching /v1/parts/${partId}`);
        const response = await client.get(`/v1/parts/${partId}`);
        console.log('Part response:', response.data);
        return response.data;
      } catch (error) {
        console.error('Failed to load part:', error);
        return null;
      }
    },
  });

  // Fetch revisions
  const { data: revisions, refetch } = useQuery({
    queryKey: ['revisions', partId],
    queryFn: async () => {
      try {
        const response = await client.get(`/v1/parts/${partId}/revisions`);
        return response.data;
      } catch (error) {
        console.error('Failed to load revisions:', error);
        return [];
      }
    },
  });

  // Create RFQ mutation
  const createRfqMutation = useMutation({
    mutationFn: async () => {
      const response = await client.post(`/v1/parts/${partId}/revisions/rfq`, {
        revision_number: 1,
        summary: 'First RFQ',
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('RFQ created!');
      refetch();
    },
    onError: (error: any) => {
      toast.error('Failed to create RFQ');
    },
  });

  if (isLoading) {
    return <div className="p-8 text-center">Loading...</div>;
  }

  if (partError) {
    console.error('Part error:', partError);
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

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-4xl mx-auto">
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
            {part.supplier && (
              <div>
                <div className="text-sm text-gray-600">Supplier</div>
                <div className="font-medium text-gray-900">{part.supplier}</div>
              </div>
            )}
            {part.description && (
              <div className="col-span-2">
                <div className="text-sm text-gray-600">Description</div>
                <div className="font-medium text-gray-900">{part.description}</div>
              </div>
            )}
          </div>
        </div>

        {/* Revisions */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-xl font-bold text-gray-900">Revisions</h2>
            <button
              onClick={() => createRfqMutation.mutate()}
              disabled={createRfqMutation.isPending}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 text-sm font-medium"
            >
              {createRfqMutation.isPending ? 'Creating...' : '+ Create RFQ'}
            </button>
          </div>

          {revisions && revisions.length > 0 ? (
            <div className="space-y-2">
              {revisions.map((rev: any) => (
                <div key={rev.id} className="p-4 border border-gray-200 rounded-lg">
                  <div className="flex justify-between items-start mb-2">
                    <div className="font-bold text-gray-900">{rev.revision_name}</div>
                    <div className="text-xs bg-blue-100 text-blue-800 px-2 py-1 rounded-full capitalize">
                      {rev.phase.replace('_phase', '').replace('_', ' ')}
                    </div>
                  </div>
                  <div className="text-sm text-gray-600">{rev.summary}</div>
                  <div className="text-xs text-gray-500 mt-2">Status: {rev.status}</div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No revisions yet. Create an RFQ to start.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
