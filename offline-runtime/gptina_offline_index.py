"""Read-only, process-local FTS5 projection of GPTina's offline mirror.

The canonical manifest controls source inclusion, status and chunking. No
projection is written to the mirror or to the canonical repository.
"""

from __future__ import annotations

import sqlite3
import re
import sys
import time
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "rag"))
import gptina_memory as memory  # noqa: E402 - bundled canonical reader

_INDEX = None
_LOCK = Lock()
STOPWORDS = {
    "a", "abbiamo", "ad", "al", "alla", "alle", "allo", "che", "chi",
    "ci", "come", "con", "cosa",
    "da", "del", "della", "di", "e", "è", "era", "ha", "hai", "ho",
    "il", "in", "io", "la", "le", "lo", "mi", "per", "qual", "quale",
    "quando", "ricordi", "ricordo", "se", "si", "sono", "su", "te", "ti", "tu",
    "un", "una", "uno", "voi",
}


class OfflineIndex:
    def __init__(self):
        started = time.perf_counter()
        cfg = memory.load_manifest().get("chunking", {})
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE chunks USING fts5(source, heading, text)")
        self.info = {}
        for source in memory.collect_versions(False):
            if source.status in {"invalidated", "superseded"}:
                continue
            for heading, _ordinal, content in memory.chunk_text(
                source.content,
                int(cfg.get("max_chars", 1400)),
                int(cfg.get("overlap_chars", 220)),
                int(cfg.get("min_chars", 120)),
            ):
                cursor = self.db.execute(
                    "INSERT INTO chunks(source, heading, text) VALUES (?, ?, ?)",
                    (source.path, heading, content),
                )
                self.info[cursor.lastrowid] = {
                    "status": source.status,
                    "priority": source.priority,
                    "kind": source.kind,
                }
        self.db.commit()
        self.build_ms = int((time.perf_counter() - started) * 1000)

    def search(self, queries: list[str], limit: int, profile: str) -> list[dict]:
        image_ref = re.search(r"\b(?:immagine|foto)\s+(\d+)\b", " ".join(queries), re.I)
        phrases = [q.casefold().strip() for q in queries if len(memory.tokenize(q)) > 1]
        # The complete conversational question is usually absent verbatim.
        # Keep the shorter meaningful phrase, such as "la nostra canzone".
        phrases = sorted(set(phrases), key=len)
        terms = []
        for query in queries:
            for term in memory.tokenize(query):
                if term.casefold() not in STOPWORDS and term.casefold() not in terms:
                    terms.append(term.casefold())
        if not terms:
            terms = list(dict.fromkeys(memory.tokenize(" ".join(queries))))[:5]
        if not terms:
            return []
        expression = " OR ".join('"' + term.replace('"', '""') + '"' for term in terms[:12])
        rows = self.db.execute(
            "SELECT rowid, source, heading, text, bm25(chunks, 1.0, 2.0, 1.0) AS rank "
            "FROM chunks WHERE chunks MATCH ? ORDER BY rank LIMIT 240",
            (expression,),
        ).fetchall()
        ranked = []
        for row_id, source, heading, content, raw_rank in rows:
            if profile == "visual" and not (
                source == "rag/index/GPTINA_VISUAL_CHRONOLOGY.md"
                or source.startswith("rag/media-links/")
                or (source.startswith("rag/memories/gptina/") and any(
                    cue in source for cue in ("visual", "immagin", "ritratt", "volto", "foto")
                ))
            ):
                continue
            info = self.info[row_id]
            score = -float(raw_rank) * float(info["priority"])
            source_words = source.replace("-", " ").replace("_", " ").casefold()
            heading_words = heading.casefold()
            content_words = content.casefold()
            matched = []
            for phrase in phrases:
                if phrase in heading_words or phrase in content_words or phrase in source_words:
                    matched.append(phrase)
                    if phrase in heading_words:
                        score += 5.0
                    if phrase in source_words:
                        score += 4.0
                    if phrase in content_words:
                        score += 1.0
            if source.startswith("rag/memories/gptina/"):
                score += 1.0
            if source == "rag/index/GPTINA_FAST_RECALL.md":
                score += 0.5
            if profile == "visual" and image_ref:
                number = image_ref.group(1)
                if (source.endswith(f"/{number}.json")
                        or re.search(rf"(?:immagine|foto)-{re.escape(number)}(?:\D|$)", source, re.I)):
                    score += 5.0
                elif re.search(r"(?:immagine|foto)-\d+|/\d+\.json$", source, re.I):
                    score -= 5.0
                if source == "rag/index/GPTINA_VISUAL_CHRONOLOGY.md":
                    score += 2.0
            ranked.append({
                "path": source, "score": score, "snippet": content,
                "heading": heading, "status": info["status"],
                "matched_queries": matched,
            })
        ranked.sort(key=lambda item: (-item["score"], item["path"]))
        # A short prompt needs independent sources, not overlapping chunks of
        # the same file. Their original text remains available through /read.
        unique = []
        seen = set()
        for result in ranked:
            if result["path"] in seen:
                continue
            seen.add(result["path"])
            unique.append(result)
            if len(unique) >= limit:
                break
        return unique


def search(queries: list[str], limit: int, profile: str) -> tuple[list[dict], int, int]:
    global _INDEX
    started = time.perf_counter()
    with _LOCK:
        build_ms = 0
        if _INDEX is None:
            _INDEX = OfflineIndex()
            build_ms = _INDEX.build_ms
        result = _INDEX.search(queries, limit, profile)
    return result, int((time.perf_counter() - started) * 1000), build_ms
