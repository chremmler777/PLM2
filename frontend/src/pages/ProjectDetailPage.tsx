/**
 * ProjectDetailPage - Product-centric project overview with hierarchical tree view of parts
 */
import { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import client, { API_BASE_URL } from '../api/client';
import Viewer3D from '../components/Viewer3D';
import UploadDialog from '../components/parts/UploadDialog';
import RevisionWorkflowSection from '../components/workflows/RevisionWorkflowSection';
import PartBOMSection from '../components/PartBOMSection';
import PartRelationsSection from '../components/PartRelationsSection';
import ProcessFlowSection from '../components/ProcessFlowSection';
import PPAPSection from '../components/PPAPSection';
import MilestoneStrip from '../components/MilestoneStrip';
import ProjectLessonsSection from '../components/ProjectLessonsSection';
import ProjectSepSection from '../components/ProjectSepSection';
import ProjectChangesSection from '../components/ProjectChangesSection';
import ProjectPaintSection from '../components/paint/ProjectPaintSection';
import ColourSwatch from '../components/paint/ColourSwatch';
import { projectPaintOverview } from '../api/paints';
import type { PartPaintLayer } from '../types/paint';
import StartChangeModal from '../components/changes/StartChangeModal';
import StartChangeButton from '../components/changes/StartChangeButton';
import CustomerDataDialog, { type CustomerDataInput } from '../components/parts/CustomerDataDialog';
import CustomerPackageDialog from '../components/parts/CustomerPackageDialog';
import BomTree, { type BomNode } from '../components/parts/BomTree';
import { revisionLabel } from '../components/parts/RevisionBadge';
import { comparePartNumbers, stripProjectCode } from '../lib/partDisplay';
import AssemblyTreeList from '../components/parts/AssemblyTreeList';
import { toast } from 'sonner';
import { UploadedBy } from '../components/common/UploadedBy';
import RevisionStrip from '../components/parts/RevisionStrip';
import DocumentPane, { type PaneDocument, type MirrorNotice } from '../components/parts/DocumentPane';
import RevisionFilesGrouped from '../components/parts/RevisionFilesGrouped';
import { useProjectStructure, articleOf, ProjectStructure } from '../hooks/queries/useProjectStructure';

// Types
export type CustomerNaming = 'vw' | 'scout' | null;
export const CUSTOMER_NAMING_LABELS: Record<Exclude<CustomerNaming, null>, string> = { vw: 'VW group', scout: 'Scout' };

interface Project {
  id: number;
  name: string;
  code: string;
  status: string;
  customer_naming?: CustomerNaming;
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
  phase: 'review' | 'official';
  status: string;
  created_at: string;
  summary?: string;
  part_phase_at_receipt?: string;
  customer_index?: string | null;
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

export interface RevisionFile {
  id: number;
  revision_id: number;
  filename: string;
  file_type: string;
  mime_type: string;
  file_size: number;
  cad_format: string | null;
  has_viewer: boolean;
  uploaded_at: string;
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
  kind?: string | null;
  note?: string | null;
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
  // Optional throughout: files uploaded before provenance was recorded have none.
  uploaded_at?: string | null;
  uploaded_by?: number | null;
  uploaded_by_name?: string | null;
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

// Order by the embedded tool number: "3450" for a tool, the middle "3450" for
// an article like "20-3450-001-0". Groups each tool with the articles it produces
// (tool first), so the list runs 3450 → 3457 instead of all 10-/20- prefixes first.
function comparePartNodes(a: TreeNode, b: TreeNode): number {
  return comparePartNumbers(a.part.part_number, b.part.part_number);
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

    children.sort(comparePartNodes);
    return { part, children };
  }

  // Find root parts (no parent)
  for (const part of parts) {
    if (!part.parent_part_id) {
      const node = buildNode(part.id);
      if (node) roots.push(node);
    }
  }

  roots.sort(comparePartNodes);
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

interface WhereUsedEntry {
  part_id: number;
  part_number: string;
  revision_name: string;
  customer_index?: string | null;
  parents: WhereUsedEntry[];
}

function flattenUsedIn(list: WhereUsedEntry[], acc: WhereUsedEntry[] = []): WhereUsedEntry[] {
  for (const u of list) {
    if (!acc.some((a) => a.part_id === u.part_id)) acc.push(u);
    flattenUsedIn(u.parents, acc);
  }
  return acc;
}

export function BomTreeSection({ partId, revisionId, revisionName, onOpenPart }: {
  partId: number; revisionId: number; revisionName?: string; onOpenPart(id: number): void;
}) {
  const { data: tree } = useQuery({
    queryKey: ['bom-tree', partId, revisionId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/bom-tree`, { params: { revision_id: revisionId } })).data as BomNode,
  });
  const { data: usedIn } = useQuery({
    queryKey: ['where-used', partId],
    queryFn: async () => (await client.get(`/v1/parts/${partId}/where-used`)).data as WhereUsedEntry[],
  });
  const parents = usedIn ? flattenUsedIn(usedIn) : [];
  return (
    <div className="bg-slate-800 rounded-lg border border-slate-700 p-4 mb-4" data-testid="bom-tree-section">
      <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
        <h3 className="font-semibold text-slate-100">
          Bill of materials{revisionName ? <span className="text-slate-400 font-normal"> · {revisionName}</span> : null}
        </h3>
        {parents.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap text-xs">
            <span className="text-slate-400 mr-1">Used in</span>
            {parents.map((u) => (
              <button key={u.part_id} onClick={() => onOpenPart(u.part_id)}
                className="px-2 py-0.5 rounded bg-slate-700 text-slate-100 hover:bg-slate-600 font-mono">
                {u.part_number} <span className="text-slate-400 font-sans">{revisionLabel(u.revision_name, u.customer_index)}</span>
              </button>
            ))}
          </div>
        )}
      </div>
      {tree ? <BomTree tree={tree} onOpenPart={onOpenPart} /> : <p className="text-slate-400 text-sm">Loading…</p>}
    </div>
  );
}

function phaseColor(phase: string): string {
  return phase === 'official' ? 'bg-amber-900/30 text-amber-300' : 'bg-blue-900/30 text-blue-300';
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
  projectCode,
  paintByPartId,
  structure,
  onSelectRevision,
}: {
  node: TreeNode;
  selectedPartId: number | null;
  onSelect: (id: number) => void;
  projectCode?: string;
  paintByPartId?: Map<number, PartPaintLayer>;
  onContextMenu: (e: React.MouseEvent, id: number) => void;
  depth?: number;
  draggingPartId: number | null;
  invalidDropIds: Set<number>;
  onDragStartPart: (id: number) => void;
  onDragEndPart: () => void;
  onDropOnPart: (targetId: number) => void;
  structure?: ProjectStructure;
  onSelectRevision?: (partId: number, revisionId: number) => void;
}) {
  const article = articleOf(structure, node.part.id);
  const hasChildren = node.children.length > 0;
  const hasStructure = !!article && (article.revisions.length > 0 || article.related.length > 0);
  const expandable = hasChildren || hasStructure;
  const [expanded, setExpanded] = useState(hasChildren);
  const [dragOver, setDragOver] = useState(false);
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
        {expandable ? (
          <button
            aria-label={expanded ? 'Collapse' : 'Expand'}
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
          <span className="text-slate-400 text-xs">{node.part.part_number}</span>
          <span className="mx-1">•</span>
          <span>{stripProjectCode(node.part.name, projectCode)}</span>
          {hasChildren && (
            <span className="ml-2 text-xs text-slate-500">
              ({node.children.length})
            </span>
          )}
          {article?.mirror_of && <span data-testid={`tree-mirror-${node.part.id}`} className="ml-2 text-[10px] text-red-300">⇄ mirror of {article.mirror_of.part_number}</span>}
          {article && article.mirrored_by.length > 0 && <span data-testid={`tree-mirror-${node.part.id}`} className="ml-2 text-[10px] text-red-300">⇄ mirrored by {article.mirrored_by.map((m) => m.part_number).join(', ')}</span>}
        </div>
        {paintByPartId?.get(node.part.id) && (
          <span data-testid={`paint-swatch-${node.part.id}`} className="flex-shrink-0 flex items-center">
            <ColourSwatch
              hex={paintByPartId.get(node.part.id)!.paint.colour_hex}
              code={paintByPartId.get(node.part.id)!.paint.colour_code}
            />
          </span>
        )}
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

      {expanded && hasStructure && (
        <div className="ml-6 my-1 space-y-1 text-xs" style={{ marginLeft: `${depth * 20 + 24}px` }}>
          {article!.revisions.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Revisions</span>
              {article!.revisions.map((r) => (
                <button key={r.id} data-testid={`tree-rev-${r.id}`} onClick={(e) => { e.stopPropagation(); onSelectRevision?.(node.part.id, r.id); }}
                  className={`px-1.5 py-0.5 rounded ${r.parent_revision_id ? 'bg-amber-900/40 text-amber-200' : 'bg-slate-700 text-slate-200'} ${r.is_active ? 'font-semibold' : ''}`}>
                  {revisionLabel(r.revision_name, r.customer_index)}{r.parent_revision_id ? ' proposal' : ''}{r.is_active ? ' ●' : ''}
                </button>
              ))}
            </div>
          )}
          {article!.related.length > 0 && (
            <div className="flex flex-wrap items-center gap-1">
              <span className="text-slate-500 w-16">Linked</span>
              {article!.related.map((r) => (
                <button key={`${r.relation_type}-${r.part_id}`} data-testid={`tree-rel-${r.part_id}`} onClick={(e) => { e.stopPropagation(); onSelect(r.part_id); }}
                  className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                  {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, projectCode)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

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
              projectCode={projectCode}
              paintByPartId={paintByPartId}
              structure={structure}
              onSelectRevision={onSelectRevision}
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
    customer_part_number: '',
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
        customer_part_number: data.customer_part_number || null,
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
        customer_part_number: '',
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
            <label className="block text-sm font-medium text-slate-300 mb-1">Customer Part Number</label>
            <input
              type="text"
              data-testid="add-part-customer-number"
              value={formData.customer_part_number}
              onChange={(e) => setFormData({ ...formData, customer_part_number: e.target.value })}
              className="w-full bg-slate-700 border border-slate-600 rounded px-3 py-2 text-slate-100 text-sm"
              placeholder="e.g., 3CR.807.425"
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

export function CustomerNamingSelect({ projectId, value }: { projectId: number; value: CustomerNaming }) {
  const queryClient = useQueryClient();
  const save = useMutation({
    mutationFn: async (next: CustomerNaming) => {
      const res = await client.patch(`/v1/plants/projects/${projectId}`, { customer_naming: next });
      return res.data;
    },
    onSuccess: () => {
      toast.success('Customer file naming saved');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to save');
    },
  });
  return (
    <label className="flex items-center gap-2 text-xs text-slate-400">
      Customer file naming
      <select
        aria-label="Customer file naming"
        value={value ?? ''}
        disabled={save.isPending}
        onChange={(e) => save.mutate((e.target.value || null) as CustomerNaming)}
        className="px-2 py-1 rounded bg-slate-900 border border-slate-700 text-slate-100 text-xs"
      >
        <option value="">None</option>
        {(Object.keys(CUSTOMER_NAMING_LABELS) as Array<'vw' | 'scout'>).map((k) => (
          <option key={k} value={k}>{CUSTOMER_NAMING_LABELS[k]}</option>
        ))}
      </select>
    </label>
  );
}

// Revision File List Item
export function RevisionFileRow({
  file,
  isViewing,
  locked,
  onView,
  onOpen,
}: {
  file: RevisionFile;
  isViewing: boolean;
  locked: boolean;
  onView?: () => void;
  onOpen?: () => void;
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
          {file.kind && (
            <span data-testid="file-kind" title={file.note ?? undefined}
              className="px-1.5 py-0.5 rounded text-xs font-medium flex-shrink-0 bg-blue-900/50 text-blue-300">{file.kind}</span>
          )}
        </div>
        <div className="flex items-center gap-2 mt-1">
          <p className="text-slate-400 text-xs">{(file.file_size / 1024 / 1024).toFixed(2)} MB</p>
          {noPreview && <span className="text-yellow-400 text-xs">No 3D preview available</span>}
        </div>
        {file.note && <p data-testid="file-note" className="text-slate-500 text-xs truncate">{file.note}</p>}
        {/* Who put the file on the record and when. */}
        <UploadedBy name={file.uploaded_by_name} at={file.uploaded_at} className="block" />
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
        {onOpen && (
          <button onClick={onOpen}
            className="px-2 py-0.5 rounded bg-slate-600 hover:bg-slate-500 text-white font-medium text-xs">
            Open
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
  const [openDocId, setOpenDocId] = useState<number | null>(null);
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [showStartChange, setShowStartChange] = useState(false);
  const [changelogPartId, setChangelogPartId] = useState<number | null>(null);
  const [draggingPartId, setDraggingPartId] = useState<number | null>(null);
  const [topLevelDragOver, setTopLevelDragOver] = useState(false);
  const [categoryFilter, setCategoryFilter] = useState<string>('all');

  const { data: project, isLoading: projectLoading } = useProject(id);
  const { data: parts, isLoading: partsLoading } = useProjectParts(id);
  const { data: paintOverview } = useQuery({
    queryKey: ['project-paint-overview', id],
    queryFn: () => projectPaintOverview(id),
    enabled: !!id,
  });
  // Top layer (layer_order 1) per painted part, for the swatch on the tree row.
  const paintByPartId = useMemo(() => {
    const map = new Map<number, PartPaintLayer>();
    for (const part of paintOverview ?? []) {
      const top = part.layers.find((l) => l.layer_order === 1) ?? part.layers[0];
      if (top) map.set(part.part_id, top);
    }
    return map;
  }, [paintOverview]);
  // Every part that requires paint, layer or not - the Painted chip counts
  // these, so the filter must select the same set (a part marked required
  // with no layer yet was counted but filtered out, 2026-09-21).
  const paintedIds = useMemo(
    () => new Set((paintOverview ?? []).map((part) => part.part_id)),
    [paintOverview],
  );
  const { data: partRevisions } = usePartRevisions(selectedPartId || 0);
  const { data: revisionFiles } = useRevisionFiles(selectedRevisionId || 0);
  const { data: structure } = useProjectStructure(id);
  const article = articleOf(structure, selectedPartId);
  const mirrorSource = article?.mirror_of ? articleOf(structure, article.mirror_of.part_id) : undefined;
  const mirrorFiles = useRevisionFiles(mirrorSource?.active_revision_id ?? 0);
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
        label: f.uploaded_by_name
          ? `${f.part_name} (${f.revision_name}) · ${f.uploaded_by_name}`
          : `${f.part_name} (${f.revision_name})`,
      })),
    [assemblyFiles]
  );

  // Explicit revision request (e.g. clicking a revision chip in the tree) wins over
  // the default-revision effect below, which otherwise resets to active/latest
  // whenever selectedPartId changes.
  const pendingRevisionRef = useRef<{ partId: number; revisionId: number } | null>(null);

  // Default revision selection: active revision if known, otherwise the latest
  useEffect(() => {
    setViewingFileId(null);
    setOpenDocId(null);
    if (pendingRevisionRef.current?.partId === selectedPartId) {
      const pending = pendingRevisionRef.current;
      if (partRevisions?.some((r) => r.id === pending.revisionId)) {
        pendingRevisionRef.current = null;
        setSelectedRevisionId(pending.revisionId);
        return;
      }
      if (!partRevisions || partRevisions.length === 0) {
        // Revisions for this part haven't loaded yet — wait for the next
        // effect run instead of falling through to the default selection.
        return;
      }
      pendingRevisionRef.current = null;
    }
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

  const [showCustomerData, setShowCustomerData] = useState(false);
  const [showPackage, setShowPackage] = useState(false);
  const [uploadFiles, setUploadFiles] = useState<File[] | null>(null);
  const [uploadDrag, setUploadDrag] = useState(false);
  const customerDataMutation = useMutation({
    mutationFn: async (v: CustomerDataInput) => {
      const res = await client.post(`/v1/parts/${selectedPartId}/revisions/customer-data`, v);
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Recorded ${data.revision_name}`);
      setShowCustomerData(false);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
      queryClient.invalidateQueries({ queryKey: ['parts', id] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to record customer data');
    },
  });

  const proposalMutation = useMutation({
    mutationFn: async (parentRevisionId: number) => {
      const res = await client.post(`/v1/parts/${selectedPartId}/revisions/proposals`, { parent_revision_id: parentRevisionId });
      return res.data;
    },
    onSuccess: (data) => {
      toast.success(`Created ${data.revision_name}`);
      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
      queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
      setSelectedRevisionId(data.id);
      setViewingFileId(null);
      setOpenDocId(null);
    },
    onError: (error: unknown) => {
      toast.error((error as { response?: { data?: { detail?: string } } })?.response?.data?.detail || 'Failed to create proposal');
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
  const visibleNodes: TreeNode[] = categoryFilter === 'all' || categoryFilter === 'assemblies'
    ? partTree
    : (parts ?? [])
        .filter((p) =>
          categoryFilter === 'painted' ? paintedIds.has(p.id) : p.item_category === categoryFilter
        )
        .map((p) => ({ part: p, children: [] }))
        .sort(comparePartNodes);

  const selectedRevision = partRevisions?.find((r) => r.id === selectedRevisionId);
  const revisionLocked = !!selectedRevision && LOCKED_REVISION_STATUSES.includes(selectedRevision.status);
  const viewableFiles = revisionFiles?.filter((f) => f.has_viewer) ?? [];
  const viewingFile = viewableFiles.find((f) => f.id === viewingFileId) ?? viewableFiles[0] ?? null;
  const viewerUrl = viewingFile
    ? `${API_BASE_URL}/v1/parts/revision-files/${viewingFile.id}/viewer`
    : null;

  const openDoc = revisionFiles?.find((f) => f.id === openDocId) ?? null;
  const docKind = (f: RevisionFile): 'pdf' | 'image' => (f.mime_type === 'application/pdf' || /\.pdf$/i.test(f.filename) ? 'pdf' : 'image');
  const revName = selectedRevision ? revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index) : '';
  let paneDoc: PaneDocument | null = null;
  let paneMirror: MirrorNotice | null = null;
  if (openDoc) paneDoc = { fileId: openDoc.id, filename: openDoc.filename, kind: docKind(openDoc), revisionName: revName };
  else if (viewingFile || assemblyActive) paneDoc = { fileId: viewingFile?.id ?? 0, filename: assemblyActive ? 'Assembly' : viewingFile!.filename, kind: '3d', revisionName: revName };
  else if (article?.mirror_of && mirrorSource) {
    const src = mirrorFiles.data ?? [];
    const pick = src.find((f) => f.has_viewer) ?? src.find((f) => f.file_type === 'drawing') ?? null;
    if (pick) {
      paneDoc = { fileId: pick.id, filename: pick.filename, kind: pick.has_viewer ? '3d' : docKind(pick), revisionName: `${mirrorSource.part_number} · active` };
      paneMirror = { sourcePartId: mirrorSource.part_id, sourceNumber: mirrorSource.customer_part_number ?? mirrorSource.part_number, sourceName: mirrorSource.name };
    }
  }
  const paneViewerUrl = paneMirror && paneDoc?.kind === '3d' ? `${API_BASE_URL}/v1/parts/revision-files/${paneDoc.fileId}/viewer` : viewerUrl;

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
          <h1 className="text-3xl font-semibold tracking-tight text-slate-100">
            {project.name} <span className="text-slate-400 text-sm">({project.code})</span>
          </h1>
          <div className="mt-2">
            <MilestoneStrip projectId={id} />
          </div>
        </div>
        <div className="flex items-center gap-2">
          <CustomerNamingSelect projectId={id} value={project.customer_naming ?? null} />
          <StartChangeButton label="Start change request"
            onClick={() => setShowStartChange(true)}
            className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 text-white text-sm font-medium" />
          <button
            onClick={() => setShowAddModal(true)}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium"
          >
            + Add Part
          </button>
        </div>
      </div>

      {showStartChange && (
        <StartChangeModal
          open
          onClose={() => setShowStartChange(false)}
          prefill={{ projectId: id }}
        />
      )}

      <ProjectSepSection projectId={id} />

      <ProjectChangesSection projectId={id} />

      <ProjectPaintSection projectId={id} />

      <ProjectLessonsSection projectId={id} />

      {/* Two-column layout */}
      <div className="grid grid-cols-3 gap-6">
        {/* Left: Parts Tree */}
        <div>
          <h2 className="text-sm font-semibold text-slate-300 uppercase tracking-wide mb-1">
            Items ({visibleNodes.length}{categoryFilter !== 'all' ? ` of ${parts?.length ?? 0}` : ''})
          </h2>
          <p className="text-xs text-slate-500 mb-2">Drag a part onto a ★ sub-assembly to restructure</p>
          <div className="flex flex-wrap gap-1 mb-3">
            {[['all', 'All'], ...Object.entries(CATEGORY_META).map(([k, v]) => [k, `${v.icon} ${v.label}`]), ['assemblies', '🧩 Assemblies'], ['painted', `🎨 Painted (${paintOverview?.length ?? 0})`]].map(
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
          {categoryFilter === 'assemblies' ? (
            <AssemblyTreeList projectId={Number(id)} selectedPartId={selectedPartId}
              onSelect={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }} />
          ) : partsLoading ? (
            <p className="text-slate-500 text-sm">Loading...</p>
          ) : (parts?.length ?? 0) === 0 ? (
            <p className="text-slate-500 text-sm">No parts yet</p>
          ) : (
            <div className="space-y-1">
              {visibleNodes.map((node) => (
                <TreeNodeComponent
                  key={node.part.id}
                  node={node}
                  projectCode={project.code}
                  paintByPartId={paintByPartId}
                  selectedPartId={selectedPartId}
                  onSelect={setSelectedPartId}
                  onContextMenu={handleContextMenu}
                  draggingPartId={draggingPartId}
                  invalidDropIds={invalidDropIds}
                  onDragStartPart={setDraggingPartId}
                  onDragEndPart={() => setDraggingPartId(null)}
                  onDropOnPart={handleDropOnPart}
                  structure={structure}
                  onSelectRevision={(pid, rid) => { pendingRevisionRef.current = { partId: pid, revisionId: rid }; setSelectedPartId(pid); setSelectedRevisionId(rid); setViewingFileId(null); setOpenDocId(null); }}
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
                  {article?.mirror_of && (
                    <button data-testid="mirror-chip" onClick={() => { setSelectedPartId(article.mirror_of!.part_id); setViewingFileId(null); setOpenDocId(null); }}
                      className="px-2 py-0.5 rounded border border-red-500 text-red-300 text-xs">
                      ⇄ Mirror of {article.mirror_of.customer_part_number ?? article.mirror_of.part_number} · data on that part
                    </button>
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
                {partRevisions && partRevisions.length > 0 && (
                  <div className="border-b border-slate-700 bg-slate-800/60">
                    <RevisionStrip
                      revisions={partRevisions}
                      selectedId={selectedRevisionId}
                      activeId={selectedPart.active_revision_id}
                      onSelect={(revId) => { setSelectedRevisionId(revId); setViewingFileId(null); setOpenDocId(null); }}
                      onNewProposal={(majorId) => proposalMutation.mutate(majorId)}
                    />
                  </div>
                )}

                {showPackage && selectedPartId && (
                  <CustomerPackageDialog open assemblyId={selectedPartId}
                    projectParts={(parts ?? []).map((p) => ({ id: p.id, part_number: p.part_number, name: p.name }))}
                    officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
                    onClose={() => setShowPackage(false)}
                    onDone={(r) => {
                      toast.success(`Stored ${r.created.length} new, kept ${r.kept.length}`);
                      setShowPackage(false);
                      queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                      queryClient.invalidateQueries({ queryKey: ['parts', id] });
                      queryClient.invalidateQueries({ queryKey: ['bom-tree'] });
                      queryClient.invalidateQueries({ queryKey: ['project-assemblies', id] });
                      queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
                    }} />
                )}

                {!partRevisions || partRevisions.length === 0 ? (
                  <div className="p-6 text-center">
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
                    <DocumentPane document={paneDoc} mirror={paneMirror}
                      onOpenPart={(pid) => { setSelectedPartId(pid); setViewingFileId(null); setOpenDocId(null); }}>
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
                          onClick={() => setViewingFileId(null)}
                          className="absolute top-2 right-2 z-10 px-2 py-1 rounded bg-slate-700/80 hover:bg-slate-600 text-slate-200 text-xs font-medium"
                        >
                          ← Assembly view
                        </button>
                      )}
                    </DocumentPane>
                    {/* Files list + uploader */}
                    <div className="p-2 bg-slate-700/50 max-h-56 overflow-y-auto space-y-1">
                      <RevisionFilesGrouped
                        files={revisionFiles ?? []}
                        locked={revisionLocked}
                        viewingFileId={viewingFile?.id ?? null}
                        revisionName={selectedRevision ? revisionLabel(selectedRevision.revision_name, selectedRevision.customer_index) : ''}
                        onView={(f) => { setViewingFileId(f.id); setOpenDocId(null); }}
                        onOpen={(f) => setOpenDocId(f.id)}
                      />
                      {!revisionLocked && selectedRevisionId && (
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
                        partId={selectedPart.id}
                        currentRevision={{ id: selectedRevision.id, revision_name: selectedRevision.revision_name,
                          customer_index: selectedRevision.customer_index, phase: selectedRevision.phase }}
                        revisionNames={(partRevisions ?? []).map((r) => r.revision_name)}
                        officialOnly={(partRevisions ?? []).some((r) => r.phase === 'official')}
                        projectNaming={project?.customer_naming ?? null}
                        initialFiles={uploadFiles}
                        onClose={(targetRevisionId) => {
                          setUploadFiles(null);
                          if (targetRevisionId != null) {
                            queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                            queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
                            queryClient.invalidateQueries({ queryKey: ['parts', id] });
                            queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
                            setSelectedRevisionId(targetRevisionId);
                          }
                        }}
                        onDone={(targetRevisionId) => {
                          setUploadFiles(null);
                          queryClient.invalidateQueries({ queryKey: ['part-revisions', selectedPartId] });
                          queryClient.invalidateQueries({ queryKey: ['revision-files', targetRevisionId] });
                          queryClient.invalidateQueries({ queryKey: ['parts', id] });
                          queryClient.invalidateQueries({ queryKey: ['project-structure', id] });
                          setSelectedRevisionId(targetRevisionId);
                        }}
                      />
                    )}
                  </>
                )}
              </div>

              {/* Relation chips: article's related items and mirror links */}
              {article && (article.related.length > 0 || article.mirror_of || article.mirrored_by.length > 0) && (
                <div className="flex flex-wrap gap-1 px-2 py-1 border-t border-slate-700">
                  {article.related.map((r) => (
                    <button key={`${r.relation_type}-${r.part_id}`} data-testid={`relation-chip-${r.part_id}`}
                      onClick={() => { setSelectedPartId(r.part_id); setViewingFileId(null); setOpenDocId(null); }}
                      className="px-2 py-0.5 rounded bg-slate-700 hover:bg-slate-600 text-xs text-slate-200">
                      <span className="text-slate-400">{r.label}</span> {CATEGORY_META[r.item_category]?.icon} {r.part_number} {stripProjectCode(r.name, project?.code)}
                    </button>
                  ))}
                  {article.mirrored_by.map((m) => (
                    <button key={m.part_id} onClick={() => { setSelectedPartId(m.part_id); setViewingFileId(null); setOpenDocId(null); }}
                      className="px-2 py-0.5 rounded border border-red-700 text-xs text-red-300">
                      ⇄ mirrored by {m.part_number}
                    </button>
                  ))}
                </div>
              )}

              {/* Process route, derived from serves/feeds (tools and equipment only) */}
              {selectedPart.item_category !== 'article' && (
                <ProcessFlowSection
                  partId={selectedPart.id}
                  onSelectPart={setSelectedPartId}
                />
              )}

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
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                />
              )}

              {/* Quality / PPAP (articles only) */}
              {selectedRevisionId && selectedPart.item_category === 'article' && (
                <PPAPSection
                  revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                  revisionFiles={(revisionFiles ?? []).map((f) => ({ id: f.id, filename: f.filename }))}
                />
              )}

              {/* Multi-level BOM tree from the selected revision, plus where this part is used */}
              {selectedRevisionId && (
                <BomTreeSection partId={selectedPart.id} revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
                  onOpenPart={(id) => { setSelectedPartId(id); setViewingFileId(null); setOpenDocId(null); }} />
              )}

              {/* BOM editor (anything we build ourselves, revision-scoped) */}
              {selectedPart.part_type !== 'purchased' && selectedRevisionId && (
                <PartBOMSection
                  partId={selectedPart.id}
                  revisionId={selectedRevisionId}
                  revisionName={revisionLabel(selectedRevision?.revision_name, selectedRevision?.customer_index)}
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
                          setOpenDocId(null);
                        }}
                        className={`p-3 rounded border cursor-pointer transition ${
                          rev.id === selectedRevisionId
                            ? 'bg-blue-900/30 border-blue-600'
                            : 'bg-slate-700/50 border-slate-600 hover:bg-slate-700'
                        }`}
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-mono font-semibold text-slate-100 text-sm">{revisionLabel(rev.revision_name, rev.customer_index)}</span>
                          <span className={`px-2 py-0.5 rounded text-xs font-medium ${phaseColor(rev.phase)}`}>
                            {rev.phase}{rev.part_phase_at_receipt ? ` · ${rev.part_phase_at_receipt}` : ''}
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
