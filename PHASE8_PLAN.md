# Owlume Phase 8 — Persistence Design (No Integration Yet)

**Date:** 2026-10-28. No code changes for persistence. This document proposes a
design based on the Phase 7 audit.

## 1. Current state

All user state lives in `st.session_state`:
- `selected_topics`, `custom_topics`, `subtopics`, `active_topic`
- `discover_preferences`, `disabled_subtypes`
- `bookmarks` (list of `{article, category, saved_at}`)
- `library` (list of `{title, url, topic, summary, ts}`)
- `followed_sources` (set of source names/URLs)
- `negative_feedback` (set of "topic::source" keys)
- `read_articles` (set of URLs)
- `alerts` (list of keywords)
- `local_city`, `local_region`, `local_interests`
- `chat_history`, `briefing`
- `feed_pool`, `feed_pool_key`, `feed_pool_errors`

**Supabase client** (`svc`) is initialized when credentials exist but is never
used for reads/writes. No tables are defined in the codebase.

**engine.py** has a separate SQLite persistence layer (`owlume.db`) with
`articles`, `feedback`, and `user_prefs` tables. It is NOT imported by app.py.
Its schema uses `make_article` (different field names than app.py's `_make_article`).
Wiring it in would require a deliberate migration.

## 2. Proposed Supabase schema

### Tables

```sql
-- Users (managed by Supabase Auth or a simple user table)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE,
    role TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- User interests
CREATE TABLE user_interests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    is_custom BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, topic)
);

-- User subtopics
CREATE TABLE user_subtopics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    subtopic TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, topic, subtopic)
);

-- Discovery preferences
CREATE TABLE user_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    preferences TEXT[] DEFAULT '{}',
    disabled_subtypes TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Bookmarks
CREATE TABLE bookmarks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    article_title TEXT,
    article_source TEXT,
    article_topic TEXT,
    article_summary TEXT,
    category TEXT DEFAULT 'Read later',
    saved_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Saved library
CREATE TABLE library (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    article_title TEXT,
    article_topic TEXT,
    article_summary TEXT,
    saved_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Followed sources
CREATE TABLE followed_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_url TEXT,
    followed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, source_name)
);

-- Negative feedback
CREATE TABLE negative_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    feedback_key TEXT NOT NULL,  -- "topic::source"
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, feedback_key)
);

-- Read articles
CREATE TABLE read_articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    read_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Alerts
CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, keyword)
);

-- Local news config
CREATE TABLE local_config (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    city TEXT,
    region TEXT,
    interests TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Cached articles (optional, for performance)
CREATE TABLE cached_articles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    summary TEXT,
    source TEXT,
    topic TEXT,
    date_str TEXT,
    relevance REAL,
    image TEXT,
    extracted_text TEXT,
    extraction_status TEXT,
    retrieved_at TIMESTAMPTZ DEFAULT now(),
    expires_at TIMESTAMPTZ
);
```

## 3. Ownership boundaries

| State | Owner | Persistence |
|---|---|---|
| User profile/role | Supabase (users table) | Persistent |
| Interests | Supabase (user_interests) | Persistent |
| Subtopics | Supabase (user_subtopics) | Persistent |
| Discovery preferences | Supabase (user_preferences) | Persistent |
| Disabled subtypes | Supabase (user_preferences) | Persistent |
| Bookmarks | Supabase (bookmarks) | Persistent |
| Library | Supabase (library) | Persistent |
| Followed sources | Supabase (followed_sources) | Persistent |
| Negative feedback | Supabase (negative_feedback) | Persistent |
| Read articles | Supabase (read_articles) | Persistent |
| Alerts | Supabase (alerts) | Persistent |
| Local config | Supabase (local_config) | Persistent |
| Feed pool | session_state (ephemeral) | Session only |
| Extraction cache | In-memory dict | Process only |
| Chat history | session_state (ephemeral) | Session only |
| Briefing | session_state (ephemeral) | Session only |

## 4. Row-level security

Every table with `user_id` must have RLS enabled:
```sql
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can only access their own bookmarks"
    ON bookmarks FOR ALL
    USING (auth.uid() = user_id);
```

## 5. Migration strategy

1. **Phase 1 (read-only):** Add Supabase reads that populate session_state on startup. Fall back to empty state if Supabase is unavailable.
2. **Phase 2 (write-through):** Add Supabase writes alongside session_state updates. Keep session_state as the source of truth for the UI.
3. **Phase 3 (source of truth):** Make Supabase the source of truth, with session_state as a cache. Add conflict resolution for concurrent edits.
4. **Rollback:** Each phase can be reverted independently. Session_state fallback ensures the app works without Supabase.

## 6. engine.py disposition

The `engine.py` module has:
- SQLite persistence (`owlume.db`)
- Crossref and Europe PMC adapters (not in app.py)
- Adaptive ranking with UserPrefs
- Feedback persistence

**Recommendation:** Do NOT integrate engine.py. Reasons:
1. Different article schema (uses `make_article` with different field names)
2. Different dedup logic (URL-only vs DOI+URL+title)
3. Different relevance scoring (simple word overlap vs multi-signal)
4. Would require a full data migration
5. The active app's `content_quality.py` and `feed_strategy.py` are more sophisticated

Instead, selectively port useful features from engine.py if needed:
- Crossref/Europe PMC adapters (add to app.py's adapter set)
- Feedback persistence pattern (adapt to Supabase)

## 7. What should NOT persist

- Feed pool cache (rebuilt per session, too large)
- Extraction cache (in-memory is fine for prototype)
- Chat history (session-only by design)
- Briefing (regenerated per session)
- Basket adaptation results (derived from interests/preferences)

## 8. Implementation order

1. Create Supabase tables (manual, via dashboard)
2. Add read functions (load interests, bookmarks, follows on startup)
3. Add write functions (save bookmark, follow source, etc.)
4. Migrate session_state to use Supabase as source of truth
5. Add error handling for Supabase unavailability
6. Test with multiple users

## 9. Risks

- Supabase free tier has rate limits and cold starts
- RLS policies must be tested thoroughly
- Migration from session-only to persistent could lose data if not done carefully
- The app currently works without Supabase credentials (graceful degradation)
