import { useQuery } from '@tanstack/react-query'
import { pnlApi } from '../../../api/pnl'
import OfferVsActualTable from './OfferVsActualTable'
import ActualCostsPanel from './ActualCostsPanel'

/** The actual-phase half of the P&L card: the offer-vs-actual table and the
 *  actual cost entries that feed it. */
export default function OfferVsActualSection({ changeId, departments }: {
  changeId: number
  departments?: { id: number; name: string }[]
}) {
  const { data } = useQuery({
    queryKey: ['offer-vs-actual', changeId],
    queryFn: () => pnlApi.offerVsActual(changeId),
    retry: false,
  })
  return (
    <>
      {data && <OfferVsActualTable data={data} />}
      <ActualCostsPanel changeId={changeId} departments={departments} />
    </>
  )
}
