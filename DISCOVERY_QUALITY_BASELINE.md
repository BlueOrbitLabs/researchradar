# Owlume discovery quality baseline — Phase 2

**Run date:** 2026-10-27  
**Data:** 25 deterministic, explicitly synthetic article fixtures in
`tests/test_discovery_quality_baseline.py`; **no live-provider records were
used**. The relevance calculations call `content_quality.relevance_score` with
the current topic catalogue terms and Owlume's deterministic no-OpenAI fallback
(`terms` and `relevance_core` equal the input topic). Local scores call the pure
`content_quality.local_relevance_score` extracted without changing its scoring
weights.

This is a repeatable code-path baseline, not an estimate of production/live-feed
quality. Synthetic relevance labels are hand-set fixture expectations and should
not be interpreted as calibrated human judgments.

## Aggregate results

| Measure | Baseline |
|---|---:|
| Candidate fixtures | 25 |
| Passed structural gate | 21 / 25 (84.0%) |
| Nonempty URLs passing basic shape check | 23 / 24 |
| Records with source field | 24 / 25 |
| Valid publication dates | 20 / 21 structurally-valid records |
| Unknown publication dates | 1 |
| Dated records within 30 days of baseline date | 19 |
| Dated records older than one year | 1 |
| Records after DOI/URL/title deduplication | 19 / 21 |
| Duplicates removed | 2 / 21 (9.5%) |
| Explicit canonical-URL duplicate pair collapsed | 1 / 1 |
| Explicit near-title duplicate pair collapsed | 1 / 1 |
| Publisher attribution among structurally accepted records | 21 / 21 (100%) |
| Google News publisher suffix resolved in fixture | `The Hindu` |
| Distinct publishers / topic labels after dedupe | 19 / 5 |
| Missing summary / source / date / title / URL | 1 / 1 / 1 / 1 / 1 |

The 23/24 URL measure counts only nonempty URLs; one additional fixture has no
URL. Structural acceptance separately rejects missing/invalid URL, missing
publisher and missing-title records.

## Relevance by interest fixture

`Eligible` means current `My Fields` floor (`relevance >= 0.30`); this is
measured on fixture candidates and does not represent provider retrieval yield.

| Interest | Candidates | Eligible | Top ranked title |
|---|---:|---:|---|
| Health & Medicine | 5 | 2 | Epidemiology study links vaccine coverage to fewer hospital admissions |
| Health Economics | 3 | 1 | Health economics analysis compares hospital payment models |
| AI & Technology | 4 | 0 | — |
| Climate & Environment | 3 | 1 | Climate policy study measures urban carbon emissions |
| Policy & Government | 4 | 1 | Government policy introduces new data protection regulation |

Across 20 fixture records manually marked as relevant, the deterministic
fallback scorer produced 5 true positives, 15 false negatives and no false
positives (precision 1.00, recall 0.25). This deliberately exposes a potential
recall weakness: for example, an “artificial intelligence” headline can be
semantically on-topic while not matching the literal “AI & Technology” label
or the limited fallback terms strongly enough. OpenAI-expanded terms may alter
this result, but no live AI-assisted evaluation was run.

## Local-news fixture

For city `Hyderabad`, region `Telangana`, and interest `Health & Medicine`, the
existing location score returned `[0.8, 0.3, 0.0]` for city+region+health,
region+health, and an unrelated national announcement respectively. This tests
the current local scoring rule only; it does not test whether live city feeds
return locally relevant stories.

## Run

```bash
python3 tests/test_discovery_quality_baseline.py
python3 -m unittest discover -s tests
```

The fixture suite checks profile coverage, date handling, exact/near duplicates,
attribution, location ranking, URL/metadata validation and publisher/topic
diversity. Live-source quality, per-adapter yield, redirects, and real-world
relevance remain unmeasured in this phase.
