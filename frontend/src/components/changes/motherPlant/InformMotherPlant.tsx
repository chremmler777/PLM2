/**
 * "Inform mother plant" (spec 2026-09-25 §14): on a mother-plant change the
 * validated timing is not published to a customer; the PM tells the mother
 * plant and stamps it here (POST /changes/{id}/mother-plant/inform).
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { motherPlantApi, motherPlantKey } from '../../../api/motherPlant'
import { formatDate } from '../../../lib/format'
import type { ChangeRequest } from '../../../types/change'
import { plantName, plantText } from '../../../lib/plantName'
import { btnPrimary } from '../../common/buttonStyles'
import { toastError } from '../../../lib/apiError'

const primary = btnPrimary

export default function InformMotherPlant({ change, canInform, timingValidated }: {
  change: ChangeRequest; canInform: boolean; timingValidated: boolean
}) {
  const qc = useQueryClient()
  const inform = useMutation({
    mutationFn: () => motherPlantApi.inform(change.id),
    onSuccess: (s) => {
      qc.setQueryData(motherPlantKey(change.id), s)
      qc.invalidateQueries({ queryKey: ['change', change.id] })
      qc.invalidateQueries({ queryKey: ['change-my-actions', change.id] })
      toast.success(plantText('mp.informed', change.mother_plant_name))
    },
    onError: (e: unknown) => toastError(e, 'Could not record it'),
  })
  const live = ['approved', 'in_implementation'].includes(change.status)
  const plant = plantName(change.mother_plant_name)
  return (
    <div className="flex flex-wrap items-center gap-3" data-testid="timing-inform-mother">
      {change.plan_published_at ? (
        <p className="text-sm text-emerald-300" data-testid="timing-mother-informed">
          {plant} informed of the timing {formatDate(change.plan_published_at)}
          {change.plan_published_by_name ? ` by ${change.plan_published_by_name}` : ''}.
        </p>
      ) : (
        <p className="text-sm text-slate-300">{plantText('mp.stillToTell', change.mother_plant_name)}</p>
      )}
      {live && timingValidated && canInform && (
        <>
          <button type="button" className={primary} disabled={inform.isPending}
            onClick={() => inform.mutate()} data-testid="timing-inform-mother-button">
            {plantText(change.plan_published_at ? 'mp.informAgain' : 'mp.inform', change.mother_plant_name)}
          </button>
          <span className="text-xs text-slate-400">Records that the PM sent them the validated timing. Export it above to attach.</span>
        </>
      )}
      {live && timingValidated && !canInform && !change.plan_published_at && (
        <span className="text-xs text-slate-400">{plantText('mp.pmInforms', change.mother_plant_name)}</span>
      )}
    </div>
  )
}
