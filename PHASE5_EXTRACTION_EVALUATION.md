# Owlume Phase 5 — Extraction Integration Evaluation

**Date:** 2026-10-27. No application code changed in this phase.

## 1. Current extraction approach

Owlume's active pipeline (`app.py`) never fetches full article text. Every adapter
produces `title`, `url`, `summary` (provider snippet/abstract), `date`, `source`,
`topic`, and `relevance`. AI prompts (`build_summary_prompt`, etc.) receive
`title` + `summary[:300]` only. Extraction status is recorded as
`feed_excerpt`, `abstract`, or `metadata_only`.

## 2. Candidate library evaluation

### Trafilatura (adbar/trafilatura)
- **Licence:** Apache 2.0 (compatible with Owlume's MIT project).
- **Maintenance:** Active (pushed 26 Oct 2026, 7,029 stars, 473 forks, 80 open issues).
- **Dependencies:** lxml, courlan, htmldate, justext, urllib3, charset_normalizer, certifi. Moderate footprint (~15MB installed).
- **Extraction quality:** Consistently top-ranked in article extraction benchmarks. Handles boilerplate stripping, metadata extraction (title, author, date, image), and structured output (JSON, markdown, TEI).
- **Verdict:** Strongest candidate for full-text extraction. Apache 2.0 licence is compatible. However, it cannot extract from Google News redirect URLs (the primary Owlume news source), which return Google's own page, not the article.

### newspaper3k (codelucas/newspaper)
- **Licence:** MIT.
- **Maintenance:** Effectively unmaintained (513 open issues, last meaningful push 26 Oct 2026 but the project is in maintenance mode). Python 3.12+ compatibility is shaky.
- **Dependencies:** Heavy — nltk, jieba3k, tinysegmenter, tldextract, feedfinder2, cssselect, lxml, Pillow, PyYAML, and language corpora downloads.
- **Extraction quality:** Inferior to Trafilatura in benchmarks. Provides `top_image`, `authors`, `publish_date`, `text`, `summary`, `keywords`.
- **Verdict:** Not recommended. Heavier dependencies, worse extraction, effectively unmaintained. Its `top_image` extraction is useful but not worth the dependency cost.

### open-news (alphap365/open-news)
- **Licence:** MIT.
- **Maintenance:** Active (pushed 10 Oct 2026, 48 stars).
- **Dependencies:** Large — lxml, httpx, beautifulsoup4, feedparser, googlenewsdecoder, requests, ddgs, langdetect, legacy-cgi, plus optional Playwright and NLP.
- **Extraction quality:** Combines Google News search, RSS discovery, extraction, filtering, deduplication, ranking. Overlaps Owlume's existing adapters significantly.
- **Verdict:** Not recommended for selective integration. It is a full acquisition library, not a focused extraction tool. Its Google News decoder could be useful for resolving redirect URLs, but that is a narrow benefit for a large dependency.

### News Pulse (ParthAhuja4/news-pulse)
- **Licence:** None declared (GitHub shows no licence). Code reuse is not permitted without explicit permission.
- **Maintenance:** Low (1 star, no recent commits beyond Sep 2026).
- **Verdict:** Cannot reuse code. Its Trafilatura + BeautifulSoup extraction pattern is a useful reference only.

## 3. Controlled benchmark

### Test method
Fetched 5 Google News RSS articles and attempted extraction with both Trafilatura and newspaper3k.

### Results

| Method | Articles with text | Avg words extracted | Metadata quality | Date extraction | Image extraction |
|---|---|---|---|---|---|
| Trafilatura | 0/5 | 0 | N/A (Google redirect pages) | N/A | N/A |
| newspaper3k | 0/5 | 0 | "Google News" (incorrect) | None | Google's placeholder image (misleading) |
| Current (RSS snippets) | 5/5 | ~30-80 words | Publisher from title suffix | From RSS `published_parsed` | Rarely available |

### Key finding
**Google News redirect URLs cannot be extracted from.** Both Trafilatura and newspaper3k fail on Google News RSS article links because they resolve to Google's own redirect page, not the original article. This is the primary news source in Owlume's pipeline.

For direct publisher RSS feeds (BBC, The Hindu, etc.), Trafilatura would likely succeed, but Owlume primarily uses Google News RSS for news discovery.

### Wikipedia test (accessible article)
- Trafilatura: 28,248 words extracted, title + date + author metadata
- newspaper3k: 82 words extracted, incorrect title, no date, misleading image

Trafilatura is dramatically superior for accessible articles.

## 4. Recommendation

### Recommended integration (Phase 6 or later)
1. **Add Trafilatura as an optional dependency** (`trafilatura>=1.6.0` in requirements.txt, in an optional extra).
2. **Use it only for direct publisher feeds** where Owlume has the actual article URL (not Google News redirects).
3. **Store extracted text** in the article record with `extraction_status: "full_text"`.
4. **Feed AI prompts** with extracted text (up to 1500 chars) instead of 300-char snippets when available.
5. **Keep the snippet fallback** for Google News-sourced articles and paywalled content.
6. **Do not fetch full text on every UI rerun** — extract once during pool building, cache in the article record.

### Not recommended
- newspaper3k: unmaintained, heavy, worse extraction.
- open-news: full acquisition library, overlaps existing adapters, large dependency footprint.
- News Pulse: no licence declared, cannot reuse code.

### Licence compatibility
- Trafilatura: Apache 2.0 — compatible with Owlume's MIT project. Versions prior to 1.8.0 were GPLv3+; current version (2.3.1) is Apache 2.0.
- newspaper3k: MIT — compatible but not recommended.
- open-news: MIT — compatible but not recommended.

### Dependency impact
Adding Trafilatura would add ~15MB (lxml, courlan, htmldate, justext, urllib3, charset_normalizer, certifi). Most of these are already transitive dependencies of `requests` and `feedparser`. The incremental cost is modest.

### Remaining gaps
- Google News redirect URL resolution: neither Trafilatura nor newspaper3k can resolve these. A `googlenewsdecoder` library (used by open-news) could resolve them, but that adds another dependency.
- Paywall handling: Trafilatura cannot access paywalled content. Full text would be unavailable for such articles.
- Performance: Trafilatura's `fetch_url` makes an HTTP request per article. For a pool of 50 articles, this adds ~10-30 seconds to pool building. Should be limited to a subset (e.g., top 10 by relevance) or run asynchronously.

## 5. Conclusion

Trafilatura is the clear winner for full-text extraction quality and should be the chosen library if Owlume proceeds with extraction integration. However, the Google News redirect URL problem means that extraction will only benefit direct publisher RSS feeds, not the primary Google News discovery pipeline. The current snippet-based approach remains the practical default for most articles.

No code changes were made in this phase. No dependencies were added. No commits or pushes were made.
