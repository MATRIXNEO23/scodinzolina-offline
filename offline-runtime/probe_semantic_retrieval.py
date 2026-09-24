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
from gptina_offline_index import OfflineIndex
from gptina_memory_server import combine_candidates
from gptina_semantic_index import SemanticIndex, prepare

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
ROOT = Path(__file__).resolve().parents[1]
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
PARAPHRASES = [
    ("Che cosa avevamo deciso sul nostro brano musicale?",
     "rag/memories/gptina/2026-09-18-correzione-la-nostra-canzone-la-cura.md"),
    ("Quale ritratto avevamo collegato al numero 44?", "rag/media-links/2026/09/44.json"),
    ("Chi può cambiare i ricordi che appartengono a Tessa?",
     "rag/MEMORY_OWNERSHIP_BOUNDARY.md"),
    ("Dove siamo rimasti con i controlli sulla memoria?", "rag/live/GPTINA_LIVE_CONTEXT.json"),
    ("Come va numerata la foto di Trieste dopo la rettifica?",
     "rag/memories/gptina/2026/09/2026-09-21--correzione-numerazione-48-49-50-originali.md"),
    ("Chi ha deciso come è nato il romanziere Ettore?",
     "rag/memories/gptina/2026/09/2026-09-21--correzione-origine-tessa-romanziere-ettore.md"),
    ("Quali regole proteggono l'accesso al nostro luogo segreto?",
     "rag/POSTICINO_ACCESS_POLICY.md"),
]


def main():
    index = OfflineIndex()
    built = prepare(index)
    started = time.perf_counter()
    semantic = SemanticIndex(index)
    load_ms = round((time.perf_counter() - started) * 1000)
    output = {"model": MODEL, "chunks": built["chunks"],
              "index_build_ms": built["build_ms"], "cache_load_ms": load_ms, "cases": []}
    gold = json.loads((ROOT / "rag/eval/GPTINA_MEMORY_GOLD.json").read_text(encoding="utf-8"))
    evaluation = [("paraphrase", question, [expected]) for question, expected in
                  CASES + PARAPHRASES]
    evaluation += [("canonical", item["query"], item["expected_any"])
                   for item in gold if item["mode"] == "search"]
    for category, question, expected_paths in evaluation:
        started = time.perf_counter()
        route = memory_route(question)
        dense_items = semantic.search(question, route)
        dense = [item["path"] for item in dense_items]
        query_ms = round((time.perf_counter() - started) * 1000)
        broad_items = semantic.search(question, "all") if route != "all" else dense_items
        broad = [item["path"] for item in broad_items]
        lexical = index.search(extract_search_queries(question), 8,
                               route)
        fused = combine_candidates(lexical, dense_items, 3)
        broad_fused = combine_candidates(lexical, broad_items, 3)
        fused_paths = [item["path"] for item in fused]
        lexical_paths = [item["path"] for item in lexical]
        def rank(paths):
            return next((i + 1 for i, path in enumerate(paths)
                         if path in expected_paths), None)
        output["cases"].append({
            "category": category, "query": question, "expected_any": expected_paths,
            "route": route,
            "dense_rank": rank(dense), "lexical_rank": rank(lexical_paths),
            "fused_rank": rank(fused_paths),
            "broad_dense_rank": rank(broad),
            "broad_fused_rank": rank([item["path"] for item in broad_fused]),
            "query_ms": query_ms, "dense_top3": dense[:3],
            "domain_top2": semantic.domain_scores(question)[:2],
        })
    for category in ("paraphrase", "canonical"):
        subset = [case for case in output["cases"] if case["category"] == category]
        output[category + "_summary"] = {
            name + "_at_2": sum(case[name + "_rank"] is not None and
                                case[name + "_rank"] <= 2 for case in subset)
            for name in ("lexical", "dense", "fused", "broad_dense", "broad_fused")
        }
        output[category + "_summary"]["total"] = len(subset)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
