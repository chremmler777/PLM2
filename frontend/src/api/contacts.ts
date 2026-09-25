import client from './client'

export interface Contact {
  name: string
  email?: string | null
  source?: string
  /** The PLM2 user behind the contact, when the backend could resolve one:
   *  an attendee picked from it is stored as that user, not as free text. */
  user_id?: number | null
  username?: string | null
}

export const contactsApi = {
  list: () => client.get<Contact[]>('/v1/contacts').then((r) => r.data),
}
