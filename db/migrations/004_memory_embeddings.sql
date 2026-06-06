-- User- and session-scoped conversation memory stored as pgVector embeddings.
-- Complements the JSONB `conversations.messages` audit log with semantic retrieval.

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope       TEXT NOT NULL CHECK (scope IN ('session', 'user')),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id  TEXT,
    turn_index  INTEGER NOT NULL DEFAULT 0,
    content     TEXT NOT NULL,
    embedding   vector(768) NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_session_turn
    ON memory_embeddings (session_id, turn_index)
    WHERE scope = 'session';

CREATE INDEX IF NOT EXISTS idx_memory_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS idx_memory_user_scope
    ON memory_embeddings (user_id, scope, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_session_scope
    ON memory_embeddings (session_id)
    WHERE scope = 'session';
