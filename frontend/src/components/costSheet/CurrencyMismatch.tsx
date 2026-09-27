/**
 * Rows whose currency is not their plant's quote currency (for example a
 * Silao row copied from before the plant's currency changed). Shown on the
 * draft and in the publish dialog. Nothing is relabelled or converted: the
 * number was typed in the row's currency, so Sales checks it.
 */
import type { CurrencyMismatchRow } from '../../types/costSheet'

/** "Silao Mexico (quote currency USD): 2 rows in EUR" per plant and currency. */
export function mismatchLines(rows: CurrencyMismatchRow[]): string[] {
  const groups = new Map<string, { plant: string; quote: string; cur: string; n: number }>()
  for (const r of rows) {
    const key = `${r.plant_id}|${r.currency}`
    const g = groups.get(key)
    if (g) g.n += 1
    else groups.set(key, { plant: r.plant_name, quote: r.plant_currency, cur: r.currency, n: 1 })
  }
  return [...groups.values()].map((g) =>
    `${g.plant} (quote currency ${g.quote}): ${g.n} ${g.n === 1 ? 'row' : 'rows'} in ${g.cur}`)
}

export default function CurrencyMismatch({ rows, publishing = false }: {
  rows: CurrencyMismatchRow[] | undefined
  /** In the publish dialog: says the rows are published as they are. */
  publishing?: boolean
}) {
  if (!rows || rows.length === 0) return null
  return (
    <div role="status" data-testid="currency-mismatch"
      className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
      <p className="font-medium">
        {rows.length === 1 ? '1 row is' : `${rows.length} rows are`} not in their plant&apos;s quote currency.
      </p>
      <ul className="mt-1 list-disc pl-5 text-amber-200/90">
        {mismatchLines(rows).map((l) => <li key={l}>{l}</li>)}
      </ul>
      <p className="mt-1 text-amber-200/80">
        {publishing
          ? 'They are published as they are: nothing is converted. Costing at that plant then shows the amounts per currency.'
          : 'Nothing is converted. Check each rate and switch the row to the quote currency where the number is in it.'}
      </p>
    </div>
  )
}
