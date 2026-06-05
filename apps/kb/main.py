"""MCP Knowledge Base service — semantic RAG pipeline with pgvector persistence.

  POST /query           — full RAG: retrieve relevant chunks + generate answer via OpenAI
  POST /search          — semantic similarity search (retrieval only, no generation)
  POST /documents       — add and index a document
  GET  /documents       — paginated list
  DELETE /documents/{id} — remove a document
  GET  / and GET /health
"""

from __future__ import annotations

import logging
import os
import uuid
from contextlib import contextmanager
from typing import Any, Generator

import numpy as np
import openai
import psycopg2
import psycopg2.extras
from fastapi import FastAPI, HTTPException
from pgvector.psycopg2 import register_vector
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

_log = logging.getLogger("kb")

_embedder = SentenceTransformer("all-MiniLM-L6-v2")

# Accept either asyncpg-style or plain psycopg2-style URL
_DSN = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")


# ── DB helpers ────────────────────────────────────────────────────────────────

def _new_conn() -> psycopg2.extensions.connection:
    conn = psycopg2.connect(_DSN)
    register_vector(conn)
    return conn


@contextmanager
def _conn() -> Generator[psycopg2.extensions.connection, None, None]:
    conn = _new_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── App + startup init ────────────────────────────────────────────────────────

app = FastAPI(title="MCP Knowledge Base", version="3.0.0")


@app.on_event("startup")
def _init_db() -> None:
    """Ensure vector extension and kb_documents table exist."""
    if not _DSN:
        _log.warning("DATABASE_URL not set — KB running without persistence")
        return
    try:
        conn = psycopg2.connect(_DSN)
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS kb_documents (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    title TEXT,
                    content TEXT NOT NULL,
                    metadata JSONB DEFAULT '{}',
                    embedding vector(384),
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)
        conn.commit()
        conn.close()
        _log.info("KB database ready")
    except Exception as exc:
        _log.warning("KB _init_db failed (service will be degraded): %s", exc)


# ── Core search logic ─────────────────────────────────────────────────────────

def _semantic_search(query: str, top_k: int, min_score: float) -> list[dict[str, Any]]:
    query_vec = _embedder.encode(query, convert_to_numpy=True).astype(np.float32)
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id::text, title, content, metadata,
                       1 - (embedding <=> %s) AS score
                FROM kb_documents
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_vec, query_vec, top_k),
            )
            rows = cur.fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "content": r["content"],
            "metadata": r["metadata"] or {},
            "score": round(float(r["score"]), 4),
        }
        for r in rows
        if float(r["score"]) >= min_score
    ]


# ── Pydantic models ───────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    min_score: float = 0.0


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    min_score: float = 0.1
    model: str = "gpt-4o-mini"


class AddDocumentRequest(BaseModel):
    content: str
    title: str | None = None
    metadata: dict[str, Any] | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/")
@app.get("/health")
def health() -> dict[str, Any]:
    if not _DSN:
        return {"status": "degraded", "error": "DATABASE_URL not set", "documents": 0}
    try:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM kb_documents")
                (count,) = cur.fetchone()
        return {"status": "healthy", "documents": count}
    except Exception as exc:
        return {"status": "degraded", "error": str(exc), "documents": 0}


@app.post("/search")
def search(req: SearchRequest) -> list[dict[str, Any]]:
    return _semantic_search(req.query, req.top_k, req.min_score)


@app.post("/query")
def query(req: QueryRequest) -> dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")

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

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
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
        "answer": response.choices[0].message.content,
        "sources": [{"id": c["id"], "title": c["title"], "score": c["score"]} for c in chunks],
        "question": req.question,
    }


@app.post("/documents", status_code=201)
def add_document(req: AddDocumentRequest) -> dict[str, Any]:
    doc_id = str(uuid.uuid4())
    embedding = _embedder.encode(req.content, convert_to_numpy=True).astype(np.float32)
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO kb_documents (id, title, content, metadata, embedding)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (doc_id, req.title, req.content, psycopg2.extras.Json(req.metadata or {}), embedding),
            )
    return {"id": doc_id, "status": "indexed", "title": req.title}


@app.get("/documents")
def list_documents(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id::text, title, metadata FROM kb_documents ORDER BY created_at DESC LIMIT %s OFFSET %s",
                (limit, offset),
            )
            rows = cur.fetchall()
    return [{"id": r["id"], "title": r["title"], "metadata": r["metadata"] or {}} for r in rows]


@app.delete("/documents/{document_id}")
def delete_document(document_id: str) -> dict[str, str]:
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM kb_documents WHERE id = %s::uuid", (document_id,))
            if cur.rowcount == 0:
                raise HTTPException(status_code=404, detail=f"Document '{document_id}' not found")
    return {"deleted": document_id}
