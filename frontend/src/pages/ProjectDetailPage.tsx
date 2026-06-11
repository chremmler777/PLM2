/**
 * ProjectDetailPage - Product-centric project overview with hierarchical tree view of parts
 */
import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client, { API_BASE_URL } from '../api/client';
import Viewer3D from '../components/Viewer3D';
import CADUploader from '../components/CADUploader';
import RevisionWorkflowSection from '../components/workflows/RevisionWorkflowSection';
import PartBOMSection from '../components/PartBOMSection';
import PartRelationsSection from '../components/PartRelationsSection';
import PPAPSection from '../components/PPAPSection';
import MilestoneStrip from '../components/MilestoneStrip';
import ProjectLessonsSection from '../components/ProjectLessonsSection';
import ProjectSepSection from '../components/ProjectSepSection';
import { toast } from 'sonner';

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
  item_category: string;
  calibration_interval_months?: number | null;
  last_calibrated_at?: string | null;
  next_calibration_due?: string | null;
}

// Controlled item categories (automotive PLM)
const CATEGORY_META: Record<string, { label: string; icon: string; badge: string }> = {
  article: { label: 'Article', icon: '📄', badge: 'bg-slate-600 text-slate-200' },
  tool: { label: 'Tool', icon: '🔧', badge: 'bg-orange-900/50 text-orange-300' },
  assembly_equipment: { label: 'Equipment', icon: '🏗️', badge: 'bg-cyan-900/50 text-cyan-300' },
  gauge: { label: 'Gauge', icon: '📏', badge: 'bg-pink-900/50 text-pink-300' },
};

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

interface RevisionFile {
  id: number;
  revision_id: number;
  filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  cad_format: string | null;
  has_viewer: boolean;
  uploaded_at: string;
}

