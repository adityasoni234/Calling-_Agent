-- Runs once, on first initialisation of an empty data volume.
-- Migration 0001 also creates the extension, so a database restored from a
-- dump without this init step still ends up correct.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- lead search (Phase 7)
