import client from './client'

export interface Contact {
  name: string
  email?: string | null
  source?: string
}

export const contactsApi = {
  list: () => client.get<Contact[]>('/v1/contacts').then((r) => r.data),
}
