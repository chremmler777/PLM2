/** Contract every department questionnaire follows. */
export interface DepartmentFieldsProps {
  value: Record<string, unknown>
  onChange: (next: Record<string, unknown>) => void
}
