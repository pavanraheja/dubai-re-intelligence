"""
Evidence rules — the part that decides whether an answer is allowed to exist.

Every answer returned by this tool carries:
  - provenance: how many rows, which window, which source file
  - confidence: HIGH / MEDIUM / LOW, from sample size and comparability
  - caveats:    stated before anyone asks
  - refusals:   questions the data cannot support, refused explicitly

Design rule: an answer without stated failure conditions is a story, not a finding.
"""
from dataclasses import dataclass, field
from datetime import datetime

# --- thresholds. Deliberately explicit rather than buried in the code. ---
MIN_ROWS_ANSWER = 30      # below this, refuse outright
MIN_ROWS_HIGH = 200       # above this (per side), confidence can be HIGH
STALE_DAYS = 180          # data older than this is flagged, not silently used
OFFPLAN_GAP_PP = 15       # off-plan share gap that breaks like-for-like comparison

# Question shapes this dataset cannot answer, whatever the model thinks.
FORWARD_WORDS = ("next month", "next year", "next 6", "next six", "forecast",
                 "predict", "will it", "going to", "future", "2027", "2028")
CAUSAL_WORDS = ("why", "because", "caused", "reason for", "driver of")
OUT_OF_SCOPE = ("rent", "rental", "yield", "mortgage", "service charge",
                "population", "visa", "interest rate")


@dataclass
class Evidence:
    rows: int = 0
    window: tuple = None          # (min_date, max_date)
    source: str = ""
    confidence: str = "LOW"
    caveats: list = field(default_factory=list)
    refusals: list = field(default_factory=list)

    def as_text(self):
        out = []
        if self.window:
            lo, hi = self.window
            out.append(f"Basis: {self.rows:,} rows · {lo:%b %Y}–{hi:%b %Y} · {self.source}")
        else:
            out.append(f"Basis: {self.rows:,} rows · {self.source}")
        out.append(f"Confidence: {self.confidence}")
        for c in self.caveats:
            out.append(f"  ! {c}")
        for r in self.refusals:
            out.append(f"  x REFUSED: {r}")
        return "\n".join(out)


def grade(rows_per_side, window, source, today=None):
    """Confidence from sample size and staleness. No model opinion involved."""
    ev = Evidence(rows=sum(rows_per_side), window=window, source=source)
    smallest = min(rows_per_side) if rows_per_side else 0

    if smallest < MIN_ROWS_ANSWER:
        ev.confidence = "INSUFFICIENT"
        ev.refusals.append(
            f"sample too small to answer (smallest group {smallest} rows, "
            f"minimum {MIN_ROWS_ANSWER})")
        return ev

    ev.confidence = "HIGH" if smallest >= MIN_ROWS_HIGH else "MEDIUM"

    if window:
        today = today or datetime.now()
        age = (today - window[1]).days
        if age > STALE_DAYS:
            ev.caveats.append(
                f"data ends {window[1]:%b %Y}, {age} days old — treat as historic, not current")
            if ev.confidence == "HIGH":
                ev.confidence = "MEDIUM"
    return ev


def check_like_for_like(ev, shares):
    """shares: {label: offplan_share_pct}. Comparing off-plan to ready is not like-for-like."""
    if len(shares) == 2:
        (a, sa), (b, sb) = shares.items()
        if abs(sa - sb) >= OFFPLAN_GAP_PP:
            ev.caveats.append(
                f"off-plan share differs ({a} {sa:.0f}% vs {b} {sb:.0f}%) — "
                f"not like-for-like; price gap is partly product mix, not market")
            if ev.confidence == "HIGH":
                ev.confidence = "MEDIUM"
    return ev


def scope_refusals(question):
    """Refuse before computing. Cheaper, and honest about what the source contains."""
    q = question.lower()
    out = []
    if any(w in q for w in FORWARD_WORDS):
        out.append("forward-looking question — this source is transaction history, "
                   "it contains no forward data. I can show the trend, not the forecast")
    if any(q.startswith(w) or f" {w} " in q for w in CAUSAL_WORDS):
        out.append("causal question — transactions show association, not cause. "
                   "I can show what moved together, not what caused what")
    for w in OUT_OF_SCOPE:
        if w in q:
            out.append(f"'{w}' is not in DLD sales transactions — out of scope for this dataset")
            break
    return out
