import client from './client'

export interface AuditEntry {
  id: number
  entity_type: string
  entity_id: number
  action: string
  user_id: number | null
  user_name: string | null
  timestamp: string
  old_values: string | null
  new_values: string | null
  correlation_id: string | null
  log_level: string
}
export interface AuditVerify {
  valid: boolean
  checked: number
  first_broken_id: number | null
  // Only populated when verify() is called with a correlation_id.
  correlation_entries?: number | null
  correlation_ok?: boolean | null
  /** With change_id (spec §16): this change's own entries, by entity ids. */
  change_entries?: number | null
  change_ok?: boolean | null
  change_first_broken_id?: number | null
  /** 'change': a break inside this change's entries; 'global': elsewhere. */
  break_scope?: 'none' | 'global' | 'change' | null
}

export const auditApi = {
  list: (params: { correlation_id?: string; change_id?: number; entity_type?: string; limit?: number; offset?: number }) =>
    client.get<AuditEntry[]>('/v1/audit', { params }).then((r) => r.data),
  verify: (params?: { correlation_id?: string; change_id?: number }) =>
    client.get<AuditVerify>('/v1/audit/verify', { params }).then((r) => r.data),
  downloadCsv: async (params: { correlation_id?: string; change_id?: number }) => {
    const res = await client.get('/v1/audit/export', { params, responseType: 'blob' })
    const url = URL.createObjectURL(res.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `audit_${params.correlation_id ?? 'export'}.csv`
    a.click()
    URL.revokeObjectURL(url)
  },
}
