"""Persist ordered conversation turns and their committed revisions in SQLite."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from personal_agent.application.conversation.errors import ConversationOperationConflict
from personal_agent.application.conversation.journal import InMemoryInteractionJournal, session_lock_key
from personal_agent.application.conversation.journal_lock import exclusive_run_lock
from personal_agent.application.conversation.models import ConversationMessage, InteractionTrace, SessionId
from personal_agent.capabilities.contracts.model import ModelResponseRecord
from personal_agent.kernel.contracts.scope import AuthenticatedPrincipal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS turn (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    user_text TEXT NOT NULL,
    predecessor_id TEXT,
    predecessor_revision INTEGER,
    predecessor_reply TEXT,
    UNIQUE (tenant_id, user_id, session_id, number),
    FOREIGN KEY (predecessor_id, predecessor_revision) REFERENCES revision(turn_id, number)
);
CREATE TABLE IF NOT EXISTS revision (
    turn_id TEXT NOT NULL REFERENCES turn(id),
    number INTEGER NOT NULL,
    facts TEXT NOT NULL,
    PRIMARY KEY (turn_id, number)
);
"""

_TIMELINE = """
WITH RECURSIVE lineage(id, revision) AS (
    SELECT ?, COALESCE(?, (SELECT MAX(number) FROM revision WHERE turn_id = ?))
    UNION ALL
    SELECT turn.predecessor_id, turn.predecessor_revision
    FROM lineage JOIN turn ON turn.id = lineage.id
    WHERE turn.predecessor_id IS NOT NULL
)
SELECT turn.id, revision.number, turn.user_text, turn.predecessor_reply, revision.facts
FROM lineage
JOIN turn ON turn.id = lineage.id
LEFT JOIN revision ON revision.turn_id = lineage.id AND revision.number = lineage.revision
AND (? OR lineage.id = ?)
ORDER BY turn.number
"""

_TAIL = """SELECT id, number FROM turn WHERE tenant_id=? AND user_id=? AND session_id=?
ORDER BY number DESC LIMIT 1"""


@dataclass(slots=True)
class _DecodedSessionHistory:
    principal: AuthenticatedPrincipal
    session_id: SessionId
    predecessors: dict[str, InteractionTrace] = field(default_factory=dict)


