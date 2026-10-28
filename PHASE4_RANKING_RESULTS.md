# Owlume Phase 4 — ranking and freshness results

**Measurement date:** 2026-10-27.  
**Evidence:** controlled synthetic fixture baseline only; no live-provider
accuracy claim. The Phase 2 baseline is retained unchanged in
`DISCOVERY_QUALITY_BASELINE.md`.

## Changes made

- **Publication-date handling:** `content_quality.publication_date_value()` is
  now used by briefing eligibility, feed sorting and ranking freshness. RSS
  `date_source="updated"` without a publication date is treated as unknown,
  not fresh. Partial `YYYY-MM` dates parse as the first day of that month; date
  objects/datetimes are handled safely. Future-dated items do not receive a
  freshness boost and are excluded from Emerging / discovery recency windows.
- **Historical research:** remains eligible in My Fields when relevant; its
  freshness score remains low. Emerging/briefing windows still require current
  publication dates.
- **Unknown source quality:** index/adapter labels (`OpenAlex`, `PubMed`,
  `arXiv`, `DOAJ`, `Crossref`, etc.) no longer confer publisher credibility.
  Unknown or missing publisher quality is `None`, not a fabricated numeric
  value. Weighted scoring renormalizes over available signals so missing
  quality is neither a bonus nor a penalty. Known publisher-name tiers remain
  explicitly heuristic; domain suffix evidence is used only when a
  `publisher_domain`/`source_domain` field exists.
- **Relevance false negatives:** added a deterministic, small alias experiment
  using existing multiword catalogue keywords (e.g. “artificial intelligence”
  for “AI & Technology”). It reuses existing phrase weights and makes an alias
  in the summary Relevant, never High. Lifestyle-penalty items do not receive
  the alias boost. No per-article AI request or new dependency was added.
- **Duplicate metadata conflicts:** duplicate DOI records retain both original
  source links, preserve date conflicts with provenance, prefer a direct
  publisher over an index/aggregator label, and select richer summaries and
  provider-declared content type where present. Near-title dedupe still keeps
  distinct titles below the existing similarity threshold separate.
- **Local news:** remains excluded from the general pool; fixture smoke tests
  confirm explicit Local News topics are not sent through general discovery.

## Synthetic baseline comparison

| Measure | Phase 2 | Phase 4 |
|---|---:|---:|
| Manually expected-relevant fixture records | 20 | 20 |
| True positives at the existing Relevant threshold | 5 | 9 |
| False positives | 0 | 0 |
| False negatives | 15 | 11 |
| Fixture precision / recall | 1.00 / 0.25 | 1.00 / 0.45 |
| AI & Technology fixture candidates eligible | 0 / 4 | 2 / 4 |
| Health & Medicine fixture candidates eligible | 2 / 5 | 3 / 5 |

These results measure only the labelled synthetic fixtures. The alias change
improved their lexical recall without increasing fixture false positives; it
does not demonstrate live-feed accuracy or semantic understanding.

## Tests

- Added `tests/test_phase4_ranking_quality.py` (22 focused regression tests):
  malformed/partial/update-only/future dates, historical research, recent weak
  content, source-quality uncertainty, DOI conflicts, retained links, distinct
  similar titles, malformed metadata, pool validation/local isolation, and the
  curated alias experiment.
- Full suite: **122 tests passed**.
- `py_compile`: passed for changed Python files.
- AppTest smoke: Feed, Discover, Saved, Ask, Briefing, Alerts and Local News all
  rendered with zero exceptions/errors.

## Remaining risks

- Relevance remains lexical/curated-alias based, not semantic embeddings. AI
  expansion may change live results and was not measured here.
- Synthetic relevance labels are hand-authored; a representative human-labeled
  live sample is needed before any further score/threshold tuning.
- Named publisher tiers remain heuristics, not verified editorial-quality
  audits. Most active adapters do not provide a separate publisher-domain
  evidence field, so many sources correctly remain quality-unknown.
- `engine.py` remains a separate, unused SQLite implementation and was not
  integrated or migrated in this phase.
