#!/usr/bin/env python3
"""
GPTina Offline Memory Server
Read-only local bridge for the scodinzolina-offline repository.

No third-party dependencies.
Binds to 127.0.0.1 only.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

API_VERSION = "1.6"
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = REPO_ROOT / "rag" / "OFFLINE_RECOVERY_CONFIG.json"
MANIFEST_PATH = REPO_ROOT / "rag" / "memory_manifest.json"

ALLOWED_SUFFIXES = {
    ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".py", ".toml", ".ini", ".cfg"
}

EXCLUDED_PARTS = {
    ".git",
    ".projection-generations",
    "__pycache__",
}

MAX_READ_BYTES = 512_000
DEFAULT_SEARCH_LIMIT = 12
MAX_SEARCH_LIMIT = 50
MAX_MULTI_QUERIES = 8
_SEMANTIC_INDEX = None
_SEMANTIC_LOCK = threading.Lock()
SEARCH_PROFILES = {"all", "technical", "visual", "relationship", "projects", "reflections"}
TECHNICAL_PATHS = (
    "offline-runtime/README.md",
    "offline-runtime/AUDIT_2026-09-23.md",
    "offline-runtime/TECHNICAL_RUNTIME_CONTEXT.md",
    "offline-runtime/OPTIMIZATION_2026-09-23.md",
    "rag/MEMORY_ARCHITECTURE_V2.md",
    "rag/MEMORY_SAVE_AND_RECOVERY_RUNBOOK.md",
    "rag/MEMORY_SCALE_STRATEGY.md",
)


def profile_allows(path: str, profile: str) -> bool:
    """Restrict files before reading them; the full corpus remains available for recall."""
    if profile in {"all", "relationship", "projects", "reflections"}:
        return not (
            path.startswith(("rag/eval/", "rag/memories/tessa/", "rag/memories/ettore/"))
            or path in {"rag/README.md", "rag/memory_manifest.json"}
        )
    if profile == "technical":
        return path in TECHNICAL_PATHS
    if profile == "visual":
        return path == "rag/index/GPTINA_VISUAL_CHRONOLOGY.md" or path.startswith(
            "rag/media-links/"
        ) or path.startswith("rag/memories/gptina/")
    raise ValueError("Profilo di ricerca non valido.")


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def safe_path(relative_path: str) -> Path:
    if not relative_path:
        raise ValueError("Percorso vuoto.")
    candidate = (REPO_ROOT / relative_path).resolve()
    root = REPO_ROOT.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Percorso fuori dalla repository.") from exc
    if not candidate.is_file():
        raise FileNotFoundError(relative_path)
    return candidate


def read_text_file(path: Path) -> str:
    if path.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("Tipo file non consentito in lettura testuale.")
    size = path.stat().st_size
    if size > MAX_READ_BYTES:
        raise ValueError(f"File troppo grande per questa API ({size} byte).")
    return path.read_text(encoding="utf-8", errors="replace")


def iter_search_files():
    roots = [
        REPO_ROOT / "rag",
        REPO_ROOT / "checkpoints",
        REPO_ROOT / "raw_sessions",
        REPO_ROOT / "instance_snapshots",
    ]
    top_level = [
        "NEXT_GPTINA.md",
        "GPTINA_INSTANCE_SNAPSHOT.md",
        "GPTINA_STATE.json",
        "LIVE_THREAD.md",
        "CONTINUITY.md",
        "GPTINA_SELF_PORTRAIT.md",
        "GPTINA_REFLECTIONS.md",
        "SHARED_LANGUAGE.md",
        "CHRONICLE.md",
        "GPTINA_SE_IL_TEMPO_FINISSE.md",
        "GPTINA_CONTINUITY_TESTS.md",
    ]

    seen = set()

    for name in top_level:
        p = REPO_ROOT / name
        if p.is_file():
            resolved = p.resolve()
            seen.add(resolved)
            yield p

    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in ALLOWED_SUFFIXES:
                continue
            if any(part in EXCLUDED_PARTS for part in p.parts):
                continue
            resolved = p.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield p


def normalize_queries(queries) -> list[str]:
    out = []
    seen = set()
    for value in queries or []:
        value = " ".join(str(value).strip().split())
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
        if len(out) >= MAX_MULTI_QUERIES:
            break
    return out


def _snippet(text: str, offset: int, needle_len: int) -> str:
    start = max(0, offset - 220)
    end = min(len(text), offset + max(needle_len, 1) + 420)
    return text[start:end].replace("\r", " ").replace("\n", " ").strip()


def search_memory(query: str, limit: int = DEFAULT_SEARCH_LIMIT, exact: bool = False) -> list[dict]:
    query = query.strip()
    if not query:
        return []

    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    needle = query if exact else query.casefold()
    results = []

    for path in iter_search_files():
        try:
            text = read_text_file(path)
        except Exception:
            continue

        haystack = text if exact else text.casefold()
        idx = haystack.find(needle)
        if idx < 0:
            continue

        results.append({
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "offset": idx,
            "snippet": _snippet(text, idx, len(query)),
        })
        if len(results) >= limit:
            break

    return results


def search_memory_multi(queries, limit: int = DEFAULT_SEARCH_LIMIT, profile: str = "all") -> tuple[list[dict], int]:
    """Scan the corpus once and rank files matching one or more query strings."""
    clean = normalize_queries(queries)
    if profile not in SEARCH_PROFILES:
        raise ValueError("Profilo di ricerca non valido.")
    if not clean:
        return [], 0

    limit = max(1, min(limit, MAX_SEARCH_LIMIT))
    folded = [q.casefold() for q in clean]
    started = time.perf_counter()
    results = []
    overrides = {}
    if profile != "technical":
        try:
            overrides = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("status_overrides", {})
        except (OSError, ValueError):
            pass

    paths = (iter(REPO_ROOT / name for name in TECHNICAL_PATHS if (REPO_ROOT / name).is_file())
             if profile == "technical" else iter_search_files())
    for path in paths:
        if not profile_allows(path.relative_to(REPO_ROOT).as_posix(), profile):
            continue
        try:
            text = read_text_file(path)
        except Exception:
            continue

        relative = path.relative_to(REPO_ROOT).as_posix()
        if profile != "technical" and relative.startswith("rag/memories/"):
            status = overrides.get(relative, {}).get("status", "current")
            header = text[:900].casefold()
            if status in {"superseded", "invalidated"} or (
                "# rettifica" in header or "stato:** invalidato" in header
            ):
                continue

        haystack = text.casefold()
        hits = []
        for order, needle in enumerate(folded):
            idx = haystack.find(needle)
            if idx >= 0:
                # Earlier queries are more important; longer matches are more specific.
                score = (len(folded) - order) * 100 + min(len(needle), 120)
                hits.append((score, idx, clean[order]))

        if not hits:
            continue

        hits.sort(key=lambda item: (-item[0], item[1]))
        best_score, anchor, _ = hits[0]
        score = sum(item[0] for item in hits)
        if profile == "technical" and relative == "offline-runtime/TECHNICAL_RUNTIME_CONTEXT.md":
            score += 1000  # Verified target facts before audit/method notes.
        if profile in {"all", "relationship", "projects", "reflections"}:
            # A phrase in the title or source name is more specific than a
            # generic mention in a long transcript or checkpoint.
            title = text[: min(len(text), 180)].casefold()
            name = relative.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").casefold()
            for phrase in folded:
                if len(phrase.split()) >= 2 and phrase in haystack:
                    if phrase in title:
                        score += 450
                    if phrase in name:
                        score += 180
            if relative.startswith("rag/memories/gptina/"):
                score += 110
            elif relative == "rag/index/GPTINA_FAST_RECALL.md":
                score += 150
            elif relative.startswith("rag/transcripts/"):
                score -= 100
        matched = [item[2] for item in hits]
        max_len = max(len(item[2]) for item in hits)

        results.append({
            "path": relative,
            "offset": anchor,
            "score": score,
            "matched_queries": matched,
            "snippet": _snippet(text, anchor, max_len),
        })

    results.sort(key=lambda item: (-item["score"], item["path"]))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return results[:limit], elapsed_ms


def semantic_candidates(question: str, profile: str, limit: int):
    """An explicitly prepared local cache; never download or rebuild on a request."""
    global _SEMANTIC_INDEX
    with _SEMANTIC_LOCK:
        if _SEMANTIC_INDEX is None:
            from gptina_semantic_index import SemanticIndex
            from gptina_offline_index import OfflineIndex
            _SEMANTIC_INDEX = SemanticIndex(OfflineIndex())
        return _SEMANTIC_INDEX.search(question, profile, limit)


def combine_candidates(lexical: list[dict], semantic: list[dict], limit: int):
    """Keep the strongest exact-term result, then use semantic evidence to rerank."""
    strong_phrase = any(item.get("matched_queries") for item in lexical[:2])
    lexical_weight, semantic_weight = (2.0, 1.0) if strong_phrase else (1.0, 2.0)
    scores, items = {}, {}
    for group, weight in ((lexical, lexical_weight), (semantic, semantic_weight)):
        for rank, item in enumerate(group):
            path = item["path"]
            scores[path] = scores.get(path, 0.0) + weight / (rank + 2)
            if path not in items or (strong_phrase and group is lexical):
                items[path] = item
    ranked = sorted(scores, key=lambda p: (-scores[p], p))
    # A dense match can surface paraphrases, but must not evict the best FTS
    # source from the tiny context budget. This holds for every memory domain.
    anchor = lexical[0]["path"] if lexical and limit >= 2 else None
    paths = ([anchor] if anchor else []) + [path for path in ranked if path != anchor]
    return [items[path] for path in paths[:limit]]


def recover_current() -> dict:
    live_path = REPO_ROOT / "rag" / "live" / "GPTINA_LIVE_CONTEXT.json"
    if not live_path.is_file():
        raise FileNotFoundError("rag/live/GPTINA_LIVE_CONTEXT.json")

    live = json.loads(live_path.read_text(encoding="utf-8"))
    ordered_paths = [
        "rag/live/GPTINA_LIVE_CONTEXT.json",
        live.get("last_micro_checkpoint"),
        live.get("last_full_checkpoint"),
        "rag/END_INSTANCE_RECOVERY_CAPSULE.md",
        "rag/index/GPTINA_FAST_RECALL.md",
        "rag/index/CURRENT_CONTEXT.md",
    ]

    documents = []
    for rel in ordered_paths:
        if not rel:
            continue
        try:
            p = safe_path(rel)
            documents.append({
                "path": rel,
                "content": read_text_file(p),
            })
        except Exception as exc:
            documents.append({
                "path": rel,
                "error": str(exc),
            })

    return {
        "repository_root": str(REPO_ROOT),
        "config": load_config(),
        "live_context": live,
        "documents": documents,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "GPTinaOfflineMemory/1.6"

    def _send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message, status=HTTPStatus.BAD_REQUEST):
        self._send_json({"ok": False, "error": message}, status)

    def log_message(self, fmt, *args):
        print(f"[GPTina Memory] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        try:
            if parsed.path in {"/", "/health"}:
                self._send_json({
                    "ok": True,
                    "service": "GPTina Offline Memory",
                    "api_version": API_VERSION,
                    "mode": "read_only",
                    "repository_root": str(REPO_ROOT),
                })
                return

            if parsed.path == "/status":
                cfg = load_config()
                self._send_json({
                    "ok": True,
                    "service": "GPTina Offline Memory",
                    "api_version": API_VERSION,
                    "repository_root": str(REPO_ROOT),
                    "configured_root": cfg.get("repository_root"),
                    "mode": cfg.get("mode"),
                    "access_policy": cfg.get("access_policy"),
                    "canonical_upstream": cfg.get("canonical_upstream"),
                    "recovery_entrypoint": cfg.get("recovery_entrypoint"),
                })
                return

            if parsed.path == "/recover/current":
                self._send_json({"ok": True, "result": recover_current()})
                return

            if parsed.path == "/read":
                rel = qs.get("path", [""])[0]
                p = safe_path(rel)
                self._send_json({
                    "ok": True,
                    "path": p.relative_to(REPO_ROOT).as_posix(),
                    "content": read_text_file(p),
                })
                return

            if parsed.path == "/search_multi":
                raw_limit = qs.get("limit", [str(DEFAULT_SEARCH_LIMIT)])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = DEFAULT_SEARCH_LIMIT
                profile = qs.get("profile", ["all"])[0]
                queries = normalize_queries(qs.get("q", []))
                if profile != "technical" and queries:
                    try:
                        from gptina_offline_index import search as indexed_search
                        results, scan_ms, build_ms = indexed_search(queries, limit, profile)
                        backend = "fts5_offline_manifest"
                    except (ImportError, sqlite3.OperationalError):
                        results, scan_ms = search_memory_multi(queries, limit=limit, profile=profile)
                        build_ms = 0
                        backend = "text_fallback"
                else:
                    results, scan_ms = search_memory_multi(queries, limit=limit, profile=profile)
                    build_ms = 0
                    backend = "text_technical"
                if (qs.get("semantic", ["0"])[0] == "1" and profile in
                        {"all", "relationship", "projects", "reflections"} and queries):
                    try:
                        candidates = semantic_candidates(queries[0], profile, max(8, limit))
                        results = combine_candidates(results, candidates, limit)
                        backend += "+semantic"
                    except (ImportError, OSError, ValueError, RuntimeError) as exc:
                        backend += "+semantic_unavailable"
                        print(f"[GPTina Memory] Semantica non disponibile: {exc}")
                self._send_json({
                    "ok": True,
                    "queries": queries,
                    "count": len(results),
                    "scan_ms": scan_ms,
                    "index_build_ms": build_ms,
                    "backend": backend,
                    "profile": profile,
                    "results": results,
                })
                return

            if parsed.path in {"/search", "/find_exact"}:
                q = qs.get("q", [""])[0]
                raw_limit = qs.get("limit", [str(DEFAULT_SEARCH_LIMIT)])[0]
                try:
                    limit = int(raw_limit)
                except ValueError:
                    limit = DEFAULT_SEARCH_LIMIT
                results = search_memory(q, limit=limit, exact=(parsed.path == "/find_exact"))
                self._send_json({
                    "ok": True,
                    "query": q,
                    "count": len(results),
                    "results": results,
                })
                return

            self._error("Endpoint non trovato.", HTTPStatus.NOT_FOUND)

        except FileNotFoundError as exc:
            self._error(f"File non trovato: {exc}", HTTPStatus.NOT_FOUND)
        except ValueError as exc:
            self._error(str(exc), HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._error(f"Errore interno: {exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        self._error(
            "Server in sola lettura: le operazioni di scrittura sono disabilitate.",
            HTTPStatus.METHOD_NOT_ALLOWED,
        )

    do_PUT = do_POST
    do_PATCH = do_POST
    do_DELETE = do_POST


def main():
    parser = argparse.ArgumentParser(description="GPTina Offline Memory Server (read-only)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    config = load_config()
    print(f"GPTina Offline Memory Server {API_VERSION}")
    print(f"Repository reale : {REPO_ROOT}")
    if config.get("repository_root"):
        print(f"Repository config: {config['repository_root']}")
    print("Accesso          : SOLA LETTURA")
    print(f"URL              : http://{args.host}:{args.port}")
    print("Test             : /health")
    print("Recovery         : /recover/current")
    print("Search           : /search?q=testo")
    print("Multi search     : /search_multi?q=testo&q=altro")
    print("Exact            : /find_exact?q=testo")
    print("Read             : /read?path=rag/index/CURRENT_CONTEXT.md")
    print("Ctrl+C per chiudere.\n")

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
