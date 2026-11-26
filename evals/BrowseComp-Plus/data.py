"""Pin official BrowseComp-Plus inputs and release references only for scoring."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from collections.abc import Iterator
from fnmatch import fnmatch
from pathlib import Path
from types import ModuleType
from typing import Literal, overload

import httpx
from huggingface_hub import HfApi, hf_hub_download, snapshot_download
from pydantic import BaseModel

from evals.run_deepseek_harness import sha256

UPSTREAM = "046949032b0328319cc9a02663a759ec601d9402"
QUESTIONS = "Tevatron/browsecomp-plus"
QUESTION_REV = "144cff8e35b5eaef7e526346aa60774a9deb941f"
QUESTION_ROWS_SHA256 = "2127874427cc899d25f5173ca3f6e33c9268aabaab024f34384484141673e833"
CORPUS = "Tevatron/browsecomp-plus-corpus"
CORPUS_REV = "b27b02bc3e45511b8b82a13e6f90ce761df726f6"
INDEXES = "Tevatron/browsecomp-plus-indexes"
INDEX_REV = "b3f37f70c33829eb09d04784a54277a31871fd63"
INDEX_DIR = "qwen3-embedding-8b"
TOKENIZER = "Qwen/Qwen3-0.6B"
TOKENIZER_REV = "c1899de289a04d12100db370d81485cdf75e47ca"
IDS = ("769", "770", "771", "772", "773")


class Question(BaseModel):
    query_id: str
    query: str


class Reference(Question):
    answer: str


class ViewerRow(BaseModel):
    row: Reference


@overload
def select(upstream: Path, *, include_answers: Literal[True]) -> Iterator[Reference]: ...


@overload
def select(upstream: Path, *, include_answers: Literal[False] = False) -> Iterator[Question]: ...


def select(upstream: Path, *, include_answers: bool = False) -> Iterator[Question]:
    revision = subprocess.check_output(
        ("git", "-C", str(upstream), "rev-parse", "HEAD"), text=True,
    ).strip()
    if revision != UPSTREAM:
        raise ValueError(f"Expected BrowseComp-Plus checkout {UPSTREAM}, found {revision}")
    decrypt = load_source(upstream / "scripts_build_index/decrypt_dataset.py", "browsecomp_decrypt")
    cache = upstream.parent / "encrypted-selected-rows.json"
    if cache.is_file():
        selected = [Reference.model_validate(row) for row in json.loads(cache.read_bytes())]
    else:
        if HfApi().dataset_info(QUESTIONS).sha != QUESTION_REV:
            raise ValueError("Hugging Face viewer is no longer on the pinned questions revision")
        response = httpx.get(
            "https://datasets-server.huggingface.co/rows",
            params={"dataset": QUESTIONS, "config": "default", "split": "test", "offset": 0, "length": len(IDS)},
            timeout=45,
        ).raise_for_status()
        selected = [ViewerRow.model_validate(row).row for row in response.json()["rows"]]
    encoded = json.dumps(
        [item.model_dump() for item in selected], sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")
    if hashlib.sha256(encoded).hexdigest() != QUESTION_ROWS_SHA256:
        raise ValueError("Selected rows differ from the pinned question release")
    if not cache.is_file():
        cache.write_bytes(encoded)
    if tuple(item.query_id for item in selected) != IDS:
        raise ValueError("Unexpected public dataset row order")
    for item in selected:
        query = decrypt.decrypt_string(item.query, decrypt.DEFAULT_CANARY)
        if include_answers:
            yield Reference(query_id=item.query_id, query=query,
                            answer=decrypt.decrypt_string(item.answer, decrypt.DEFAULT_CANARY))
        else:
            yield Question(query_id=item.query_id, query=query)


def load_source(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def artifacts(cache: Path, action: Literal["download", "verify"]) -> dict[str, str]:
    files = {}
    folder = cache / "indexes"
    pattern = f"{INDEX_DIR}/*.pkl"
    if action == "download":
        snapshot_download(INDEXES, repo_type="dataset", revision=INDEX_REV,
                          allow_patterns=pattern, local_dir=folder)
    metadata = HfApi().dataset_info(INDEXES, revision=INDEX_REV, files_metadata=True)
    candidates = [item for item in metadata.siblings if fnmatch(item.rfilename, pattern)]
    if len(candidates) != 4:
        raise ValueError("Expected four pinned BrowseComp-Plus 8B index shards")
    for item in candidates:
        path = folder / item.rfilename
        digest = sha256(path)
        if item.lfs is None or digest != item.lfs.sha256:
            raise ValueError(f"Unexpected SHA-256 for {path}")
        files[path.relative_to(cache).as_posix()] = digest
    tokenizer = Path(hf_hub_download(
        TOKENIZER, "tokenizer.json", revision=TOKENIZER_REV, local_dir=cache / "tokenizer",
    ))
    files[tokenizer.relative_to(cache).as_posix()] = sha256(tokenizer)
    return files
