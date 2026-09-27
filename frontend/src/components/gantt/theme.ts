/**
 * Theme tokens. The component sets them as CSS variables on its root
 * (`--g-*`), so a host can override any of them with CSS; the image export
 * resolves the same names to literal colours.
 */
export type GanttThemeName = 'dark' | 'light'

export interface GanttTheme {
  bg: string
  panel: string
  headerBg: string
  gridLine: string
  rowLine: string
  text: string
  textMuted: string
  textFaint: string
  offDay: string
  groupBg: string
  selectBg: string
  hoverBg: string
  accent: string
  link: string
  linkBad: string
  critical: string
  baseline: string
  slip: string
  summary: string
  idea: string
  today: string
  focus: string
}

export const THEMES: Record<GanttThemeName, GanttTheme> = {
  dark: {
    bg: '#0f172a', panel: '#0f172a', headerBg: '#0b1222', gridLine: '#334155', rowLine: '#1e293b',
    text: '#e2e8f0', textMuted: '#94a3b8', textFaint: '#64748b', offDay: 'rgba(30,41,59,0.6)',
    groupBg: 'rgba(30,41,59,0.85)', selectBg: 'rgba(12,74,110,0.45)', hoverBg: 'rgba(30,41,59,0.6)',
    accent: '#38bdf8', link: '#64748b', linkBad: '#f87171', critical: '#ef4444', baseline: '#94a3b8',
    slip: '#ef4444', summary: '#cbd5e1', idea: '#fbbf24', today: '#38bdf8', focus: '#fbbf24',
  },
  light: {
    bg: '#ffffff', panel: '#ffffff', headerBg: '#f8fafc', gridLine: '#cbd5e1', rowLine: '#e2e8f0',
    text: '#0f172a', textMuted: '#475569', textFaint: '#94a3b8', offDay: 'rgba(226,232,240,0.7)',
    groupBg: 'rgba(241,245,249,0.95)', selectBg: 'rgba(186,230,253,0.55)', hoverBg: 'rgba(241,245,249,0.9)',
    accent: '#0284c7', link: '#64748b', linkBad: '#dc2626', critical: '#dc2626', baseline: '#64748b',
    slip: '#dc2626', summary: '#334155', idea: '#b45309', today: '#0284c7', focus: '#d97706',
  },
}

const cssName = (k: string) => `--g-${k.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`)}`

/** The CSS variables for a theme, as a style object. */
export function themeVars(t: GanttTheme): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(t)) out[cssName(k)] = v
  return out
}

/** `var(--g-link)` for a token. */
export const v = (k: keyof GanttTheme) => `var(${cssName(k)})`

/** Resolve the live values on an element (host overrides included). */
export function resolveTheme(el: Element | null, fallback: GanttTheme): GanttTheme {
  if (!el || typeof getComputedStyle !== 'function') return fallback
  const cs = getComputedStyle(el)
  const out = { ...fallback }
  for (const k of Object.keys(fallback) as (keyof GanttTheme)[]) {
    const val = cs.getPropertyValue(cssName(k)).trim()
    if (val) out[k] = val
  }
  return out
}

export interface GanttKindStyle {
  label: string
  color: string
  /** hatch = striped fill (buffers). */
  pattern?: 'solid' | 'hatch'
  /** Draw as a diamond whatever the duration. */
  milestone?: boolean
}

export const DEFAULT_KIND: GanttKindStyle = { label: 'Task', color: '#0ea5e9' }
