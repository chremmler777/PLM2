/** Release stage of a change (spec 2026-09-25 section 7). */

export type ReleaseCheckStatus = 'open' | 'done' | 'na'

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
