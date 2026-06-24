from __future__ import annotations

import hashlib
import logging
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml

from personal_agent.kernel.config import Settings
from personal_agent.kernel.graph_results import GraphAskResult, GraphCaptureResult
from personal_agent.kernel.models import KnowledgeNote
from personal_agent.kernel.projections import GraphIngestDocument, graph_ingest_document_from_note

logger = logging.getLogger(__name__)


class MicrosoftGraphRagStore:
    """Adapter for the Microsoft GraphRAG CLI.

    Microsoft GraphRAG is project-directory based: documents are exported to an
    ``input`` folder, ``graphrag index`` builds parquet artifacts, and
    ``graphrag query`` generates answers over those artifacts. Unlike Graphiti,
    the CLI does not return episode UUIDs, so this adapter exposes GraphRAG's
    generated answer as provider-neutral graph facts.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = settings.ms_graphrag.root

    def configured(self) -> bool:
        if not self.settings.ms_graphrag.enabled:
            return False
        executable = _command_prefix(self.settings.ms_graphrag.executable)[0]
        return bool(shutil.which(executable) or Path(executable).exists())

    def status(self) -> dict[str, str | bool]:
        return {
            "configured": self.configured(),
            "root": str(self.root),
            "executable": self.settings.ms_graphrag.executable,
            "query_method": self.settings.ms_graphrag.query_method,
            "index_method": self.settings.ms_graphrag.index_method,
        }

    def ingest_note(
        self,
        note: KnowledgeNote,
        trace_id: str | None = None,  # noqa: ARG002
        attempt: int | None = None,  # noqa: ARG002
    ) -> GraphCaptureResult:
        if not self.configured():
            return GraphCaptureResult(enabled=False, error="Microsoft GraphRAG is not configured.")
        document = graph_ingest_document_from_note(note)
        path = self._write_input_document(document)
        if self.settings.ms_graphrag.auto_index:
            index_result = self.build_index()
            if not index_result.enabled:
                return index_result
        return GraphCaptureResult(
            enabled=True,
            episode_uuid=self._document_key(document),
            entity_names=[document.title] if document.title else [],
            relation_facts=[f"Microsoft GraphRAG input document exported: {path.name}"],
        )

    def ingest_notes(
        self,
        notes: list[KnowledgeNote],
        *,
        trace_id: str | None = None,
        max_workers: int | None = None,  # noqa: ARG002
    ) -> dict[str, GraphCaptureResult]:
        return {note.id: self.ingest_note(note, trace_id=trace_id) for note in notes}

    def build_index(self) -> GraphCaptureResult:
        if not self.configured():
            return GraphCaptureResult(enabled=False, error="Microsoft GraphRAG is not configured.")
        config_result = self._ensure_project_config()
        if config_result is not None:
            return config_result
        result = self._run([
            "index",
            "--root",
            str(self.root),
            "--method",
            self.settings.ms_graphrag.index_method,
        ])
        if result.returncode != 0:
            return GraphCaptureResult(enabled=False, error=_command_error(result))
        return GraphCaptureResult(enabled=True, relation_facts=["Microsoft GraphRAG index built."])

    def ask(self, question: str, user_id: str, trace_id: str | None = None) -> GraphAskResult:  # noqa: ARG002
        if not self.configured():
            return GraphAskResult(enabled=False, error="Microsoft GraphRAG is not configured.")
        command = [
            "query",
            "--root",
            str(self.root),
            "--method",
            self.settings.ms_graphrag.query_method,
        ]
        if self.settings.ms_graphrag.response_type:
            command.extend(["--response-type", self.settings.ms_graphrag.response_type])
        command.append(question)
        result = self._run(command)
        if result.returncode != 0:
            return GraphAskResult(enabled=False, error=_command_error(result))
        answer = _clean_query_output(result.stdout)
        facts = _answer_facts(answer)
        return GraphAskResult(
            enabled=True,
            answer=answer or None,
            relation_facts=facts,
            entity_names=[],
            related_episode_uuids=[],
        )

    def clear_user_group(self, user_id: str) -> int:  # noqa: ARG002
        input_dir = self.root / "input"
        count = 0
        if input_dir.exists():
            for path in input_dir.glob("*.txt"):
                path.unlink()
                count += 1
        return count

    def clear_all_data(self) -> int:
        if not self.root.exists():
            return 0
        count = sum(1 for path in self.root.rglob("*") if path.is_file())
        shutil.rmtree(self.root)
        return count

    def delete_episode(self, episode_uuid: str) -> bool:
        path = self.root / "input" / f"{episode_uuid}.txt"
        if not path.exists():
            return False
        path.unlink()
        return True

    def get_topology(self, user_id: str | None = None) -> dict:  # noqa: ARG002
        return {
            "nodes": [],
            "links": [],
            "provider": "ms_graphrag",
            "note": "Microsoft GraphRAG topology lives in parquet artifacts and is not exposed by this adapter yet.",
        }

    def _write_input_document(self, document: GraphIngestDocument) -> Path:
        input_dir = self.root / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        path = input_dir / f"{self._document_key(document)}.txt"
        path.write_text(_document_text(document), encoding="utf-8")
        return path

    def _ensure_project_config(self) -> GraphCaptureResult | None:
        settings_path = self.root / "settings.yaml"
        if not settings_path.exists():
            completion_model = _completion_model(self.settings)
            embedding_model = _embedding_model(self.settings)
            init = self._run([
                "init",
                "--root",
                str(self.root),
                "--model",
                completion_model,
                "--embedding",
                embedding_model,
            ])
            if init.returncode != 0:
                return GraphCaptureResult(enabled=False, error=_command_error(init))
        self._patch_project_settings(settings_path)
        return None

    def _patch_project_settings(self, settings_path: Path) -> None:
        raw = settings_path.read_text(encoding="utf-8")
        config = yaml.safe_load(raw) or {}

        completion_models = config.setdefault("completion_models", {})
        completion = completion_models.setdefault("default_completion_model", {})
        completion["model_provider"] = self.settings.ms_graphrag.completion_model_provider
        completion["model"] = _completion_model(self.settings)
        completion["api_key"] = _completion_api_key(self.settings)
        _set_optional(completion, "api_base", _completion_api_base(self.settings))

        embedding_models = config.setdefault("embedding_models", {})
        embedding = embedding_models.setdefault("default_embedding_model", {})
        embedding["model_provider"] = self.settings.ms_graphrag.embedding_model_provider
        embedding["model"] = _embedding_model(self.settings)
        embedding["api_key"] = _embedding_api_key(self.settings)
        _set_optional(embedding, "api_base", _embedding_api_base(self.settings))

        settings_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")

    def _document_key(self, document: GraphIngestDocument) -> str:
        digest = hashlib.sha1(document.id.encode("utf-8")).hexdigest()[:12]
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in document.id)
        return f"{safe_id[:80]}_{digest}"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        command = [*_command_prefix(self.settings.ms_graphrag.executable), *args]
        logger.info("Running Microsoft GraphRAG command: %s", " ".join(command[:4]))
        return subprocess.run(
            command,
            cwd=None,
            text=True,
            capture_output=True,
            timeout=self.settings.ms_graphrag.command_timeout_seconds,
            check=False,
        )


def _document_text(document: GraphIngestDocument) -> str:
    parts = [
        f"Title: {document.title}",
        f"Summary: {document.summary}",
        f"Source: {document.source_type} {document.source_ref}",
        "",
        document.content,
    ]
    return "\n".join(part for part in parts if part is not None).strip()


def _completion_model(settings: Settings) -> str:
    return settings.ms_graphrag.completion_model or settings.graphiti.llm_model or settings.openai.model


def _completion_api_key(settings: Settings) -> str | None:
    return settings.ms_graphrag.completion_api_key or settings.graphiti.llm_api_key or settings.openai.api_key


def _completion_api_base(settings: Settings) -> str | None:
    return settings.ms_graphrag.completion_api_base or settings.graphiti.llm_base_url or settings.openai.base_url


def _embedding_model(settings: Settings) -> str:
    return settings.ms_graphrag.embedding_model or settings.openai.embedding_model


def _embedding_api_key(settings: Settings) -> str | None:
    return settings.ms_graphrag.embedding_api_key or settings.openai.embedding_api_key or settings.openai.api_key


def _embedding_api_base(settings: Settings) -> str | None:
    return settings.ms_graphrag.embedding_api_base or settings.openai.embedding_base_url or settings.openai.base_url


def _set_optional(target: dict, key: str, value: str | None) -> None:
    if value:
        target[key] = value
    else:
        target.pop(key, None)


def _command_prefix(raw: str) -> list[str]:
    parts = shlex.split(raw, posix=False)
    return parts or ["graphrag"]


def _command_error(result: subprocess.CompletedProcess[str]) -> str:
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    return (stderr or stdout or f"graphrag exited with {result.returncode}")[:1000]


def _clean_query_output(stdout: str) -> str:
    lines = [line.rstrip() for line in stdout.splitlines()]
    cleaned = [
        line for line in lines
        if line.strip() and not line.lower().startswith(("info:", "success:", "creating"))
    ]
    return "\n".join(cleaned).strip()


def _answer_facts(answer: str) -> list[str]:
    lines = [line.strip(" -*\t") for line in answer.splitlines() if line.strip()]
    if not lines and answer.strip():
        lines = [answer.strip()]
    return lines[:8]
