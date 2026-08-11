/**
 * Per-department questionnaire registry: department name → extra fields.
 *
 * The accordion asks this map and renders whatever it finds, so a new
 * questionnaire is one entry here plus its component — the bucket itself never
 * learns about departments.
 */
import type { ComponentType } from 'react'
import PackagingAssessmentFields from './PackagingAssessmentFields'
import type { DepartmentFieldsProps } from './types'

export const DEPARTMENT_FIELDS: Record<string, ComponentType<DepartmentFieldsProps>> = {
  'Packaging Engineer': PackagingAssessmentFields,
}

export type { DepartmentFieldsProps }
