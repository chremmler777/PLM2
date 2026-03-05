/**
 * ProjectDetailPage - Product-centric project overview with hierarchical tree view of parts
 */
import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client from '../api/client';
import Viewer3D from '../components/Viewer3D';

// Types
interface Project {
  id: number;
  name: string;
  code: string;
  status: string;
}

interface Part {
  id: number;
  part_number: string;
  name: string;
  part_type: string;
  supplier?: string | null;
  data_classification?: string;
  active_revision_id: number | null;
  parent_part_id?: number | null;
}

interface PartRevision {
  id: number;
  part_id: number;
  revision_name: string;
  phase: string;
  status: string;
  created_at: string;
  summary?: string;
}

interface ContextMenu {
  partId: number;
  x: number;
  y: number;
}

interface TreeNode {
  part: Part;
  children: TreeNode[];
}

// Queries
function useProject(projectId: number) {
  return useQuery<Project>({
    queryKey: ['project', projectId],
    queryFn: async () => {
      const res = await client.get(`/v1/plants/projects`);
      return res.data.find((p: Project) => p.id === projectId);
    },
    enabled: !!projectId,
  });
}

function useProjectParts(projectId: number) {
  return useQuery<Part[]>({
    queryKey: ['parts', projectId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/project/${projectId}`);
      return res.data;
    },
    enabled: !!projectId,
  });
}

function usePartRevisions(partId: number) {
  return useQuery<PartRevision[]>({
    queryKey: ['part-revisions', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/revisions`);
      return res.data;
    },
    enabled: !!partId,
  });
}

// Build tree structure from flat parts list
function buildPartTree(parts: Part[]): TreeNode[] {
  const partMap = new Map<number, Part>(parts.map((p) => [p.id, p]));
  const roots: TreeNode[] = [];
  const visited = new Set<number>();

  function buildNode(partId: number): TreeNode | null {
    if (visited.has(partId)) return null;
    visited.add(partId);

    const part = partMap.get(partId);
    if (!part) return null;

    const children: TreeNode[] = [];
    for (const candidate of parts) {
      if (candidate.parent_part_id === partId) {
        const childNode = buildNode(candidate.id);
        if (childNode) children.push(childNode);
      }
    }

    return { part, children };
  }

  // Find root parts (no parent)
  for (const part of parts) {
    if (!part.parent_part_id) {
      const node = buildNode(part.id);
      if (node) roots.push(node);
    }
  }

  return roots;
}

// Color helpers
function typeColor(partType: string): string {
  const colors: Record<string, string> = {
    purchased: 'bg-slate-600 text-slate-200',
    internal_mfg: 'bg-amber-900/50 text-amber-300',
    sub_assembly: 'bg-blue-900/50 text-blue-300',
  };
  return colors[partType] || 'bg-slate-700 text-slate-300';
}

function phaseColor(phase: string): string {
  const colors: Record<string, string> = {
    rfq_phase: 'bg-blue-900/30 text-blue-300',
    engineering: 'bg-yellow-900/30 text-yellow-300',
    freeze: 'bg-green-900/30 text-green-300',
    ecn: 'bg-purple-900/30 text-purple-300',
  };
  return colors[phase] || 'bg-slate-700/30 text-slate-300';
}

function statusColor(status: string): string {
  const colors: Record<string, string> = {
    draft: 'text-slate-400',
    in_progress: 'text-blue-400',
    in_review: 'text-yellow-400',
    approved: 'text-green-400',
    frozen: 'text-green-500',
    rejected: 'text-red-400',
    cancelled: 'text-slate-500',
  };
  return colors[status] || 'text-slate-300';
}

// Context Menu Component
function ContextMenuComponent({ menu, onClose }: { menu: ContextMenu | null; onClose: () => void }) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menu) return;

    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        onClose();
      }
    }

    function handleEscape(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }

    document.addEventListener('mousedown', handleClick);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClick);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [menu, onClose]);

  if (!menu) return null;

  return (
    <div
      ref={containerRef}
      className="fixed z-50 bg-slate-700 border border-slate-600 rounded-lg shadow-lg min-w-max"
      style={{ top: `${menu.y}px`, left: `${menu.x}px` }}
    >
      <button className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600">
        Revisions
      </button>
      <button className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600">
        View Changelog
      </button>
      <button className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600">
        Start ECR
      </button>
      <button className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600 border-t border-slate-600">
        Create Next Revision
      </button>
    </div>
  );
}

