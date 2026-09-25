/**
 * The customer offer of an engineering change (spec 2026-09-25 section 6).
 *
 * Every version is a row: a draft Sales edits, then sent, then superseded,
 * accepted or declined. `data` is the whole editable document; `totals` are
 * always the server's arithmetic, the UI never recomputes the business rule.
 */

export type OfferStatus = 'draft' | 'sent' | 'superseded' | 'accepted' | 'declined'

export interface OfferIssue {
  code: string
  message: string
  task_id?: number | null
}

export type CostLineCategory = 'internal' | 'external' | 'other'

export interface OfferCostLine {
  key: string
  label: string
  department?: string | null
  category: CostLineCategory
  amount: number
  source_amount?: number | null
  include: boolean
  /** Where the customer reads this line in the CBD (Engineering, Tooling,
   *  Sampling and trials, Machine time, Supplier parts, Other), when the
   *  backend names it. Internal department labels never reach the customer. */
  customer_category?: string | null
}

export interface OfferFactor {
  key: string
  label: string
  type: 'pct' | 'amount'
  value: number
  sign: 1 | -1
  enabled: boolean
  note?: string | null
  /** Printed as its own line on the offer. Hidden factors are spread over the
   *  included cost lines in the PDF; the total is the same either way.
   *  Backend default: false for overhead and margin. */
  show?: boolean
}

/** A factor's "show on offer" with the backend's default when absent. */
export const factorShown = (f: Pick<OfferFactor, 'key' | 'show'>): boolean =>
  f.show ?? (f.key !== 'overhead' && f.key !== 'margin')

export interface OfferRisk {
  concern_id: number
  label: string
  severity?: number | null
  department?: string | null
  show: boolean
  type: 'pct' | 'amount'
  value: number
  note?: string | null
}

export type ChangeoverMode = 'running_change' | 'customer_pays_scrap'

export interface OfferChangeover {
  mode: ChangeoverMode
  scrap_qty?: number | null
  scrap_unit_price?: number | null
  note?: string | null
}

export interface PiecePriceRow {
  label: string
  driver?: string | null
  delta_per_piece: number
}

export interface OfferPiecePrice {
  enabled: boolean
  annual_volume?: number | null
  rows: PiecePriceRow[]
}

export interface OfferTiming {
  include: boolean
  weeks_from_order?: number | null
  milestones?: { label: string; date: string }[]
  disclaimer?: string | null
}

export interface OfferFreeField {
  label: string
  value: string
  amount?: number | null
}

export interface OfferTerms {
  payment?: string | null
  incoterms?: string | null
  delivery?: string | null
  notes?: string | null
}

export interface OfferData {
  recipient?: { company?: string | null; contact?: string | null; address?: string | null }
  subject?: string | null
  intro?: string | null
  cbd_mode?: 'detailed' | 'rough'
  rough_description?: string | null
  cost_lines?: OfferCostLine[]
  factors?: OfferFactor[]
  risks?: OfferRisk[]
  changeover?: OfferChangeover
  piece_price?: OfferPiecePrice
  timing?: OfferTiming
  free_fields?: OfferFreeField[]
  terms?: OfferTerms
  /** Risk surcharges as their own lines on the offer; folded into the cost
   *  lines otherwise (default). */
  show_risk_surcharge?: boolean
  /** PDF section 1, as the customer reads it (seeded from the change description). */
  scope_text?: string | null
  /** Printed on the offer: a word to the customer about this version. */
  customer_note?: string | null
}

export interface OfferTotals {
  base: number
  /** show: printed as its own row; hidden ones are folded into the CBD rows. */
  factors: { key: string; label: string; amount: number; show?: boolean }[]
  risks_total: number
  scrap: number
  free: number
  total_one_time: number
  piece_price_delta?: number | null
  annual_effect?: number | null
  internal_cost?: number | null
  margin_abs?: number | null
  margin_pct?: number | null
}

export interface OfferDiffRow {
  field: string
  before: unknown
  after: unknown
}

export interface OfferOut {
  id: number
  version: number
  status: OfferStatus
  currency: string
  data: OfferData
  totals: OfferTotals
  change_note?: string | null
  sent_at?: string | null
  sent_by_name?: string | null
  received_at?: string | null
  valid_until?: string | null
  days_left?: number | null
  expired?: boolean
  created_at: string
  created_by_name?: string | null
  diff?: OfferDiffRow[] | null
  /** The sender as the PDF prints it ("Issued by"): the company profile's
   *  legal name, when the backend sends it. */
  issued_by?: string | null
  warnings?: OfferIssue[]
  /** Spec §15 phase 2: the costing's currency and the cost sheet versions it used. */
  costing_currency?: string | null
  costing_totals_by_currency?: Record<string, { grand_total: number }>
  cost_sheet_versions_used?: number[]
  cost_sheet_current_version?: number | null
}
