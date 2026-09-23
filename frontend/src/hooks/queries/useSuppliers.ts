/**
 * Supplier options for pickers (part supplier, toolmaker). Active suppliers only.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

export interface SupplierOption {
  id: number;
  name: string;
}

export function useSuppliers() {
  return useQuery<SupplierOption[]>({
    queryKey: ['suppliers', false],
    queryFn: async () => (await client.get('/v1/suppliers')).data,
  });
}
