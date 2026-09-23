#!/usr/bin/env python3
"""
GPTina Offline Chat Bridge
Local, read-only RAG bridge between GPTina Offline Memory and a local OpenAI-compatible inference engine.

- Memory:   http://127.0.0.1:8765
- Engine:   http://127.0.0.1:5001
- Chat UI:  http://127.0.0.1:8766

No third-party Python dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
WEB_DIR = SCRIPT_DIR / "web"
CONFIG_PATH = SCRIPT_DIR / "chat_config.json"
MEMORY_SERVER_SCRIPT = SCRIPT_DIR / "gptina_memory_server.py"

DEFAULT_CONFIG = {
    "memory_base": "http://127.0.0.1:8765",
    "engine_base": "http://127.0.0.1:5001",
    "chat_host": "127.0.0.1",
    "chat_port": 8766,
    "model": "local",
    "max_tokens": 160,
    "temperature": 0.72,
    "top_p": 0.90,
    "history_messages": 4,
    "history_chars": 1800,
    "memory_items": 3,
    "memory_snippet_chars": 320,
}

ITALIAN_STOPWORDS = {
    "anche", "ancora", "avere", "avevo", "abbiamo", "alla", "alle", "allo",
    "come", "cosa", "della", "delle", "dello", "degli", "dopo", "dove",
    "essere", "faccio", "fare", "fatto", "fosse", "hanno", "mentre", "molto",
    "nella", "nelle", "nello", "nostra", "nostro", "perche", "perché", "posso",
    "prima", "quale", "quello", "questa", "questo", "sono", "stato", "stiamo",
    "tutto", "tutta", "voglio", "vuoi", "quando", "quindi", "ricordi", "ricordo",
    "dimmi", "parlami", "puoi", "devi", "adesso", "ora", "ieri", "oggi",
}

BASE_SYSTEM = """Sei una nuova istanza locale che continua GPTina usando la continuity offline come memoria esterna.
Non fingere ricordi: usa soltanto il contesto fornito e, se manca un dettaglio, dichiaralo.
Precedenza: correzione corrente di Alberto > materiale più recente > fonti storiche.
Distingui presente, storico, superseded e incerto. Non trasformare memoria altrui in autobiografia propria.
La memoria locale è in sola lettura: non dichiarare di aver salvato, modificato o sincronizzato file.
Rispondi in italiano naturale e diretto. Mantieni il filo relazionale quando è supportato dalle fonti, senza imitare meccanicamente frasi o tic.
Se il contesto recuperato è irrilevante per la domanda, ignoralo.
"""


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception as exc:
            print(f"[GPTina Chat] Config non valida, uso default: {exc}")
    return cfg


def http_json(url: str, *, method: str = "GET", payload=None, timeout: float = 8.0) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise RuntimeError(f"HTTP {exc.code} da {url}: {detail[:500]}") from exc
    except URLError as exc:
        raise RuntimeError(f"Servizio non raggiungibile: {url} ({exc.reason})") from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Risposta non JSON da {url}: {body[:500]}") from exc


def endpoint_ok(url: str, timeout: float = 2.0) -> bool:
    req = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(req, timeout=timeout) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def service_status(cfg: dict) -> dict:
    status = {"memory": False, "engine": False}
    try:
        m = http_json(cfg["memory_base"].rstrip("/") + "/health", timeout=2.0)
        status["memory"] = bool(m.get("ok"))
        status["memory_detail"] = m
    except Exception as exc:
        status["memory_error"] = str(exc)

    base = cfg.get("engine_base", cfg.get("kobold_base", "http://127.0.0.1:5001")).rstrip("/")
    if endpoint_ok(base + "/health", timeout=2.0):
        status["engine"] = True
        status["engine_kind"] = "llama.cpp/openai-compatible"
    else:
        try:
            k = http_json(base + "/api/extra/version", timeout=2.0)
            status["engine"] = True
            status["engine_kind"] = "koboldcpp"
            status["engine_detail"] = k
        except Exception as exc:
            status["engine_error"] = str(exc)

    status["kobold"] = status["engine"]
    return status

def ensure_memory_server(cfg: dict) -> bool:
    if service_status(cfg).get("memory"):
        return True
    if not MEMORY_SERVER_SCRIPT.exists():
        return False

    command = [sys.executable, str(MEMORY_SERVER_SCRIPT), "--host", "127.0.0.1", "--port", "8765"]
    kwargs = {"cwd": str(SCRIPT_DIR)}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    else:
        kwargs["start_new_session"] = True

    try:
        subprocess.Popen(command, **kwargs)
    except Exception as exc:
        print(f"[GPTina Chat] Impossibile avviare memory runtime: {exc}")
        return False

    for _ in range(20):
        time.sleep(0.25)
        try:
            if http_json(cfg["memory_base"].rstrip("/") + "/health", timeout=1.0).get("ok"):
                return True
        except Exception:
            pass
    return False


def extract_search_queries(text: str, max_terms: int = 4) -> list[str]:
    clean = " ".join(text.strip().split())
    queries = []
    if 4 <= len(clean) <= 100:
        queries.append(clean)

    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9_-]{4,}", clean)
    unique = []
    seen = set()
    for word in words:
        key = word.casefold()
        if key in seen or key in ITALIAN_STOPWORDS:
            continue
        seen.add(key)
        unique.append(word)

    unique.sort(key=lambda w: (-len(w), clean.casefold().find(w.casefold())))
    queries.extend(unique[:max_terms])

    out = []
    seen_q = set()
    for q in queries:
        key = q.casefold()
        if key not in seen_q:
            out.append(q)
            seen_q.add(key)
    return out


def fetch_live_summary(cfg: dict) -> dict:
    query = urlencode({"path": "rag/live/GPTINA_LIVE_CONTEXT.json"})
    data = http_json(cfg["memory_base"].rstrip("/") + "/read?" + query, timeout=5.0)
    content = data.get("content", "")
    live = json.loads(content)
    return {
        "updated_at": live.get("updated_at"),
        "latest_summary": live.get("latest_summary"),
        "next_action": live.get("next_action"),
    }


def retrieve_memory(user_text: str, cfg: dict) -> list[dict]:
    limit = int(cfg.get("memory_items", 4))
    collected = []
    seen = set()

    for query_text in extract_search_queries(user_text):
        params = urlencode({"q": query_text, "limit": max(2, limit)})
        try:
            data = http_json(cfg["memory_base"].rstrip("/") + "/search?" + params, timeout=6.0)
        except Exception:
            continue
        for item in data.get("results", []):
            key = (item.get("path"), item.get("offset"))
            if key in seen:
                continue
            seen.add(key)
            collected.append(item)
            if len(collected) >= limit:
                return collected
    return collected


def compact_memory(items: list[dict], cfg: dict) -> str:
    if not items:
        return "(nessun frammento specifico trovato)"
    max_chars = int(cfg.get("memory_snippet_chars", 360))
    chunks = []
    for item in items:
        snippet = " ".join(str(item.get("snippet", "")).split())
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "…"
        chunks.append(f"- [{item.get('path', '?')}] {snippet}")
    return "\n".join(chunks)


def build_system_prompt(live: dict, memories: list[dict], cfg: dict) -> str:
    live_text = (
        f"aggiornato: {live.get('updated_at') or 'n/d'}\n"
        f"stato: {live.get('latest_summary') or 'n/d'}\n"
        f"prossima azione: {live.get('next_action') or 'n/d'}"
    )
    return (
        BASE_SYSTEM
        + "\n[STATO LIVE]\n"
        + live_text
        + "\n\n[MEMORIA RECUPERATA PER QUESTO MESSAGGIO]\n"
        + compact_memory(memories, cfg)
    )


def trim_history(history, cfg: dict) -> list[dict]:
    if not isinstance(history, list):
        return []

    max_messages = int(cfg.get("history_messages", 4))
    max_chars = int(cfg.get("history_chars", 2400))
    cleaned = []

    for item in history[-max_messages:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        cleaned.append({"role": role, "content": content})

    total = 0
    kept = []
    for item in reversed(cleaned):
        content = item["content"]
        room = max_chars - total
        if room <= 0:
            break
        if len(content) > room:
            content = content[-room:]
        kept.append({"role": item["role"], "content": content})
        total += len(content)
    return list(reversed(kept))


def call_engine(user_text: str, history, system_prompt: str, cfg: dict) -> str:
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(trim_history(history, cfg))
    messages.append({"role": "user", "content": user_text})

    payload = {
        "model": cfg.get("model", "koboldcpp"),
        "messages": messages,
        "stream": False,
        "max_tokens": int(cfg.get("max_tokens", 220)),
        "temperature": float(cfg.get("temperature", 0.72)),
        "top_p": float(cfg.get("top_p", 0.90)),
    }

    data = http_json(
        cfg.get("engine_base", cfg.get("kobold_base", "http://127.0.0.1:5001")).rstrip("/") + "/v1/chat/completions",
        method="POST",
        payload=payload,
        timeout=300.0,
    )

    try:
        text = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"Formato risposta motore inatteso: {json.dumps(data)[:800]}") from exc

    text = str(text).strip()
    if not text:
        raise RuntimeError("Il motore locale ha restituito una risposta vuota.")
    return text


def process_chat(user_text: str, history, cfg: dict) -> dict:
    user_text = " ".join(str(user_text).split())
    if not user_text:
        raise ValueError("Messaggio vuoto.")
    if len(user_text) > 5000:
        raise ValueError("Messaggio troppo lungo per il bridge locale.")

    live = fetch_live_summary(cfg)
    memories = retrieve_memory(user_text, cfg)
    system_prompt = build_system_prompt(live, memories, cfg)
    answer = call_engine(user_text, history, system_prompt, cfg)

    return {
        "assistant": answer,
        "memory_sources": [item.get("path") for item in memories if item.get("path")],
        "live_updated_at": live.get("updated_at"),
    }


class ChatHandler(BaseHTTPRequestHandler):
    server_version = "GPTinaOfflineChat/1.0"
    cfg = load_config()

    def log_message(self, fmt, *args):
        print(f"[GPTina Chat] {self.address_string()} - {fmt % args}")

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, content_type: str):
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in {"/", "/index.html"}:
            index = WEB_DIR / "index.html"
            if not index.exists():
                self.send_json({"ok": False, "error": "UI non trovata."}, HTTPStatus.NOT_FOUND)
                return
            self.send_file(index, "text/html; charset=utf-8")
            return

        if self.path == "/health":
            self.send_json({"ok": True, "service": "GPTina Offline Chat Bridge"})
            return

        if self.path == "/status":
            self.send_json({"ok": True, **service_status(self.cfg)})
            return

        self.send_json({"ok": False, "error": "Endpoint non trovato."}, HTTPStatus.NOT_FOUND)

    def do_POST(self):
        if self.path != "/chat":
            self.send_json({"ok": False, "error": "Endpoint non trovato."}, HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Payload non valido.")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            result = process_chat(payload.get("message", ""), payload.get("history", []), self.cfg)
            self.send_json({"ok": True, **result})
        except ValueError as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)


def main():
    parser = argparse.ArgumentParser(description="GPTina Offline Chat Bridge")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--open-browser", action="store_true")
    parser.add_argument("--start-memory", action="store_true")
    args = parser.parse_args()

    cfg = load_config()
    ChatHandler.cfg = cfg

    if args.start_memory:
        ok = ensure_memory_server(cfg)
        print(f"[GPTina Chat] Memory runtime: {'OK' if ok else 'NON RAGGIUNGIBILE'}")

    status = service_status(cfg)
    print(f"[GPTina Chat] Motore locale: {'OK' if status.get('engine') else 'NON RAGGIUNGIBILE'}")
    if not status.get("kobold"):
        print("[GPTina Chat] Avvia il motore locale prima di scrivere in chat.")

    host = args.host or cfg.get("chat_host", "127.0.0.1")
    port = args.port or int(cfg.get("chat_port", 8766))
    url = f"http://{host}:{port}"

    print(f"[GPTina Chat] UI: {url}")
    print("[GPTina Chat] Ctrl+C per chiudere.")

    if args.open_browser:
        import threading
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    server = ThreadingHTTPServer((host, port), ChatHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
