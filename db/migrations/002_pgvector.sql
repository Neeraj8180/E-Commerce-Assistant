-- 002_pgvector.sql — embeddings table for RAG.
-- Embedding dimension matches `nomic-embed-text` (768).

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS embeddings (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type    TEXT        NOT NULL,
    doc_id      TEXT        NOT NULL,
    chunk_index INTEGER     NOT NULL DEFAULT 0,
    title       TEXT,
    content     TEXT        NOT NULL,
    embedding   vector(768) NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{}'::JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (doc_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw
    ON embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_embeddings_doc_type ON embeddings(doc_type);
