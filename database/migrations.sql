-- ============================================================
-- Social Media Automation Agent — Database Schema
-- Run once on your Neon database (via Neon SQL Editor)
-- ============================================================

-- Published & draft posts
CREATE TABLE IF NOT EXISTS posts (
    id              SERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    content_linkedin TEXT,
    content_twitter  TEXT,
    content_medium   TEXT,
    content_github   TEXT,
    image_url        TEXT,
    platforms        TEXT[]  NOT NULL DEFAULT '{}',
    linkedin_url     TEXT,
    twitter_url      TEXT,
    medium_url       TEXT,
    github_url       TEXT,
    hashtags         TEXT[]  DEFAULT '{}',
    status           TEXT    NOT NULL DEFAULT 'published',  -- published | draft | failed
    posted_at        TIMESTAMPTZ DEFAULT NOW(),
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Scheduled (future) posts
CREATE TABLE IF NOT EXISTS scheduled_posts (
    id              SERIAL PRIMARY KEY,
    topic           TEXT NOT NULL,
    content_linkedin TEXT,
    content_twitter  TEXT,
    content_medium   TEXT,
    content_github   TEXT,
    image_url        TEXT,
    platforms        TEXT[]  NOT NULL DEFAULT '{}',
    scheduled_time   TIMESTAMPTZ NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'pending',  -- pending | posted | cancelled
    job_id           TEXT,                                -- APScheduler job id
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Per-user style preferences (updated via Telegram /style command)
CREATE TABLE IF NOT EXISTS user_style_prefs (
    id                SERIAL PRIMARY KEY,
    telegram_user_id  BIGINT UNIQUE NOT NULL,
    tone              TEXT DEFAULT 'entrepreneur',        -- entrepreneur | technical | storyteller | custom
    custom_notes      TEXT,                              -- free-form style instructions
    updated_at        TIMESTAMPTZ DEFAULT NOW()
);

-- OAuth tokens (LinkedIn access token stored securely in DB)
CREATE TABLE IF NOT EXISTS oauth_tokens (
    id            SERIAL PRIMARY KEY,
    platform      TEXT UNIQUE NOT NULL,  -- linkedin | twitter
    access_token  TEXT,
    refresh_token TEXT,
    person_urn    TEXT,                  -- LinkedIn: urn:li:person:xxx
    expires_at    TIMESTAMPTZ,
    extra_data    JSONB DEFAULT '{}',
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- Post chain memory (for connected storytelling)
CREATE TABLE IF NOT EXISTS post_context (
    id          SERIAL PRIMARY KEY,
    summary     TEXT NOT NULL,        -- brief summary of last post
    topic       TEXT NOT NULL,
    platforms   TEXT[] DEFAULT '{}',
    posted_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_posts_posted_at      ON posts(posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_scheduled_status     ON scheduled_posts(status, scheduled_time);
CREATE INDEX IF NOT EXISTS idx_post_context_recent  ON post_context(posted_at DESC);

-- ── Migration: Add image_data column for storing image bytes ───────────────
ALTER TABLE posts           ADD COLUMN IF NOT EXISTS image_data BYTEA;
ALTER TABLE scheduled_posts ADD COLUMN IF NOT EXISTS image_data BYTEA;

-- ── Migration: Remove Twitter columns (run once) ──────────────────────────────
-- Run these in Neon SQL Editor to drop Twitter columns from existing tables:
--
-- ALTER TABLE posts            DROP COLUMN IF EXISTS content_twitter;
-- ALTER TABLE posts            DROP COLUMN IF EXISTS twitter_url;
-- ALTER TABLE scheduled_posts  DROP COLUMN IF EXISTS content_twitter;
