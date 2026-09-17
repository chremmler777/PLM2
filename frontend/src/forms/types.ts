export type FieldType = 'text' | 'multiline' | 'number' | 'date' | 'checkbox' | 'choice' | 'multichoice' | 'user' | 'computed';

export interface FieldDef {
  id: string; label: string; type: FieldType; help?: string; required?: boolean; readonly?: boolean;
  options?: string[]; min?: number; max?: number; step?: number; expr?: string; prefill?: string; width?: number;
}
export interface FieldsSection { id: string; title: string; kind: 'fields'; fields: FieldDef[] }
export interface TableSection {
  id: string; title: string; kind: 'table'; min_rows?: number; columns: FieldDef[];
  footer?: { label: string; expr: string }[]; prefill?: string;
}
export type Section = FieldsSection | TableSection;
export interface FormDefinitionBody {
  key: string; version: number; title: string; implements?: string | null; cardinality: 'single' | 'multi';
  gate_items: boolean; sep_items: string[]; signatures: string[]; required_for_submit: string[];
  references?: { title: string; path: string }[]; sections: Section[];
}
export type Row = Record<string, unknown>;
export type FormData = Record<string, Record<string, unknown> | Row[] | undefined>;

export interface Signature { user_id: number; user_name: string | null; at: string }
export interface FormEvent { id: number; user_id: number; user_name: string | null; event: string; role: string | null; diff: Record<string, unknown> | null; created_at: string }
export interface FormInstance {
  id: number; project_id: number; key: string; title: string; version: number; implements: string | null;
  cardinality: 'single' | 'multi'; status: 'draft' | 'submitted' | 'reopened'; data: FormData;
  owner_id: number | null; owner_name: string | null; updated_by_name: string | null; updated_at: string;
  submitted_by_name: string | null; submitted_at: string | null;
  signatures: Record<string, Signature | null>; references: { title: string; path: string }[]; sep_items: string[];
  definition?: FormDefinitionBody; events?: FormEvent[];
}
export interface FormGroup {
  key: string; title: string; version: number; implements: string | null; cardinality: 'single' | 'multi';
  sep_items: string[]; signatures: string[]; instances: FormInstance[];
}
export interface ItemFormInfo { key: string; title: string; instance_id: number | null; status: string | null }
