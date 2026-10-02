"""Process-flow and Gantt graphics for the audit implementation plans.

Flows are drawn from explicit node positions (grid units) so every figure is
reproducible from this file; nothing is hand-edited afterwards.
"""
import json
import sys
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK = "#1F2937"
MUTED = "#6B7280"
FILL = {
    "stage": ("#E8EEF7", "#2F5597"),   # main path
    "gate": ("#FFF4DB", "#B7791F"),    # hard gate / decision
    "side": ("#EAF5EC", "#2F7D3B"),    # side track / feed
    "end": ("#F1F1F1", "#4B5563"),     # terminal
    "risk": ("#FCEBEA", "#B42318"),    # escalation
}


def _fit(fig, ax, txt, max_w):
    """Shrink a text until it fits max_w data units."""
    r = fig.canvas.get_renderer()
    px = ax.transData.transform((max_w, 0))[0] - ax.transData.transform((0, 0))[0]
    while txt.get_window_extent(r).width > px and txt.get_fontsize() > 5:
        txt.set_fontsize(txt.get_fontsize() - 0.2)


def flow(spec, out):
    """spec: {w, h, nodes: {id: [x, y, label, kind, (width)]}, edges: [[a, b, label?, style?]],
    lanes: [[y0, y1, label]]}"""
    W, H = spec["w"], spec["h"]
    fig, ax = plt.subplots(figsize=(W, H), dpi=200)
    ax.set_xlim(0, W)
    ax.set_ylim(0, H)
    ax.axis("off")
    for lane in spec.get("lanes", []):
        y0, y1, label = lane[:3]
        x0, x1 = (lane[3], lane[4]) if len(lane) > 3 else (0.05, W - 0.05)
        ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0,
                                    boxstyle="round,pad=0,rounding_size=0.08",
                                    fc="#FAFAFA", ec="#D1D5DB", lw=0.8, zorder=0))
        ax.text(x0 + 0.1, y1 - 0.12, label, ha="left", va="top", fontsize=7.5,
                color=MUTED, fontweight="bold", zorder=1)
    boxes = {}
    for nid, n in spec["nodes"].items():
        x, y, label, kind = n[:4]
        bw = n[4] if len(n) > 4 else 1.55
        bh = n[5] if len(n) > 5 else 0.62
        fc, ec = FILL[kind]
        ax.add_patch(FancyBboxPatch((x - bw / 2, y - bh / 2), bw, bh,
                                    boxstyle="round,pad=0.02,rounding_size=0.08",
                                    fc=fc, ec=ec, lw=1.2, zorder=3))
        lines = label.split("\n")
        t1 = ax.text(x, y + (0.11 if len(lines) > 1 else 0), lines[0], ha="center",
                     va="center", fontsize=9.2, color=INK, fontweight="bold", zorder=4)
        _fit(fig, ax, t1, bw - 0.12)
        if len(lines) > 1:
            t2 = ax.text(x, y - 0.13, "\n".join(lines[1:]), ha="center", va="center",
                         fontsize=7.3, color=MUTED, zorder=4, linespacing=1.05)
            _fit(fig, ax, t2, bw - 0.12)
        boxes[nid] = (x, y, bw, bh)
    for e in spec["edges"]:
        a, b = e[0], e[1]
        label = e[2] if len(e) > 2 else None
        style = e[3] if len(e) > 3 else "solid"
        xa, ya, wa, ha = boxes[a]
        xb, yb, wb, hb = boxes[b]
        # attach on the facing sides
        if abs(xb - xa) >= abs(yb - ya):
            sa = (xa + (wa / 2) * (1 if xb > xa else -1), ya)
            sb = (xb - (wb / 2) * (1 if xb > xa else -1), yb)
        else:
            sa = (xa, ya + (ha / 2) * (1 if yb > ya else -1))
            sb = (xb, yb - (hb / 2) * (1 if yb > ya else -1))
        rad = e[4] if len(e) > 4 else 0.0
        ax.add_patch(FancyArrowPatch(sa, sb, arrowstyle="-|>", mutation_scale=9,
                                     lw=1.0, color=INK if style == "solid" else MUTED,
                                     linestyle="-" if style == "solid" else (0, (3, 2)),
                                     connectionstyle=f"arc3,rad={rad}", zorder=2))
        if label:
            mx, my = (sa[0] + sb[0]) / 2, (sa[1] + sb[1]) / 2
            ax.text(mx, my + 0.1, label, ha="center", va="bottom", fontsize=7.2,
                    color=MUTED, zorder=5,
                    bbox=dict(fc="white", ec="none", pad=0.6, alpha=0.9))
    fig.savefig(out, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    plt.close(fig)


def gantt(rows, out, start, end, today=None, milestones=()):
    """rows: [[label, start_iso, end_iso, phase]] phase in program/test/final/run"""
    colors = {"program": "#2F5597", "test": "#B7791F", "final": "#2F7D3B",
              "run": "#9CA3AF", "group": "#1F2937"}
    s0, e0 = date.fromisoformat(start), date.fromisoformat(end)
    n = len(rows)
    fig, ax = plt.subplots(figsize=(7.8, 0.3 * n + 0.9), dpi=200)
    for i, (label, a, b, ph) in enumerate(rows):
        y = n - 1 - i
        da, db = date.fromisoformat(a), date.fromisoformat(b)
        if ph == "group":
            ax.barh(y, (db - da).days + 1, left=(da - s0).days, height=0.22,
                    color=colors[ph])
        else:
            ax.barh(y, max((db - da).days + 1, 2), left=(da - s0).days, height=0.55,
                    color=colors[ph], alpha=0.9)
    ax.set_yticks(range(n))
    ax.set_yticklabels([r[0] for r in reversed(rows)], fontsize=7)
    for lbl, r in zip(reversed(ax.get_yticklabels()), rows):
        if r[3] == "group":
            lbl.set_fontweight("bold")
    # month grid
    ticks, labels = [], []
    d = date(s0.year, s0.month, 1)
    while d <= e0:
        if d >= s0:
            ticks.append((d - s0).days)
            labels.append(d.strftime("%b '%y"))
        d = date(d.year + (d.month // 12), d.month % 12 + 1, 1)
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, fontsize=7)
    ax.set_xlim(0, (e0 - s0).days)
    ax.set_ylim(-0.6, n - 0.4)
    ax.grid(axis="x", color="#E5E7EB", lw=0.8)
    ax.set_axisbelow(True)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(axis="y", length=0)
    if today:
        t = (date.fromisoformat(today) - s0).days
        ax.axvline(t, color="#B42318", lw=1)
        ax.text(t, n - 0.35, " today", color="#B42318", fontsize=6.5, va="bottom")
    for label, d_iso in milestones:
        t = (date.fromisoformat(d_iso) - s0).days
        ax.axvline(t, color=INK, lw=0.8, ls=(0, (2, 2)))
        ax.text(t, -0.55, f" {label}", color=INK, fontsize=6.3, va="bottom", rotation=0)
    handles = [plt.Rectangle((0, 0), 1, 1, color=colors[k]) for k in ("program", "test", "final", "run")]
    ax.legend(handles, ["Programming", "Testing", "Finalisation / release", "Operation / follow-up"],
              fontsize=6.5, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=4, frameon=False)
    fig.savefig(out, bbox_inches="tight", pad_inches=0.05, facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    cfg = json.load(open(sys.argv[1]))
    for f in cfg.get("flows", []):
        flow(f["spec"], f["out"])
    for g in cfg.get("gantts", []):
        gantt(g["rows"], g["out"], g["start"], g["end"], g.get("today"), g.get("milestones", []))
