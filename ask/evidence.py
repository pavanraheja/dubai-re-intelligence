"""
Evidence rules — the part that decides whether an answer is allowed to exist.

Every answer returned by this tool carries:
  - provenance: how many rows, which window, which source file
  - confidence: HIGH / MEDIUM / LOW, from sample size and comparability
  - caveats:    stated before anyone asks
  - refusals:   questions the data cannot support, refused explicitly

Design rule: an answer without stated failure conditions is a story, not a finding.
"""
import os
import re
from dataclasses import dataclass, field
from datetime import datetime

# --- thresholds. Deliberately explicit rather than buried in the code. ---
MIN_ROWS_ANSWER = 30      # below this, refuse outright
MIN_ROWS_HIGH = 200       # above this (per side), confidence can be HIGH
STALE_DAYS = 180          # data older than this is flagged, not silently used
OFFPLAN_GAP_PP = 15       # off-plan share gap that breaks like-for-like comparison

# Question shapes this dataset cannot answer, whatever the model thinks.
# Regex with word boundaries: "will" must not fire inside "Willow", "why" inside "whyte".
FORWARD = (r"\bwill\b", r"\bwon't\b", r"\bgoing to\b", r"\bheading\b", r"\boutlook\b",
           r"\bforecast", r"\bpredict", r"\bprojection", r"\bexpect", r"\bfuture\b",
           r"\bnext (week|month|quarter|year|\d+|six|twelve)\b", r"\bkeep (going|rising|falling)\b",
           r"\b20(2[7-9]|3\d)\b")
CAUSAL = (r"\bwhy\b", r"\bbecause\b", r"\bcaus", r"\bdrove\b", r"\bdriv(en|er|ers|ing)\b",
          r"\bbehind\b", r"\bdue to\b", r"\bpush(ed)? (up|down)\b", r"\bimpact of\b",
          r"\beffect of\b", r"\breason\b")
ADVICE = (r"\bshould (i|we)\b", r"\bgood investment\b", r"\bworth (buying|it)\b",
          r"\brecommend", r"\bover-?priced\b", r"\bunder-?priced\b", r"\bover-?valued\b",
          r"\bunder-?valued\b", r"\bfair value\b", r"\bbubble\b", r"\bpeak\b", r"\bbottom\b",
          r"\btime to (buy|sell)\b", r"\bbuy or\b", r"\bgood value\b", r"\bvalue or\b",
          r"\b(smarter|better|best) (buy|investment|bet)\b", r"\bwait to buy\b")
OUT_OF_SCOPE = ("rent", "rental", "yield", "mortgage", "service charge",
                "population", "people live", "residents", "visa", "interest rate")
# Supply needs completions / unsold inventory. DLD sales records are the demand side only.
SUPPLY = (r"\bsupply\b", r"\boversupply\b", r"\babsorb", r"\binventory\b", r"\bunsold\b",
          r"\bpipeline\b", r"\bhand(ed)? ?over", r"\bcompletions?\b", r"\bstock\b",
          r"\bnew units\b")

# Places people ask about that this extract does not cover. Registry names come from
# pipeline/dld_area_names.txt (written by fetch_dld.py); these are the marketing names
# people actually type, which the registry does not use.
OTHER_PLACES = ("downtown", "dubai marina", "marina", "jvc", "jumeirah village", "jlt",
                "palm jumeirah", "the palm", "business bay", "dubai hills", "arabian ranches",
                "damac hills", "damac lagoons", "sobha hartland", "mbr city", "meydan",
                "town square", "silicon oasis", "motor city", "sports city", "al furjan",
                "discovery gardens", "dubai south", "expo city", "azizi venice", "al barsha",
                "deira", "bur dubai", "mirdif", "jumeirah", "city walk", "bluewaters",
                "dubai islands", "tilal al ghaf", "the valley", "the springs", "the lakes")
OUR_NAMES = ("emaar south", "dubai creek harbour", "creek harbour", "al khairan first")


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


def _any(patterns, q):
    return any(re.search(p, q) for p in patterns)


def _area_names():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "pipeline", "dld_area_names.txt")
    names = set(OTHER_PLACES)
    if os.path.exists(path):
        names |= {l.strip().lower() for l in open(path) if len(l.strip()) > 3}
    return {n for n in names if n not in OUR_NAMES and n != "dubai"}


def scope_refusals(question):
    """Refuse before computing. Cheaper, and honest about what the source contains."""
    q = question.lower()
    out = []
    if _any(FORWARD, q):
        out.append("forward-looking question — this source is transaction history, "
                   "it contains no forward data. I can show the trend, not the forecast")
    if _any(CAUSAL, q):
        out.append("causal question — transactions show association, not cause. "
                   "I can show what moved together, not what caused what")
    if _any(ADVICE, q):
        out.append("advice question — whether to buy, or whether a price is 'right', is a "
                   "judgement this data cannot make. I can show the numbers that judgement "
                   "would use")
    for w in OUT_OF_SCOPE:
        # word boundary: "rent" must not fire inside "current" (found by the independent eval)
        if re.search(rf"\b{w}", q):
            out.append(f"'{w}' is not in DLD sales transactions — out of scope for this dataset")
            break
    if _any(SUPPLY, q):
        out.append("supply question — absorption needs units delivered and unsold stock; "
                   "DLD sales records only show the demand side. I can show deal volume, "
                   "which is not absorption")
    stripped = q
    for n in OUR_NAMES:
        stripped = stripped.replace(n, " ")
    for name in sorted(_area_names(), key=len, reverse=True):
        if re.search(rf"\b{re.escape(name)}\b", stripped):
            out.append(f"'{name.title()}' is not in this extract — it covers Emaar South and "
                       f"Dubai Creek Harbour only. Answering with those would answer a "
                       f"different question")
            break
    return out
