import client from './client'
import type { OfferData, OfferOut } from '../types/changeOffer'

/** Offer versions of a change (spec section 6). Newest first on list. */
export const changeOfferApi = {
  list: (changeId: number) =>
    client.get<OfferOut[]>(`/v1/changes/${changeId}/offers`).then((r) => r.data),

  /** Creates the draft: v1 seeded from costing, later versions cloned. */
  create: (changeId: number) =>
    client.post<OfferOut>(`/v1/changes/${changeId}/offers`).then((r) => r.data),

  /** Draft only. Top-level keys deep-merge; a list replaces the list. */
  patch: (changeId: number, offerId: number, body: { data?: OfferData; currency?: string }) =>
    client.patch<OfferOut>(`/v1/changes/${changeId}/offers/${offerId}`, body).then((r) => r.data),

  /** Re-seeds cost lines and risks from costing, keeping overrides by key. */
  refresh: (changeId: number, offerId: number) =>
    client.post<OfferOut>(`/v1/changes/${changeId}/offers/${offerId}/refresh`).then((r) => r.data),

  send: (changeId: number, offerId: number, body: { received_at?: string; change_note?: string }) =>
    client.post<OfferOut>(`/v1/changes/${changeId}/offers/${offerId}/send`, body).then((r) => r.data),

  received: (changeId: number, offerId: number, receivedAt: string) =>
    client.post<OfferOut>(`/v1/changes/${changeId}/offers/${offerId}/received`,
      { received_at: receivedAt }).then((r) => r.data),

  /** The rendered PDF as a blob, for a new-tab preview through an object URL. */
  pdf: (changeId: number, offerId: number) =>
    client.get<Blob>(`/v1/changes/${changeId}/offers/${offerId}/pdf`, { responseType: 'blob' })
      .then((r) => r.data),
}
