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
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
CONFIG_PATH = REPO_ROOT / "rag" / "OFFLINE_RECOVERY_CONFIG.json"

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
            seen.add(p.resolve())
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

        start = max(0, idx - 220)
        end = min(len(text), idx + len(query) + 420)
        snippet = text[start:end].replace("\r", " ").replace("\n", " ").strip()
        results.append({
            "path": path.relative_to(REPO_ROOT).as_posix(),
            "offset": idx,
            "snippet": snippet,
        })
        if len(results) >= limit:
            break

    return results


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
    server_version = "GPTinaOfflineMemory/1.0"

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
                    "mode": "read_only",
                    "repository_root": str(REPO_ROOT),
                })
                return

            if parsed.path == "/status":
                cfg = load_config()
                self._send_json({
                    "ok": True,
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
    print("GPTina Offline Memory Server")
    print(f"Repository reale : {REPO_ROOT}")
    if config.get("repository_root"):
        print(f"Repository config: {config['repository_root']}")
    print("Accesso          : SOLA LETTURA")
    print(f"URL              : http://{args.host}:{args.port}")
    print("Test             : /health")
    print("Recovery         : /recover/current")
    print("Search           : /search?q=testo")
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
