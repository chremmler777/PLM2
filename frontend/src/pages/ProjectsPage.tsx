/**
 * ProjectsPage - List all projects with ability to create new ones
 */
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';

interface Project {
  id: number;
  name: string;
  code: string;
  description: string | null;
  status: string;
  plant_id: number;
}

interface Plant {
  id: number;
  name: string;
  code: string;
  location: string;
  is_active: boolean;
}

function useProjects() {
  return useQuery<Project[]>({
    queryKey: ['projects'],
    queryFn: async () => {
      const res = await client.get('/v1/plants/projects');
      return res.data;
    },
  });
}

function usePlants() {
  return useQuery<Plant[]>({
    queryKey: ['plants'],
    queryFn: async () => {
      const res = await client.get('/v1/plants');
      return res.data;
    },
  });
}

function AddProjectModal({
  isOpen,
  onClose,
  plants,
}: {
  isOpen: boolean;
  onClose: () => void;
  plants: Plant[] | undefined;
}) {
  const queryClient = useQueryClient();
  const [formData, setFormData] = useState({
    name: '',
    code: '',
    description: '',
    plant_id: '',
  });

  const createMutation = useMutation({
    mutationFn: async (data: typeof formData) => {
      const res = await client.post('/v1/plants/projects', {
        name: data.name,
        code: data.code,
        description: data.description || null,
        plant_id: parseInt(data.plant_id, 10),
      });
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setFormData({ name: '', code: '', description: '', plant_id: '' });
      onClose();
    },
  });

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Create New Project</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Project Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., Test Project"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Project Number *</label>
            <input
              type="text"
              value={formData.code}
              onChange={(e) => setFormData({ ...formData, code: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., PRJ-001"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Plant *</label>
            <select
              value={formData.plant_id}
              onChange={(e) => setFormData({ ...formData, plant_id: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            >
              <option value="">Select a plant</option>
              {(plants ?? []).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.code})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="Optional description"
              rows={3}
            />
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button
            onClick={onClose}
            className="flex-1 px-4 py-2 rounded border border-slate-600 text-slate-300 hover:bg-slate-700 text-sm font-medium"
          >
            Cancel
          </button>
          <button
            onClick={() => createMutation.mutate(formData)}
            disabled={createMutation.isPending || !formData.name || !formData.code || !formData.plant_id}
            className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
          >
            {createMutation.isPending ? 'Creating...' : 'Create Project'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function ProjectsPage() {
  const navigate = useNavigate();
  const [showAddModal, setShowAddModal] = useState(false);
  const { data: projects, isLoading } = useProjects();
  const { data: plants } = usePlants();

  return (
    <div className="p-6">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-slate-100">Projects</h1>
          <p className="text-slate-400 text-sm mt-1">Select a project to view parts and revisions</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
        >
          + New Project
        </button>
      </div>

      {isLoading ? (
        <div className="text-slate-400">Loading projects...</div>
      ) : (projects ?? []).length === 0 ? (
        <div className="text-slate-500 text-sm bg-slate-800 border border-slate-700 rounded-lg p-4">
          <p className="mb-2">No projects yet. Create your first project to get started.</p>
          <button
            onClick={() => setShowAddModal(true)}
            className="text-blue-400 hover:text-blue-300 text-sm font-medium"
          >
            Create Project
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {(projects ?? []).map((p) => (
            <button
              key={p.id}
              onClick={() => navigate(`/projects/${p.id}`)}
              className="text-left p-4 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg transition"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-slate-100">{p.name}</h3>
                  <p className="text-sm text-slate-400 mt-1">{p.code}</p>
                  {p.description && <p className="text-sm text-slate-300 mt-1">{p.description}</p>}
                </div>
                <span
                  className={`px-3 py-1 rounded-full text-xs font-medium ${
                    p.status === 'active' ? 'bg-green-900/60 text-green-300' : 'bg-slate-700 text-slate-400'
                  }`}
                >
                  {p.status}
                </span>
              </div>
            </button>
          ))}
        </div>
      )}

      <AddProjectModal isOpen={showAddModal} onClose={() => setShowAddModal(false)} plants={plants} />
    </div>
  );
}
