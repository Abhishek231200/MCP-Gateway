"""MCP Knowledge Base service — semantic RAG pipeline.

  POST /query           — full RAG: retrieve relevant chunks + generate answer via Claude
  POST /search          — semantic similarity search (retrieval only, no generation)
  POST /documents       — add and index a document
  GET  /documents       — paginated list
  DELETE /documents/{id} — remove a document
  GET  /health
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import anthropic
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

app = FastAPI(title="MCP Knowledge Base", version="2.0.0")

# ── Embedding model ───────────────────────────────────────────────────────────
# all-MiniLM-L6-v2: 384-dim, 22 MB, fast CPU inference, good semantic quality
_embedder = SentenceTransformer("all-MiniLM-L6-v2")

# ── In-memory store ───────────────────────────────────────────────────────────
_docs: dict[str, dict[str, Any]] = {}
_embeddings: np.ndarray | None = None  # shape (n_docs, 384)
_ordered_ids: list[str] = []


def _rebuild_index() -> None:
    global _embeddings, _ordered_ids
    if not _docs:
        _embeddings = None
        _ordered_ids = []
        return
    _ordered_ids = list(_docs.keys())
    texts = [_docs[i]["content"] for i in _ordered_ids]
    _embeddings = _embedder.encode(texts, convert_to_numpy=True)


def _cosine_scores(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """query_vec: (d,)  matrix: (n, d)  →  scores: (n,)"""
    q = query_vec / (np.linalg.norm(query_vec) + 1e-10)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True) + 1e-10
    return (matrix / norms) @ q


def _semantic_search(query: str, top_k: int, min_score: float) -> list[dict[str, Any]]:
    if not _docs or _embeddings is None:
        return []
    query_vec = _embedder.encode(query, convert_to_numpy=True)
    scores = _cosine_scores(query_vec, _embeddings)
    top_n = min(top_k, len(_ordered_ids))
    top_indices = np.argsort(scores)[::-1][:top_n]
    results = []
    for idx in top_indices:
        score = float(scores[idx])
        if score < min_score:
            continue
        doc_id = _ordered_ids[int(idx)]
        doc = _docs[doc_id]
        results.append({
            "id": doc_id,
            "content": doc["content"],
            "title": doc.get("title"),
            "metadata": doc.get("metadata", {}),
            "score": round(score, 4),
        })
    return results


# ── Pydantic models ───────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.0


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    min_score: float = 0.1
    model: str = "claude-haiku-4-5-20251001"


class AddDocumentRequest(BaseModel):
    content: str
    title: str | None = None
    metadata: dict[str, Any] | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "healthy", "documents": len(_docs)}


@app.post("/search")
def search(req: SearchRequest) -> list[dict[str, Any]]:
    """Semantic retrieval only — no generation."""
    return _semantic_search(req.query, req.top_k, req.min_score)


@app.post("/query")
def query(req: QueryRequest) -> dict[str, Any]:
    """Full RAG: retrieve relevant chunks then generate a grounded answer via Claude."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    chunks = _semantic_search(req.question, req.top_k, req.min_score)

    if not chunks:
        return {
            "answer": "I don't have enough information in the knowledge base to answer that question.",
            "sources": [],
            "question": req.question,
        }

    context = "\n\n".join(
        f"[{i + 1}] {c['title'] or 'Untitled'}\n{c['content']}"
        for i, c in enumerate(chunks)
    )

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=req.model,
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": (
                "Answer the question using only the provided context. "
                "If the context doesn't contain enough information, say so.\n\n"
                f"Context:\n{context}\n\n"
                f"Question: {req.question}"
            ),
        }],
    )

    return {
        "answer": message.content[0].text,
        "sources": [{"id": c["id"], "title": c["title"], "score": c["score"]} for c in chunks],
        "question": req.question,
    }


@app.post("/documents", status_code=201)
def add_document(req: AddDocumentRequest) -> dict[str, Any]:
    doc_id = str(uuid.uuid4())
    _docs[doc_id] = {
        "id": doc_id,
        "content": req.content,
        "title": req.title,
        "metadata": req.metadata or {},
    }
    _rebuild_index()
    return {"id": doc_id, "status": "indexed", "title": req.title}


@app.get("/documents")
def list_documents(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    all_docs = list(_docs.values())
    paged = all_docs[offset: offset + limit]
    return [
        {"id": d["id"], "title": d.get("title"), "metadata": d.get("metadata", {})}
        for d in paged
    ]


@app.delete("/documents/{document_id}")
def delete_document(document_id: str) -> dict[str, str]:
    if document_id not in _docs:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found")
    del _docs[document_id]
    _rebuild_index()
    return {"deleted": document_id}
