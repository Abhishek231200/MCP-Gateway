-- Runs once on first postgres container startup (docker-entrypoint-initdb.d)
-- Creates the database and grants privileges.
-- Alembic handles all table/index creation via migrations.

\c mcp_gateway

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- for fuzzy text search on server names/tools
