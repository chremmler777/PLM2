import client from './client'
import type {
  EscalationLevel, IssueActionIn, IssueCostIn, IssueCreate, IssueCustomerIn, IssueOut,
  IssuePatch, IssueRouteIn,
} from '../types/validationIssue'

/** Validation issues of a change (spec 2026-09-25 §12). */
const base = (changeId: number) => `/v1/changes/${changeId}/validation/issues`

export const validationIssuesKey = (changeId: number) => ['change', changeId, 'validation-issues'] as const

export const validationIssuesApi = {
  list: (changeId: number) =>
    client.get<IssueOut[]>(base(changeId)).then((r) => r.data),

  create: (changeId: number, body: IssueCreate) =>
    client.post<IssueOut>(base(changeId), body).then((r) => r.data),

  update: (changeId: number, iid: number, body: IssuePatch) =>
    client.patch<IssueOut>(`${base(changeId)}/${iid}`, body).then((r) => r.data),

  contain: (changeId: number, iid: number, containment: string) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/contain`, { containment }).then((r) => r.data),

  rootCause: (changeId: number, iid: number, rootCause: string) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/root-cause`, { root_cause: rootCause }).then((r) => r.data),

  route: (changeId: number, iid: number, body: IssueRouteIn) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/route`, body).then((r) => r.data),

  customer: (changeId: number, iid: number, body: IssueCustomerIn) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/customer`, body).then((r) => r.data),

  cost: (changeId: number, iid: number, body: IssueCostIn) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/cost`, body).then((r) => r.data),

  addAction: (changeId: number, iid: number, body: IssueActionIn) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/actions`, body).then((r) => r.data),

  actionDone: (changeId: number, iid: number, aid: number) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/actions/${aid}/done`, {}).then((r) => r.data),

  close: (changeId: number, iid: number, note: string) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/close`, { note }).then((r) => r.data),

  /** Manual escalation (PM, lead, Sales) with a reason. */
  escalate: (changeId: number, iid: number, body: { level: EscalationLevel; reason: string }) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/escalate`, body).then((r) => r.data),

  acknowledge: (changeId: number, iid: number, eid: number) =>
    client.post<IssueOut>(`${base(changeId)}/${iid}/escalations/${eid}/acknowledge`, {}).then((r) => r.data),
}
