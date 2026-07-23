import client from './client';
import type {
  ChangeRequest, ChangeDetail, ChangeTask,
  ChangeRouting, DeviationRequest,
  CostLine, CostLineIn, Summation, Gate, DepartmentRateRef, ActivityRef,
  TransitionDeviation, ImpactTreeResponse, ImplementationProgress, MyActionsResponse,
  ChangeMeeting, MeetingParticipant,
} from '../types/change';
import type { Escalation } from '../types/workflow';

export const changesApi = {
  list: (params: { project_id?: number; status?: string; change_type?: string }) =>
    client.get<ChangeRequest[]>('/v1/changes', { params }).then((r) => r.data),

  get: (id: number) =>
    client.get<ChangeDetail>(`/v1/changes/${id}`).then((r) => r.data),

  create: (body: {
    project_id: number; title: string; change_type: string;
    reason?: string; description?: string; priority?: string; lead_id?: number;
    customer_relevant?: boolean;
  }) => client.post<ChangeRequest>('/v1/changes', body).then((r) => r.data),

  update: (id: number, body: Record<string, unknown>) =>
    client.patch<ChangeRequest>(`/v1/changes/${id}`, body).then((r) => r.data),

  transition: (id: number, to_status: string, opts?: { cancellation_reason?: string }) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/transition`, { to_status, ...opts }).then((r) => r.data),

  listDeviations: (id: number) =>
    client.get<TransitionDeviation[]>(`/v1/changes/${id}/deviations`).then((r) => r.data),
  proposeDeviation: (id: number, body: { to_status: string; reason: string }) =>
    client.post<TransitionDeviation>(`/v1/changes/${id}/deviations`, body).then((r) => r.data),
  decideDeviation: (id: number, devId: number, body: { decision: 'approved' | 'rejected'; note?: string }) =>
    client.post<TransitionDeviation>(`/v1/changes/${id}/deviations/${devId}/decide`, body).then((r) => r.data),

  addImpactedItem: (id: number, body: { part_id: number; is_lead?: boolean; impact_note?: string; eng_level_before?: string }) =>
    client.post(`/v1/changes/${id}/impacted-items`, body).then((r) => r.data),

  removeImpactedItem: (id: number, itemId: number) =>
    client.delete(`/v1/changes/${id}/impacted-items/${itemId}`).then((r) => r.data),

  seedImpacted: (id: number) =>
    client.post(`/v1/changes/${id}/impacted-items/seed`).then((r) => r.data),

  submitAssessment: (id: number, body: { department_id: number; verdict: string; cost_impact?: number; lead_time_impact_days?: number; conditions?: string; notes?: string; effort_hours?: number }) =>
    client.post(`/v1/changes/${id}/assessments`, body).then((r) => r.data),

  customerResponse: (id: number, response: string) =>
    client.post(`/v1/changes/${id}/customer-response`, { response }).then((r) => r.data),

  signOff: (id: number, role: 'pm' | 'quality') =>
    client.post(`/v1/changes/${id}/sign-off`, { role }).then((r) => r.data),

  myTasks: () =>
    client.get<ChangeTask[]>('/v1/changes/my-tasks').then((r) => r.data),

  myActions: (id: number): Promise<MyActionsResponse> =>
    client.get(`/v1/changes/${id}/my-actions`).then((r) => r.data),

  myEscalations: (): Promise<Escalation[]> =>
    client.get('/v1/changes/my-escalations').then((r) => r.data),

  acceptAssessment: (changeId: number, assessmentId: number) =>
    client.post(`/v1/changes/${changeId}/assessments/${assessmentId}/accept`).then((r) => r.data),

  uploadAttachment: (id: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    // The client sets a global Content-Type: application/json default; it must
    // be cleared here so the browser sets multipart/form-data WITH its boundary.
    // Otherwise FastAPI can't find the `file` field and returns 422.
    return client
      .post(`/v1/changes/${id}/attachments`, fd, {
        headers: { 'Content-Type': undefined },
      })
      .then((r) => r.data);
  },

  deleteAttachment: (id: number, attachmentId: number) =>
    client.delete(`/v1/changes/${id}/attachments/${attachmentId}`).then((r) => r.data),

  getRouting: (id: number) =>
    client.get<ChangeRouting>(`/v1/changes/${id}/routing`).then((r) => r.data),

  postDeviation: (id: number, body: DeviationRequest) =>
    client.post<ChangeRouting>(`/v1/changes/${id}/routing/deviation`, body).then((r) => r.data),

  approveDeviation: (id: number) =>
    client.post<ChangeRouting>(`/v1/changes/${id}/routing/deviation/approve`).then((r) => r.data),

  getCostLines: (id: number, aid: number) =>
    client.get<CostLine[]>(`/v1/changes/${id}/assessments/${aid}/cost-lines`).then((r) => r.data),
  putCostLines: (id: number, aid: number, lines: CostLineIn[]) =>
    client.put<CostLine[]>(`/v1/changes/${id}/assessments/${aid}/cost-lines`, { lines }).then((r) => r.data),
  getSummation: (id: number) =>
    client.get<Summation>(`/v1/changes/${id}/summation`).then((r) => r.data),
  getGates: (id: number) =>
    client.get<Gate[]>(`/v1/changes/${id}/gates`).then((r) => r.data),
  putGate: (id: number, gateKey: string, body: { decision: string; remark?: string }) =>
    client.put<Gate>(`/v1/changes/${id}/gates/${gateKey}`, body).then((r) => r.data),
  referenceRates: () =>
    client.get<DepartmentRateRef[]>('/v1/changes/reference/rates').then((r) => r.data),
  referenceActivities: (departmentId: number) =>
    client.get<ActivityRef[]>('/v1/changes/reference/activities', { params: { department_id: departmentId } }).then((r) => r.data),

  getImpactTree: (changeId: number): Promise<ImpactTreeResponse> =>
    client.get(`/v1/changes/${changeId}/impact-tree`).then((r) => r.data),
  suggestImpact: (changeId: number, partIds: number[]): Promise<{ suggested_part_ids: number[] }> =>
    client.post(`/v1/changes/${changeId}/impact-tree/suggest`, { part_ids: partIds }).then((r) => r.data),
  applyImpactSelection: (changeId: number, partIds: number[]): Promise<{ impacted_part_ids: number[] }> =>
    client.put(`/v1/changes/${changeId}/impacted-items`, { part_ids: partIds }).then((r) => r.data),
  confirmImpact: (changeId: number): Promise<ChangeDetail> =>
    client.post(`/v1/changes/${changeId}/impact/confirm`).then((r) => r.data),

  getImplementation: (changeId: number): Promise<ImplementationProgress> =>
    client.get(`/v1/changes/${changeId}/implementation`).then((r) => r.data),
  signNoGeometryChange: (partId: number, revisionId: number, reason: string) =>
    client.post(`/v1/parts/${partId}/revisions/${revisionId}/no-geometry-change`, { reason }).then((r) => r.data),

  listMeetings: (id: number) =>
    client.get<ChangeMeeting[]>(`/v1/changes/${id}/meetings`).then((r) => r.data),
  createMeeting: (id: number, body: {
    meeting_date?: string; channel?: 'meeting' | 'chat' | 'email';
    participants: MeetingParticipant[];
    notes?: string; selected_department_ids: number[];
  }) => client.post<ChangeMeeting>(`/v1/changes/${id}/meetings`, body).then((r) => r.data),
  updateMeeting: (id: number, meetingId: number, body: Record<string, unknown>) =>
    client.patch<ChangeMeeting>(`/v1/changes/${id}/meetings/${meetingId}`, body).then((r) => r.data),
  decideMeeting: (id: number, meetingId: number, decision: 'proceed' | 'reject' | 'needs_info') =>
    client.post<ChangeMeeting>(`/v1/changes/${id}/meetings/${meetingId}/decide`, { decision }).then((r) => r.data),
  approveInternalCosts: (id: number, note?: string) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/internal-approval`, { note: note ?? null }).then((r) => r.data),
};