// Tree Node Component
function TreeNodeComponent({
  node,
  selectedPartId,
  onSelect,
  onContextMenu,
  depth = 0,
}: {
  node: TreeNode;
  selectedPartId: number | null;
  onSelect: (id: number) => void;
  onContextMenu: (e: React.MouseEvent, id: number) => void;
  depth?: number;
}) {
  const [expanded, setExpanded] = useState(true);
  const hasChildren = node.children.length > 0;
  const isRoot = depth === 0;
  const isHeadline = isRoot || hasChildren;

  return (
    <div>
      <button
        onClick={() => onSelect(node.part.id)}
        onContextMenu={(e) => onContextMenu(e, node.part.id)}
        className={`text-left px-2 rounded border transition flex items-center gap-2 ${
          selectedPartId === node.part.id
            ? 'bg-blue-900/40 border-blue-500'
            : isHeadline
              ? 'border-slate-600 bg-slate-700/40 hover:bg-slate-700/60'
              : 'border-slate-700 bg-slate-800/30 hover:bg-slate-800/50'
        } ${isHeadline ? 'py-2.5' : 'py-2'}`}
        style={{ marginLeft: `${depth * 20}px`, width: `calc(100% - ${depth * 20}px)` }}
      >
        {hasChildren ? (
          <button
            onClick={(e) => {
              e.stopPropagation();
              setExpanded(!expanded);
            }}
            className="text-slate-400 hover:text-slate-200 text-xs w-4 h-4 flex items-center justify-center flex-shrink-0"
          >
            {expanded ? '▼' : '▶'}
          </button>
        ) : (
          <span className="w-4 flex-shrink-0"></span>
        )}

        <div className={`truncate flex-1 min-w-0 ${isHeadline ? 'text-slate-50 text-sm font-bold' : 'text-slate-100 text-sm font-medium'}`}>
          <span className="text-slate-400 text-xs">{node.part.id}</span>
          <span className="mx-1">•</span>
          <span>{node.part.name}</span>
          {hasChildren && (
            <span className="ml-2 text-xs text-slate-500">
              ({node.children.length})
            </span>
          )}
        </div>
        {node.part.part_type === 'sub_assembly' && <span className="text-yellow-400 text-sm flex-shrink-0">★</span>}
        <span className={`px-2 py-0.5 rounded text-xs font-medium flex-shrink-0 ${typeColor(node.part.part_type)}`}>
          {node.part.part_type.replace(/_/g, ' ')}
        </span>
      </button>

      {expanded && hasChildren && (
        <div>
          {node.children.map((child) => (
            <TreeNodeComponent
              key={child.part.id}
              node={child}
              selectedPartId={selectedPartId}
              onSelect={onSelect}
              onContextMenu={onContextMenu}
              depth={depth + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}

interface CatalogPart {
  id: number;
  part_number: string;
  name: string;
  supplier: string | null;
  unit: string;
}

function useCatalogParts() {
  return useQuery<CatalogPart[]>({
    queryKey: ['catalog-parts'],
    queryFn: async () => {
      const res = await client.get('/v1/catalog-parts?is_active=true');
      return res.data;
    },
  });
}

// Add Part Modal
function AddPartModal({
  projectId,
  parts,
  isOpen,
  onClose,
}: {
  projectId: number;
  parts: Part[] | undefined;
  isOpen: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const { data: catalogParts } = useCatalogParts();
  const [formData, setFormData] = useState({
    part_number: '',
    name: '',
    part_type: 'purchased',
    supplier: '',
    description: '',
    parent_part_id: '',
    catalog_part_id: '',
  });

  const createMutation = useMutation({
    mutationFn: async (data: typeof formData) => {
      const payload: any = {
        project_id: projectId,
        part_number: data.part_number,
        name: data.name,
        part_type: data.part_type,
        supplier: data.supplier || null,
        description: data.description || null,
        data_classification: 'confidential',
      };
      if (data.parent_part_id) {
        payload.parent_part_id = parseInt(data.parent_part_id, 10);
      }
      const res = await client.post('/v1/parts', payload);
      return res.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['parts', projectId] });
      setFormData({
        part_number: '',
        name: '',
        part_type: 'purchased',
        supplier: '',
        description: '',
        parent_part_id: '',
      });
      onClose();
    },
  });

  if (!isOpen) return null;

  const subAssemblies = parts?.filter((p) => p.part_type === 'sub_assembly') || [];

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Add New Part</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Part Number *</label>
            <input
              type="text"
              value={formData.part_number}
              onChange={(e) => setFormData({ ...formData, part_number: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., P-001"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Name *</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., Housing"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Type *</label>
            <select
              value={formData.part_type}
              onChange={(e) => setFormData({ ...formData, part_type: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            >
              <option value="purchased">Purchased</option>
              <option value="internal_mfg">Internal Manufacturing</option>
              <option value="sub_assembly">Sub-Assembly</option>
            </select>
          </div>

          {formData.part_type === 'purchased' && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Catalog Part</label>
              <select
                value={formData.catalog_part_id}
                onChange={(e) => {
                  const selectedId = e.target.value;
                  const selected = catalogParts?.find((p) => p.id === parseInt(selectedId, 10));
                  if (selected) {
                    setFormData({
                      ...formData,
                      catalog_part_id: selectedId,
                      part_number: selected.part_number,
                      name: selected.name,
                      supplier: selected.supplier || '',
                    });
                  } else {
                    setFormData({ ...formData, catalog_part_id: selectedId, part_number: '', name: '', supplier: '' });
                  }
                }}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="">-- Create new purchased part --</option>
                {catalogParts?.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.part_number} - {p.name}
                  </option>
                ))}
              </select>
              {!formData.catalog_part_id && (
                <p className="text-xs text-slate-400 mt-1">Or fill in the details below to create a new part</p>
              )}
            </div>
          )}

          {subAssemblies.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Parent Sub-Assembly (optional)</label>
              <select
                value={formData.parent_part_id}
                onChange={(e) => setFormData({ ...formData, parent_part_id: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="">None (top-level)</option>
                {subAssemblies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.part_number} - {p.name}
                  </option>
                ))}
              </select>
            </div>
          )}

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
            disabled={createMutation.isPending || !formData.part_number || !formData.name}
            className="flex-1 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
          >
            {createMutation.isPending ? 'Creating...' : 'Add Part'}
          </button>
        </div>
      </div>
    </div>
  );
}

// Main Component
export default function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>();
  const id = projectId ? parseInt(projectId, 10) : 0;
  const navigate = useNavigate();

  const [selectedPartId, setSelectedPartId] = useState<number | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: partRevisions } = usePartRevisions(selectedPartId || 0);

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
  const partTree = parts ? buildPartTree(parts) : [];

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
          <h1 className="text-3xl font-bold text-slate-100">
            {project.name} <span className="text-slate-400 text-sm">({project.code})</span>
          </h1>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
        >
          + Add Part
        </button>
      </div>

      {/* Two-column layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Left: Parts Tree */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-4">
            Parts ({parts?.length ?? 0})
          </h2>
          {partsLoading ? (
            <p className="text-slate-500 text-sm">Loading...</p>
          ) : (parts?.length ?? 0) === 0 ? (
            <p className="text-slate-500 text-sm">No parts yet</p>
          ) : (
            <div className="space-y-1">
              {partTree.map((node) => (
                <TreeNodeComponent
                  key={node.part.id}
                  node={node}
                  selectedPartId={selectedPartId}
                  onSelect={setSelectedPartId}
                  onContextMenu={handleContextMenu}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: Part Detail */}
        <div
          className="col-span-2 space-y-4 min-h-96"
          onClick={() => setSelectedPartId(null)}
        >
          {selectedPart ? (
            <div onClick={(e) => e.stopPropagation()}>
              {/* Part Info Card */}
              <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
                <h2 className="text-lg font-bold text-slate-100">{selectedPart.name}</h2>
                <div className="text-slate-400 text-sm mt-1 flex items-center gap-2">
                  <span className="font-mono">{selectedPart.part_number}</span>
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${typeColor(selectedPart.part_type)}`}>
                    {selectedPart.part_type.replace(/_/g, ' ')}
                  </span>
                </div>
                {selectedPart.supplier && <p className="text-slate-400 text-sm mt-2">Supplier: {selectedPart.supplier}</p>}
                {selectedPart.data_classification && (
                  <p className="text-slate-400 text-sm">Classification: {selectedPart.data_classification}</p>
                )}
              </div>

              {/* CAD Viewer */}
              <div className="bg-slate-800 rounded-lg border border-slate-700 h-96 overflow-hidden">
                <Viewer3D fileId={null} />
              </div>

              {/* BOM Section (sub_assembly only) */}
              {selectedPart.part_type === 'sub_assembly' && (
                <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
                  <h3 className="text-sm font-semibold text-slate-200 mb-3">BOM</h3>
                  <div className="text-slate-400 text-sm">
                    <p>No BOM items yet — add parts to this sub-assembly</p>
                  </div>
                  <button
                    disabled
                    title="Coming soon"
                    className="mt-3 px-3 py-1 rounded bg-slate-700/50 text-slate-500 text-sm font-medium cursor-not-allowed"
                  >
                    + Add Item
                  </button>
                </div>
              )}

              {/* Revisions Section */}
              <div className="bg-slate-800 rounded-lg border border-slate-700 p-4">
                <h3 className="text-sm font-semibold text-slate-200 mb-3">Revisions</h3>
                {!partRevisions || partRevisions.length === 0 ? (
                  <p className="text-slate-500 text-sm">No revisions yet</p>
                ) : (
                  <div className="space-y-2 max-h-64 overflow-y-auto">
                    {partRevisions.map((rev) => (
                      <div key={rev.id} className="p-3 bg-slate-700/50 rounded border border-slate-600">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono font-semibold text-slate-100 text-sm">{rev.revision_name}</span>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${phaseColor(rev.phase)}`}>
                            {rev.phase.replace(/_/g, ' ')}
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
      <ContextMenuComponent menu={contextMenu} onClose={() => setContextMenu(null)} />

      {/* Add Part Modal */}
      <AddPartModal projectId={id} parts={parts} isOpen={showAddModal} onClose={() => setShowAddModal(false)} />
    </div>
  );
}
