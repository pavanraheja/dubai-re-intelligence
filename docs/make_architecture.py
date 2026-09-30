#!/usr/bin/env python3
"""
Generate the architecture diagram from one description, in two renderings:

  docs/architecture.svg        fixed colours, for GitHub (README)
  docs/architecture_inline.svg theme tokens (currentColor / CSS vars), for HTML pages

    python docs/make_architecture.py

Kept as code so the diagram changes in the same commit as the system it describes.
Only built components are solid; dashed = roadmap, not built.
"""
import glob, os, re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Counted, not typed: the diagram must not drift from the repo.
N_EVAL = sum(1 for f in glob.glob(os.path.join(ROOT, "evals", "questions_*.jsonl"))
             for line in open(f) if line.strip())
N_TESTS = sum(len(re.findall(r"^def test_", open(f).read(), re.M))
              for f in glob.glob(os.path.join(ROOT, "*", "test_*.py")))

W, H = 1066, 750
BW = 150                                   # box width
COL = [52, 220, 388, 556, 724, 892]        # column x positions (gap 18)
LANES = [  # (y, height, label)
    (30, 140, "DATA"),
    (185, 165, "ASK"),
    (365, 125, "LEARN"),
    (505, 115, "DECIDE"),
    (635, 105, "NEXT"),
]


