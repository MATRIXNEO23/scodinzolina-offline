"""Read-only, process-local FTS5 projection of GPTina's offline mirror.

The canonical manifest controls source inclusion, status and chunking. No
projection is written to the mirror or to the canonical repository.
"""

from __future__ import annotations

import fnmatch
import json
import sqlite3
import re
import time
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "rag/memory_manifest.json"
WORD_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ_]+", re.UNICODE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")

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
DOMAIN_KINDS = {
    "relationship": {"gptina_memory", "fast_router", "shared_language",
                     "self_portrait", "historical_live_thread", "chronicle"},
    "projects": {"gptina_memory", "checkpoint", "live_context", "current_router",
                 "fast_router"},
    "reflections": {"gptina_memory", "reflection", "self_portrait", "fast_router"},
}


def tokenize(value: str) -> list[str]:
    return [match.group(0).casefold() for match in WORD_RE.finditer(value)]


def frontmatter(text: str) -> tuple[str | None, str, list[str]]:
    """Read only the three scalar/list keys needed for effective status."""
    if not text.startswith("---\n"):
        return None, "current", []
    end = text.find("\n---\n", 4)
    if end < 0:
        return None, "current", []
    lines = text[4:end].splitlines()
    values = {}
    supersedes = []
    in_supersedes = False
    for line in lines:
        if line.startswith("supersedes:"):
            in_supersedes = True
            inline = line.partition(":")[2].strip()
            if inline.startswith("[") and inline.endswith("]"):
                supersedes.extend(x.strip().strip("\"'") for x in inline[1:-1].split(",") if x.strip())
            elif inline and inline != "[]":
                supersedes.append(inline.strip("\"'"))
            continue
        if line and not line[0].isspace():
            in_supersedes = False
            key, _, value = line.partition(":")
            if key in {"memory_id", "status"}:
                values[key] = value.strip().strip("\"'")
        elif in_supersedes and line.lstrip().startswith("- "):
            supersedes.append(line.lstrip()[2:].strip().strip("\"'"))
    return values.get("memory_id"), values.get("status", "current"), supersedes


def chunks(text: str, max_chars: int, overlap: int, min_chars: int):
    heading = "(root)"
    blocks = []
    buf = []
    for line in text.splitlines():
        found = HEADING_RE.match(line)
        if found:
            if buf:
                blocks.append((heading, "\n".join(buf).strip()))
            heading, buf = found.group(2).strip(), [line]
        else:
            buf.append(line)
    if buf:
        blocks.append((heading, "\n".join(buf).strip()))
    for heading, block in blocks:
        if len(block) <= max_chars:
            if len(block) >= min_chars:
                yield heading, block
            continue
        start = 0
        while start < len(block):
            end = min(len(block), start + max_chars)
            if end < len(block):
                cut = block.rfind("\n", start, end)
                if cut <= start + max_chars // 2:
                    cut = block.rfind(". ", start, end)
                    if cut > start:
                        cut += 1
                if cut > start:
                    end = cut
            piece = block[start:end].strip()
            if len(piece) >= min_chars:
                yield heading, piece
            if end >= len(block):
                break
            start = max(start + 1, end - overlap)


def manifest_sources(manifest: dict):
    """Apply the canonical manifest patterns and ownership exclusions."""
    found = {}
    for key, exclusions, inside_rag in (
        ("sources", manifest.get("exclude", []), False),
        ("rag_sources", manifest.get("rag_exclude", ["rag/index/**", "rag/memories/tessa/**"]), True),
    ):
        for spec in manifest.get(key, []):
            for path in ROOT.glob(spec["pattern"]):
                rel = path.relative_to(ROOT).as_posix()
                if not path.is_file() or rel.startswith("rag/") != inside_rag:
                    continue
                if any(fnmatch.fnmatch(rel, pattern) for pattern in exclusions):
                    continue
                found[rel] = (path, spec)
    return found


