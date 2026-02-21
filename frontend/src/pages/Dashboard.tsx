/**
 * Dashboard - Simple landing page
 * Shows Part creation and workflow for testing
 */

import { useState } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import client from '../api/client';
import { toast } from 'sonner';

export default function Dashboard() {
  const navigate = useNavigate();
  const [projectId] = useState(1);
  const [formData, setFormData] = useState({
    part_number: '',
    name: '',
    part_type: 'purchased',
  });

  // Fetch parts
  const { data: parts, refetch } = useQuery({
    queryKey: ['parts', projectId],
    queryFn: async () => {
      try {
        const response = await client.get(`/v1/parts/project/${projectId}`);
        return response.data;
      } catch (error) {
        console.error('Failed to load parts:', error);
        return [];
      }
    },
  });

  // Create part mutation
  const createPartMutation = useMutation({
    mutationFn: async (data: any) => {
      const response = await client.post('/v1/parts', {
        project_id: projectId,
        ...data,
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success('Part created!');
      setFormData({ part_number: '', name: '', part_type: 'purchased' });
      refetch();
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to create part');
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.part_number || !formData.name) {
      toast.error('Fill in all fields');
      return;
    }
    createPartMutation.mutate(formData);
  };

  return (
    <div className="min-h-screen bg-gray-50 p-8">
      <div className="max-w-2xl mx-auto">
        <h1 className="text-4xl font-bold text-gray-900 mb-2">PLM System</h1>
        <p className="text-gray-600 mb-8">Create parts and manage revisions</p>

        {/* Create Part Form */}
        <div className="bg-white rounded-lg border border-gray-200 p-6 mb-8">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Create New Part</h2>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Part Number (e.g., PA-001)
              </label>
              <input
                type="text"
                value={formData.part_number}
                onChange={(e) => setFormData({ ...formData, part_number: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="PA-001"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Part Name
              </label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Main Housing"
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Type
              </label>
              <select
                value={formData.part_type}
                onChange={(e) => setFormData({ ...formData, part_type: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="purchased">Purchased Part</option>
                <option value="internal_mfg">Internal Manufacturing</option>
                <option value="sub_assembly">Sub-Assembly</option>
              </select>
            </div>

            <button
              type="submit"
              disabled={createPartMutation.isPending}
              className="w-full px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-400 font-medium"
            >
              {createPartMutation.isPending ? 'Creating...' : 'Create Part'}
            </button>
          </form>
        </div>

        {/* Parts List */}
        <div className="bg-white rounded-lg border border-gray-200 p-6">
          <h2 className="text-xl font-bold text-gray-900 mb-4">Parts in Project</h2>
          {parts && parts.length > 0 ? (
            <div className="space-y-2">
              {parts.map((part: any) => (
                <button
                  key={part.id}
                  onClick={() => navigate(`/parts/${part.id}`)}
                  className="w-full text-left px-4 py-3 rounded-lg border border-gray-200 bg-gray-50 hover:bg-blue-50 hover:border-blue-300 cursor-pointer transition"
                >
                  <div className="font-bold text-gray-900">{part.part_number}</div>
                  <div className="text-sm text-gray-600">{part.name}</div>
                  <div className="text-xs text-gray-500 mt-1">Type: {part.part_type}</div>
                </button>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-gray-500">
              No parts yet. Create one above.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
