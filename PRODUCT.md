# Product brief — Dubai RE Intelligence

**Owner:** Pavan Raheja · **Status:** working prototype, live at [dubai-re-intelligence-seven.vercel.app](https://dubai-re-intelligence-seven.vercel.app) · **Last reviewed:** 27 Sep 2026

## The decision it serves
An investment committee choosing where the next allocation goes: **Emaar South or Dubai Creek Harbour.** The committee asks questions in plain language, often mid-meeting. Before this tool, each question went to whoever could open a spreadsheet, and came back as a number with no basis attached.

## The request versus the problem
**Requested:** "a dashboard for all of Dubai."
**Actual problem:** decisions were being made on numbers nobody in the room could trace or defend. The shortage was never data. It was the confident number that should not have existed: a forecast dressed as a fact, a price gap that was really a product-mix gap, an answer about the wrong area.

So the product is narrow on purpose: two communities, every number carrying its basis, and explicit refusals where the data cannot support the question.

## From committee questions to requirements
| What the committee actually asked | Requirement it became |
|---|---|
| "Is Creek Harbour more expensive than Emaar South?" | Compare on median AED/sqft **and** flag when off-plan mix differs by more than 15 points, because then the gap is partly product, not market |
| "Where are prices heading?" | Refuse. Transaction history contains no forward data. Show the trend, labelled as not a forecast |
| "Why did prices rise?" | Refuse. Transactions show association, not cause |
| "Should we buy?" / "Is it overpriced?" | Refuse. That is the committee's judgement; the tool shows the numbers the judgement uses |
| "Is Emaar South absorbing supply faster?" | Refuse. Absorption needs delivered and unsold units; sales records are the demand side only |
| "What about Downtown?" | Refuse. Never answer with a different area's numbers |
| "What do 2-beds go for?" | Split by bedrooms and flag any segment under 30 sales as unreliable |

## The evidence contract (non-negotiable, enforced in code)
1. **A model may choose which tool runs. It never produces a number,** and it cannot override a refusal.
2. Every answer states its row count, date window, source and pull date.
3. Confidence is graded by rules: fewer than 30 rows means no answer at all, not a low-confidence one.
4. Refusals are checked **before** anything is computed, and each one says why.
5. When the data is stale, or the comparison is not like-for-like, the answer says so and is downgraded.
6. Every threshold is a named constant in one file (`ask/evidence.py`), so the rules can be argued with instead of being buried.
7. **The two communities are never pooled into one number.** A pooled median is mostly the bigger community and can move on mix alone. When no community is named, each is shown separately.

## How it is measured
- **Guardrail metric: missed refusals** (answering a question the data cannot support). Target: zero. This is the expensive error.
- **Secondary metric: over-refusals / wrong tool.** Annoying, not dangerous.
- Three labelled question sets (`evals/`): **dev** (33, tuned on), **holdout** (23, written at the same time, never tuned on), and **independent** (40, written by a separate model that saw only the tool's description, never the code, committed before it was first run).
- **The baseline was poor, and that is recorded:** before this round, the tool scored 58% on dev and 52% on holdout, with 21 questions answered that should have been refused.
- **First real user session (27 Sep):** the only question typed by hand, "what is going on with Dubai creek harbor", got a generic two-community table, and the five refused-on-purpose examples read as failures. Lesson: **a wrong view feels like a refusal**, so over-routing is measured too. A 30-question everyday set scored 18/30 before fixes and 30/30 after (tuned). Every refusal now offers one-tap questions the data can answer.
- **The independent set's first-contact score was 34/40 (85%).** It found a real bug: `rent` matched inside "cu*rrent*". It now scores 40/40, but that is a tuned number. The next clean number needs a new independent set.

## The learning loop (how the product gets better from use)
Every live question is logged with what the tool did. `insights/review.py` reads the logs and reports four things: where people **rephrased** (the answer probably missed), which **refusals** are most common (demand for data the product lacks, mapped to roadmap items), which questions the planner **did not recognise**, and new questions proposed as **eval candidates**.

It learns through people, on purpose. It never edits a rule, threshold or label itself: a public input that retrained its own rules could be steered by anyone typing into it. The loop proposes, a person labels, the eval set grows, and the next change is measured against it. Its first run, on the owner's own sessions, flagged the exact rephrase chain that exposed the pooled-trend bug, from timing and shared words alone.

**First live catch, 28 Sep:** "how many studios sold in creek harbour recently" was routed to the latest-deals list because of the word "recently". The loop proposed it as an eval candidate with the suggested label `notable_transactions`, which was the bug itself. Auto-accepting that label would have written the mistake into the test set as correct. A person corrected it to a bedroom breakdown; the fix now also says "no studio sales recorded, the answer is zero" instead of listing other segments. That is why the human gate exists.

Privacy: no IP or identifying data is logged, and visitors' questions are never committed to the public repo.

## What was deliberately cut
| Cut | Why |
|---|---|
| All-of-Dubai view | Breadth without a decision attached. Two communities drive the committee's choice |
| Forecasting | The source has no forward data; any forecast would be invented |
| Rents and yields | Not in sales records. Adding them means a second source and a second evidence contract |
| LLM-written answers | Numbers are computed in pandas. The model's only job is routing |
| An API key on the public demo | The rules planner costs $0 per question and cannot leak a key |

## Known limits (stated, not hidden)
- **Current calendar year only.** The land department's public API serves nothing before 1 Jan 2026 (checked: earlier ranges return empty, not an error). Year-on-year is therefore *not computed*, rather than estimated.
- **Townhouses are recorded as villas** in the registry. That split cannot be recovered from this source.
- **"Emaar South" does not exist in the registry.** It is defined by project name in `pipeline/communities.py`, and every excluded project in those registry areas is listed in `pipeline/extract_report.json`. That report caught Grove Ridge and Vista Ridge on the first pull: 348 sales, which would have been a 30% undercount.
- The rules planner is keyword-based. It is measured, not magic, and it will meet phrasings it has not seen.

## Decision log
| Date | Decision | Basis |
|---|---|---|
| 2025 | Two communities, not all of Dubai | Only these two drove allocation decisions |
| 25 Sep 2026 | Add the agent layer: the model picks the tool, never the number | A chatbot on a dataset is easy; making it say "I don't know" in the right places is the product |
| 27 Sep 2026 | Refuse supply and absorption questions | Self-review: the flagship demo question could not actually be answered from sales data |
| 27 Sep 2026 | Replace synthetic demo data with real DLD sales | Synthetic data labelled "real format" is a trust bug in a tool whose whole promise is provenance |
| 27 Sep 2026 | Refuse year-on-year rather than estimate it | The API serves the current year only |
| 27 Sep 2026 | Add advice and unknown-area refusals, and an independent eval set | Baseline eval: 21 questions answered that should have been refused |
| 27 Sep 2026 | Dashboard: "BUY / SELL" signals renamed to momentum labels; rental yields labelled MODELLED | The same product cannot refuse advice in one screen and give it in the next. Rents are hard-coded 2025 estimates, not registry data |
| 27 Sep 2026 | Add a one-community snapshot, notable deals, project and off-plan splits; refusals suggest answerable questions | First live session: the hand-typed question got a generic table, and refusals read as failures. Everyday set 18/30 → 30/30 |
| 28 Sep 2026 | Build the learning loop: log outcomes, flag rephrase chains, map refusals to roadmap, propose eval candidates; human approves every change | Both live bugs were found by a person noticing a rephrase. That should not depend on someone watching |
| 28 Sep 2026 | Never pool the two communities; trends in "both" are shown side by side | Second live session: "price trend in both" returned one pooled line (−1.6%, HIGH confidence) while the two communities actually moved in opposite directions (−2.1% and +2.2%). Real-user set 5/7 → 7/7 |
| 27 Sep 2026 | Dashboard: stop blending synthetic history into real charts | A concat bug was silently dropping every real row, so the dashboard reported real data while plotting synthetic data |

## What's next, in priority order
1. **Benchmark an LLM planner against the same eval sets**, as a constrained classifier with a versioned prompt and locked settings. Publish accuracy **and** cost per 100 questions next to the rules planner, and ship whichever wins on missed refusals.
2. **Historic data** (the land department's bulk archive), so year-on-year moves from refused to answerable.
3. **Supply data** (project completions), so the most-asked refused question becomes an answer.
4. **Run the learning loop on a schedule** (built; see above) and review its report weekly. The most-refused category is the roadmap: it shows what decision-makers need that the data does not yet give them.

## Carrying the pattern beyond real estate
Nothing here is specific to property. Any agent that speaks to a decision-maker, such as an economic, fiscal or trade analyst answering a ministry, needs the same contract: **declare the source, declare the refusal categories, publish the eval score before it ships.** On a platform with many agents, the platform should enforce that contract so no agent can skip it. That is what makes a set of agents trustworthy, and it scales better than reviewing each agent by hand.
