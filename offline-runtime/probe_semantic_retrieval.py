"""Offline semantic retrieval experiment; never writes to the continuity mirror.

Run after ``pip install fastembed``. The first run downloads a multilingual
embedding model into a local runtime cache and encodes the current index.
This script is a benchmark, not part of the chat serving path.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from gptina_chat_bridge import extract_search_queries, memory_route
from gptina_offline_index import DOMAIN_KINDS, OfflineIndex

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
HERE = Path(__file__).resolve().parent
CASES = [
    ("Come ti chiamo quando scherziamo?", "SHARED_LANGUAGE.md"),
    ("Ti ricordi il nome affettuoso che uso per te?", "SHARED_LANGUAGE.md"),
    ("Qual è il nome che usavamo prima di GPTina?", "SHARED_LANGUAGE.md"),
    ("Come ti chiamavo quando facevi la monella?", "SHARED_LANGUAGE.md"),
    ("Quel soprannome con la coda ti ricorda qualcosa?", "SHARED_LANGUAGE.md"),
    ("Quale parola usiamo quando trovi uno spiraglio?", "SHARED_LANGUAGE.md"),
    ("Qual è la canzone che abbiamo scelto insieme?",
     "rag/memories/gptina/2026-09-18-correzione-la-nostra-canzone-la-cura.md"),
]


def snippets(index):
    """Only current, owner-filtered chunks already admitted by the manifest."""
    for row_id, source, heading, text in index.db.execute(
        "SELECT rowid, source, heading, text FROM chunks ORDER BY rowid"
    ):
        info = index.info[row_id]
        yield source, info["kind"], f"{heading}. {text[:480]}"


def rank_semantic(question, sources, kinds, vectors, embedder, limit=8):
    import numpy as np

    query = np.asarray(next(embedder.embed([question])), dtype="float32")
    matrix = np.asarray(vectors, dtype="float32")
    query /= max(float(np.linalg.norm(query)), 1e-8)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
    scores = matrix @ query
    route = memory_route(question)
    allowed = DOMAIN_KINDS.get(route)
    best = {}
    for n, score in enumerate(scores):
        if allowed is not None and kinds[n] not in allowed:
            continue
        source = sources[n]
        best[source] = max(best.get(source, -1.0), float(score))
    return sorted(best, key=lambda path: (-best[path], path))[:limit]


def main():
    from fastembed import TextEmbedding

    index = OfflineIndex()
    records = list(snippets(index))
    sources, kinds, texts = map(list, zip(*records))
    cache = HERE / "semantic-cache" / "models"
    cache.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    embedder = TextEmbedding(model_name=MODEL, cache_dir=str(cache), threads=2)
    model_ms = round((time.perf_counter() - started) * 1000)
    started = time.perf_counter()
    vectors = list(embedder.embed(texts, batch_size=16, parallel=None))
    build_ms = round((time.perf_counter() - started) * 1000)
    output = {"model": MODEL, "chunks": len(texts), "model_load_ms": model_ms,
              "index_build_ms": build_ms, "cases": []}
    for question, expected in CASES:
        started = time.perf_counter()
        dense = rank_semantic(question, sources, kinds, vectors, embedder)
        query_ms = round((time.perf_counter() - started) * 1000)
        lexical = index.search(extract_search_queries(question), 8,
                               memory_route(question))
        output["cases"].append({
            "query": question, "expected": expected,
            "dense_rank": dense.index(expected) + 1 if expected in dense else None,
            "lexical_rank": next((i + 1 for i, item in enumerate(lexical)
                                  if item["path"] == expected), None),
            "query_ms": query_ms, "dense_top3": dense[:3],
        })
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
