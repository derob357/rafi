-- Rafi Assistant Database Migrations
-- Run this SQL against your Supabase project to create all required tables.
-- Requires the pgvector extension to be enabled.

-- Enable pgvector extension for embedding storage and similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable full-text search capabilities
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- =============================================================================
-- Table: messages
-- Stores all conversation messages with vector embeddings for semantic search.
-- =============================================================================
CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    embedding vector(1536),
    source TEXT NOT NULL DEFAULT 'telegram_text'
        CHECK (source IN ('telegram_text', 'telegram_voice', 'twilio_call', 'system')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_created_at ON messages (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages (role);
CREATE INDEX IF NOT EXISTS idx_messages_source ON messages (source);

-- Full-text search index on message content
CREATE INDEX IF NOT EXISTS idx_messages_content_fts
    ON messages USING gin (to_tsvector('english', content));

-- HNSW index for fast cosine similarity search on embeddings
CREATE INDEX IF NOT EXISTS idx_messages_embedding
    ON messages USING hnsw (embedding vector_cosine_ops);

-- =============================================================================
-- Table: tasks
-- Stores user tasks with status tracking and due dates.
-- =============================================================================
CREATE TABLE IF NOT EXISTS tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'completed')),
    due_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks (due_date);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks (created_at DESC);

-- =============================================================================
-- Table: notes
-- Stores user notes with title and body content.
-- =============================================================================
CREATE TABLE IF NOT EXISTS notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT NOT NULL,
    content TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes (created_at DESC);

-- Full-text search on notes
CREATE INDEX IF NOT EXISTS idx_notes_content_fts
    ON notes USING gin (to_tsvector('english', title || ' ' || COALESCE(content, '')));

-- =============================================================================
-- Table: call_logs
-- Stores Twilio call records with transcripts and summaries.
-- =============================================================================
CREATE TABLE IF NOT EXISTS call_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    call_sid TEXT NOT NULL,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    duration_seconds INTEGER DEFAULT 0,
    transcript TEXT DEFAULT '',
    summary TEXT DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_call_logs_call_sid ON call_logs (call_sid);
CREATE INDEX IF NOT EXISTS idx_call_logs_created_at ON call_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_call_logs_direction ON call_logs (direction);

-- =============================================================================
-- Table: settings
-- Key-value store for runtime user settings (JSON-encoded values).
-- =============================================================================
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Table: oauth_tokens
-- Encrypted OAuth token storage for Google API access.
-- =============================================================================
CREATE TABLE IF NOT EXISTS oauth_tokens (
    provider TEXT PRIMARY KEY,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ,
    scopes TEXT DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- =============================================================================
-- Table: events_cache
-- Cached Google Calendar events for reminder scheduling.
-- =============================================================================
CREATE TABLE IF NOT EXISTS events_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    google_event_id TEXT NOT NULL UNIQUE,
    summary TEXT DEFAULT '',
    location TEXT DEFAULT '',
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ NOT NULL,
    reminded BOOLEAN NOT NULL DEFAULT FALSE,
    snoozed_until TIMESTAMPTZ,
    synced_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_cache_google_id ON events_cache (google_event_id);
CREATE INDEX IF NOT EXISTS idx_events_cache_start_time ON events_cache (start_time);
CREATE INDEX IF NOT EXISTS idx_events_cache_reminded ON events_cache (reminded);

-- =============================================================================
-- RPC Function: match_messages
-- Performs cosine similarity search on message embeddings via pgvector.
-- Used by the memory service for semantic recall.
-- =============================================================================
CREATE OR REPLACE FUNCTION match_messages(
    query_embedding vector(1536),
    match_count INT DEFAULT 5,
    match_threshold FLOAT DEFAULT 0.7
)
RETURNS TABLE (
    id UUID,
    role TEXT,
    content TEXT,
    source TEXT,
    created_at TIMESTAMPTZ,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.role,
        m.content,
        m.source,
        m.created_at,
        1 - (m.embedding <=> query_embedding) AS similarity
    FROM messages m
    WHERE m.embedding IS NOT NULL
        AND 1 - (m.embedding <=> query_embedding) > match_threshold
    ORDER BY m.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- =============================================================================
-- RPC Function: hybrid_search_messages
-- Combines cosine similarity with full-text search for hybrid retrieval.
-- =============================================================================
CREATE OR REPLACE FUNCTION hybrid_search_messages(
    query_embedding vector(1536),
    query_text TEXT,
    match_count INT DEFAULT 5,
    match_threshold FLOAT DEFAULT 0.5
)
RETURNS TABLE (
    id UUID,
    role TEXT,
    content TEXT,
    source TEXT,
    created_at TIMESTAMPTZ,
    similarity FLOAT,
    rank FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        m.id,
        m.role,
        m.content,
        m.source,
        m.created_at,
        1 - (m.embedding <=> query_embedding) AS similarity,
        ts_rank_cd(to_tsvector('english', m.content), plainto_tsquery('english', query_text)) AS rank
    FROM messages m
    WHERE m.embedding IS NOT NULL
        AND (
            1 - (m.embedding <=> query_embedding) > match_threshold
            OR to_tsvector('english', m.content) @@ plainto_tsquery('english', query_text)
        )
    ORDER BY
        (0.7 * (1 - (m.embedding <=> query_embedding)))
        + (0.3 * ts_rank_cd(to_tsvector('english', m.content), plainto_tsquery('english', query_text)))
        DESC
    LIMIT match_count;
END;
$$;

-- =============================================================================
-- Trigger: Auto-update updated_at timestamps
-- =============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER notes_updated_at
    BEFORE UPDATE ON notes
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE OR REPLACE TRIGGER oauth_tokens_updated_at
    BEFORE UPDATE ON oauth_tokens
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- =============================================================================
-- Row Level Security (RLS)
-- Enable RLS on all tables. The service_role_key bypasses RLS,
-- but this prevents accidental exposure via the anon key.
-- =============================================================================
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE call_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE events_cache ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (the assistant uses service_role_key)
CREATE POLICY service_role_all_messages ON messages
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY service_role_all_tasks ON tasks
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY service_role_all_notes ON notes
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY service_role_all_call_logs ON call_logs
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY service_role_all_settings ON settings
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY service_role_all_oauth_tokens ON oauth_tokens
    FOR ALL USING (auth.role() = 'service_role');
CREATE POLICY service_role_all_events_cache ON events_cache
    FOR ALL USING (auth.role() = 'service_role');
