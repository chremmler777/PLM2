/**
 * Image and print export. The whole chart (all rows, not just the visible
 * window) is drawn as one standalone SVG string with literal colours, then
 * rasterised through a canvas (PNG) or opened in a print window.
 */
import { fmtShort, toDay, type Cal } from './engine/calendar'
import { key } from './engine/tree'
import type { GanttLink, GanttTask } from './engine/types'
import type { GanttMarker, TaskGeo } from './GanttChart'
import type { CellContext, GanttColumn } from './columns'
import {
  anchorX, barGeo, linkSides, majorTicks, minorTicks, offDaySpans, routeLink, xOf,
  type Range, type Row, type Zoom,
} from './layout'
import { DEFAULT_KIND, type GanttKindStyle, type GanttTheme } from './theme'

export interface SvgExportInput {
  title?: string
  rows: Row[]
  columns: GanttColumn[]
  ctx: (t: GanttTask) => CellContext
  geo: Map<string, TaskGeo>
  links: GanttLink[]
  range: Range
  ppd: number
  unit: Zoom
  cal: Cal
  theme: GanttTheme
  kinds: Record<string, GanttKindStyle>
  markers: GanttMarker[]
  today: number | null
  critical: Set<string> | null
  showBaselines: boolean
  rowH: number
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
const HEADER = 44
const TITLE = 28

/** Truncate text to a pixel width (rough, 11px font). */
export function clip(s: string, px: number, size = 11): string {
  const max = Math.floor((px - 6) / (size * 0.56))
  if (s.length <= max) return s
  return max <= 1 ? '' : `${s.slice(0, max - 1)}…`
}

export function buildChartSvg(p: SvgExportInput): { svg: string; width: number; height: number } {
  const th = p.theme
  const gw = p.columns.reduce((n, c) => n + c.width, 0)
  const cw = (p.range.to - p.range.from) * p.ppd
  const width = Math.ceil(gw + cw)
  const top = (p.title ? TITLE : 0)
  const strip = p.markers.length ? 16 : 0
  const bodyTop = top + HEADER + strip
  const height = Math.ceil(bodyTop + Math.max(1, p.rows.length) * p.rowH)
  const o: string[] = []
  o.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" font-family="Inter, Segoe UI, Arial, sans-serif">`)
  o.push(`<rect width="${width}" height="${height}" fill="${th.bg}"/>`)
  if (p.title) o.push(`<text x="10" y="19" font-size="14" font-weight="700" fill="${th.text}">${esc(p.title)}</text>`)
  // Grid header
  o.push(`<rect x="0" y="${top}" width="${width}" height="${HEADER + strip}" fill="${th.headerBg}"/>`)
  let cx = 0
  for (const c of p.columns) {
    o.push(`<text x="${cx + 6}" y="${top + HEADER + strip - 8}" font-size="10" fill="${th.textFaint}">${esc(c.title.toUpperCase())}</text>`)
    cx += c.width
  }
  // Chart header
  const X = (d: number) => gw + xOf(d, p.range, p.ppd)
  o.push(`<rect x="${gw}" y="${top}" width="${cw}" height="${HEADER}" fill="${th.headerBg}"/>`)
  for (const m of majorTicks(p.range, p.ppd, p.unit)) {
    o.push(`<line x1="${gw + m.x}" x2="${gw + m.x}" y1="${top}" y2="${top + HEADER}" stroke="${th.gridLine}"/>`)
    if (m.label) o.push(`<text x="${gw + m.x + 6}" y="${top + 15}" font-size="11" font-weight="600" fill="${th.text}">${esc(m.label)}</text>`)
  }
  o.push(`<line x1="${gw}" x2="${width}" y1="${top + 22.5}" y2="${top + 22.5}" stroke="${th.gridLine}"/>`)
  for (const t of minorTicks(p.range, p.ppd, p.unit)) {
    o.push(`<line x1="${gw + t.x}" x2="${gw + t.x}" y1="${top + 23}" y2="${top + HEADER}" stroke="${th.rowLine}"/>`)
    if (t.label) o.push(`<text x="${gw + t.x + t.w / 2}" y="${top + 37}" font-size="10" text-anchor="middle" fill="${th.textFaint}">${esc(t.label)}</text>`)
  }
  o.push(`<line x1="0" x2="${width}" y1="${bodyTop - 0.5}" y2="${bodyTop - 0.5}" stroke="${th.gridLine}"/>`)
  const bodyH = height - bodyTop
  if (p.unit === 'day' || p.unit === 'week') {
    for (const s of offDaySpans(p.range, p.cal)) o.push(`<rect x="${X(s.day)}" y="${bodyTop}" width="${s.len * p.ppd}" height="${bodyH}" fill="${th.offDay}"/>`)
  }
  o.push(`<line x1="${gw - 0.5}" x2="${gw - 0.5}" y1="${top}" y2="${height}" stroke="${th.gridLine}"/>`)
  const pad = 7
  const barH = p.rowH - 2 * pad
  const idx = new Map<string, number>()
  p.rows.forEach((r, i) => { if (r.type === 'task') idx.set(key(r.task.id), i) })
  // Rows + grid text
  p.rows.forEach((r, i) => {
    const y = bodyTop + i * p.rowH
    if (r.type === 'group') {
      o.push(`<rect x="0" y="${y}" width="${width}" height="${p.rowH}" fill="${th.groupBg}"/>`)
      o.push(`<text x="8" y="${y + p.rowH / 2 + 3.5}" font-size="10" font-weight="700" fill="${th.text}">${esc(r.label.toUpperCase())} (${r.count})</text>`)
      return
    }
    o.push(`<line x1="0" x2="${width}" y1="${y + p.rowH - 0.5}" y2="${y + p.rowH - 0.5}" stroke="${th.rowLine}"/>`)
    const c = p.ctx(r.task)
    let x = 0
    for (const col of p.columns) {
      const raw = col.text?.(r.task, c) ?? ''
      const indent = col.key === 'name' ? r.depth * 14 + 4 : 0
      const txt = clip(raw, col.width - indent)
      const anchor = col.align === 'right' ? 'end' : 'start'
      const tx = col.align === 'right' ? x + col.width - 6 : x + 6 + indent
      o.push(`<text x="${tx}" y="${y + p.rowH / 2 + 3.5}" font-size="11" text-anchor="${anchor}" fill="${col.key === 'name' ? th.text : th.textMuted}"${r.summary && col.key === 'name' ? ' font-weight="600"' : ''}>${esc(txt)}</text>`)
      x += col.width
    }
  })
  // Markers + today
  for (const m of p.markers) {
    const x = X(toDay(m.date))
    o.push(`<line x1="${x}" x2="${x}" y1="${top + HEADER}" y2="${height}" stroke="${m.color ?? '#94a3b8'}" stroke-width="1.5" stroke-dasharray="4 3"/>`)
    // Label in the marker strip under the scale, never over bars.
    o.push(`<text x="${x + 4}" y="${top + HEADER + 12}" font-size="10" font-weight="600" fill="${m.color ?? '#94a3b8'}">${esc(`${m.label} ${fmtShort(toDay(m.date))}`)}</text>`)
  }
  if (p.today != null && p.today >= p.range.from && p.today <= p.range.to) {
    o.push(`<line x1="${X(p.today)}" x2="${X(p.today)}" y1="${bodyTop}" y2="${height}" stroke="${th.today}" stroke-width="1.5"/>`)
  }
  // Links
  const geoOf = (k: string) => { const g = p.geo.get(k); return g ? barGeo(g.s, g.e, p.range, p.ppd, g.milestone) : null }
  o.push(`<defs><marker id="a" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 Z" fill="${th.link}"/></marker></defs>`)
  for (const l of p.links) {
    const fi = idx.get(key(l.from)), ti = idx.get(key(l.to))
    if (fi == null || ti == null) continue
    const fb = geoOf(key(l.from)), tb = geoOf(key(l.to))
    if (!fb || !tb) continue
    const s = linkSides(l.type)
    const d = routeLink({
      x1: anchorX(fb, s.from), y1: fi * p.rowH + pad + barH / 2, row1: fi, fromSide: s.from,
      x2: anchorX(tb, s.to), y2: ti * p.rowH + pad + barH / 2, row2: ti, toSide: s.to, rowH: p.rowH,
    })
    o.push(`<path transform="translate(${gw},${bodyTop})" d="${d}" fill="none" stroke="${th.link}" stroke-width="1.25" marker-end="url(#a)"/>`)
  }
  // Bars
  p.rows.forEach((r, i) => {
    if (r.type !== 'task') return
    const t = r.task
    const k = key(t.id)
    const b = geoOf(k)
    if (!b) return
    const y = bodyTop + i * p.rowH + pad
    const x = gw + b.x
    const style = (t.kind && p.kinds[t.kind]) || DEFAULT_KIND
    const color = t.color ?? style.color
    const crit = !!p.critical?.has(k) && !t.isIdea
    if (p.showBaselines && t.baselineStart && t.baselineEnd) {
      const bs = toDay(t.baselineStart), be = toDay(t.baselineEnd)
      o.push(`<rect x="${X(bs)}" y="${y + barH + 1}" width="${Math.max(2, (be - bs) * p.ppd)}" height="3" fill="${th.baseline}" opacity="0.6"/>`)
    }
    if (r.summary) {
      o.push(`<path d="M${x},${y + 2} H${x + b.w} V${y + 9} L${x + b.w - 5},${y + 14} L${x + b.w - 10},${y + 9} H${x + 10} L${x + 5},${y + 14} L${x},${y + 9} Z" fill="${crit ? th.critical : th.summary}"/>`)
    } else if (b.milestone || style.milestone) {
      const cy = y + barH / 2
      o.push(`<path d="M${x},${cy - 7} L${x + 7},${cy} L${x},${cy + 7} L${x - 7},${cy} Z" fill="${t.isIdea ? 'none' : color}" stroke="${crit ? th.critical : color}"/>`)
    } else {
      if (crit) o.push(`<rect x="${x - 2.5}" y="${y - 2.5}" width="${b.w + 5}" height="${barH + 5}" rx="4" fill="none" stroke="${th.critical}" stroke-width="1.5"/>`)
      const dash = t.isIdea ? ' stroke-dasharray="4 3"' : ''
      o.push(`<rect x="${x}" y="${y}" width="${b.w}" height="${barH}" rx="3" fill="${color}" fill-opacity="${t.isIdea ? 0.25 : 0.92}" stroke="${t.isIdea ? color : 'none'}"${dash}/>`)
      if (style.pattern === 'hatch') {
        for (let hx = x - barH; hx < x + b.w; hx += 6) {
          const x1 = Math.max(x, hx), x2 = Math.min(x + b.w, hx + barH)
          if (x2 > x1) o.push(`<line x1="${x1}" y1="${y + barH - (x1 - hx)}" x2="${x2}" y2="${y + barH - (x2 - hx)}" stroke="#94a3b8" stroke-width="1.5"/>`)
        }
      }
    }
    const lx = b.milestone ? x + 12 : x + b.w + 6
    o.push(`<text x="${lx}" y="${y + barH / 2 + 3.5}" font-size="11" fill="${t.isIdea ? th.idea : th.textMuted}">${esc(t.name)}</text>`)
  })
  o.push('</svg>')
  return { svg: o.join(''), width, height }
}

/** Rasterise an SVG string to a PNG blob (2x for sharpness, capped for huge charts). */
export function svgToPng(svg: string, width: number, height: number, scale = 2): Promise<Blob> {
  return new Promise((resolve, reject) => {
    const maxSide = 16000
    const s = Math.max(0.25, Math.min(scale, maxSide / width, maxSide / height))
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = Math.ceil(width * s)
      canvas.height = Math.ceil(height * s)
      const ctx = canvas.getContext('2d')
      if (!ctx) { reject(new Error('Canvas is not available')); return }
      ctx.scale(s, s)
      ctx.drawImage(img, 0, 0)
      canvas.toBlob((b) => (b ? resolve(b) : reject(new Error('Could not create the image'))), 'image/png')
    }
    img.onerror = () => reject(new Error('Could not render the chart image'))
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
  })
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** HTML for the print window: the chart scaled to the page width, landscape. */
export function printHtml(svg: string, title: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(title)}</title>
<style>@page{size:A3 landscape;margin:10mm}html,body{margin:0;background:#fff}svg{width:100%;height:auto}</style></head>
<body>${svg}<script>window.onload=function(){setTimeout(function(){window.print()},50)}</script></body></html>`
}

export function openPrint(svg: string, title: string): boolean {
  const w = window.open('', '_blank')
  if (!w) return false
  w.document.open()
  w.document.write(printHtml(svg, title))
  w.document.close()
  return true
}
