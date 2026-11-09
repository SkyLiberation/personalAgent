"""观察独立研究 Web 进程的真实同步 SQL；不替换生产执行或返回值。"""
from __future__ import annotations

import argparse
from collections.abc import Callable
import contextlib
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
import inspect
import os
from pathlib import Path
import re
from threading import Lock
import threading
from typing import Annotated, Literal

import psycopg
import psycopg_pool
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

from .retrieval_knowledge_snapshot import TABLES
from .retrieval_qualification_review import Digest

ROOT = Path(__file__).resolve().parents[2]
TABLE_NAMES = frozenset(name for name, _ in TABLES)
OWNER_SOURCES = (
    "src/personal_agent/infra/storage/postgres_common.py",
    "src/personal_agent/infra/storage/postgres_knowledge_store.py",
    "src/personal_agent/infra/storage/postgres_knowledge_lifecycle_store.py",
    "src/personal_agent/infra/storage/postgres_memory_store.py",
    "src/personal_agent/infra/storage/postgres_memory_schema.py",
    "src/personal_agent/infra/storage/postgres_debug_reset_store.py",
    "evals/product_baselines/retrieval_knowledge_write_audit.py",
)
_DML = re.compile(r"\b(?:INSERT|UPDATE|DELETE|TRUNCATE|MERGE|COPY)\b", re.I)
_OPAQUE = re.compile(r"\b(?:CALL|EXECUTE)\b", re.I)
_DDL = re.compile(r"\b(?:CREATE|ALTER|DROP)\b", re.I)
_NESTED_WRITES = re.compile(r"\bWITH\b|\bDO\s+\$[a-zA-Z_0-9]*\$", re.I)
_WORDS = re.compile(r"[a-zA-Z_][a-zA-Z_0-9]*")
_SQL_NONCODE = re.compile(r"'(?:''|[^'])*'|--[^\n]*(?:\n|$)|/\*.*?\*/", re.S)


def _sql_code(text: str) -> tuple[str, bool]:
    """只屏蔽当前 SQL 的普通字面量/注释；复杂语法保持未知。"""
    certain = True

    def remove(match: re.Match[str]) -> str:
        nonlocal certain
        value = match.group()
        if value.startswith("'") and "\\" in value or value.startswith("/*") and "/*" in value[2:]:
            certain = False
        return " "

    code = _SQL_NONCODE.sub(remove, text)
    return code, certain and "'" not in code and "/*" not in code


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WriteAuditConfiguration(_Strict):
    principal: AuthenticatedPrincipal
    interaction_run_ref: str = Field(min_length=1)
    preparation_sha256: Digest
    directory: Path


class SqlStarted(_Strict):
    kind: Literal["sql_started"] = "sql_started"
    sequence: int = Field(ge=1)
    thread_id: int
    at: AwareDatetime
    operation: Literal["execute", "executemany"]
    sql_template_sha256: Digest
    mentioned_knowledge_tables: tuple[str, ...]
    possible_row_write: bool
    schema_statement: bool
    opaque_execution: bool
    unclassified_syntax: bool


class SqlFinished(_Strict):
    kind: Literal["sql_finished"] = "sql_finished"
    sequence: int = Field(ge=1)
    at: AwareDatetime
    command_statuses: tuple[str, ...]
    affected_rows: int | None = Field(default=None, ge=0)
    response_complete: bool


class CoverageIssue(_Strict):
    kind: Literal["coverage_issue"] = "coverage_issue"
    at: AwareDatetime
    reason: str


AuditEntry = Annotated[SqlStarted | SqlFinished | CoverageIssue, Field(discriminator="kind")]


class WriteAuditInstallation(_Strict):
    configuration: WriteAuditConfiguration
    pid: int = Field(gt=0)
    installed_at: AwareDatetime
    psycopg_version: str
    psycopg_pool_version: str
    owner_sources: dict[str, Digest]
    driver_sources: dict[str, Digest]
    coverage: Literal["synchronous_psycopg_cursor_method_observation_v2"]


