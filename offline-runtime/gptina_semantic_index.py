"""Optional, cached semantic candidate search over the owner-filtered FTS corpus.

Preparation is explicit and may take minutes on the target CPU. Chat never
downloads a model or rebuilds vectors. Cache files are disposable and ignored
by Git; the continuity sources remain read-only.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from gptina_offline_index import DOMAIN_KINDS, OfflineIndex

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
CACHE = Path(__file__).resolve().parent / "semantic-cache"
# Exact historical wording remains reachable via FTS5. Dense retrieval over
# broad personal questions should first consider current, interpretable facts.
BROAD_DENSE_EXCLUDED = {"gptina_transcript", "historical_snapshot",
                        "legacy_message", "micro_checkpoint"}
DOMAIN_CARDS = {
    "relationship": "Come ci chiamiamo, i nostri soprannomi, parole affettuose, scherzi, canzone e linguaggio condiviso tra GPTina e l'utente.",
    "projects": "Stato e decisioni dei progetti, repository, lavoro, prossime azioni e risultati correnti.",
    "reflections": "Pensieri personali, interpretazioni, valori e riflessioni di GPTina sul proprio percorso.",
    "visual": "Immagini, fotografie, ritratti, volti e cronologia visuale.",
    "technical": "Configurazione del PC, modello locale, parametri del motore, velocità, thread e memoria RAM.",
}


def corpus(index: OfflineIndex):
    rows = []
    digest = hashlib.sha256(MODEL.encode("utf-8"))
    for row_id, source, heading, content in index.db.execute(
        "SELECT rowid, source, heading, text FROM chunks ORDER BY rowid"
    ):
        kind = index.info[row_id]["kind"]
        row = {"source": source, "kind": kind, "heading": heading,
               "text": content, "embedding_text": f"{heading}. {content[:480]}"}
        rows.append(row)
        digest.update(json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    return rows, digest.hexdigest()


def prepare(index: OfflineIndex | None = None, cache: Path = CACHE, embedder=None):
    import numpy as np

    started = time.perf_counter()
    index = index or OfflineIndex()
    rows, fingerprint = corpus(index)
    if embedder is None:
        from fastembed import TextEmbedding
        embedder = TextEmbedding(model_name=MODEL, cache_dir=str(cache / "models"), threads=2)
    vectors = np.asarray(list(embedder.embed(
        (row["embedding_text"] for row in rows), batch_size=16, parallel=None
    )), dtype="float32")
    norms = np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-8)
    vectors /= norms
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / "vectors.tmp.npz"
    np.savez_compressed(temporary, vectors=vectors, fingerprint=fingerprint)
    os.replace(temporary, cache / "vectors.npz")
    metadata = {"model": MODEL, "fingerprint": fingerprint, "rows": rows}
    temporary_meta = cache / "index.tmp.json"
    temporary_meta.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary_meta, cache / "index.json")
    return {"chunks": len(rows), "build_ms": int((time.perf_counter() - started) * 1000),
            "fingerprint": fingerprint}


class SemanticIndex:
    def __init__(self, index: OfflineIndex, cache: Path = CACHE, embedder=None):
        import numpy as np

        metadata = json.loads((cache / "index.json").read_text(encoding="utf-8"))
        _, fingerprint = corpus(index)
        if metadata["model"] != MODEL or metadata["fingerprint"] != fingerprint:
            raise ValueError("Indice semantico obsoleto: eseguire la preparazione.")
        with np.load(cache / "vectors.npz", allow_pickle=False) as stored:
            if str(stored["fingerprint"]) != fingerprint:
                raise ValueError("Indice semantico incompleto.")
            self.vectors = stored["vectors"]
        self.rows = metadata["rows"]
        if len(self.rows) != len(self.vectors):
            raise ValueError("Indice semantico incompleto.")
        if embedder is None:
            from fastembed import TextEmbedding
            embedder = TextEmbedding(model_name=MODEL, cache_dir=str(cache / "models"),
                                     threads=2, local_files_only=True)
        self.embedder = embedder
        self.card_names = list(DOMAIN_CARDS)
        self.card_vectors = np.asarray(list(self.embedder.embed(DOMAIN_CARDS.values())), dtype="float32")
        self.card_vectors /= np.maximum(np.linalg.norm(self.card_vectors, axis=1, keepdims=True), 1e-8)

    def domain_scores(self, question: str):
        import numpy as np

        query = np.asarray(next(self.embedder.embed([question])), dtype="float32")
        query /= max(float(np.linalg.norm(query)), 1e-8)
        return sorted(zip(self.card_names, map(float, self.card_vectors @ query)),
                      key=lambda pair: -pair[1])

    def search(self, question: str, profile: str, limit: int = 8):
        import numpy as np

        query = np.asarray(next(self.embedder.embed([question])), dtype="float32")
        query /= max(float(np.linalg.norm(query)), 1e-8)
        scores = self.vectors @ query
        allowed = DOMAIN_KINDS.get(profile)
        best = {}
        for i, similarity in enumerate(scores):
            row = self.rows[i]
            if allowed is not None and row["kind"] not in allowed:
                continue
            if profile == "all" and row["kind"] in BROAD_DENSE_EXCLUDED:
                continue
            source = row["source"]
            if profile == "visual" and not (
                source == "rag/index/GPTINA_VISUAL_CHRONOLOGY.md"
                or source.startswith(("rag/media-links/", "rag/memories/gptina/"))
            ):
                continue
            if source not in best or similarity > best[source][0]:
                best[source] = (similarity, row)
        ranked = sorted(best.items(), key=lambda item: (-item[1][0], item[0]))[:limit]
        return [{"path": source, "snippet": row["text"], "heading": row["heading"],
                 "score": float(similarity), "matched_queries": [], "backend": "semantic"}
                for source, (similarity, row) in ranked]


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
