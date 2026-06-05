-- Runs once on first postgres container startup (docker-entrypoint-initdb.d)
-- Creates the database and grants privileges.
-- Alembic handles all table/index creation via migrations.

\c mcp_gateway

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for fuzzy text search on server names/tools
CREATE EXTENSION IF NOT EXISTS vector;     -- pgvector for KB embeddings

CREATE TABLE IF NOT EXISTS kb_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title TEXT,
    content TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(384),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