class SqliteInteractionJournal(InMemoryInteractionJournal):
    """One authoritative journal. Model wire originals retain their existing file format."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._database = self._root / "sessions.sqlite3"
        self._decoded_history: ContextVar[_DecodedSessionHistory | None] = ContextVar(
            "decoded_session_history", default=None,
        )
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_SCHEMA)

    def _original_directory(self, run_ref: str, invocation_id: str) -> Path:
        self._validate_run_ref(run_ref)
        if not re.fullmatch(r"[0-9a-f]{32}", invocation_id):
            raise ConversationOperationConflict("模型调用原件身份不合法")
        return self._root / run_ref / invocation_id

    @staticmethod
    def _write_immutable_original(target, text):
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        if target.exists():
            if target.read_bytes() != raw:
                raise ConversationOperationConflict("模型原件已存在且内容冲突")
            return
        temporary = target.parent / f".{uuid4().hex[:12]}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

    def _write_request_original(self, run_ref, invocation_id, text):
        self._write_immutable_original(self._original_directory(run_ref, invocation_id) / "request.json", text)

    def _read_request_original(self, run_ref, invocation_id):
        return (self._original_directory(run_ref, invocation_id) / "request.json").read_text(encoding="utf-8")

    def _write_response_original(self, run_ref: str, invocation_id: str, sequence: int, text: str) -> None:
        directory = self._original_directory(run_ref, invocation_id)
        self._write_immutable_original(directory / f"{sequence}.json", text)

    def _response_originals(self, run_ref: str, invocation_id: str) -> tuple[ModelResponseRecord, ...]:
        directory = self._original_directory(run_ref, invocation_id)
        response_names = {path.name for path in directory.glob("*.json")} - {"request.json"}
        result = []
        attempts = set()
        for sequence in range(len(response_names)):
            name = f"{sequence}.json"
            if name not in response_names:
                raise ConversationOperationConflict("模型响应原件序号不连续")
            record = ModelResponseRecord.model_validate_json((directory / name).read_bytes())
            if record.invocation_id != invocation_id or record.attempt_id in attempts:
                raise ConversationOperationConflict("模型响应原件调用身份不匹配或尝试身份重复")
            attempts.add(record.attempt_id)
            result.append(record)
        return tuple(result)

    @contextmanager
    def exclusive_session(self, *, principal: AuthenticatedPrincipal, session_id: SessionId) -> Iterator[None]:
        key = session_lock_key(principal, session_id)
        root = self._root.resolve()
        with exclusive_run_lock(f"file:{os.path.normcase(str(root))}:conversation:{key}",
                                root.parent / "conversation_locks" / f"{key}.lock"):
            token = self._decoded_history.set(_DecodedSessionHistory(principal, session_id))
            try:
                yield
            finally:
                self._decoded_history.reset(token)

    def exclusive_run(self, run_ref: str):
        self._validate_run_ref(run_ref)
        root = self._root.resolve()
        return exclusive_run_lock(
            f"file:{os.path.normcase(str(root))}:{run_ref}",
            root / run_ref / ".writer.lock",
        )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self._database)
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @staticmethod
    def _append_message_pair(
        messages: list[ConversationMessage], user_text: str, predecessor_reply: str | None,
    ) -> None:
        if predecessor_reply is not None:
            messages.append(ConversationMessage(role="assistant", content=predecessor_reply))
        messages.append(ConversationMessage(role="user", content=user_text))

    @staticmethod
    def _trace(facts: str, messages: list[ConversationMessage]) -> InteractionTrace:
        return InteractionTrace.model_validate({**json.loads(facts), "messages": tuple(messages)})

    def _decode_timeline(
        self, rows: list[tuple[str, int | None, str, str | None, str | None]], *, all_turns: bool,
    ) -> tuple[InteractionTrace, ...]:
        messages: list[ConversationMessage] = []
        traces: list[InteractionTrace] = []
        history = self._decoded_history.get() if all_turns else None
        tail = len(rows) - 1
        for index, (run_ref, revision, user_text, previous_reply, facts) in enumerate(rows):
            self._append_message_pair(messages, user_text, previous_reply)
            if not all_turns and index != tail:
                continue
            if facts is None:
                raise ConversationOperationConflict("会话前驱修订未提交")
            # The database selects the revision on every read. Reuse only an already
            # decoded predecessor of the locked session with the same input lineage.
            if history is not None and index < tail:
                cached = history.predecessors.get(run_ref)
                if cached is not None and cached.revision == revision and cached.messages == tuple(messages):
                    traces.append(cached)
                    continue
            trace = self._trace(facts, messages)
            if (history is not None and index < tail and trace.principal == history.principal
                    and trace.conversation_id == history.session_id):
                history.predecessors[run_ref] = trace
            traces.append(trace)
        return tuple(traces)

    def _latest(self, db: sqlite3.Connection, run_ref: str) -> InteractionTrace | None:
        rows = db.execute(_TIMELINE, (run_ref, None, run_ref, False, run_ref)).fetchall()
        return self._decode_timeline(rows, all_turns=False)[0] if rows else None

    def get(self, interaction_run_ref: str) -> InteractionTrace | None:
        self._validate_run_ref(interaction_run_ref)
        with closing(self._connect()) as db:
            return self._latest(db, interaction_run_ref)

    def put(self, trace: InteractionTrace, *, expected_revision: int | None = None) -> None:
        with self.exclusive_run(trace.interaction_run_ref), closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = self._latest(db, trace.interaction_run_ref)
            self._check_revision(trace, previous, expected_revision)
            if previous == trace:
                return
            if previous is None:
                self._insert_turn(db, trace)
            db.execute("INSERT INTO revision VALUES (?, ?, ?)", (
                trace.interaction_run_ref, trace.revision, trace.model_dump_json(exclude={"messages"}),
            ))

    def _insert_turn(self, db: sqlite3.Connection, trace: InteractionTrace) -> None:
        scope = (trace.principal.tenant_id, trace.principal.user_id, trace.conversation_id)
        tail = db.execute(_TAIL, scope).fetchone()
        if not trace.messages or trace.messages[-1].role != "user":
            raise ConversationOperationConflict("轮次缺少本次用户输入")
        predecessor = self._latest(db, tail[0]) if tail is not None else None
        if predecessor is None:
            if len(trace.messages) != 1:
                raise ConversationOperationConflict("新会话只能提交本次用户输入")
            number, parent_id, parent_revision, parent_reply = 1, None, None, None
        else:
            if (len(trace.messages) != len(predecessor.messages) + 2
                    or trace.messages[-2].role != "assistant"
                    or trace.messages[:-2] != predecessor.messages):
                raise ConversationOperationConflict("已提交的会话前驱变化，请重新提交")
            number = tail[1] + 1
            parent_id, parent_revision = predecessor.interaction_run_ref, predecessor.revision
            parent_reply = trace.messages[-2].content
        db.execute("INSERT INTO turn VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
            trace.interaction_run_ref, *scope, number, trace.messages[-1].content,
            parent_id, parent_revision, parent_reply,
        ))

    def session_runs(self, *, principal: AuthenticatedPrincipal, session_id: SessionId) -> tuple[InteractionTrace, ...]:
        with closing(self._connect()) as db:
            rows = db.execute(
                """SELECT turn.id, revision.number, turn.user_text, turn.predecessor_reply, revision.facts
                FROM turn JOIN revision ON revision.turn_id = turn.id
                AND revision.number = (SELECT MAX(r.number) FROM revision r WHERE r.turn_id = turn.id)
                WHERE turn.tenant_id=? AND turn.user_id=? AND turn.session_id=? ORDER BY turn.number""",
                (principal.tenant_id, principal.user_id, session_id),
            ).fetchall()
        return self._decode_timeline(rows, all_turns=True)

    def last_turn(self, *, principal: AuthenticatedPrincipal, session_id: SessionId) -> InteractionTrace | None:
        with closing(self._connect()) as db:
            tail = db.execute(_TAIL, (principal.tenant_id, principal.user_id, session_id)).fetchone()
            return self._latest(db, tail[0]) if tail is not None else None

    def _history_candidates(self, trace: InteractionTrace) -> tuple[InteractionTrace, ...]:
        with closing(self._connect()) as db:
            run_ref = trace.interaction_run_ref
            rows = db.execute(_TIMELINE, (run_ref, trace.revision, run_ref, True, run_ref)).fetchall()
        return self._decode_timeline(rows, all_turns=True)