class OfflineIndex:
    def __init__(self):
        started = time.perf_counter()
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cfg = manifest.get("chunking", {})
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE chunks USING fts5(source, heading, text)")
        self.info = {}
        sources = manifest_sources(manifest)
        records = {}
        ids = {}
        for rel, (path, spec) in sources.items():
            content = path.read_text(encoding="utf-8", errors="replace")
            if rel.startswith("rag/memories/") and path.suffix == ".json":
                try:
                    obj = json.loads(content)
                    content = str(obj.get("text") or obj.get("memory") or obj.get("content") or content)
                except ValueError:
                    pass
            if rel.startswith("rag/media-links/") and path.suffix == ".json":
                try:
                    obj = json.loads(content)
                    content = (f"Immagine: {obj.get('image_id', '')}. "
                               f"File: {obj.get('image_path', '')}. "
                               f"Cue: {', '.join(obj.get('cue', []))}. "
                               f"Stato: {obj.get('status', '')}. "
                               f"Memorie collegate: {', '.join(obj.get('memory_refs', []))}.")
                except (ValueError, TypeError):
                    pass
            memory_id, status, replaces = frontmatter(content)
            override = manifest.get("status_overrides", {}).get(rel)
            if override:
                status = str(override.get("status", status))
            if rel.startswith("rag/memories/") and (
                "# rettifica" in content[:900].casefold()
                or "stato:** invalidato" in content[:900].casefold()
                or "non deve essere usata come memoria canonica" in content[:900].casefold()
            ):
                status = "invalidated"
            records[rel] = (content, spec, status, replaces)
            if memory_id:
                ids[memory_id] = rel
        # New current records supersede older records without editing them.
        for _rel, (_content, _spec, status, replaces) in records.items():
            if status != "current":
                continue
            pending = list(replaces)
            seen = set()
            while pending:
                target = pending.pop()
                target_path = ids.get(target, target)
                if target_path in seen or target_path not in records:
                    continue
                seen.add(target_path)
                pending.extend(records[target_path][3])
                old_content, old_spec, _old_status, old_replaces = records[target_path]
                records[target_path] = (old_content, old_spec, "superseded", old_replaces)
        for rel, (content, spec, status, _replaces) in records.items():
            if status in {"invalidated", "superseded"}:
                continue
            # YAML metadata is for routing/provenance, not the short factual
            # excerpt shown to the model. A hit on memory_id otherwise sends
            # only a truncated header instead of the actual correction.
            indexed_content = content
            if content.startswith("---\n"):
                boundary = content.find("\n---\n", 4)
                if boundary >= 0:
                    indexed_content = content[boundary + 5:]
            for heading, chunk in chunks(
                indexed_content,
                int(cfg.get("max_chars", 1400)),
                int(cfg.get("overlap_chars", 220)),
                int(cfg.get("min_chars", 120)),
            ):
                cursor = self.db.execute(
                    "INSERT INTO chunks(source, heading, text) VALUES (?, ?, ?)",
                    (rel, heading, chunk),
                )
                self.info[cursor.lastrowid] = {
                    "status": status,
                    "priority": float(spec.get("priority", 1.0)),
                    "kind": spec.get("kind", "source"),
                }
        self.db.commit()
        self.build_ms = int((time.perf_counter() - started) * 1000)

    def search(self, queries: list[str], limit: int, profile: str) -> list[dict]:
        image_ref = re.search(
            r"\b(?:immagine|foto|ritratto|numero|n[°º])\s*(?:n[°º]\s*)?(\d+)\b",
            " ".join(queries), re.I,
        )
        phrases = [q.casefold().strip() for q in queries if len(tokenize(q)) > 1]
        # The complete conversational question is usually absent verbatim.
        # Keep the shorter meaningful phrase, such as "la nostra canzone".
        phrases = sorted(set(phrases), key=len)
        terms = []
        for query in queries:
            for term in tokenize(query):
                if term.casefold() not in STOPWORDS and term.casefold() not in terms:
                    terms.append(term.casefold())
        if not terms:
            terms = list(dict.fromkeys(tokenize(" ".join(queries))))[:5]
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
            info = self.info[row_id]
            if profile in DOMAIN_KINDS and info["kind"] not in DOMAIN_KINDS[profile]:
                continue
            if profile == "visual" and not (
                source == "rag/index/GPTINA_VISUAL_CHRONOLOGY.md"
                or source.startswith("rag/media-links/")
                or source.startswith("rag/memories/gptina/")
            ):
                continue
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
