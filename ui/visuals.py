"""SVG visuals for the Streamlit UI. Owner: C. Pure functions returning SVG/HTML strings (testable, no Streamlit).

Every value drawn comes from a real run (evidence, trace) or, for the start-screen illustration, from the
committed sample data (data/sample), and the illustration says so.
"""

from __future__ import annotations

import base64
from collections import defaultdict
from html import escape
from typing import Any

INK, MUTED, RULE, PAPER = "#17232E", "#5B6B77", "#D5DDD8", "#FFFFFF"
GREEN, HIGH, MEDIUM, LOW, REVIEW = "#0B7A55", "#B4232A", "#B86E00", "#3E7B4F", "#5A4A9C"
SEV = {"high": HIGH, "medium": MEDIUM, "low": LOW}
SOURCE_LABEL = {"inventory": "Inventory system", "pos": "Point of sale", "supplier": "Supplier portal",
                "regulator": "Regulator register"}
SOURCE_ORDER = ["regulator", "inventory", "pos", "supplier"]
FONT = "Public Sans, system-ui, sans-serif"
MONO = "ui-monospace, Menlo, monospace"


def _t(x: float, y: float, text: str, size: float = 13, weight: int = 400, fill: str = INK, family: str = FONT,
       anchor: str = "start") -> str:
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}">{escape(str(text))}</text>')


def _clip(s: str, n: int) -> str:
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


# ---------------- start screen: one batch, four spellings ----------------

