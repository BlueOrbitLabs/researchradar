-- Owlume Phase 12b: Initial persistence schema (Supabase Auth compatible)
-- Run this in Supabase SQL Editor or via migration tool.
-- All user-owned tables use RLS for isolation. Foreign keys target auth.users.

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- User interests
CREATE TABLE IF NOT EXISTS user_interests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    is_custom BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, topic)
);

-- User subtopics
CREATE TABLE IF NOT EXISTS user_subtopics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    subtopic TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, topic, subtopic)
);

-- Discovery preferences
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    preferences TEXT[] DEFAULT '{}',
    disabled_subtypes TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Bookmarks
CREATE TABLE IF NOT EXISTS bookmarks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    article_title TEXT,
    article_source TEXT,
    article_topic TEXT,
    article_summary TEXT,
    category TEXT DEFAULT 'Read later',
    saved_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Followed sources
CREATE TABLE IF NOT EXISTS followed_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    source_url TEXT,
    followed_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, source_name)
);

-- Negative feedback
CREATE TABLE IF NOT EXISTS negative_feedback (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    feedback_key TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, feedback_key)
);

-- Read articles
CREATE TABLE IF NOT EXISTS read_articles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    article_url TEXT NOT NULL,
    read_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, article_url)
);

-- Alerts
CREATE TABLE IF NOT EXISTS alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(user_id, keyword)
);

-- Local news config
CREATE TABLE IF NOT EXISTS local_config (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    city TEXT,
    region TEXT,
    interests TEXT[] DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Enable RLS on all user-owned tables
ALTER TABLE user_interests ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_subtopics ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_preferences ENABLE ROW LEVEL SECURITY;
ALTER TABLE bookmarks ENABLE ROW LEVEL SECURITY;
ALTER TABLE followed_sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE negative_feedback ENABLE ROW LEVEL SECURITY;
ALTER TABLE read_articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE local_config ENABLE ROW LEVEL SECURITY;

-- RLS policies: owner-only access with explicit write checks.
-- FOR ALL covers SELECT/INSERT/UPDATE/DELETE; WITH CHECK prevents ownership changes.
CREATE POLICY "Users own their interests" ON user_interests
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their subtopics" ON user_subtopics
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their preferences" ON user_preferences
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their bookmarks" ON bookmarks
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their follows" ON followed_sources
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their feedback" ON negative_feedback
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their read articles" ON read_articles
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their alerts" ON alerts
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users own their local config" ON local_config
    FOR ALL
    USING (auth.uid() = user_id)
    WITH CHECK (auth.uid() = user_id);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
CREATE INDEX IF NOT EXISTS idx_followed_user ON followed_sources(user_id);
CREATE INDEX IF NOT EXISTS idx_read_articles_user ON read_articles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_interests_user ON user_interests(user_id);
