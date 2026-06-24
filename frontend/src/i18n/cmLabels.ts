// Label keys for the Änderungsmitteilung UI. DE/EN now; sub-project C swaps the
// runtime locale. Components import t(key) instead of hard-coding strings.
export type Lang = 'de' | 'en';
export const cmLabels: Record<string, Record<Lang, string>> = {
  one_time: { de: 'Einmal-Aufwand', en: 'One-time cost' },
  lifecycle: { de: 'Lifecycle', en: 'Lifecycle' },
  internal: { de: 'interner Aufwand', en: 'Internal cost' },
  external: { de: 'externer Aufwand', en: 'External cost' },
  hours: { de: 'Stunden', en: 'Hours' },
  activity: { de: 'Tätigkeit', en: 'Activity' },
  total: { de: 'Summe', en: 'Total' },
  producibility: { de: 'Herstellbarkeit', en: 'Producibility' },
  feasibility: { de: 'Realisierbar?', en: 'Feasible?' },
  budget: { de: 'Budget geprüft?', en: 'Budget checked?' },
  release: { de: 'Techn. Freigabe?', en: 'Technical release?' },
};
export const t = (key: string, lang: Lang = 'en'): string => cmLabels[key]?.[lang] ?? key;