def hero_svg() -> str:
    """Four real records of the same recalled batch, as each system wrote it (data/sample, Glumet XR 500mg)."""
    w, h = 1080, 430
    parts = [(f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg" '
             'aria-label="The same recalled batch written four different ways by four systems, reconciled by RecallGuard '
             'into an action list">')]

    # 1. NPRA notice
    x, y = 10, 14
    parts += [f'<rect x="{x}" y="{y}" width="330" height="86" rx="3" fill="{PAPER}" stroke="{RULE}"/>',
              f'<rect x="{x}" y="{y}" width="330" height="7" fill="{HIGH}"/>',
              _t(x + 16, y + 30, "NPRA recall notice, degree II", 12, 600, HIGH),
              _t(x + 16, y + 52, "Glumet XR Tablet 500mg", 15, 700),
              _t(x + 16, y + 73, "Batch 5036723 · MAL13015050AZ", 13, 500, MUTED)]
    # 2. Inventory table
    x, y = 10, 116
    parts += [f'<rect x="{x}" y="{y}" width="330" height="86" rx="3" fill="{PAPER}" stroke="{RULE}"/>',
              f'<rect x="{x}" y="{y}" width="330" height="26" fill="#EAF0ED"/>',
              _t(x + 14, y + 18, "Inventory", 12, 600, MUTED),
              _t(x + 110, y + 18, "Batch", 12, 600, MUTED), _t(x + 196, y + 18, "Product", 12, 600, MUTED),
              f'<line x1="{x + 100}" y1="{y}" x2="{x + 100}" y2="{y + 86}" stroke="{RULE}"/>',
              f'<line x1="{x + 186}" y1="{y}" x2="{x + 186}" y2="{y + 86}" stroke="{RULE}"/>',
              _t(x + 14, y + 52, "OUT-08", 13, 600), _t(x + 110, y + 52, "5036723", 13, 700),
              _t(x + 196, y + 52, "Glumet XR", 13), _t(x + 196, y + 70, "Tablet 500mg", 13)]
    # 3. POS receipt (zigzag foot)
    x, y = 30, 218
    zig = " ".join(f"L{x + 250 - i * 10},{y + 96 + (6 if i % 2 == 0 else 0)}" for i in range(26))
    parts += [f'<path d="M{x},{y} L{x + 250},{y} L{x + 250},{y + 96} {zig} L{x},{y + 96} Z" fill="{PAPER}" stroke="{RULE}"/>',
              _t(x + 125, y + 22, "POINT OF SALE  ·  OUT-04", 11, 400, MUTED, MONO, "middle"),
              _t(x + 16, y + 48, "glumet xr tab 500mg", 13, 400, INK, MONO),
              _t(x + 16, y + 68, "batch  s036723", 13, 700, INK, MONO),
              _t(x + 16, y + 86, "sold after 15 Apr 2026", 11, 400, HIGH, MONO)]
    # 4. Supplier delivery note
    x, y = 10, 330
    parts += [f'<rect x="{x}" y="{y}" width="330" height="86" rx="3" fill="{PAPER}" stroke="{RULE}"/>',
              f'<line x1="{x}" y1="{y + 28}" x2="{x + 330}" y2="{y + 28}" stroke="{RULE}" stroke-dasharray="4 3"/>',
              _t(x + 16, y + 20, "Supplier delivery note", 12, 600, MUTED),
              _t(x + 16, y + 52, "GLUMET XR TABLET 500MG (BTL)", 13, 600),
              _t(x + 16, y + 73, "Lot 503-6723 · outlet not recorded", 13, 500, MUTED)]

    # connectors into the agents
    cx, cy = 560, 215
    for sy in (57, 159, 266, 373):
        parts.append(f'<path d="M345,{sy} C450,{sy} 450,{cy} {cx - 92},{cy}" fill="none" stroke="{GREEN}" '
                     f'stroke-width="1.6" stroke-opacity=".55"/>')
    parts += [f'<rect x="{cx - 92}" y="{cy - 58}" width="184" height="116" rx="10" fill="{GREEN}"/>',
              _t(cx, cy - 22, "RecallGuard", 18, 700, PAPER, anchor="middle"),
              _t(cx, cy + 2, "5 agents match, check", 12.5, 400, "#D9F0E6", anchor="middle"),
              _t(cx, cy + 20, "and rank every record", 12.5, 400, "#D9F0E6", anchor="middle"),
              _t(cx, cy + 42, "same batch: 5036723", 12.5, 700, PAPER, anchor="middle"),
              f'<path d="M{cx + 92},{cy} L{cx + 150},{cy}" stroke="{GREEN}" stroke-width="2"/>',
              f'<path d="M{cx + 150},{cy - 6} L{cx + 160},{cy} L{cx + 150},{cy + 6} Z" fill="{GREEN}"/>']

    # action plan stubs
    x0 = 728
    parts += [_t(x0, 92, "Action plan", 15, 700)]
    stubs = [("OUT-04", "sold 11 units after the recall", "Pharmacist to check", REVIEW),
             ("OUT-06", "sold 9 units after the recall", "Pharmacist to check", REVIEW),
             ("OUT-08", "18 in stock · sold 7", "Confirmed by Critic", GREEN),
             ("OUT-07", "sold 7 units after the recall", "Confirmed by Critic", GREEN)]
    for i, (outlet, line, status, col) in enumerate(stubs):
        y = 108 + i * 62
        parts += [f'<rect x="{x0}" y="{y}" width="340" height="52" rx="3" fill="{PAPER}" stroke="{RULE}"/>',
                  f'<rect x="{x0}" y="{y}" width="5" height="52" fill="{MEDIUM}"/>',
                  _t(x0 + 18, y + 22, outlet, 14, 700), _t(x0 + 92, y + 22, status, 11.5, 600, col),
                  _t(x0 + 18, y + 41, line, 12.5, 400, MUTED)]
    parts.append(_t(x0, 375, "Example: Glumet XR 500mg recall on the committed sample data.", 11.5, 400, MUTED))
    parts.append("</svg>")
    return "".join(parts)


# ---------------- results: how each system wrote it ----------------

