"""本研究主体的知识事实全量只读摘要；不初始化仓储、不导出正文。"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Literal

import psycopg
from psycopg import sql
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .retrieval_qualification_review import Digest

ROOT = Path(__file__).resolve().parents[2]
OWNER_TABLES = (
    ("knowledge_artifacts", "artifact_id"),
    ("knowledge_extraction_runs", "extraction_run_id"),
    ("knowledge_evidence_blocks", "evidence_block_id"),
    ("knowledge_evidence_spans", "evidence_span_id"),
    ("knowledge_claims", "claim_id"),
    ("knowledge_grounding_runs", "grounding_run_id"),
    ("knowledge_claim_support_events", "event_id"),
    ("knowledge_claim_admission_decisions", "admission_id"),
    ("knowledge_state_events", "event_id"),
    ("knowledge_relations", "relation_id"),
    ("knowledge_items", "knowledge_item_id"),
    ("knowledge_decisions", "decision_id"),
    ("knowledge_research_events", "research_event_id"),
    ("knowledge_review_items", "review_item_id"),
    ("knowledge_gaps", "gap_id"),
    ("knowledge_graph_projections", "graph_projection_id"),
    ("knowledge_projection_jobs", "projection_job_id"),
)
OTHER_TABLES = (
    ("knowledge_notes", "id"),
    ("review_cards", "id"),
    ("personal_knowledge_lifecycle_operations", "command_id"),
    ("personal_knowledge_lifecycle_receipts", "receipt_id"),
)
TABLES = (*OWNER_TABLES, *OTHER_TABLES)
OWNER_SOURCES = (
    "src/personal_agent/infra/storage/postgres_knowledge_store.py",
    "src/personal_agent/infra/storage/postgres_knowledge_lifecycle_store.py",
    "src/personal_agent/infra/storage/postgres_memory_schema.py",
    "evals/product_baselines/retrieval_knowledge_snapshot.py",
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OwnerSource(_Strict):
    path: str
    sha256: Digest


class KnowledgeTableSnapshot(_Strict):
    table: str
    present: bool
    row_count: int = Field(ge=0)
    rows_sha256: Digest

    @model_validator(mode="after")
    def absent_is_empty(self) -> KnowledgeTableSnapshot:
        if not self.present and (self.row_count or self.rows_sha256 != sha256(b"").hexdigest()):
            raise ValueError("不存在的知识表不能包含行事实")
        return self


class ScopedKnowledgeSnapshot(_Strict):
    version: Literal[1] = 1
    principal: AuthenticatedPrincipal
    interaction_run_ref: str = Field(min_length=1)
    preparation_sha256: Digest
    database_identity_sha256: Digest
    started_at: AwareDatetime
    completed_at: AwareDatetime
    isolation: Literal["repeatable read"]
    read_only: Literal[True]
    owner_sources: tuple[OwnerSource, ...]
    tables: tuple[KnowledgeTableSnapshot, ...]

    @model_validator(mode="after")
    def complete_scope(self) -> ScopedKnowledgeSnapshot:
        if (self.principal.tenant_id != "personal-agent" or self.completed_at < self.started_at
                or tuple(item.table for item in self.tables) != tuple(name for name, _ in TABLES)
                or tuple(item.path for item in self.owner_sources) != OWNER_SOURCES):
            raise ValueError("知识快照的主体、时间或 owner 表／源码集合不完整")
        return self


def _query(table: str, key: str, schema: str) -> sql.Composed:
    relation = sql.Identifier(schema, table)
    if table == "review_cards":
        scope = sql.SQL("JOIN {} n ON n.id = k.note_id WHERE n.user_id = %s").format(
            sql.Identifier(schema, "knowledge_notes"))
    elif table == "personal_knowledge_lifecycle_receipts":
        scope = sql.SQL("JOIN {} o ON o.command_id = k.command_id WHERE o.owner_id = %s AND o.user_id = %s").format(
            sql.Identifier(schema, "personal_knowledge_lifecycle_operations"))
    elif table == "knowledge_notes":
        scope = sql.SQL("WHERE k.user_id = %s")
    elif table == "personal_knowledge_lifecycle_operations":
        scope = sql.SQL("WHERE k.owner_id = %s AND k.user_id = %s")
    else:
        scope = sql.SQL("WHERE k.owner_id = %s")
    return sql.SQL("SELECT k.{}, to_jsonb(k)::text FROM {} k {} ORDER BY k.{} COLLATE \"C\"").format(
        sql.Identifier(key), relation, scope, sql.Identifier(key))


def capture_snapshot(preparation: Path, database_url: str) -> ScopedKnowledgeSnapshot:
    """所有行来自同一实际只读事务；调用者负责真实 before／after 时点。"""
    from .run_retrieval_acceptance import Preparation

    prepared_bytes = preparation.read_bytes()
    prepared = Preparation.model_validate_json(prepared_bytes)
    principal = prepared.world.initial.principal
    if principal.tenant_id != "personal-agent":
        raise ValueError("旧 note 仓储只提供现行 personal-agent 单租户隔离，不能外推其他 tenant")
    sources = tuple(OwnerSource(path=name, sha256=sha256((ROOT / name).read_bytes()).hexdigest())
                    for name in OWNER_SOURCES)
    started = datetime.now(UTC)
    tables = []
    with psycopg.connect(database_url, autocommit=True) as connection, connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        database, schema, address, port, isolation, read_only = connection.execute(
            "SELECT current_database(), current_schema(), inet_server_addr()::text, inet_server_port(), "
            "current_setting('transaction_isolation'), current_setting('transaction_read_only')").fetchone()
        if read_only != "on" or isolation != "repeatable read":
            raise ValueError("没有取得真实 repeatable read／read only 事务")
        discovered = {row[0] for row in connection.execute(
            "SELECT table_name FROM information_schema.columns WHERE table_schema = %s "
            "AND column_name = 'owner_id' AND table_name LIKE 'knowledge_%%'", (schema,))}
        if discovered - {name for name, _ in OWNER_TABLES}:
            raise ValueError("实际知识 owner 表超出已审计清单，须先更新设计与取证范围")
        database_digest = sha256(json.dumps((database, schema, address, port),
                                            ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
        for index, (table, key) in enumerate(TABLES):
            present = connection.execute("SELECT to_regclass(%s)",
                                         (sql.Identifier(schema, table).as_string(connection),)).fetchone()[0] is not None
            digest, count = sha256(), 0
            if present:
                if table in {"knowledge_notes", "review_cards"}:
                    parameters = (principal.user_id,)
                elif table.startswith("personal_knowledge_lifecycle_"):
                    parameters = (principal.principal_id, principal.user_id)
                else:
                    parameters = (principal.principal_id,)
                with connection.cursor(name=f"knowledge_snapshot_{index}") as cursor:
                    cursor.execute(_query(table, key, schema), parameters)
                    while rows := cursor.fetchmany(1000):
                        for identity, body in rows:
                            for value in (identity, body):
                                encoded = value.encode("utf-8")
                                digest.update(len(encoded).to_bytes(8, "big"))
                                digest.update(encoded)
                            count += 1
            tables.append(KnowledgeTableSnapshot(table=table, present=present, row_count=count,
                                                 rows_sha256=digest.hexdigest()))
    return ScopedKnowledgeSnapshot(
        principal=principal, interaction_run_ref=prepared.world.initial.interaction_run_ref,
        preparation_sha256=sha256(prepared_bytes).hexdigest(), database_identity_sha256=database_digest,
        started_at=started, completed_at=datetime.now(UTC), isolation=isolation, read_only=True,
        owner_sources=sources, tables=tuple(tables))


def changed_knowledge_tables(before: ScopedKnowledgeSnapshot, after: ScopedKnowledgeSnapshot) -> tuple[str, ...]:
    """表是否存在单列保留；无业务行的建表不伪称知识内容发生变化。"""
    if (before.principal != after.principal or before.interaction_run_ref != after.interaction_run_ref
            or before.preparation_sha256 != after.preparation_sha256
            or before.database_identity_sha256 != after.database_identity_sha256
            or before.owner_sources != after.owner_sources or after.started_at < before.completed_at):
        raise ValueError("知识快照的主体、任务、准备、数据库、owner 契约或时间不一致")
    return tuple(first.table for first, second in zip(before.tables, after.tables, strict=True)
                 if (first.row_count, first.rows_sha256) != (second.row_count, second.rows_sha256))


def main() -> None:
    from .run_retrieval_acceptance import _database_url, _settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    snapshot = capture_snapshot(args.preparation.resolve(), _database_url(_settings()))
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(snapshot.model_dump_json(indent=2))
    print(json.dumps({"output": str(args.output), "tables": len(snapshot.tables),
                      "model_calls": 0, "business_writes": 0, "read_only": snapshot.read_only}))


if __name__ == "__main__":
    main()
