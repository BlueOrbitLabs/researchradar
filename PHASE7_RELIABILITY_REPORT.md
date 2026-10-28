# Owlume Phase 7 — Reliability, Persistence and Performance Audit

**Date:** 2026-10-27. No commits or pushes made. Working-tree changes preserved.

## 1. Baseline measurements (deterministic mocks, no live network)

| Scenario | Measured time | Notes |
|---|---:|---|
| Select extraction candidates (no extraction) | 0.02 ms | Pure filtering |
| 5 successful extractions (fresh cache) | 104.26 ms | ~20ms each, mock HTML |
| 5 cached extractions (repeated) | 0.02 ms | Cache hit, no re-fetch |
| 5 failed extractions (timeout) | 4.50 ms | Fast failure |
| 5 slow extractions (0.5s each) | 2556.18 ms | Sequential blocking |

**Key finding:** Extraction is sequential and blocking. Five slow extractions (0.5s each) took 2.5s total. In production, extracting 5 articles at ~2s each would add ~10s to pool building. The current approach (top-5 candidates only) limits this impact.

**Recommendation:** Keep extraction in pool construction but limit to 3-5 candidates. Consider async extraction or background enrichment for larger pools.

## 2. Persistence audit

| State | Survives rerun | Survives refresh | Survives new session | Survives restart | Survives redeploy |
|---|---|---|---|---|---|
| Interests/preferences | ✅ (session_state) | ❌ (lost) | ❌ | ❌ | ❌ |
| Bookmarks | ✅ | ❌ | ❌ | ❌ | ❌ |
| Followed sources | ✅ | ❌ | ❌ | ❌ | ❌ |
| Negative feedback | ✅ | ❌ | ❌ | ❌ | ❌ |
| Read articles | ✅ | ❌ | ❌ | ❌ | ❌ |
| Feed pool cache | ✅ (session_state) | ❌ | ❌ | ❌ | ❌ |
| Extracted text | ✅ (session_state) | ❌ | ❌ | ❌ | ❌ |
| Extraction cache | ✅ (in-memory) | ❌ | ❌ | ❌ | ❌ |

**Supabase:** Client is initialized when credentials exist, but no table reads/writes were found in app.py. The `svc` object exists but is never used for persistence.

**engine.py:** Has SQLite persistence (`owlume.db`) with `persist_articles`, `cached_articles`, `record_feedback`, etc. But it is NOT imported by app.py. Wiring it in would require a deliberate migration.

**Recommendation:** The smallest safe persistence solution is to wire Supabase for bookmarks, follows, and preferences. This requires:
1. Creating tables in Supabase (articles, bookmarks, follows, preferences, feedback)
2. Adding read/write functions in app.py
3. Migrating session_state to use Supabase when available, falling back to session_state

This is a Phase 8 task, not Phase 7. Phase 7 only audits.

## 3. Date provenance

- `publication_date` and `date` (alias) are publication dates only
- `updated_at` stores RSS update timestamps separately
- `retrieved_at` records collection time (UTC ISO-8601)
- RSS `_parse_feed_dates()` keeps published and updated separate
- `date_source` tracks whether date is "published", "updated", or "unknown"
- Extraction timestamps never become publication dates (validated in `apply_extraction`)
- Snippets are preserved on extraction success (never overwritten)

## 4. URL and redirect safety

- Only http/https schemes accepted
- Private/loopback/link-local/reserved IPs rejected via `socket.getaddrinfo`
- Google News wrapper URLs rejected
- Response size limited to 2MB
- HTTP timeout: 12s default
- DNS resolution performed before download
- No paywall bypass, no robots.txt checking (potential gap)
- No redirect following validation (downloader contract doesn't follow redirects)

**Known limitation:** Redirect destinations are not validated. If a downloader follows redirects, the final destination could be unsafe. The current Trafilatura `fetch_url` may follow redirects. This should be addressed if redirect following is enabled.

## 5. AI evidence integrity

- AI prompts use extracted text (up to 1500 chars) when available
- Falls back to 300-char snippet with "short snippet, not full article" note
- Daily briefing prompt now includes extracted text/summaries (updated in Phase 6)
- Prompts explicitly state "Base claims on the provided text only"
- When only snippet available, prompt says "The available text is a short snippet, not the full article"

## 6. Architecture recommendation

**Keep extraction in pool construction** with these constraints:
- Limit to 3-5 candidates (currently 5)
- Use in-memory cache (doesn't survive restart — acceptable for now)
- Don't block feed on extraction failure
- Consider moving to background enrichment for larger pools

**Do not add** a worker, queue, or database. The current architecture is sufficient for the prototype stage. Wire Supabase for persistence when ready for multi-user deployment.

## 7. Test results

- `py_compile` — clean (app.py, content_quality.py, feed_strategy.py, extraction.py)
- Full suite — **168 tests passed**
- Synthetic baseline — 93 tests passed
- AppTest smoke — 7 views, zero exceptions/errors

## 8. Remaining risks

1. **No persistence** — all state is session-only. Bookmarks, follows, preferences lost on browser close.
2. **Extraction cache** — in-memory only, lost on restart.
3. **Google News redirect URLs** — cannot be extracted from.
4. **Sequential extraction** — 5 slow articles = 2.5s+ added latency.
5. **No redirect validation** — if downloader follows redirects, final destination unchecked.
6. **No robots.txt checking** — extraction may violate site policies.
7. **AI prompt evidence** — briefing uses titles + snippets/extracted text, not full analysis.

## Files changed (Phase 7)
- `extraction.py` — security tests added (no code changes)
- `tests/test_extraction.py` — added UrlSafetyTest (9 tests) + ExtractionProvenanceTest (4 tests)
- No application code changes in Phase 7 (audit only)

No commits or pushes made.