def spellings(exposures: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Distinct spellings per source system, from the run's own evidence."""
    out: dict[str, dict[str, Any]] = defaultdict(lambda: {"batch": set(), "product_name": set(), "reg_no": set(),
                                                          "records": set()})
    for e in exposures:
        for ev in e.get("evidence") or []:
            src = ev.get("source")
            if not src:
                continue
            out[src]["records"].add(ev.get("record_id"))
            if ev.get("field") in ("batch", "product_name", "reg_no") and ev.get("value") not in (None, ""):
                out[src][ev["field"]].add(str(ev["value"]))
    return {s: {k: sorted(v) for k, v in d.items()} | {"n": len(d["records"])} for s, d in out.items()}


def spellings_html(sp: dict[str, dict[str, Any]], recall_batches: list[str]) -> str:
    if not sp:
        return ""
    targets = {"".join(ch for ch in b.upper() if ch.isalnum()) for b in recall_batches}
    cards = []
    for src in [s for s in SOURCE_ORDER if s in sp] + [s for s in sp if s not in SOURCE_ORDER]:
        d = sp[src]
        batches = "".join(
            f'<span class="sp-b{" odd" if "".join(c for c in b.upper() if c.isalnum()) not in targets else ""}">'
            f'{escape(b)}</span>' for b in d["batch"][:5])
        names = "".join(f"<li>{escape(_clip(n, 40))}</li>" for n in d["product_name"][:3])
        more = len(d["product_name"]) - 3
        cards.append(f"""
<div class="sp-card sp-{escape(src)}">
  <div class="sp-head"><b>{escape(SOURCE_LABEL.get(src, src))}</b><span>{d['n']} record{'s' if d['n'] != 1 else ''}</span></div>
  <div class="sp-batches">{batches or '<span class="sp-none">no batch recorded</span>'}</div>
  <ul>{names}{f'<li class="more">and {more} more</li>' if more > 0 else ''}</ul>
</div>""")
    return f'<div class="sp-row">{"".join(cards)}</div>'


# ---------------- agent pipeline ----------------

PIPE = [("PlannerAgent", "Planner", "reads the catalogue"), ("RetrieverAgent", "Retriever", "pulls the records"),
        ("ReconcilerAgent", "Reconciler", "matches them"), ("ConflictCriticAgent", "Critic", "re-checks each one"),
        ("ReporterAgent", "Reporter", "ranks the actions")]
SPONSOR_LABEL = {"zetaris": "Zetaris", "meterless.nightshift": "Nightshift", "meterless.world_model": "World Model",
                 "meterless.hmem": "H-MEM"}


def pipeline_svg(events: list[dict[str, Any]]) -> str:
    acts: dict[str, int] = defaultdict(int)
    calls: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for ev in events:
        a = ev.get("agent_name") or ""
        acts[a] += 1
        if ev.get("sponsor_call"):
            calls[a][SPONSOR_LABEL.get(ev["sponsor_call"], ev["sponsor_call"])] += 1
    w, h, bw = 1080, 176, 176
    gap = (w - 20 - bw * len(PIPE)) / (len(PIPE) - 1)
    parts = [(f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" xmlns="http://www.w3.org/2000/svg" '
             'aria-label="Agent pipeline with the number of actions and sponsor calls per agent">')]
    for i, (key, label, verb) in enumerate(PIPE):
        x = 10 + i * (bw + gap)
        n = acts.get(key, 0)
        active = n > 0
        parts += [(f'<rect x="{x}" y="10" width="{bw}" height="92" rx="8" fill="{GREEN if active else PAPER}" '
                  f'stroke="{GREEN if active else RULE}"/>'),
                  _t(x + 16, 38, label, 16, 700, PAPER if active else MUTED),
                  _t(x + 16, 58, verb, 12, 400, "#D9F0E6" if active else MUTED),
                  _t(x + 16, 88, f"{n} action{'s' if n != 1 else ''}", 13, 600, PAPER if active else MUTED)]
        if i < len(PIPE) - 1:
            ax = x + bw
            parts += [f'<path d="M{ax + 4},56 L{ax + gap - 10},56" stroke="{MUTED}" stroke-width="1.5"/>',
                      f'<path d="M{ax + gap - 10},51 L{ax + gap - 3},56 L{ax + gap - 10},61 Z" fill="{MUTED}"/>']
        for j, (sp, c) in enumerate(sorted(calls.get(key, {}).items())):
            parts.append(_t(x + 2, 126 + j * 18, f"{sp} ×{c}", 12, 600, INK))
    parts.append("</svg>")
    return "".join(parts)


def as_img(svg: str, alt: str, max_width: str = "100%") -> str:
    """Embed SVG as an <img> data URI: Streamlit's HTML sanitiser drops inline <svg>, an image survives."""
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (f'<img src="data:image/svg+xml;base64,{data}" alt="{escape(alt)}" '
            f'style="width:100%;max-width:{max_width};height:auto;display:block">')