def diagram(theme):
    fixed = theme == "fixed"
    ink = "#16202a" if fixed else "currentColor"
    muted = "#5a6672" if fixed else "var(--muted)"
    surface = "#ffffff" if fixed else "var(--surface)"
    lane_bg = "#f5f6f2" if fixed else "var(--soft)"
    gate = "#1d5b8f" if fixed else "var(--accent)"
    font = 'font-family="IBM Plex Sans, system-ui, -apple-system, Segoe UI, sans-serif"'
    o = []
    add = o.append

    def box(x, y, title, sub, w=BW, h=52, accent=False, dashed=False):
        stroke = gate if accent else ink
        dash = ' stroke-dasharray="5 4"' if dashed else ""
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="{surface}" '
            f'stroke="{stroke}" stroke-width="{2 if accent else 1.2}"{dash}/>')
        add(f'<text x="{x + w / 2}" y="{y + (20 if sub else h / 2 + 4)}" text-anchor="middle" '
            f'font-size="13" font-weight="600" fill="{gate if accent else ink}">{title}</text>')
        if sub:
            add(f'<text x="{x + w / 2}" y="{y + 37}" text-anchor="middle" font-size="11" '
                f'fill="{muted}">{sub}</text>')

    def arrow(points, label=None, lx=None, ly=None, anchor="middle", color=None):
        c = color or ink
        pts = " ".join(f"{x},{y}" for x, y in points)
        add(f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="1.4" '
            f'marker-end="url(#{"ag" if color else "a"})"/>')
        if label:
            add(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" font-size="11" '
                f'fill="{muted}">{label}</text>')

    add(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" {font} '
        f'aria-label="Architecture: real land-registry sales are pulled into a CSV; each question passes '
        f'a refusal gate before a planner that only picks a tool name, pandas computes every number, '
        f'and a confidence grade is attached; every question is logged, reviewed, and changes to the '
        f'eval set pass a human gate before the next deploy; in the decision workbench the person sets the criteria and makes the call, the engine only ranks and stress-tests.">')
    add('<defs>'
        f'<marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{ink}"/></marker>'
        f'<marker id="ag" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{gate}"/></marker>'
        '</defs>')
    if fixed:
        add(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#ffffff"/>')

    for y, h, label in LANES:
        dash = ' stroke-dasharray="5 4"' if label.startswith("NEXT") else ""
        add(f'<rect x="8" y="{y}" width="{W - 16}" height="{h}" rx="10" fill="{lane_bg}" '
            f'stroke="{muted}" stroke-width="0.8"{dash}/>')
        add(f'<text transform="translate(30 {y + h / 2}) rotate(-90)" text-anchor="middle" '
            f'font-size="11" font-weight="600" letter-spacing="1" fill="{muted}">{label}</text>')

    # ── lane 1: data ──
    c = COL
    box(c[0], 85, "DLD open-data API", "current year only")
    box(c[1], 85, "fetch_dld.py", "sales · flats, villas")
    box(c[2], 85, "communities.py", "defines Emaar South")
    box(c[3], 62, "transactions.csv", "kept: 3,974 rows", h=46)
    box(c[3], 118, "extract_report.json", "excluded, each listed", h=46)
    arrow([(c[0] + BW, 111), (c[1], 111)], "pull, no key", c[1] - 9, 79)
    arrow([(c[1] + BW, 111), (c[2], 111)], "filter", c[2] - 9, 79)
    arrow([(c[2] + BW, 104), (c[3], 85)])
    arrow([(c[2] + BW, 118), (c[3], 141)])

    # ── lane 2: ask ──
    y = 225
    box(c[0], y, "Visitor", "page.html")
    box(c[1], y, "normalise", "harbor → harbour")
    box(c[2], y, "REFUSAL GATE", "6 categories", accent=True)
    box(c[3], y, "planner", "rules · Claude optional")
    box(c[4], y, "7 pandas tools", "medians")
    box(c[5], y, "evidence grade", "basis · confidence")
    arrow([(c[0] + BW, 251), (c[1], 251)], "asks", c[1] - 9, 219)
    arrow([(c[1] + BW, 251), (c[2], 251)])
    arrow([(c[2] + BW, 251), (c[3], 251)], "allowed", c[3] - 9, 219)
    arrow([(c[3] + BW, 251), (c[4], 251)], "tool name only", c[4] - 9, 219)
    arrow([(c[4] + BW, 251), (c[5], 251)], "numbers", c[5] - 9, 219)
    # the CSV feeds the tools
    arrow([(c[3] + BW, 84), (c[4] + 70, 84), (c[4] + 70, y)], "read by", c[4] + 78, 150, "start")
    # answer back to the visitor, and the refused path joining it
    arrow([(c[5] + 30, 277), (c[5] + 30, 318), (c[0] + 70, 318), (c[0] + 70, 277)],
          "answer card: number · basis · confidence", c[4] - 30, 312, "start")
    add(f'<polyline points="{c[2] + 70},277 {c[2] + 70},318" fill="none" stroke="{gate}" '
        f'stroke-width="1.4"/>')
    add(f'<text x="{c[2] + 78}" y="300" font-size="11" fill="{gate}">refused: reason + 2 questions '
        f'that work</text>')

    # ── lane 3: learn (right to left) ──
    y = 405
    box(c[5], y, "Vercel logs", "kept briefly")
    box(c[4], y, "review.py", "archive · replay")
    box(c[3], y, "report", "rephrases · refusals")
    box(c[2], y, "HUMAN GATE", "confirm / correct labels", accent=True)
    box(c[1], y, "evals/", f"{N_EVAL} Qs · {N_TESTS} tests")
    box(c[0], y, "deploy", "must pass evals")
    arrow([(c[5] + 110, 277), (c[5] + 110, y)], "1 log line, no IP", c[5] + 104, 378, "end")
    arrow([(c[5], 431), (c[4] + BW, 431)], "archive", c[5] - 9, 399)
    arrow([(c[4], 431), (c[3] + BW, 431)], "replay on today's code", c[4] - 9, 399)
    arrow([(c[3], 431), (c[2] + BW, 431)], "proposed labels", c[3] - 9, 399)
    arrow([(c[2], 431), (c[1] + BW, 431)], "approved", c[2] - 9, 399, color=gate)
    arrow([(c[1], 431), (c[0] + BW, 431)], "must pass", c[1] - 9, 399)
    arrow([(c[0] + 70, y), (c[0] + 70, 353)], "ships", c[0] + 78, 382, "start")

    # ── lane 4: decide (the person sets criteria and makes the call) ──
    y = 540
    box(c[0], y, "dubai_south.csv", "13,240 sales")
    box(c[1], y, "YOU SET CRITERIA", "in your own words", accent=True)
    box(c[2], y, "decide/engine.py", "percentile scores")
    box(c[3], y, "stress test", "2,000 weightings")
    box(c[4], y, "gaps + warnings", "what data can't say")
    box(c[5], y, "YOU DECIDE", "memo · reversal criteria", accent=True)
    arrow([(c[0] + BW, 566), (c[1], 566)], "options", c[1] - 9, 534)
    arrow([(c[1] + BW, 566), (c[2], 566)], "weights", c[2] - 9, 534, color=gate)
    arrow([(c[2] + BW, 566), (c[3], 566)], "ranking", c[3] - 9, 534)
    arrow([(c[3] + BW, 566), (c[4], 566)], "how settled", c[4] - 9, 534)
    arrow([(c[4] + BW, 566), (c[5], 566)], "evidence", c[5] - 9, 534)
    add(f'<text x="{c[4] + 88}" y="160" font-size="11" fill="{muted}">+ Dubai South extract → DECIDE</text>')

    # ── lane 4: roadmap (dashed = not built) ──
    nxt = [("nightly DLD pull", "fresh data, auto"), ("historic archive", "makes YoY answerable"),
           ("supply source", "completions, unsold"), ("LLM planner", "benchmark, ~$0.11/100 Qs"),
           ("loop on a schedule", "weekly roadmap report")]
    for i, (t, s) in enumerate(nxt):
        box(52 + i * 202, 668, t, s, w=184, h=48, dashed=True)
    add(f'<text x="52" y="655" font-size="11" fill="{muted}">ranked by refusal counts from LEARN and by the '
        f'prioritisation rules in PRODUCT.md</text>')

    add('</svg>')
    return "\n".join(o)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    open(os.path.join(here, "architecture.svg"), "w").write(diagram("fixed"))
    open(os.path.join(here, "architecture_inline.svg"), "w").write(diagram("inline"))
    print("wrote docs/architecture.svg, docs/architecture_inline.svg")
