/**
 * The other plant a change comes from (origin mother_plant, spec §14), named
 * the way people say it: "KTX Weissenburg", "KTX Solingen". The stored name
 * may carry a code in brackets ("KTX Weissenburg (WUG)"); the screen drops
 * it. Without a name the text says both plants.
 */
import { t, type Lang } from '../i18n/cmLabels'

export const plantName = (name?: string | null): string =>
  name?.trim() ? name.trim().replace(/\s*\([^)]*\)$/, '').trim() : t('mp.generic')

/** A cmLabels text with the plant in its `{p}` slot. */
export const plantText = (key: string, name?: string | null, lang: Lang = 'en'): string =>
  t(key, lang).split('{p}').join(plantName(name))
