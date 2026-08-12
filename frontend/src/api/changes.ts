import client from './client';
import type {
  ChangeRequest, ChangeDetail, ChangeTask,
  ChangeRouting, DeviationRequest,
  CostLine, CostLineIn, Summation, Gate, DepartmentRateRef, ActivityRef,
  TransitionDeviation, ImpactTreeResponse, ImplementationProgress, MyActionsResponse,
  ChangeMeeting, MeetingParticipant, ChangeConcern, ConcernKind, AttachmentKind,
  AssessmentObjectsResponse, ChecklistItemDef, RiskType, RiskSeverity,
  CostPosition, CostPositionIn, CostingOffer, CostingOfferIn,
  ChangeNegotiation, NegotiationChannel, BankBuildMode,
  ImplBooking, ImplReport, ImplEscalation, ImplEscalationDirection, ImplDepartmentState,
  ValidationState, ValidationCheckKey,
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

  transition: (id: number, to_status: string, opts?: {
    cancellation_reason?: string;
    /**
     * Why the flow is going backwards. Mandatory on in_validation →
     * in_implementation: a change that returns to the shop floor because its
     * checks did not pass has to say so in writing.
     */
    reason?: string;
  }) =>
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

  // What each routed department is actually assessing — tools, gauges, documents
  // and parts, derived from the impacted set.
  assessmentObjects: (id: number) =>
    client.get<AssessmentObjectsResponse>(`/v1/changes/${id}/assessment-objects`)
      .then((r) => r.data),

  submitAssessment: (id: number, body: { department_id: number; verdict: string; cost_impact?: number; lead_time_impact_days?: number; conditions?: string; notes?: string; effort_hours?: number; details?: Record<string, unknown> }) =>
    client.post(`/v1/changes/${id}/assessments`, body).then((r) => r.data),

  customerResponse: (
    id: number,
    response: string,
    body?: { release_due_date?: string; release_due_reason?: string | null },
  ) =>
    client.post(`/v1/changes/${id}/customer-response`, { response, ...body }).then((r) => r.data),

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

  uploadAttachment: (
    id: number, file: File,
    opts?: {
      kind?: AttachmentKind; respondsToId?: number;
      concernId?: number; assessmentId?: number; costingOfferId?: number;
    },
  ) => {
    const fd = new FormData();
    fd.append('file', file);
    // Classified uploads carry their place in the needs-info loop; a plain
    // document sends neither field and stays 'general' server-side.
    if (opts?.kind) fd.append('kind', opts.kind);
    if (opts?.respondsToId !== undefined) fd.append('responds_to_id', String(opts.respondsToId));
    // Belongs to one container — a question card or a department's assessment —
    // so it lands there and nowhere else.
    if (opts?.concernId !== undefined) fd.append('concern_id', String(opts.concernId));
    if (opts?.assessmentId !== undefined) fd.append('assessment_id', String(opts.assessmentId));
    // A vendor quote belongs to the offer it prices, not to the change at large.
    if (opts?.costingOfferId !== undefined) fd.append('costing_offer_id', String(opts.costingOfferId));
    // The client sets a global Content-Type: application/json default; it must
    // be cleared here so the browser sets multipart/form-data WITH its boundary.
    // Otherwise FastAPI can't find the `file` field and returns 422.
    return client
      .post(`/v1/changes/${id}/attachments`, fd, {
        headers: { 'Content-Type': undefined },
      })
      .then((r) => r.data);
  },

  // Sales confirms the rejection letter went out; the backend closes the change.
  markRejectionSent: (id: number) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/rejection-sent`).then((r) => r.data),

  deleteAttachment: (id: number, attachmentId: number) =>
    client.delete(`/v1/changes/${id}/attachments/${attachmentId}`).then((r) => r.data),

  recommendedDepartments: (id: number) =>
    client.get<{ id: number; name: string }[]>(`/v1/changes/${id}/recommended-departments`)
      .then((r) => r.data),

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
  // How long this department needs once the work starts — the timing half of
  // costing, kept next to the money it belongs with.
  setCostLeadTime: (id: number, departmentId: number, days: number) =>
    client.post(`/v1/changes/${id}/cost-lead-time`, {
      department_id: departmentId, lead_time_days: days,
    }).then((r) => r.data),

  // What the part will weigh, as the Tool Engineer quotes it during costing.
  // An estimate by contract: the validated figure is a separate field the
  // backend fills later, so this endpoint only ever writes the guess.
  setWeightEstimate: (id: number, weightG: number | null) =>
    client.put(`/v1/changes/${id}/weight-estimate`, { weight_g: weightG })
      .then((r) => r.data),

  // Cost positions — what a department books against the change, next to the
  // old grid. One list for the whole change; each row names its department.
  listCostPositions: (id: number) =>
    client.get<CostPosition[]>(`/v1/changes/${id}/costing/positions`).then((r) => r.data),
  createCostPosition: (id: number, body: CostPositionIn) =>
    client.post<CostPosition>(`/v1/changes/${id}/costing/positions`, body).then((r) => r.data),
  updateCostPosition: (id: number, pid: number, body: Partial<CostPositionIn>) =>
    client.put<CostPosition>(`/v1/changes/${id}/costing/positions/${pid}`, body).then((r) => r.data),
  deleteCostPosition: (id: number, pid: number) =>
    client.delete(`/v1/changes/${id}/costing/positions/${pid}`).then((r) => r.data),

  // Vendor offers under an external position — one row per vendor asked.
  addCostingOffer: (id: number, pid: number, body: CostingOfferIn) =>
    client.post<CostingOffer>(`/v1/changes/${id}/costing/positions/${pid}/offers`, body)
      .then((r) => r.data),
  // The favourite is exclusive: sending {favorite: true} clears its siblings
  // server-side, so the client only has to say which one won.
  updateCostingOffer: (id: number, oid: number, body: Partial<CostingOfferIn> & { favorite?: boolean }) =>
    client.put<CostingOffer>(`/v1/changes/${id}/costing/offers/${oid}`, body).then((r) => r.data),
  // Sales' binding pick at quoting. Choosing clears the siblings server-side;
  // a reason is required whenever the pick is not the department's favourite
  // (the server answers 400 without one).
  chooseCostingOffer: (id: number, oid: number, reason?: string) =>
    client.put<CostingOffer>(`/v1/changes/${id}/costing/offers/${oid}/choose`,
      reason ? { reason } : {}).then((r) => r.data),
  deleteCostingOffer: (id: number, oid: number) =>
    client.delete(`/v1/changes/${id}/costing/offers/${oid}`).then((r) => r.data),

  // The tag vocabulary a department may file a position under.
  costingTags: (departmentId?: number) =>
    client.get<{ items: { key: string }[] }>('/v1/changes/reference/costing-tags',
      { params: departmentId != null ? { department_id: departmentId } : undefined })
      .then((r) => r.data),

  getSummation: (id: number) =>
    client.get<Summation>(`/v1/changes/${id}/summation`).then((r) => r.data),
  getGates: (id: number) =>
    client.get<Gate[]>(`/v1/changes/${id}/gates`).then((r) => r.data),
  putGate: (id: number, gateKey: string, body: { decision: string; remark?: string }) =>
    client.put<Gate>(`/v1/changes/${id}/gates/${gateKey}`, body).then((r) => r.data),
  referenceRates: () =>
    client.get<DepartmentRateRef[]>('/v1/changes/reference/rates').then((r) => r.data),
  // What a department is asked at assessment: the common questions plus its own.
  assessmentChecklist: (departmentId: number) =>
    client.get<ChecklistItemDef[]>('/v1/changes/reference/assessment-checklist',
      { params: { department_id: departmentId } }).then((r) => r.data),

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
  listConcerns: (id: number) =>
    client.get<ChangeConcern[]>(`/v1/changes/${id}/concerns`).then((r) => r.data),
  // Only risks are raisable now: a kind, how bad it is, and what it is about.
  // The old reject_proposal / needs_info raises are gone from the API.
  raiseConcern: (id: number, body: {
    kind: ConcernKind; note: string; department_id?: number;
    risk_type?: RiskType; severity?: RiskSeverity;
  }) => client.post<ChangeConcern>(`/v1/changes/${id}/concerns`, body).then((r) => r.data),

  // The risk vocabulary is the backend's list, not a hard-coded one here.
  riskTypes: () =>
    client.get<{ items: { key: string }[] }>('/v1/changes/reference/risk-types')
      .then((r) => r.data),
  // Answering records what the customer said; it does not close the question —
  // the asking side (or PM) still decides whether it is settled.
  answerConcern: (id: number, concernId: number, note: string) =>
    client.post<ChangeConcern>(`/v1/changes/${id}/concerns/${concernId}/answer`, { note })
      .then((r) => r.data),

  // Withdrawal is a recorded act, not a delete: the note says how the point was
  // addressed (mandatory for department-scoped concerns, optional in scoping).
  withdrawConcern: (id: number, concernId: number, resolutionNote?: string) =>
    client.post<ChangeConcern>(`/v1/changes/${id}/concerns/${concernId}/withdraw`, {
      resolution_note: resolutionNote ?? null,
    }).then((r) => r.data),
  decideMeeting: (id: number, meetingId: number, decision: 'proceed' | 'reject' | 'needs_info', reason?: string) =>
    client.post<ChangeMeeting>(`/v1/changes/${id}/meetings/${meetingId}/decide`, { decision, reason }).then((r) => r.data),
  approveInternalCosts: (
    id: number,
    body: { note?: string | null; release_due_date?: string; release_due_reason?: string | null },
  ) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/internal-approval`, {
      note: body.note ?? null,
      release_due_date: body.release_due_date,
      release_due_reason: body.release_due_reason ?? null,
    }).then((r) => r.data),

  // The negotiation log at `quoted`: rounds in the order they happened, and the
  // one entry Sales marked as the result. Posting a final clears the flag on
  // the others server-side — the client never has to reconcile that itself.
  listNegotiations: (id: number) =>
    client.get<ChangeNegotiation[]>(`/v1/changes/${id}/negotiations`).then((r) => r.data),
  addNegotiation: (id: number, body: {
    channel: NegotiationChannel; note: string;
    counter_price?: number | null; is_final?: boolean;
  }) => client.post<ChangeNegotiation>(`/v1/changes/${id}/negotiations`, body).then((r) => r.data),
  deleteNegotiation: (id: number, negotiationId: number) =>
    client.delete(`/v1/changes/${id}/negotiations/${negotiationId}`).then((r) => r.data),

  // Stage 7: how the approved change reaches the line. Scheduling writes the
  // mode (and, for planned scrap, the additional quote the customer bears);
  // Sales publishes the resulting plan. Two calls because they are two people's
  // decisions, not two halves of one form.
  setBankBuild: (id: number, body: {
    mode: BankBuildMode; note?: string; scrap_quote_price?: number;
  }) => client.put<ChangeRequest>(`/v1/changes/${id}/bank-build`, body).then((r) => r.data),
  publishBankBuildPlan: (id: number) =>
    client.post<ChangeRequest>(`/v1/changes/${id}/bank-build/publish`).then((r) => r.data),

  // Stage 8: how the work is actually going. The board first — one row per
  // implementing department, with the backend's own cadence verdict — then the
  // three records the board is a summary of.
  implementationState: (id: number) =>
    client.get<{ departments?: ImplDepartmentState[] } | ImplDepartmentState[]>(`/v1/changes/${id}/implementation/state`)
      .then((r) => r.data),

  listImplBookings: (id: number) =>
    client.get<ImplBooking[]>(`/v1/changes/${id}/implementation/bookings`).then((r) => r.data),
  addImplBooking: (id: number, body: {
    department_id: number; hours: number; note?: string;
  }) => client.post<ImplBooking>(`/v1/changes/${id}/implementation/bookings`, body)
    .then((r) => r.data),
  deleteImplBooking: (id: number, bookingId: number) =>
    client.delete(`/v1/changes/${id}/implementation/bookings/${bookingId}`).then((r) => r.data),

  listImplReports: (id: number) =>
    client.get<ImplReport[]>(`/v1/changes/${id}/implementation/reports`).then((r) => r.data),
  addImplReport: (id: number, body: {
    department_id: number; note: string; at_risk: boolean; risk_note?: string;
  }) => client.post<ImplReport>(`/v1/changes/${id}/implementation/reports`, body)
    .then((r) => r.data),

  listImplEscalations: (id: number) =>
    client.get<ImplEscalation[]>(`/v1/changes/${id}/implementation/escalations`)
      .then((r) => r.data),
  addImplEscalation: (id: number, body: {
    direction: ImplEscalationDirection; note: string; report_id?: number;
  }) => client.post<ImplEscalation>(`/v1/changes/${id}/implementation/escalations`, body)
    .then((r) => r.data),
  // Resolving is a written act, like withdrawing a concern: the note says how
  // the escalation was settled, and the row stays as the record.
  resolveImplEscalation: (id: number, escalationId: number, resolutionNote: string) =>
    client.put<ImplEscalation>(
      `/v1/changes/${id}/implementation/escalations/${escalationId}/resolve`,
      { resolution_note: resolutionNote },
    ).then((r) => r.data),

  // Stage 9: does the change actually work? One payload for the whole board —
  // the per-department checks plus the two planned figures they are measured
  // against, so the panel never has to correlate costing and validation itself.
  validationState: (id: number) =>
    client.get<ValidationState>(`/v1/changes/${id}/validation/state`).then((r) => r.data),

  // A department answers its own check. `value` carries the measurement for the
  // two checks that have one (cycle time in seconds, weight in grams); a fail
  // carries the note that says what went wrong.
  setValidationCheck: (id: number, body: {
    department_id: number;
    check_key: ValidationCheckKey | (string & {});
    status: 'passed' | 'failed';
    value?: number;
    note?: string;
  }) => client.post(`/v1/changes/${id}/validation/checks`, body).then((r) => r.data),

  // Sales confirming the validated weight has been taken into the quote. The
  // note is optional: acknowledging is the act, explaining it is a courtesy.
  acknowledgeWeightDelta: (id: number, note?: string) =>
    client.post(`/v1/changes/${id}/validation/weight-ack`,
      note && note.trim() !== '' ? { note: note.trim() } : {}).then((r) => r.data),
};
