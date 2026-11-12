/** Test data for the LOP screen: one line with every field line_dict sends. */
import type { LopLine, LopProjectResponse, PdbResponse } from '../../types/lop'

export function lopLine(over: Partial<LopLine> = {}): LopLine {
  return {
    id: 1, project_id: 2, kind: 'task', ref_key: null, title: 'Packaging proposal to customer',
    department_id: 10, responsible_id: 7, responsible_is_default: false,
    due_date: '2026-11-14', first_due_date: '2026-11-14', due_is_default: false, next_check_date: null,
    status: 'open', closed_at: null, closed_by: null, last_update_at: '2026-11-10', last_update_by: 5,
    created_at: '2026-11-01', created_by: 5, source_label: 'PM', text: 'Packaging proposal to customer',
    source_context: null, source_closed: false, department_name: 'Logistics', responsible_name: 'Lena Logistics',
    days_late: 0, late: false, stale: false, under_control: true, group: 'other', moved: false, reopened: false,
    meeting: null, meeting_mark: null, last_comment: null, can_manage: true, can_report: false,
    ...over,
  }
}

export function lopProject(over: Partial<LopProjectResponse> = {}): LopProjectResponse {
  return {
    project: { id: 2, code: '2277', name: 'Backpanel', lop_enabled: true },
    can_manage: true, lines: [lopLine()], last_meeting: null, meeting: null, untouched: 0,
    ...over,
  }
}

export function pdbTopic(over: Partial<LopLine> = {}): LopLine {
  return lopLine({
    id: null, project_id: null, kind: 'pdb_topic', ref_key: '501', title: null,
    department_id: null, responsible_id: null, due_date: null, first_due_date: null,
    source_label: 'PDB topic', text: 'Warpage on clip towers after T1\nTo do: adjust cooling circuit 4',
    department_name: 'Process ENG', responsible_name: null, group: 'pdb', under_control: false,
    pinned: false, tool_number: '227701', age_days: 41, escalation_level: 2, escalated: true,
    committed_until: null, handover_impact: true, pdb_department: 'Process ENG', pdb_live: true,
    ...over,
  })
}

export function pdbResponse(over: Partial<PdbResponse> = {}): PdbResponse {
  return {
    available: true, reason: null, status_reason: null, hidden: 0,
    status: {
      tool_count: 2,
      funnel: { sampling: 1, qualifying: 1, technical_handover: 0, ready: 0, series: 0 },
      tools: [
        { tool_number: '227701', tool_name: 'Backpanel LH', ps: 'B', ts: 'C', es: 'C', open_topics: 1 },
        { tool_number: '227702', tool_name: 'Backpanel RH', ps: 'C', ts: 'C', es: 'C', open_topics: 0 },
      ],
    },
    topics: [pdbTopic()],
    ...over,
  }
}
