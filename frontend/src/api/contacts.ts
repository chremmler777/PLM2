import client from './client'

export interface Contact {
  name: string
  email?: string | null
  source?: string
  /** The PLM2 user behind the contact, when the backend could resolve one:
   *  an attendee picked from it is stored as that user, not as free text. */
  user_id?: number | null
  /** The PLM2 user's department(s), so two people of the same name can be
   *  told apart in the picker. */
  department?: string | null
}

export const contactsApi = {
  list: () => client.get<Contact[]>('/v1/contacts').then((r) => r.data),
}
