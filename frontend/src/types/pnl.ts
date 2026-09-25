/**
 * P&L (Profit & Loss) types - mirror backend/app/services/pnl_service.py row/summary shapes.
 */
import type { ChangeStatus } from './change';

export type PnlBranch = 'customer' | 'internal';
export type PnlStatusGroup = 'pipeline' | 'realized';

export interface PnlRow {
  change_id: number;
  change_number: string;
  title: string;
  project_id: number | null;
  project_name: string | null;
  branch: PnlBranch;
  status: ChangeStatus;
  /** The costing currency: every amount of the row except the revenue. */
  currency?: string;
  /** The revenue's currency (the offer's); no margin when it differs. */
  revenue_currency?: string;
  currency_mismatch?: boolean;
  /** Costing lines without a rate in the cost sheet: the cost is too low. */
  no_rate?: boolean;
  warnings?: { code: string; message: string }[];
  revenue: number | null;
  internal_cost: number;
  external_cost: number;
  total_cost: number;
  margin: number | null;
  margin_pct: number | null;
  effort_hours: number;
  pending_price: boolean;
  realized: boolean;
  // offer versus doing (spec §13); absent on older payloads
  phase?: 'plan' | 'actual';
  basis?: PnlBasis;
  offer_revenue?: number | null;
  planned_cost?: number | null;
  planned_margin?: number | null;
  /** Revenue including customer-billed issue costs (actual phase only). */
  actual_revenue?: number | null;
  actual_cost?: number | null;
  /** Expected end cost while running (actual phase only). */
  forecast_cost?: number | null;
  actual_margin?: number | null;
  forecast_margin?: number | null;
  variance?: number | null;
  slip_days?: number | null;
  slip_unit?: string;
}

export interface PnlAggregate {
  revenue: number;
  internal_cost: number;
  external_cost: number;
  total_cost: number;
  margin: number;
  margin_pct: number | null;
  offer_revenue?: number;
  planned_cost?: number;
  planned_margin?: number;
  /** Changes with a price in the offer figures, and those still without one. */
  priced_count?: number;
  unpriced_count?: number;
  actual_revenue?: number;
  forecast_cost?: number;
  actual_cost?: number;
  actual_margin?: number;
  forecast_margin?: number;
  actual_count?: number;
  variance?: number;
  late_count?: number;
  max_slip_days?: number | null;
  /** Changes whose revenue is in another currency than their costing. */
  mismatch_count?: number;
  no_rate_count?: number;
}

export interface PnlByProject {
  project_id: number;
  name: string | null;
  revenue: number;
  total_cost: number;
  margin: number;
}

export interface PnlSummaryBlock {
  totals: PnlAggregate;
  pipeline: PnlAggregate;
  realized: PnlAggregate;
  by_project: PnlByProject[];
  by_branch: {
    customer: PnlAggregate;
    internal: PnlAggregate;
  };
  count: number;
}

/** The top level is the block of the main currency; by_currency has one
 *  block per costing currency (amounts are never added across currencies). */
export interface PnlSummary extends PnlSummaryBlock {
  currency?: string;
  currencies?: string[];
  by_currency?: Record<string, PnlSummaryBlock>;
}

export interface PnlFilters {
  project_id?: number;
  plant_id?: number;
  branch?: PnlBranch;
  status_group?: PnlStatusGroup;
  date_from?: string;
  date_to?: string;
}

export type PnlBasis = 'accepted_offer' | 'sent_offer' | 'internal_approval' | 'costing'
  /** Mother plant (spec §14): no offer basis, actual local costs only. */
  | 'none';

export interface OvaLine {
  key: string;
  label: string;
  kind: 'revenue' | 'cost' | 'info';
  planned: number | null;
  actual: number | null;
  variance: number | null;
  forecast?: number | null;
  in_margin: boolean;
}

export interface OvaMarginRow {
  planned: number | null;
  actual: number | null;
  forecast?: number | null;
  planned_pct: number | null;
  actual_pct: number | null;
  forecast_pct?: number | null;
  variance: number | null;
}

export interface OvaTiming {
  baseline_finish: string | null;
  forecast_finish: string | null;
  actual_finish: string | null;
  slip_days: number | null;
  unit: string;
  baseline_source: string | null;
}

export interface OfferVsActual {
  change_id: number;
  currency: string;
  /** Spec §15 phase 2: what the costing and the booked hours are priced in. */
  costing_currency?: string | null;
  actual_currency?: string | null;
  basis: PnlBasis;
  /** Basis none: the plant the change came from, when the backend names it. */
  mother_plant_name?: string | null;
  phase: 'plan' | 'actual';
  offer_version: number | null;
  frozen_at: string | null;
  lines: OvaLine[];
  /** The margin row as the server lays it out; older payloads send only the flat fields. */
  margin_row?: OvaMarginRow;
  planned_revenue: number | null;
  actual_revenue: number | null;
  planned_cost: number | null;
  actual_cost: number | null;
  planned_margin: number | null;
  actual_margin: number | null;
  planned_margin_pct: number | null;
  actual_margin_pct: number | null;
  in_progress?: boolean;
  forecast_cost?: number | null;
  forecast_margin?: number | null;
  forecast_margin_pct?: number | null;
  variance: number | null;
  booked_hours: number;
  issue_count: number;
  timing: OvaTiming;
  piece_price: { delta_per_piece: number; annual_volume: number | null; annual_effect: number | null } | null;
  warnings: string[];
}

export type ActualCostCategory = 'external' | 'scrap' | 'other';

export interface ActualCost {
  id: number;
  change_id: number;
  department_id: number | null;
  department_name: string | null;
  category: ActualCostCategory;
  vendor_name: string | null;
  amount: number;
  cost_date: string;
  note: string | null;
  attachment_id: number | null;
  created_by: number;
  created_by_name: string | null;
  created_at: string;
  can_delete: boolean;
}

export interface ActualCostList {
  items: ActualCost[];
  total: number;
  can_write: boolean;
  writable_department_ids: number[] | null;
  cost_role: boolean;
}

export interface ActualCostIn {
  category: ActualCostCategory;
  amount: number;
  cost_date: string;
  department_id?: number | null;
  vendor_name?: string | null;
  note?: string | null;
}
