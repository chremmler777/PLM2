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
  /** Spec §4 (C25): priced on an estimate, not a supplier's quote. */
  estimated?: boolean
  include: boolean
  /** Where the customer reads this line in the CBD (Engineering, Tooling,
   *  Sampling and trials, Machine time, Supplier parts, Other), when the
   *  backend names it. Internal department labels never reach the customer. */
  customer_category?: string | null
  /** Christoph 2026-11-09: what kind of block it is (who is doing what). */
  block?: CostBlock | null
  /** Our time: the department's hours and the rate they are valued at. */
  hours?: number | null
  rate?: number | null
  /** A supplier position: its costing position and, with several quotes,
   *  every quote Sales may pick (the favourite preselected). */
  position_id?: number | null
  quotes?: OfferQuote[]
  quote_offer_id?: number | null
}

export type CostBlock = 'time' | 'machine_time' | 'sampling' | 'external' | 'supplier' | 'spare_part'

export interface OfferQuote {
  offer_id: number
  vendor: string
  total: number
  /** The department's favourite. */
  recommended: boolean
  /** Sales' decision (costing: "Sales chose"). */
  chosen: boolean
}

export interface OfferFactor {
  key: string
  label: string
  /** multiplier: 1.15 adds 15 % of the cost basis (Sales markup). */
  type: 'pct' | 'amount' | 'multiplier'
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
  !SALES_MARKUP_KEYS.includes(f.key) && (f.show ?? (f.key !== 'overhead' && f.key !== 'margin'))

/** Christoph 2026-11-09: Sales' markup on top of the cost blocks (backend
 *  SALES_MARKUP_FACTORS): never its own row in the customer CBD. */
export const SALES_MARKUP_FACTORS: { key: string; label: string; type: OfferFactor['type'] }[] = [
  { key: 'sales_multiplier', label: 'Sales multiplier', type: 'multiplier' },
  { key: 'sales_overhead', label: 'Sales overhead', type: 'pct' },
  { key: 'sales_overhead_fixed', label: 'Sales overhead (fixed)', type: 'amount' },
]
export const SALES_MARKUP_KEYS = SALES_MARKUP_FACTORS.map((f) => f.key)

export type RiskSource = 'risk' | 'assumption' | 'estimate' | 'sales'

export interface OfferRisk {
  /** Identity across refreshes: c:<concern>, a:<assumption>, e:<position>, own:<id>. */
  key?: string
  /** Register risk, open assumption, costing estimate, or Sales' own text. */
  source?: RiskSource
  /** The register concern; null for the other sources. */
  concern_id: number | null
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
  /** Christoph 2026-11-09: when the old stock ends (ISO date). */
  changeover_date?: string | null
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
  /** From the quote plan. `idea: true` marks an idea block (not committed):
   *  an option for the customer, never part of the weeks from order. */
  milestones?: { label: string; date: string; idea?: boolean }[]
  disclaimer?: string | null
  /** Christoph 2026-11-09, from the quote plan: the customer reads the
   *  weeks with the Sales buffer; real time and buffer are internal. */
  real_weeks?: number | null
  sales_buffer_weeks?: number | null
  total_weeks?: number | null
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
  /** Christoph 2026-11-09: Sales' other notes, printed with the risks. */
  other_notes?: string | null
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
  /** Christoph 2026-11-09: included cost per department (internal only). */
  by_department?: { department: string; amount: number; lines: number }[]
  /** Sales multiplier + overhead, folded into the CBD rows. */
  sales_markup?: number | null
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
  /** §6: 'supplement' past approval (the changed positions only). */
  kind?: 'offer' | 'supplement'
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
  /** Spec §6: the index letter each part goes out on (a draft: live, with
   *  a newer customer index the change does not carry yet; sent: frozen). */
  indexes?: OfferPartIndex[]
  /** Spec §6 [R3] (COMMERCIAL_V2): what Send lists; a sent version keeps
   *  what it listed and the high-risk reason. null with the switch off. */
  send_list?: OfferSendList | null
  /** §7 [R4] (A4-01): what accepting this sent version lowers against its
   *  baseline (null: nothing lower). `annual` set: the piece price effect. */
  price_drop?: {
    version: number; total: number; prev_version?: number; prev_total?: number
    annual?: number; prev_annual?: number
  } | null
  /** §7: an offer out with the customer whose part index moved since. */
  index_changes?: { number: string; offer: string; now: string }[]
  /** §7 (C12): what the customer's answer on this version rests on. */
  accept_evidence?: {
    kind: 'file' | 'mail' | 'po' | 'ref'; ref?: string; attachment_id?: number
    po_match?: 'yes' | 'no'; differs?: string | null; total?: number; version?: number
    index_changes?: { number: string; offer: string; now: string }[]
  } | null
  answered_at?: string | null
}

export interface OfferPartIndex {
  number: string
  /** Audit P2-3: what the customer reads (their part number), if known. */
  customer_number?: string | null
  index: string
  newer?: { index: string; received?: string | null } | null
}

export interface OfferAssumed {
  concern_id: number
  text: string
  value: string
  risk?: string | null
  confirm_by_id?: number | null
  confirm_by_name?: string | null
  confirm_due?: string | null
}

export interface OfferSendList {
  assumed: OfferAssumed[]
  estimates: string[]
  high_risks: { concern_id: number; note: string }[]
  /** R6: still hidden, the reason an earlier version went out with carries. */
  carried_risks?: { concern_id: number; note: string; code?: string | null; reason?: string | null; version?: number }[]
  risk_reason_code?: string
  risk_reason?: string
}

export const HIGH_RISK_SEND_REASONS = ['covered_in_price', 'customer_aware', 'low_likelihood', 'other'] as const
/** F3: hours without a labour rate go out only with one of these (offer_service.NO_RATE_SEND_REASONS). */
export const NO_RATE_SEND_REASONS = ['rate_requested', 'hours_absorbed', 'covered_in_price', 'other'] as const
