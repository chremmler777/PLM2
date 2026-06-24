import client from './client';

export interface Plant {
  id: number;
  name: string;
  code: string;
}

export const plantsApi = {
  list: (): Promise<Plant[]> =>
    client.get<Plant[]>('/v1/plants').then((r) => r.data),
};
