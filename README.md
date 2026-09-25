# Dubai RE Intelligence

A small data toolkit built for decision-making on Dubai real estate. Two tools sit side-by-side: a transaction-level intelligence dashboard focused on the communities the firm invests in, and a weekly snapshot designed for investor updates.

Built while leading investment and strategy at [Dash Capital](https://pavan.blog/work) (Dubai).

## Tools

### 1. `dashboard/` — DLD Transaction Intelligence

Flask + Pandas dashboard that loads DLD (Dubai Land Department) transaction data and focuses the view on two communities: Emaar South and Dubai Creek Harbour.

- Auto-normalises two incompatible DLD export formats (old Dubai Pulse + new DLD)
- Bundled demo data — works out of the box, no setup step
- Drop real DLD CSV into `dashboard/data/dld_transactions.csv` and restart to go live

**Run**

```bash
cd dashboard
pip install flask pandas numpy
python app.py
# http://localhost:8085
```

**Real data source**

- [dubailand.gov.ae/en/open-data/real-estate-data](https://dubailand.gov.ae/en/open-data/real-estate-data/)
- [Kaggle — Dubai Real Estate Transactions](https://www.kaggle.com/datasets/alexefimik/dubai-real-estate-transactions-dataset)

### 2. `weekly-snapshot/` — Investor Weekly Snapshot

A dark-mode weekly snapshot of Dubai market performance — value (AED bn), deals, off-plan share, sourced from public DLD reporting.

**Run**

```bash
cd weekly-snapshot
python server.py
# http://localhost:8000
```


### 3. `ask/` — Ask the data a question, and be told when not to trust the answer

An agent layer over the same DLD transactions. You ask in plain English; it picks tools, runs pandas, and returns the number **with its provenance, a confidence grade, and an explicit refusal when the data cannot support the question.**

**Run**

```bash
python ask.py "Is Emaar South absorbing supply faster than Dubai Creek Harbour?"
python ask.py --demo        # the full question set, including the ones it refuses
python ask/test_ask.py      # 9 tests, all on refusal and evidence behaviour
```

No API key needed — a rule-based planner ships by default. Set `ANTHROPIC_API_KEY` and Claude picks the tools instead; **the numbers and the refusals are identical either way**, because the model only chooses which tool runs. It never produces a number and it cannot override a refusal.

**Example**

```
Q: Which community will perform better next year?

  x REFUSED: forward-looking question — this source is transaction history,
             it contains no forward data. I can show the trend, not the forecast

  What I can show instead (this does NOT answer the question asked):

[compare_communities]
  Dubai Creek Harbour     2368 txns · median AED 1920.0/sqft · +7.0% YoY · off-plan 68.7%
  Emaar South             1789 txns · median AED 1227.0/sqft · +6.9% YoY · off-plan 67.2%
  Basis: 4,157 rows · Sep 2024–Sep 2025 · DLD demo extract (real format)
  Confidence: MEDIUM
    ! data ends Sep 2025, 363 days old — treat as historic, not current
```

**What it refuses, and why**

| Refusal | Reason |
|---|---|
| Forward-looking ("next year", "forecast", "will") | The source is transaction history. It contains no forward data. |
| Causal ("why did prices rise") | Transactions show association, not cause. |
| Out of scope (rents, yields, mortgages, population) | Not in DLD sales records. |
| Thin sample (smallest group < 30 rows) | No answer is given at all — not a low-confidence one. |

**What it downgrades rather than refuses**

- **Stale data** — if the window ends more than 180 days ago, it says so and drops HIGH to MEDIUM.
- **Not like-for-like** — if off-plan share between two communities differs by more than 15 points, it says the price gap is partly product mix, not market.
- **Thin months** — months with fewer than 5 deals are dropped from trends and the drop is reported.

**Why it is built this way.** Anyone can put a chatbot on a dataset; the hard part is making it say "I don't know" in the specific places where it doesn't. Every threshold above sits in one file (`ask/evidence.py`) as a named constant, so the rules are arguable rather than buried. An answer without stated failure conditions is a story, not a finding.

## Design notes

- **Focus over breadth.** The dashboard intentionally only covers the two communities that drive firm decisions. A generic "all of Dubai" view was rejected — vanity breadth, little decision value.
- **Two data formats, one loader.** DLD exports changed mid-2025. The loader normalises both so the dashboard survives format drift.
- **Demo-first.** Every tool ships with bundled demo data so a reviewer can run it in 60 seconds without a data hunt.
- **The model chooses the question, never the answer.** In `ask/`, the planner only selects which pandas function runs. Numbers are computed, not generated, and the evidence rules can veto the planner. It degrades to a rule-based planner with no API key, because a demo that needs a secret to run is not a demo.

## License

MIT
