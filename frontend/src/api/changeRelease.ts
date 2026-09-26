import client from './client'
import type { LessonIn, LessonOut, ReleaseCheckAnswer, ReleaseState } from '../types/changeRelease'

/** Release checklist and lessons learned of a change (spec section 7). */
export const changeReleaseApi = {
  get: (changeId: number) =>
    client.get<ReleaseState>(`/v1/changes/${changeId}/release`).then((r) => r.data),

  setCheck: (changeId: number, key: string, body: ReleaseCheckAnswer) =>
    client.post(`/v1/changes/${changeId}/release/checks/${key}`, body).then((r) => r.data),

  addLesson: (changeId: number, body: LessonIn) =>
    client.post<LessonOut>(`/v1/changes/${changeId}/lessons`, body).then((r) => r.data),

  /** Needs at least one lesson on the change, or a reason why there are none. */
  completeLessons: (changeId: number, noneReason?: string) =>
    client.post(`/v1/changes/${changeId}/lessons/complete`,
      noneReason ? { none_reason: noneReason } : {}).then((r) => r.data),
}
