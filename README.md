# Dubai RE Intelligence

A small data toolkit built for decision-making on Dubai real estate. Two tools sit side-by-side: a transaction-level intelligence dashboard focused on the communities the firm invests in, and a weekly snapshot designed for investor updates.

Built while leading investment and strategy at Dash Capital (Dubai) by Pavan Raheja — **[see my work & get in touch → pavan.blog/work](https://www.pavan.blog/work?utm_source=github&utm_medium=readme&utm_campaign=dubai-re-intelligence)**.

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

## Design notes

- **Focus over breadth.** The dashboard intentionally only covers the two communities that drive firm decisions. A generic "all of Dubai" view was rejected — vanity breadth, little decision value.
- **Two data formats, one loader.** DLD exports changed mid-2025. The loader normalises both so the dashboard survives format drift.
- **Demo-first.** Every tool ships with bundled demo data so a reviewer can run it in 60 seconds without a data hunt.

## License

MIT