function useRevisionFiles(revisionId: number) {
  return useQuery<RevisionFile[]>({
    queryKey: ['revision-files', revisionId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/revisions/${revisionId}/files`);
      return res.data;
    },
    enabled: !!revisionId,
  });
}

const LOCKED_REVISION_STATUSES = ['frozen', 'cancelled', 'archived'];

interface AssemblyFileEntry {
  part_id: number;
  part_number: string;
  part_name: string;
  revision_id: number;
  revision_name: string;
  file_id: number;
}

function useAssemblyFiles(partId: number) {
  return useQuery<AssemblyFileEntry[]>({
    queryKey: ['assembly-files', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/assembly-files`);
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

interface ChangelogEntry {
  id: number;
  action: string;
  action_description: string;
  performed_by_user: string | null;
  performed_at: string;
  revision_id: number | null;
}

function useChangelog(partId: number) {
  return useQuery<ChangelogEntry[]>({
    queryKey: ['part-changelog', partId],
    queryFn: async () => {
      const res = await client.get(`/v1/parts/${partId}/changelog`);
      return res.data;
    },
    enabled: !!partId,
  });
}

// Changelog Modal
function ChangelogModal({ partId, onClose }: { partId: number; onClose: () => void }) {
  const { data: entries, isLoading } = useChangelog(partId);

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center" onClick={onClose}>
      <div
        className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-2xl w-full mx-4 max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-bold text-slate-100">Changelog</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-200 text-xl leading-none">×</button>
        </div>
        <div className="overflow-y-auto space-y-2">
          {isLoading ? (
            <p className="text-slate-400 text-sm">Loading...</p>
          ) : !entries || entries.length === 0 ? (
            <p className="text-slate-500 text-sm">No changelog entries yet</p>
          ) : (
            [...entries].reverse().map((entry) => (
              <div key={entry.id} className="p-3 bg-slate-700/50 rounded border border-slate-600 text-sm">
                <div className="flex items-center justify-between">
                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-slate-600 text-slate-200">
                    {entry.action.replace(/_/g, ' ')}
                  </span>
                  <span className="text-slate-500 text-xs">
                    {new Date(entry.performed_at).toLocaleString()}
                  </span>
                </div>
                <p className="text-slate-200 mt-1.5">{entry.action_description}</p>
                {entry.performed_by_user && (
                  <p className="text-slate-500 text-xs mt-1">by {entry.performed_by_user}</p>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

// Context Menu Component
function ContextMenuComponent({
  menu,
  onClose,
  onOpenDetails,
  onViewChangelog,
}: {
  menu: ContextMenu | null;
  onClose: () => void;
  onOpenDetails: (partId: number) => void;
  onViewChangelog: (partId: number) => void;
}) {
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
      <button
        onClick={() => {
          onOpenDetails(menu.partId);
          onClose();
        }}
        className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600"
      >
        Revisions & Lifecycle
      </button>
      <button
        onClick={() => {
          onViewChangelog(menu.partId);
          onClose();
        }}
        className="w-full text-left px-4 py-2 text-sm text-slate-200 hover:bg-slate-600"
      >
        View Changelog
      </button>
    </div>
  );
}

// Collect a part's descendant ids (for drag-and-drop cycle prevention)
function getDescendantIds(parts: Part[], partId: number): Set<number> {
  const ids = new Set<number>();
  const walk = (id: number) => {
    for (const p of parts) {
      if (p.parent_part_id === id && !ids.has(p.id)) {
        ids.add(p.id);
        walk(p.id);
      }
    }
  };
  walk(partId);
  return ids;
}

// Tree Node Component
function TreeNodeComponent({
  node,
  selectedPartId,
  onSelect,
  onContextMenu,
  depth = 0,
  draggingPartId,
  invalidDropIds,
  onDragStartPart,
  onDragEndPart,
  onDropOnPart,
}: {
  node: TreeNode;
  selectedPartId: number | null;
  onSelect: (id: number) => void;
  onContextMenu: (e: React.MouseEvent, id: number) => void;
  depth?: number;
  draggingPartId: number | null;
  invalidDropIds: Set<number>;
  onDragStartPart: (id: number) => void;
  onDragEndPart: () => void;
  onDropOnPart: (targetId: number) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const [dragOver, setDragOver] = useState(false);
  const hasChildren = node.children.length > 0;
  const isRoot = depth === 0;
  const isHeadline = isRoot || hasChildren;

  const isDropTarget =
    draggingPartId !== null &&
    draggingPartId !== node.part.id &&
    node.part.part_type === 'sub_assembly' &&
    !invalidDropIds.has(node.part.id);

  return (
    <div>
      <button
        onClick={() => onSelect(node.part.id)}
        onContextMenu={(e) => onContextMenu(e, node.part.id)}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.effectAllowed = 'move';
          onDragStartPart(node.part.id);
        }}
        onDragEnd={onDragEndPart}
        onDragOver={(e) => {
          if (isDropTarget) {
            e.preventDefault();
            setDragOver(true);
          }
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragOver(false);
          if (isDropTarget) onDropOnPart(node.part.id);
        }}
        className={`text-left px-2 rounded border transition flex items-center gap-2 ${
          dragOver && isDropTarget
            ? 'bg-green-900/40 border-green-500'
            : selectedPartId === node.part.id
              ? 'bg-blue-900/40 border-blue-500'
              : isHeadline
                ? 'border-slate-600 bg-slate-700/40 hover:bg-slate-700/60'
                : 'border-slate-700 bg-slate-800/30 hover:bg-slate-800/50'
        } ${isHeadline ? 'py-2.5' : 'py-2'} ${draggingPartId === node.part.id ? 'opacity-40' : ''}`}
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
        {node.part.item_category !== 'article' && CATEGORY_META[node.part.item_category] && (
          <span
            className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${CATEGORY_META[node.part.item_category].badge}`}
            title={CATEGORY_META[node.part.item_category].label}
          >
            {CATEGORY_META[node.part.item_category].icon}
          </span>
        )}
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
              draggingPartId={draggingPartId}
              invalidDropIds={invalidDropIds}
              onDragStartPart={onDragStartPart}
              onDragEndPart={onDragEndPart}
              onDropOnPart={onDropOnPart}
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

interface SupplierOption {
  id: number;
  name: string;
}

function useSuppliers() {
  return useQuery<SupplierOption[]>({
    queryKey: ['suppliers', false],
    queryFn: async () => (await client.get('/v1/suppliers')).data,
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
  const { data: suppliers } = useSuppliers();
  const [formData, setFormData] = useState({
    part_number: '',
    name: '',
    part_type: 'purchased',
    supplier: '',
    supplier_id: '',
    description: '',
    parent_part_id: '',
    catalog_part_id: '',
    item_category: 'article',
    calibration_interval_months: '',
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
        item_category: data.item_category,
      };
      if (data.supplier_id) {
        payload.supplier_id = parseInt(data.supplier_id, 10);
      }
      if (data.parent_part_id) {
        payload.parent_part_id = parseInt(data.parent_part_id, 10);
      }
      if (data.item_category === 'gauge' && data.calibration_interval_months) {
        payload.calibration_interval_months = parseInt(data.calibration_interval_months, 10);
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
        supplier_id: '',
        description: '',
        parent_part_id: '',
        catalog_part_id: '',
        item_category: 'article',
        calibration_interval_months: '',
      });
      onClose();
    },
  });

  if (!isOpen) return null;

  const subAssemblies = parts?.filter((p) => p.part_type === 'sub_assembly') || [];

  return (
    <div className="fixed inset-0 z-40 bg-black/50 flex items-center justify-center">
      <div className="bg-slate-800 rounded-lg border border-slate-700 p-6 max-w-md w-full mx-4">
        <h2 className="text-xl font-bold text-slate-100 mb-4">Add New Item</h2>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Item Category *</label>
            <select
              value={formData.item_category}
              onChange={(e) => setFormData({ ...formData, item_category: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
            >
              <option value="article">📄 Article (product part)</option>
              <option value="tool">🔧 Tool (die, mold, fixture)</option>
              <option value="assembly_equipment">🏗️ Assembly Equipment</option>
              <option value="gauge">📏 Gauge (calibration controlled)</option>
            </select>
          </div>

          {formData.item_category === 'gauge' && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Calibration Interval (months)</label>
              <input
                type="number"
                min="1"
                max="120"
                value={formData.calibration_interval_months}
                onChange={(e) => setFormData({ ...formData, calibration_interval_months: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
                placeholder="e.g., 12"
              />
            </div>
          )}
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

          {formData.part_type === 'purchased' && (
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Supplier</label>
              <select
                value={formData.supplier_id}
                onChange={(e) => setFormData({ ...formData, supplier_id: e.target.value })}
                className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              >
                <option value="">— No supplier —</option>
                {suppliers?.map((s) => (
                  <option key={s.id} value={s.id}>{s.name}</option>
                ))}
              </select>
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

// File type badge colors
function fileTypeColor(fileType: string): string {
  const colors: Record<string, string> = {
    cad: 'bg-blue-900/50 text-blue-300',
    drawing: 'bg-purple-900/50 text-purple-300',
    picture: 'bg-green-900/50 text-green-300',
    document: 'bg-slate-600 text-slate-200',
    test_result: 'bg-amber-900/50 text-amber-300',
  };
  return colors[fileType] || 'bg-slate-700 text-slate-300';
}

// Revision File List Item
function RevisionFileRow({
  file,
  isViewing,
  locked,
  onView,
}: {
  file: RevisionFile;
  isViewing: boolean;
  locked: boolean;
  onView?: () => void;
}) {
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: async () => {
      await client.delete(`/v1/parts/revision-files/${file.id}`);
    },
    onSuccess: () => {
      toast.success('File deleted');
      queryClient.invalidateQueries({ queryKey: ['revision-files', file.revision_id] });
    },
    onError: (error: any) => {
      const msg = error.response?.data?.detail || 'Failed to delete file';
      toast.error(msg);
    },
  });

  const noPreview = file.cad_format === 'step' && !file.has_viewer;

  return (
    <div className={`flex items-center justify-between p-1.5 rounded border text-xs ${isViewing ? 'bg-blue-900/30 border-blue-600' : 'bg-slate-700 border-slate-600'}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 ${fileTypeColor(file.file_type)}`}>
            {file.file_type.replace(/_/g, ' ')}
          </span>
          <p className="text-slate-100 truncate font-mono text-xs">{file.filename}</p>
        </div>
        <div className="flex items-center gap-2 mt-1">
          <p className="text-slate-400 text-xs">{(file.file_size / 1024 / 1024).toFixed(2)} MB</p>
          {noPreview && <span className="text-yellow-400 text-xs">No 3D preview available</span>}
        </div>
      </div>
      <div className="ml-1 flex gap-1 flex-shrink-0">
        {file.has_viewer && onView && (
          <button
            onClick={onView}
            disabled={isViewing}
            className="px-2 py-0.5 rounded bg-slate-600 hover:bg-slate-500 disabled:bg-blue-700 text-white font-medium text-xs"
          >
            {isViewing ? 'Viewing' : 'View 3D'}
          </button>
        )}
        <a
          href={`${API_BASE_URL}/v1/parts/revision-files/${file.id}/download`}
          download={file.filename}
          className="px-2 py-0.5 rounded bg-blue-600 hover:bg-blue-500 text-white font-medium text-xs"
        >
          Download
        </a>
        {!locked && (
          <button
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
            className="px-2 py-0.5 rounded bg-red-600 hover:bg-red-500 disabled:bg-red-700 text-white font-medium text-xs"
          >
            {deleteMutation.isPending ? 'Deleting...' : 'Delete'}
          </button>
        )}
      </div>
    </div>
  );
}

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
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>('all');

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: partRevisions } = usePartRevisions(selectedPartId || 0);
  const { data: revisionFiles } = useRevisionFiles(selectedRevisionId || 0);
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
        label: `${f.part_name} (${f.revision_name})`,
      })),
    [assemblyFiles]
  );

  // Default revision selection: active revision if known, otherwise the latest
  useEffect(() => {
    setViewingFileId(null);
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

  const reparentMutation = useMutation({
    mutationFn: async ({ partId, parentPartId }: { partId: number; parentPartId: number | null }) => {
      await client.put(`/v1/parts/${partId}`, { parent_part_id: parentPartId });
    },
    onSuccess: () => {
      toast.success('Part moved');
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
      queryClient.invalidateQueries({ queryKey: ['assembly-files'] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to move part');
    },
  });

  const handleDropOnPart = (targetId: number) => {
    if (draggingPartId === null) return;
    const dragged = parts?.find((p) => p.id === draggingPartId);
    if (dragged?.parent_part_id === targetId) {
      setDraggingPartId(null);
      return; // already a child of the target
    }
    reparentMutation.mutate({ partId: draggingPartId, parentPartId: targetId });
    setDraggingPartId(null);
  };

  const invalidDropIds = draggingPartId !== null && parts ? getDescendantIds(parts, draggingPartId) : new Set<number>();

  const createRfqMutation = useMutation({
    mutationFn: async () => {
      const res = await client.post(`/v1/parts/${selectedPartId}/revisions/rfq`, {
        summary: 'Initial revision',
      });
      return res.data;
    },
    onSuccess: () => {
      toast.success('Initial RFQ revision created');
      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
    },
    onError: (error: any) => {
      toast.error(error.response?.data?.detail || 'Failed to create revision');
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
  const partTree = parts ? buildPartTree(parts) : [];

  const selectedRevision = partRevisions?.find((r) => r.id === selectedRevisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const viewableFiles = revisionFiles?.filter((f) => f.has_viewer) ?? [];
  const viewingFile = viewableFiles.find((f) => f.id === viewingFileId) ?? viewableFiles[0] ?? null;
  const viewerUrl = viewingFile
    ? `${API_BASE_URL}/v1/parts/revision-files/${viewingFile.id}/viewer`
    : null;

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
          <div className="mt-2">
            <MilestoneStrip projectId={id} />
          </div>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
        >
          + Add Part
        </button>
      </div>

      <ProjectSepSection projectId={id} />

      <ProjectLessonsSection projectId={id} />

      {/* Two-column layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Left: Parts Tree */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-1">
            Items ({parts?.length ?? 0})
          </h2>
          <p className="text-xs text-slate-500 mb-2">Drag a part onto a ★ sub-assembly to restructure</p>
          <div className="flex flex-wrap gap-1 mb-3">
            {[['all', 'All'], ...Object.entries(CATEGORY_META).map(([k, v]) => [k, `${v.icon} ${v.label}`])].map(
              ([key, label]) => (
                <button
                  key={key}
                  onClick={() => setCategoryFilter(key)}
                  className={`px-2 py-1 rounded text-xs font-medium transition ${
                    categoryFilter === key
                      ? 'bg-blue-600 text-white'
                      : 'bg-slate-700 text-slate-300 hover:bg-slate-600'
                  }`}
                >
                  {label}
                </button>
              )
            )}
          </div>
          {partsLoading ? (
            <p className="text-slate-500 text-sm">Loading...</p>
          ) : (parts?.length ?? 0) === 0 ? (
            <p className="text-slate-500 text-sm">No parts yet</p>
          ) : (
            <div className="space-y-1">
              {(categoryFilter === 'all'
                ? partTree
                : (parts ?? [])
                    .filter((p) => p.item_category === categoryFilter)
                    .map((p) => ({ part: p, children: [] }))
              ).map((node) => (
                <TreeNodeComponent
                  key={node.part.id}
                  node={node}
                  selectedPartId={selectedPartId}
                  onSelect={setSelectedPartId}
                  onContextMenu={handleContextMenu}
                  draggingPartId={draggingPartId}
                  invalidDropIds={invalidDropIds}
                  onDragStartPart={setDraggingPartId}
                  onDragEndPart={() => setDraggingPartId(null)}
                  onDropOnPart={handleDropOnPart}
                />
              ))}
              {/* Top-level drop zone, visible while dragging a nested part */}
              {draggingPartId !== null &&
                parts?.find((p) => p.id === draggingPartId)?.parent_part_id != null && (
                  <div
                    onDragOver={(e) => {
                      e.preventDefault();
                      setTopLevelDragOver(true);
                    }}
                    onDragLeave={() => setTopLevelDragOver(false)}
                    onDrop={(e) => {
                      e.preventDefault();
                      setTopLevelDragOver(false);
                      if (draggingPartId !== null) {
                        reparentMutation.mutate({ partId: draggingPartId, parentPartId: null });
                        setDraggingPartId(null);
                      }
                    }}
                    className={`mt-2 px-3 py-3 rounded border-2 border-dashed text-center text-xs font-medium transition ${
                      topLevelDragOver
                        ? 'border-green-500 bg-green-900/30 text-green-300'
                        : 'border-slate-600 text-slate-400'
                    }`}
                  >
                    Drop here to move to top level
                  </div>
                )}
            </div>
          )}
        </div>

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
                  <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${typeColor(selectedPart.part_type)}`}>
                    {selectedPart.part_type.replace(/_/g, ' ')}
                  </span>
                  {CATEGORY_META[selectedPart.item_category] && (
                    <span className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${CATEGORY_META[selectedPart.item_category].badge}`}>
                      {CATEGORY_META[selectedPart.item_category].icon} {CATEGORY_META[selectedPart.item_category].label}
                    </span>
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
                  <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wide">Files & 3D Model</h3>
                  {partRevisions && partRevisions.length > 0 && (
                    <div className="flex items-center gap-2">
                      {revisionLocked && (
                        <span className="text-xs text-amber-400" title="This revision is locked; files are read-only">🔒 {selectedRevision?.status}</span>
                      )}
                      <select
                        value={selectedRevisionId ?? ''}
                        onChange={(e) => {
                          setSelectedRevisionId(parseInt(e.target.value, 10));
                          setViewingFileId(null);
                        }}
                        className="bg-slate-700 border border-slate-600 rounded px-2 py-1 text-slate-100 text-xs"
                      >
                        {partRevisions.map((rev) => (
                          <option key={rev.id} value={rev.id}>
                            {rev.revision_name} ({rev.status.replace(/_/g, ' ')})
                          </option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>

                {!partRevisions || partRevisions.length === 0 ? (
                  <div className="p-6 text-center">
                    <p className="text-slate-400 text-sm mb-3">
                      Files are managed per revision. Create the first revision to upload files.
                    </p>
                    <button
                      onClick={() => createRfqMutation.mutate()}
                      disabled={createRfqMutation.isPending}
                      className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:bg-slate-600 text-white text-sm font-medium"
                    >
                      {createRfqMutation.isPending ? 'Creating...' : '+ Create RFQ Revision'}
                    </button>
                  </div>
                ) : (
                  <>
                    {/* 3D Viewer (assembly mode shows all child models together) */}
                    {(viewerUrl || assemblyActive) && (
                      <div className="h-80 overflow-hidden border-b border-slate-700 relative">
                        <Viewer3D
                          fileId={assemblyActive ? null : viewingFile?.id ?? null}
                          viewerUrl={assemblyActive ? null : viewerUrl}
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
                      </div>
                    )}
                    {/* Files list + uploader */}
                    <div className="p-2 bg-slate-700/50 max-h-56 overflow-y-auto space-y-1">
                      {revisionFiles && revisionFiles.length > 0 ? (
                        revisionFiles.map((file) => (
                          <RevisionFileRow
                            key={file.id}
                            file={file}
                            locked={revisionLocked}
                            isViewing={viewingFile?.id === file.id}
                            onView={file.has_viewer ? () => setViewingFileId(file.id) : undefined}
                          />
                        ))
                      ) : (
                        <p className="text-slate-500 text-xs px-1 py-2">
                          No files on {selectedRevision?.revision_name} yet
                        </p>
                      )}
                      {!revisionLocked && selectedRevisionId && (
                        <CADUploader partId={selectedPart.id} revisionId={selectedRevisionId} compact />
                      )}
                    </div>
                  </>
                )}
              </div>

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
                  revisionName={selectedRevision?.revision_name}
                />
              )}

              {/* Quality / PPAP (articles only) */}
              {selectedRevisionId && selectedPart.item_category === 'article' && (
                <PPAPSection
                  revisionId={selectedRevisionId}
                  revisionName={selectedRevision?.revision_name}
                  revisionFiles={(revisionFiles ?? []).map((f) => ({ id: f.id, filename: f.filename }))}
                />
              )}

              {/* BOM Section (sub_assembly only, revision-scoped) */}
              {selectedPart.part_type === 'sub_assembly' && selectedRevisionId && (
                <PartBOMSection
                  partId={selectedPart.id}
                  revisionId={selectedRevisionId}
                  revisionName={selectedRevision?.revision_name}
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
                        }}
                        className={`p-3 rounded border cursor-pointer transition ${
                          rev.id === selectedRevisionId
                            ? 'bg-blue-900/30 border-blue-600'
                            : 'bg-slate-700/50 border-slate-600 hover:bg-slate-700'
                        }`}
                      >
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
      <ContextMenuComponent
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
