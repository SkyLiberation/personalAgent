from __future__ import annotations

from personal_agent.storage.postgres_memory_search import BM25_KEY_FIELD, bm25_text_fields_json


def ensure_memory_schema(store) -> None:
    if store._initialized:
        return
    with store._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_notes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    parent_note_id TEXT,
                    source_fingerprint TEXT,
                    graph_episode_uuid TEXT,
                    payload JSONB NOT NULL,
                    search_text TEXT NOT NULL DEFAULT '',
                    embedding_vector VECTOR(128),
                    embedding_model TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS search_text TEXT NOT NULL DEFAULT ''")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS source_fingerprint TEXT")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS deleted_by TEXT")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_reason TEXT")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_run_id TEXT")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_checkpoint_id TEXT")
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS delete_snapshot_id TEXT")
            cur.execute("DROP INDEX IF EXISTS knowledge_notes_search_vector_idx")
            cur.execute("DROP INDEX IF EXISTS knowledge_notes_search_text_trgm_idx")
            cur.execute("ALTER TABLE knowledge_notes DROP COLUMN IF EXISTS search_vector")
            cur.execute(
                """
                DO $$
                DECLARE
                    embedding_type text;
                BEGIN
                    SELECT format_type(a.atttypid, a.atttypmod)
                    INTO embedding_type
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relname = 'knowledge_notes'
                      AND n.nspname = current_schema()
                      AND a.attname = 'embedding_vector'
                      AND NOT a.attisdropped;

                    IF embedding_type IS NULL THEN
                        ALTER TABLE knowledge_notes ADD COLUMN embedding_vector vector(128);
                    ELSIF embedding_type = 'double precision[]' THEN
                        ALTER TABLE knowledge_notes
                        ALTER COLUMN embedding_vector TYPE vector(128)
                        USING CASE
                            WHEN embedding_vector IS NULL THEN NULL
                            ELSE ('[' || array_to_string(embedding_vector, ',') || ']')::vector(128)
                        END;
                    ELSIF embedding_type <> 'vector(128)' THEN
                        ALTER TABLE knowledge_notes
                        ALTER COLUMN embedding_vector TYPE vector(128)
                        USING embedding_vector::text::vector(128);
                    END IF;
                END $$;
                """
            )
            cur.execute("ALTER TABLE knowledge_notes ADD COLUMN IF NOT EXISTS embedding_model TEXT")
            cur.execute("CREATE INDEX IF NOT EXISTS knowledge_notes_user_idx ON knowledge_notes (user_id, created_at)")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS knowledge_notes_active_user_idx
                ON knowledge_notes (user_id, created_at)
                WHERE deleted_at IS NULL
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS knowledge_notes_parent_idx ON knowledge_notes (parent_note_id)")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS knowledge_notes_deleted_idx
                ON knowledge_notes (user_id, deleted_at DESC)
                WHERE deleted_at IS NOT NULL
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS knowledge_notes_episode_idx ON knowledge_notes (graph_episode_uuid)")
            cur.execute("CREATE INDEX IF NOT EXISTS knowledge_notes_fingerprint_idx ON knowledge_notes (user_id, source_fingerprint)")
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS knowledge_notes_embedding_hnsw_idx
                ON knowledge_notes
                USING hnsw (embedding_vector vector_cosine_ops)
                """
            )
            cur.execute(
                """
                UPDATE knowledge_notes
                SET search_text = concat_ws(
                        ' ',
                        payload#>>'{body,title}',
                        payload#>>'{body,summary}',
                        payload#>>'{preextract,topic}',
                        payload#>>'{source,fingerprint}',
                        payload#>>'{source,metadata}',
                        payload#>>'{body,content}'
                    ),
                    source_fingerprint = COALESCE(source_fingerprint, payload#>>'{source,fingerprint}')
                WHERE search_text = ''
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS knowledge_notes_bm25_idx
                ON knowledge_notes
                USING bm25 (id, search_text)
                WITH (key_field='{BM25_KEY_FIELD}', text_fields='{bm25_text_fields_json()}')
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS review_cards (
                    id TEXT PRIMARY KEY,
                    note_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    due_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute("CREATE INDEX IF NOT EXISTS review_cards_note_idx ON review_cards (note_id, due_at)")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS knowledge_delete_snapshots (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    target_note_id TEXT NOT NULL,
                    deleted_by TEXT NOT NULL,
                    delete_reason TEXT NOT NULL DEFAULT '',
                    run_id TEXT,
                    checkpoint_id TEXT,
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS knowledge_delete_snapshots_note_idx
                ON knowledge_delete_snapshots (user_id, target_note_id, created_at DESC)
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_episodes (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    workflow TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    search_text TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute("DROP INDEX IF EXISTS memory_episodes_search_vector_idx")
            cur.execute("DROP INDEX IF EXISTS memory_episodes_search_text_trgm_idx")
            cur.execute("ALTER TABLE memory_episodes DROP COLUMN IF EXISTS search_vector")
            cur.execute("CREATE INDEX IF NOT EXISTS memory_episodes_user_idx ON memory_episodes (user_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS memory_episodes_thread_idx ON memory_episodes (thread_id, created_at DESC)")
            cur.execute("CREATE INDEX IF NOT EXISTS memory_episodes_workflow_idx ON memory_episodes (user_id, workflow, created_at DESC)")
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS memory_episodes_bm25_idx
                ON memory_episodes
                USING bm25 (id, search_text)
                WITH (key_field='{BM25_KEY_FIELD}', text_fields='{bm25_text_fields_json()}')
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    search_text TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cur.execute("DROP INDEX IF EXISTS memory_items_search_vector_idx")
            cur.execute("DROP INDEX IF EXISTS memory_items_search_text_trgm_idx")
            cur.execute("ALTER TABLE memory_items DROP COLUMN IF EXISTS search_vector")
            cur.execute("CREATE INDEX IF NOT EXISTS memory_items_user_type_idx ON memory_items (user_id, memory_type, status, created_at DESC)")
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS memory_items_bm25_idx
                ON memory_items
                USING bm25 (id, search_text)
                WITH (key_field='{BM25_KEY_FIELD}', text_fields='{bm25_text_fields_json()}')
                """
            )
        conn.commit()
    store._initialized = True
