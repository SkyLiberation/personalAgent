"""Serve the official 8B document vectors and fixed corpus to both solvers."""

from __future__ import annotations

import json
import pickle
import socket
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from threading import Thread
from time import monotonic, sleep

import faiss
import httpx
import numpy as np
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel
from tokenizers import Tokenizer

from .data import CORPUS, CORPUS_REV, INDEX_DIR

MODEL = "Qwen/Qwen3-Embedding-8B"
DIMENSION = 4096
CORPUS_SIZE = 100_195
TOP_K = 5
SNIPPET_TOKENS = 512
QUERY_PREFIX = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:"
SEARCH_DESCRIPTION = "Search the fixed corpus. Returns the top 5 hits with document IDs, scores and snippets."
DOCUMENT_DESCRIPTION = "Retrieve the full text of a corpus document by its document ID."


class Document(BaseModel):
    docid: str
    text: str


class CorpusRow(BaseModel):
    row: Document
    truncated_cells: list[str]


class CorpusResponse(BaseModel):
    rows: list[CorpusRow]


class Hit(BaseModel):
    docid: str
    score: float
    snippet: str


class Embedding(BaseModel):
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    data: list[Embedding]


def siliconflow(values: Mapping[str, str | None]) -> tuple[str, dict[str, str]]:
    endpoint = (values.get("EMBEDDING_BASE_URL") or "").rstrip("/")
    key = values.get("EMBEDDING_API_KEY")
    if not endpoint or not key:
        raise ValueError("Expected EMBEDDING_BASE_URL and EMBEDDING_API_KEY")
    if not endpoint.endswith("/v1"):
        endpoint += "/v1"
    return endpoint, {"Authorization": f"Bearer {key}"}


class Retriever:
    def __init__(self, cache: Path, encoder: httpx.Client, corpus: httpx.Client, log: Path) -> None:
        self.encoder = encoder
        self.corpus = corpus
        self.log = log
        self.tokenizer = Tokenizer.from_file(str(cache / "tokenizer/tokenizer.json"))
        self.index = faiss.IndexFlatIP(DIMENSION)
        self.ids: list[str] = []
        faiss.omp_set_num_threads(2)
        for path in sorted((cache / "indexes" / INDEX_DIR).glob("*.pkl")):
            with path.open("rb") as source:
                vectors, ids = pickle.load(source)  # SHA-256 checked against the pinned official release.
            vectors = np.asarray(vectors, dtype=np.float32, order="C")
            if vectors.shape != (len(ids), DIMENSION):
                raise ValueError(f"Invalid encoder dimensions in {path}")
            self.index.add(vectors)
            self.ids.extend(map(str, ids))
        self.indexed_ids = frozenset(self.ids)
        if len(self.ids) != CORPUS_SIZE or len(self.indexed_ids) != CORPUS_SIZE:
            raise ValueError("Official 8B shards must cover all 100,195 unique documents")

    def documents(self, ids: list[str]) -> dict[str, Document]:
        # Only identifiers from the official index can reach this fixed corpus endpoint.
        where = " OR ".join("\"docid\"='" + docid.replace("'", "''") + "'" for docid in ids)
        response = self.corpus.get("/filter", params={
            "dataset": CORPUS, "config": "default", "split": "train", "where": where, "length": len(ids),
        }).raise_for_status()
        if response.headers.get("x-revision") != CORPUS_REV:
            raise ValueError("Document response does not match the pinned corpus revision")
        rows = CorpusResponse.model_validate_json(response.content).rows
        documents = {item.row.docid: item.row for item in rows}
        if documents.keys() != set(ids) or any("text" in item.truncated_cells for item in rows):
            raise ValueError("The fixed corpus response has missing or truncated documents")
        return documents

    def document(self, docid: str) -> Document | None:
        found = docid in self.indexed_ids
        document = self.documents([docid])[docid] if found else None
        self.record("get_document", docid=docid, found=found)
        return document

    def search(self, query: str) -> list[Hit]:
        response = self.encoder.post(
            "/v1/embeddings",
            json={"model": MODEL, "input": [QUERY_PREFIX + query], "encoding_format": "float"},
        ).raise_for_status()
        embedding = EmbeddingResponse.model_validate_json(response.content).data
        vector = np.array([item.embedding for item in embedding], dtype=np.float32)
        if vector.shape != (1, DIMENSION) or not np.isfinite(vector).all() or not np.any(vector):
            raise ValueError("Query encoder returned an invalid 4096-dimensional embedding")
        faiss.normalize_L2(vector)
        scores, indexes = self.index.search(vector, TOP_K)
        ids = [self.ids[index] for index in indexes[0]]
        documents = self.documents(ids)
        hits = []
        for score, docid in zip(scores[0], ids, strict=True):
            text = documents[docid].text
            tokens = self.tokenizer.encode(text, add_special_tokens=False)
            snippet = self.tokenizer.decode(tokens.ids[:SNIPPET_TOKENS]) if len(tokens.ids) > SNIPPET_TOKENS else text
            hits.append(Hit(docid=docid, score=float(score), snippet=snippet))
        self.record("search", query=query, docids=[hit.docid for hit in hits])
        return hits

    def record(self, tool: str, **fields: object) -> None:
        with self.log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"tool": tool, **fields}, ensure_ascii=False) + "\n")


@contextmanager
def serve(cache: Path, values: Mapping[str, str | None], log: Path) -> Iterator[int]:
    endpoint, headers = siliconflow(values)
    with (
        httpx.Client(base_url=endpoint.removesuffix("/v1"), headers=headers, timeout=30) as encoder,
        httpx.Client(base_url="https://datasets-server.huggingface.co", timeout=45) as corpus,
    ):
        retriever = Retriever(cache, encoder, corpus, log)
        security = TransportSecuritySettings(
            allowed_hosts=["127.0.0.1:*", "host.docker.internal:*"],
            enable_dns_rebinding_protection=True,
        )
        mcp = FastMCP("browsecomp", stateless_http=True, json_response=True, transport_security=security)
        hints = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
        mcp.add_tool(retriever.search, name="search", description=SEARCH_DESCRIPTION, annotations=hints)
        mcp.add_tool(retriever.document, name="get_document", description=DOCUMENT_DESCRIPTION, annotations=hints)
        app = mcp.streamable_http_app()
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
            worker = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            worker.start()
            try:
                deadline = monotonic() + 10
                while not server.started and worker.is_alive() and monotonic() < deadline:
                    sleep(0.05)
                if not server.started:
                    raise RuntimeError("Shared BrowseComp-Plus MCP did not start")
                yield port
            finally:
                server.should_exit = True
                worker.join(15)
