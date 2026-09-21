/**
 * SEP (stage-gate) types. Lifted out of ProjectSepSection so the files UI and
 * the Documents tab can speak the same shapes without importing the panel.
 */
import type { ItemFormInfo } from '../forms/types';

/** One file parked on a SEP work item. */
export interface SepItemFile {
  id: number;
  item_id: number;
  filename: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  uploaded_by: number | null;
  uploaded_by_name: string | null;
  uploaded_at: string;
}

export interface SepItem {
  id: number;
  gate_id: number;
  item_no: number;
  title_de: string;
  title_en: string;
  department: string;
  status: 'open' | 'done' | 'not_applicable';
  remark: string | null;
  responsible_id: number | null;
  responsible_name: string | null;
  completed_at: string | null;
  lessons_link: boolean;
  form: ItemFormInfo | null;
  references: { title: string; path: string }[];
  /** Files on this item. Absent on older payloads — treat as 0. */
  file_count?: number;
}

export interface SepGate {
  id: number;
  project_id: number;
  code: string;
  seq: number;
  phase_de: string;
  phase_en: string;
  status: 'pending' | 'in_progress' | 'closed';
  color: 'green' | 'yellow' | 'red';
  target_date: string | null;
  pm_signed_name: string | null;
  pm_signed_at: string | null;
  quality_signed_name: string | null;
  quality_signed_at: string | null;
  progress: { done: number; open: number; not_applicable: number; total: number; pct: number };
  open_risks: number;
  items: SepItem[];
  /** Files across all items of this gate. */
  file_count?: number;
}

export interface SepState {
  active: boolean;
  gates: SepGate[];
  rollup?: { total: { done: number; open: number; total: number; pct: number } };
}

/** Project-wide file index: gates → items → files (only items that have files). */
export interface SepProjectFilesItem {
  item_id: number;
  item_no: number;
  title_en: string;
  department: string;
  files: SepItemFile[];
}

export interface SepProjectFilesGate {
  gate_id: number;
  gate_code: string;
  phase_en: string;
  seq: number;
  items: SepProjectFilesItem[];
}
