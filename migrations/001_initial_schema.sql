-- Owlume Phase 9: Initial persistence schema
-- Run this in Supabase SQL Editor or via migration tool.
-- All tables use RLS for user isolation.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users (managed by Supabase Auth or simple table)
CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE,
    role TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- User interests
CREATE TABLE IF NOT EXISTS user_interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    is_custom BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, topic)
);

-- User subtopics
CREATE TABLE IF NOT EXISTS user_subtopics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    subtopic TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, topic, subtopic)
);

-- Discovery preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    preferences TEXT[] DEFAULT '{}',
    disabled_subtypes TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Bookmarks
CREATE TABLE IF NOT EXISTS bookmarks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
CREATE TABLE IF NOT EXISTS library (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    article_title TEXT,
    article_topic TEXT,
    article_summary TEXT,
    saved_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Followed sources
CREATE TABLE IF NOT EXISTS followed_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_url TEXT,
    followed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, source_name)
);

-- Negative feedback
CREATE TABLE IF NOT EXISTS negative_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    feedback_key TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, feedback_key)
);

-- Read articles
CREATE TABLE IF NOT EXISTS read_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    read_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, keyword)
);

-- Local news config
CREATE TABLE IF NOT EXISTS local_config (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    city TEXT,
    region TEXT,
    interests TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Cached articles (optional, for performance)
CREATE TABLE IF NOT EXISTS cached_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
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

-- Enable RLS on all user-owned tables
ALTER TABLE user_interests ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_subtopics ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE library ENABLE ROW LEVEL SECURITY;
ALTER TABLE followed_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE negative_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE read_articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE local_config ENABLE ROW LEVEL SECURITY;

-- RLS policies: users can only access their own data
CREATE POLICY "Users own their interests" ON user_interests
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their subtopics" ON user_subtopics
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their preferences" ON user_preferences
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their bookmarks" ON bookmarks
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their library" ON library
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their follows" ON followed_sources
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their feedback" ON negative_feedback
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their read articles" ON read_articles
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their alerts" ON alerts
    FOR ALL USING (auth.uid() = user_id);
CREATE POLICY "Users own their local config" ON local_config
    FOR ALL USING (auth.uid() = user_id);

-- Cached articles are shared (no RLS needed, or read-only for all)
ALTER TABLE cached_articles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Anyone can read cached articles" ON cached_articles
    FOR SELECT USING (true);
CREATE POLICY "Service role can write cached articles" ON cached_articles
    FOR ALL USING (auth.role() = 'service_role');

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
CREATE INDEX IF NOT EXISTS idx_library_user ON library(user_id);
CREATE INDEX IF NOT EXISTS idx_followed_user ON followed_sources(user_id);
CREATE INDEX IF NOT EXISTS idx_read_articles_user ON read_articles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_interests_user ON user_interests(user_id);
CREATE INDEX IF NOT EXISTS idx_cached_articles_url ON cached_articles(url);
