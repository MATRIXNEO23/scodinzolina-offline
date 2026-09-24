"""Offline semantic retrieval experiment; never writes to the continuity mirror.

Run after ``pip install fastembed``. The first run downloads a multilingual
embedding model into a local runtime cache and encodes the current index.
This script is a benchmark, not part of the chat serving path.
"""

from __future__ import annotations

import json
import time

from gptina_chat_bridge import extract_search_queries, memory_route
from gptina_offline_index import OfflineIndex
from gptina_memory_server import combine_candidates
from gptina_semantic_index import SemanticIndex, prepare

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
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


def main():
    index = OfflineIndex()
    built = prepare(index)
    started = time.perf_counter()
    semantic = SemanticIndex(index)
    load_ms = round((time.perf_counter() - started) * 1000)
    output = {"model": MODEL, "chunks": built["chunks"],
              "index_build_ms": built["build_ms"], "cache_load_ms": load_ms, "cases": []}
    for question, expected in CASES:
        started = time.perf_counter()
        route = memory_route(question)
        dense_items = semantic.search(question, route)
        dense = [item["path"] for item in dense_items]
        query_ms = round((time.perf_counter() - started) * 1000)
        lexical = index.search(extract_search_queries(question), 8,
                               route)
        fused = combine_candidates(lexical, dense_items, 3)
        fused_paths = [item["path"] for item in fused]
        output["cases"].append({
            "query": question, "expected": expected,
            "dense_rank": dense.index(expected) + 1 if expected in dense else None,
            "lexical_rank": next((i + 1 for i, item in enumerate(lexical)
                                  if item["path"] == expected), None),
            "fused_rank": (fused_paths.index(expected) + 1
                           if expected in fused_paths else None),
            "query_ms": query_ms, "dense_top3": dense[:3],
            "domain_scores": semantic.domain_scores(question),
        })
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
