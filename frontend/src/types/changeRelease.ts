/** Release stage of a change (spec 2026-09-25 section 7). */

export type ReleaseCheckStatus = 'open' | 'done' | 'na'

/** Items whose "done" carries a value: the cycle time (Tool Engineer;
 *  changed with the new seconds, or confirmed unchanged) and the optional
 *  Cm of the process-stable row (APQP). */
export type ReleaseValueKind = 'cycle_time' | 'cm'

export interface ReleaseCheckAnswer {
  status: ReleaseCheckStatus
  note?: string
  outcome?: 'changed' | 'unchanged'
  value?: number
}

export interface ReleaseCheck {
  key: string
  label: string
  department_id?: number | null
  department_name?: string | null
  status: ReleaseCheckStatus
  note?: string | null
  by_name?: string | null
  at?: string | null
  hint?: string | null
  value_kind?: ReleaseValueKind | null
  /** Answered before the item was taken off the checklist: read-only, not counted. */
  retired?: boolean
  /** C7: whether this viewer may answer the row (the backend's rule). */
  can_answer?: boolean | null
  /** C7 + R38: 'done' needs a reference (the customer's approval, the
   *  measurement report, the ERP reference, the customer mail, ...). */
  needs_ref?: boolean
  /** What that reference is (the field's words), e.g. "The measurement report". */
  ref_prompt?: string | null
  /** Why 'done' is refused right now (the drawing row without files). */
  done_refusal?: string | null
  /** C7: on a customer change 'not applicable' names the customer's waiver. */
  na_needs_ref?: boolean
  /** C7: the owner department has no member here: PM or the lead answer. */
  run_team_answers?: boolean
  /** A5-04 d: '<X> has no member here: <lead|Project Management> coordinates'. */
  no_member_hint?: string | null
  /** A5-09: the validation measurement a measured row answers from (the key
   *  is present on such a row; null: nothing measured yet). */
  measurement?: string | null
  measurement_failed?: boolean
}

export type LessonCategory =
  | 'design' | 'manufacturing' | 'quality' | 'supplier'
  | 'logistics' | 'project_management' | 'tooling' | 'other'
export type LessonType = 'success' | 'problem' | 'improvement'
export type LessonSeverity = 'low' | 'medium' | 'high' | 'critical'

export interface LessonOut {
  id: number
  title: string
  description?: string | null
  recommendation?: string | null
  category: LessonCategory | string
  lesson_type: LessonType | string
  severity: LessonSeverity | string
  status: string
  created_at?: string | null
  created_by_name?: string | null
}

export interface LessonIn {
  title: string
  description: string
  category: LessonCategory
  lesson_type: LessonType
  severity: LessonSeverity
  recommendation?: string
}

export interface ReleaseState {
  checks: ReleaseCheck[]
  open_count: number
  lessons: {
    done_at?: string | null
    done_by_name?: string | null
    none_reason?: string | null
    items: LessonOut[]
  }
  can_release: boolean
  blockers: string[]
}
