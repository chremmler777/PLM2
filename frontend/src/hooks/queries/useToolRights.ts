/**
 * May the viewer change tool data (tool fields, produces links, shrinkage, DFM)?
 * Tool Engineer or admin (backend app/services/tool_rights.py, /auth/me can_edit_tools;
 * "Act as" another department makes it view only). The backend enforces it; this only
 * hides the controls. Until /auth/me answers, and when it does not say, controls stay.
 *
 * Gauges and assembly equipment (EOATs included) follow the same pattern from the same
 * /auth/me answer (backend app/services/equipment_rights.py): gauges are APQP or
 * Project Manager, assembly equipment is Manufacturing Engineer or Project Manager.
 */
import { useQuery } from '@tanstack/react-query';
import client from '../../api/client';

interface ItemRights {
  can_edit_tools?: boolean;
  can_edit_gauges?: boolean;
  can_edit_assembly_equipment?: boolean;
}

function useItemRights(): ItemRights | undefined {
  const { data } = useQuery({
    queryKey: ['auth-me-tool-rights'],
    queryFn: async () => (await client.get('/v1/auth/me')).data as ItemRights,
    staleTime: 5 * 60_000,
  });
  return data;
}

export function useCanEditTools(): boolean {
  return useItemRights()?.can_edit_tools !== false;
}

export function useCanEditGauges(): boolean {
  return useItemRights()?.can_edit_gauges !== false;
}

export function useCanEditAssemblyEquipment(): boolean {
  return useItemRights()?.can_edit_assembly_equipment !== false;
}