class WriteAuditClosure(_Strict):
    installation_sha256: Digest
    entries_sha256: Digest
    closed_at: AwareDatetime
    active_sql_calls: int = Field(ge=0)
    observed_sql_calls: int = Field(ge=0)
    observer_healthy: bool
    sources_unchanged: bool


def _write(path: Path, model: BaseModel) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(model.model_dump_json(indent=2))


def _sources() -> dict[str, Digest]:
    return {name: sha256((ROOT / name).read_bytes()).hexdigest() for name in OWNER_SOURCES}


class KnowledgeWriteObserver:
    """只在单个专用子进程内安装；关闭封存后仍继续观察。"""

    def __init__(self, configuration: WriteAuditConfiguration) -> None:
        if threading.active_count() != 1:
            raise RuntimeError("SQL 观察必须在工作线程及正式 app 之前安装")
        self.configuration = configuration
        self.directory = configuration.directory.resolve()
        self.directory.mkdir(exist_ok=False)
        self.entries = self.directory / "entries.jsonl"
        self.entries.touch(exist_ok=False)
        self.lock = Lock()
        self.active: dict[int, tuple[SqlStarted, int]] = {}
        self.sequence = 0
        self.healthy = True
        self.methods: dict[tuple[type, str], tuple[Callable, Callable]] = {}
        entries = ((psycopg.Cursor, "execute"), (psycopg.Cursor, "executemany"),
                   (psycopg.Connection, "cursor"), (psycopg.Cursor, "copy"), (psycopg.Cursor, "stream"))
        originals = {(owner, name): getattr(owner, name) for owner, name in entries}
        driver_directory = Path(psycopg.__file__).resolve().parent
        contextmanager_source = Path(contextlib.contextmanager.__code__.co_filename).resolve()
        for (_, name), method in originals.items():
            body = inspect.unwrap(method)
            actual_source = Path(method.__code__.co_filename).resolve()
            body_source = Path(body.__code__.co_filename).resolve()
            standard_copy_wrapper = (name == "copy" and actual_source == contextmanager_source
                                     and getattr(method, "__wrapped__", None) is body)
            if (not body_source.is_relative_to(driver_directory)
                    or actual_source != body_source and not standard_copy_wrapper):
                raise RuntimeError("SQL 观察不接纳已有的未知驱动包装")
        driver_files = {
            psycopg.Cursor.execute.__code__.co_filename,
            psycopg.Connection.execute.__code__.co_filename,
            psycopg.Cursor._select_current_result.__code__.co_filename,
            inspect.unwrap(psycopg_pool.ConnectionPool.connection).__code__.co_filename,
            psycopg_pool.ConnectionPool._connect.__code__.co_filename,
        }
        driver_files.update(inspect.unwrap(method).__code__.co_filename for method in originals.values())
        driver_files.update(method.__code__.co_filename for method in originals.values())
        self.installation = WriteAuditInstallation(
            configuration=configuration, pid=os.getpid(), installed_at=datetime.now(UTC),
            psycopg_version=psycopg.__version__, psycopg_pool_version=psycopg_pool.__version__, owner_sources=_sources(),
            driver_sources={str(Path(name).resolve()): sha256(Path(name).read_bytes()).hexdigest()
                            for name in sorted(driver_files) if name},
            coverage="synchronous_psycopg_cursor_method_observation_v2")
        _write(self.directory / "installation.json", self.installation)
        for (owner, name), original in originals.items():
            wrapped = self._wrap(original, name)
            self.methods[owner, name] = original, wrapped
            setattr(owner, name, wrapped)

    def _append(self, entry: AuditEntry) -> None:
        with self.entries.open("a", encoding="utf-8") as stream:
            stream.write(entry.model_dump_json() + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _issue(self, reason: str) -> None:
        self.healthy = False
        try:
            with self.lock:
                self._append(CoverageIssue(at=datetime.now(UTC), reason=reason))
        except Exception:
            pass

    def _wrap(self, original: Callable, name: str) -> Callable:
        @wraps(original)
        def observed(instance, *args, **kwargs):
            if name in ("execute", "executemany"):
                return self._invoke(original, instance, name, args, kwargs)
            if name != "cursor":
                self._issue("unsupported_driver_entry:" + name)
            result = original(instance, *args, **kwargs)
            if name == "cursor" and type(result) is not psycopg.Cursor:
                self._issue("unsupported_cursor_type")
            return result

        return observed

    def _begin(self, cursor, operation: Literal["execute", "executemany"], query) -> int:
        if type(cursor) is not psycopg.Cursor:
            self._issue("unsupported_cursor_type")
        if isinstance(query, bytes):
            text = query.decode("utf-8")
        elif isinstance(query, str):
            text = query
        elif isinstance(query, psycopg.sql.Composable):
            text = query.as_string(cursor.connection)
        else:
            raise TypeError("unsupported_query_type")
        code_text, certain = _sql_code(text)
        tables = tuple(sorted(TABLE_NAMES.intersection(word.lower() for word in _WORDS.findall(code_text))))
        with self.lock:
            if any(identity == id(cursor) for _, identity in self.active.values()):
                self.healthy = False
                self._append(CoverageIssue(at=datetime.now(UTC), reason="overlapping_cursor_calls"))
            self.sequence += 1
            started = SqlStarted(
                sequence=self.sequence, thread_id=threading.get_ident(), at=datetime.now(UTC),
                operation=operation, sql_template_sha256=sha256(text.encode("utf-8")).hexdigest(),
                mentioned_knowledge_tables=tables, possible_row_write=bool(_DML.search(code_text)),
                schema_statement=bool(_DDL.search(code_text)), opaque_execution=bool(_OPAQUE.search(code_text)),
                unclassified_syntax=not certain or bool(
                    tables and _DML.search(code_text) and _NESTED_WRITES.search(code_text)))
            self.active[started.sequence] = started, id(cursor)
            self._append(started)
            return started.sequence

    def _finish(self, sequence: int, cursor, succeeded: bool, returned: object) -> None:
        with self.lock:
            started, _ = self.active.pop(sequence)
            results = tuple(cursor._results)
            statuses = tuple(result.command_status.decode("ascii") for result in results)
            # executemany can retain only a subset of PGresults; keep it unknown.
            complete = started.operation == "execute" and succeeded and returned is cursor and bool(results)
            rows = None
            if complete:
                mutations = [result.command_tuples for result in results
                             if re.match(rb"^(?:INSERT|UPDATE|DELETE|MERGE)\b", result.command_status)]
                if mutations and all(count is not None for count in mutations) and not any(
                        status.startswith(("TRUNCATE", "COPY")) for status in statuses):
                    rows = sum(mutations)
            self._append(SqlFinished(sequence=sequence, at=datetime.now(UTC),
                command_statuses=statuses, affected_rows=rows, response_complete=complete))

    def _invoke(self, original: Callable, cursor, operation: Literal["execute", "executemany"],
                args: tuple, kwargs: dict):
        sequence = None
        try:
            sequence = self._begin(cursor, operation, args[0] if args else kwargs.get("query"))
        except Exception as error:
            self._issue("observation_error:" + type(error).__name__)
        succeeded, result = False, None
        try:
            # No observer lock here; params/iterators and the result are untouched.
            result = original(cursor, *args, **kwargs)
            succeeded = True
            return result
        finally:
            if sequence is not None:
                try:
                    self._finish(sequence, cursor, succeeded, result)
                except Exception as error:
                    self._issue("observation_error:" + type(error).__name__)

    def close(self) -> WriteAuditClosure:
        with self.lock:
            installation_path = self.directory / "installation.json"
            report = WriteAuditClosure(
                installation_sha256=sha256(installation_path.read_bytes()).hexdigest(),
                entries_sha256=sha256(self.entries.read_bytes()).hexdigest(), closed_at=datetime.now(UTC),
                active_sql_calls=len(self.active), observed_sql_calls=self.sequence,
                observer_healthy=self.healthy and all(
                    getattr(owner, name) is wrapped for (owner, name), (_, wrapped) in self.methods.items()),
                sources_unchanged=_sources() == self.installation.owner_sources and all(
                    sha256(Path(name).read_bytes()).hexdigest() == digest
                    for name, digest in self.installation.driver_sources.items()))
            _write(self.directory / "closure.json", report)
            return report


class KnowledgeWriteAudit(_Strict):
    evidence_class: Literal["database_sql_observation_audit"] = "database_sql_observation_audit"
    auditor_source_sha256: Digest
    configuration: WriteAuditConfiguration
    installation_sha256: Digest
    entries_sha256: Digest
    closure_sha256: Digest
    coverage_complete: bool
    sql_calls: int = Field(ge=0)
    knowledge_schema_calls: int = Field(ge=0)
    possible_knowledge_row_write_calls: int = Field(ge=0)
    known_affected_rows: int = Field(ge=0)
    unknown_write_calls: int = Field(ge=0)
    coverage_issues: int = Field(ge=0)
    observed_zero_row_writes: bool
    model_calls_by_this_audit: Literal[0] = 0
    limitation: str


def audit_write_observations(directory: Path) -> KnowledgeWriteAudit:
    """关闭后日志再变化、缺响应或覆盖受损都不能给零写入结论。"""
    installation_bytes = (directory / "installation.json").read_bytes()
    installation = WriteAuditInstallation.model_validate_json(installation_bytes)
    closure_bytes = (directory / "closure.json").read_bytes()
    closure = WriteAuditClosure.model_validate_json(closure_bytes)
    entries_bytes = (directory / "entries.jsonl").read_bytes()
    entries = tuple(TypeAdapter(AuditEntry).validate_json(line) for line in entries_bytes.splitlines())
    starts = {entry.sequence: entry for entry in entries if isinstance(entry, SqlStarted)}
    finishes = {entry.sequence: entry for entry in entries if isinstance(entry, SqlFinished)}
    issues = sum(isinstance(entry, CoverageIssue) for entry in entries)
    if (len(starts) != sum(isinstance(entry, SqlStarted) for entry in entries)
            or len(finishes) != sum(isinstance(entry, SqlFinished) for entry in entries)
            or not set(finishes).issubset(starts)):
        raise ValueError("SQL 观察重复身份或响应无原请求")
    complete = (closure.installation_sha256 == sha256(installation_bytes).hexdigest()
                and closure.entries_sha256 == sha256(entries_bytes).hexdigest()
                and closure.observed_sql_calls == len(starts) and not closure.active_sql_calls
                and closure.observer_healthy and closure.sources_unchanged and not issues
                and set(starts) == set(finishes))
    writes = rows = unknown = schemas = 0
    for sequence, entry in starts.items():
        schemas += bool(entry.mentioned_knowledge_tables and entry.schema_statement)
        relevant = (bool(entry.mentioned_knowledge_tables and entry.possible_row_write)
                    or entry.opaque_execution or entry.unclassified_syntax)
        if not relevant:
            continue
        writes += 1
        finish = finishes.get(sequence)
        if (entry.opaque_execution or entry.unclassified_syntax or finish is None or not finish.response_complete
                or finish.affected_rows is None):
            unknown += 1
        else:
            rows += finish.affected_rows
    return KnowledgeWriteAudit(
        auditor_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        configuration=installation.configuration, installation_sha256=sha256(installation_bytes).hexdigest(),
        entries_sha256=sha256(entries_bytes).hexdigest(), closure_sha256=sha256(closure_bytes).hexdigest(),
        coverage_complete=complete, sql_calls=len(starts), knowledge_schema_calls=schemas,
        possible_knowledge_row_write_calls=writes, known_affected_rows=rows,
        unknown_write_calls=unknown, coverage_issues=issues,
        observed_zero_row_writes=complete and rows == 0 and unknown == 0,
        limitation="进程内同步 SQL 模板及命令事实；可能写涉及全进程表引用，不据此断言主体已写。零写入仍须同主体全量 before/after、冻结源码覆盖审读及实际进程终态。")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_write_observations(args.directory.resolve())
    _write(args.output, report)
    print(report.model_dump_json())


if __name__ == "__main__":
    main()
