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
  revenue: number | null;
  internal_cost: number;
  external_cost: number;
  total_cost: number;
  margin: number | null;
  margin_pct: number | null;
  effort_hours: number;
  pending_price: boolean;
  realized: boolean;
}

export interface PnlAggregate {
  revenue: number;
  internal_cost: number;
  external_cost: number;
  total_cost: number;
  margin: number;
  margin_pct: number | null;
}

export interface PnlByProject {
  project_id: number;
  name: string | null;
  revenue: number;
  total_cost: number;
  margin: number;
}

export interface PnlSummary {
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

export interface PnlFilters {
  project_id?: number;
  plant_id?: number;
  branch?: PnlBranch;
  status_group?: PnlStatusGroup;
}
