import client from './client';
import type {
  ChangeRequest, ChangeDetail, ChangelogEntry, ChangeTask,
  ChangeRouting, DeviationRequest,
} from '../types/change';

export const changesApi = {
  list: (params: { project_id?: number; status?: string; change_type?: string }) =>
    client.get<ChangeRequest[]>('/v1/changes', { params }).then((r) => r.data),

  get: (id: number) =>
    client.get<ChangeDetail>(`/v1/changes/${id}`).then((r) => r.data),

  create: (body: {
    project_id: number; title: string; change_type: string;
    reason?: string; description?: string; priority?: string; lead_id?: number;
  }) => client.post<ChangeRequest>('/v1/changes', body).then((r) => r.data),

  update: (id: number, body: Record<string, unknown>) =>
    client.patch<ChangeRequest>(`/v1/changes/${id}`, body).then((r) => r.data),

  transition: (id: number, to_status: string, opts?: { justification?: string; cancellation_reason?: string }) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/transition`, { to_status, ...opts }).then((r) => r.data),

  addImpactedItem: (id: number, body: { part_id: number; impact_note?: string; eng_level_before?: string }) =>
    client.post(`/v1/changes/${id}/impacted-items`, body).then((r) => r.data),

  removeImpactedItem: (id: number, itemId: number) =>
    client.delete(`/v1/changes/${id}/impacted-items/${itemId}`).then((r) => r.data),

  seedImpacted: (id: number) =>
    client.post(`/v1/changes/${id}/impacted-items/seed`).then((r) => r.data),

  submitAssessment: (id: number, body: { department_id: number; verdict: string; cost_impact?: number; lead_time_impact_days?: number; conditions?: string; notes?: string }) =>
    client.post(`/v1/changes/${id}/assessments`, body).then((r) => r.data),

  customerResponse: (id: number, response: string) =>
    client.post(`/v1/changes/${id}/customer-response`, { response }).then((r) => r.data),

  signOff: (id: number, role: 'pm' | 'quality') =>
    client.post(`/v1/changes/${id}/sign-off`, { role }).then((r) => r.data),

  changelog: (id: number) =>
    client.get<ChangelogEntry[]>(`/v1/changes/${id}/changelog`).then((r) => r.data),

  myTasks: () =>
    client.get<ChangeTask[]>('/v1/changes/my-tasks').then((r) => r.data),

  uploadAttachment: (id: number, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return client.post(`/v1/changes/${id}/attachments`, fd).then((r) => r.data);
  },

  getRouting: (id: number) =>
    client.get<ChangeRouting>(`/v1/changes/${id}/routing`).then((r) => r.data),

  postDeviation: (id: number, body: DeviationRequest) =>
    client.post<ChangeRouting>(`/v1/changes/${id}/routing/deviation`, body).then((r) => r.data),

  approveDeviation: (id: number) =>
    client.post<ChangeRouting>(`/v1/changes/${id}/routing/deviation/approve`).then((r) => r.data),
};
