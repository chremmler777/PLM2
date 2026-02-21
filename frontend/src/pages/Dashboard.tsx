/**
 * Dashboard - Organization hierarchy navigator
 * Shows Plant → Projects → Parts structure
 */

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { client } from '../api/client';
import { LoadingSkeleton } from '../components/common/LoadingSkeleton';
import { toast } from 'sonner';

interface Plant {
  id: number;
  name: string;
  code: string;
  location?: string;
  is_active: boolean;
}

interface Project {
  id: number;
  name: string;
  code: string;
  description?: string;
  status: string;
  plant_id: number;
}

interface Part {
  id: number;
  part_number: string;
  name: string;
  part_type: string;
  project_id: number;
}

export default function Dashboard() {
  const [selectedPlantId, setSelectedPlantId] = useState<number | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);

  // Fetch plants
  const { data: plants, isLoading: plantsLoading } = useQuery({
    queryKey: ['plants'],
    queryFn: async () => {
      try {
        const response = await client.get('/v1/plants');
        return response.data as Plant[];
      } catch (error) {
        toast.error('Failed to load plants');
        return [];
      }
    },
  });

  // Fetch projects for selected plant
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ['projects', selectedPlantId],
    queryFn: async () => {
      if (!selectedPlantId) return [];
      try {
        const response = await client.get(`/v1/plants/${selectedPlantId}/projects`);
        return response.data as Project[];
      } catch (error) {
        toast.error('Failed to load projects');
        return [];
      }
    },
    enabled: !!selectedPlantId,
  });

  // Fetch parts for selected project
  const { data: parts, isLoading: partsLoading } = useQuery({
    queryKey: ['parts', selectedProjectId],
    queryFn: async () => {
      if (!selectedProjectId) return [];
      try {
        const response = await client.get(`/v1/parts/project/${selectedProjectId}`);
        return response.data as Part[];
      } catch (error) {
        toast.error('Failed to load parts');
        return [];
      }
    },
    enabled: !!selectedProjectId,
  });

  const selectedPlant = plants?.find(p => p.id === selectedPlantId);
  const selectedProject = projects?.find(p => p.id === selectedProjectId);

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-6 py-6">
          <h1 className="text-3xl font-bold text-gray-900">PLM Dashboard</h1>
          <p className="text-gray-600 mt-2">Navigate through Plant → Projects → Parts</p>
        </div>
      </div>

      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="grid grid-cols-3 gap-6">
          {/* Plants Column */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="bg-blue-50 px-6 py-4 border-b border-gray-200">
              <h2 className="font-semibold text-gray-900">Plants</h2>
              <p className="text-sm text-gray-600">Select a manufacturing facility</p>
            </div>

            <div className="p-4">
              {plantsLoading ? (
                <LoadingSkeleton count={3} />
              ) : plants && plants.length > 0 ? (
                <div className="space-y-2">
                  {plants.map(plant => (
                    <button
                      key={plant.id}
                      onClick={() => {
                        setSelectedPlantId(plant.id);
                        setSelectedProjectId(null); // Reset projects when plant changes
                      }}
                      className={`w-full text-left px-4 py-3 rounded-lg border-2 transition ${
                        selectedPlantId === plant.id
                          ? 'border-blue-500 bg-blue-50'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      <div className="font-medium text-gray-900">{plant.name}</div>
                      <div className="text-sm text-gray-500">{plant.code}</div>
                      {plant.location && (
                        <div className="text-xs text-gray-400 mt-1">{plant.location}</div>
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500">
                  No plants available
                </div>
              )}
            </div>
          </div>

          {/* Projects Column */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="bg-green-50 px-6 py-4 border-b border-gray-200">
              <h2 className="font-semibold text-gray-900">Projects</h2>
              <p className="text-sm text-gray-600">
                {selectedPlant ? `In ${selectedPlant.name}` : 'Select a plant'}
              </p>
            </div>

            <div className="p-4">
              {!selectedPlantId ? (
                <div className="text-center py-8 text-gray-500">
                  Select a plant first
                </div>
              ) : projectsLoading ? (
                <LoadingSkeleton count={3} />
              ) : projects && projects.length > 0 ? (
                <div className="space-y-2">
                  {projects.map(project => (
                    <button
                      key={project.id}
                      onClick={() => setSelectedProjectId(project.id)}
                      className={`w-full text-left px-4 py-3 rounded-lg border-2 transition ${
                        selectedProjectId === project.id
                          ? 'border-green-500 bg-green-50'
                          : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      <div className="font-medium text-gray-900">{project.name}</div>
                      <div className="text-sm text-gray-500">{project.code}</div>
                      <div className="text-xs text-gray-400 mt-1">
                        Status: <span className="font-medium">{project.status}</span>
                      </div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500">
                  No projects in this plant
                </div>
              )}
            </div>
          </div>

          {/* Parts Column */}
          <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
            <div className="bg-purple-50 px-6 py-4 border-b border-gray-200">
              <h2 className="font-semibold text-gray-900">Parts (BOM)</h2>
              <p className="text-sm text-gray-600">
                {selectedProject ? `In ${selectedProject.name}` : 'Select a project'}
              </p>
            </div>

            <div className="p-4">
              {!selectedProjectId ? (
                <div className="text-center py-8 text-gray-500">
                  Select a project first
                </div>
              ) : partsLoading ? (
                <LoadingSkeleton count={3} />
              ) : parts && parts.length > 0 ? (
                <div className="space-y-2">
                  {parts.map(part => (
                    <div
                      key={part.id}
                      className="px-4 py-3 rounded-lg border border-gray-200 bg-gray-50 hover:bg-gray-100 cursor-pointer transition"
                    >
                      <div className="font-medium text-gray-900">{part.part_number}</div>
                      <div className="text-sm text-gray-600">{part.name}</div>
                      <div className="text-xs text-gray-400 mt-1">
                        Type: <span className="font-medium capitalize">{part.part_type}</span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center py-8 text-gray-500">
                  No parts in this project
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Summary Section */}
        {selectedPlant && selectedProject && (
          <div className="mt-8 bg-white rounded-lg border border-gray-200 p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Summary</h3>
            <div className="grid grid-cols-3 gap-4">
              <div className="p-4 bg-blue-50 rounded-lg">
                <div className="text-sm text-gray-600">Plant</div>
                <div className="text-lg font-semibold text-gray-900">{selectedPlant.name}</div>
              </div>
              <div className="p-4 bg-green-50 rounded-lg">
                <div className="text-sm text-gray-600">Project</div>
                <div className="text-lg font-semibold text-gray-900">{selectedProject.name}</div>
              </div>
              <div className="p-4 bg-purple-50 rounded-lg">
                <div className="text-sm text-gray-600">Parts in BOM</div>
                <div className="text-lg font-semibold text-gray-900">{parts?.length || 0}</div>
              </div>
            </div>

            {selectedProjectId && (
              <button className="mt-4 px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium transition">
                View Project Details
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
