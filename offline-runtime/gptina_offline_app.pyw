#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from tkinter import (
    BOTH, END, LEFT, RIGHT, X,
    Button, Entry, Frame, Label, StringVar, Text, Tk, Toplevel,
    filedialog, messagebox,
)
from tkinter import ttk
from urllib.request import Request, urlopen

APP_VERSION = "1.2"
MEMORY_API_VERSION = "1.2"
CHAT_API_VERSION = "1.4"

SCRIPT_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
ENGINE_EXE = SCRIPT_DIR / "engine" / "llama-server.exe"
MEMORY_SCRIPT = SCRIPT_DIR / "gptina_memory_server.py"
CHAT_SCRIPT = SCRIPT_DIR / "gptina_chat_bridge.py"
INSTALLER_SCRIPT = SCRIPT_DIR / "install_llama_engine.py"
LOCAL_CONFIG = SCRIPT_DIR / ".gptina_app_config.json"
RUNTIME_CONFIG = SCRIPT_DIR / ".gptina_runtime_config.json"
LOG_DIR = SCRIPT_DIR / "logs"

PORT_ENGINE = 5001
PORT_MEMORY = 8765
PORT_CHAT = 8766

DEFAULTS = {
    "model_path": "",
    "threads": "2",
    "context": "1024",
    "predict": "160",
}


def request_json(url: str, timeout: float = 1.5) -> dict:
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        request_json(url, timeout=timeout)
        return True
    except Exception:
        return False


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.35):
            return True
    except OSError:
        return False


def detect_models() -> list[Path]:
    roots = [
        SCRIPT_DIR.parent / "models",
        Path.home() / "Downloads" / "GPTina offline",
        Path.home() / "Downloads",
    ]
    found = []
    seen = set()

    for root in roots:
        if not root.exists():
            continue
        try:
            iterator = root.glob("*.gguf") if root.name == "Downloads" else root.rglob("*.gguf")
            for path in iterator:
                if not path.is_file():
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                found.append(path)
        except Exception:
            continue

    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def load_cfg() -> dict:
    cfg = dict(DEFAULTS)
    if LOCAL_CONFIG.exists():
        try:
            raw = json.loads(LOCAL_CONFIG.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception:
            pass

    if not cfg.get("model_path"):
        models = detect_models()
        if models:
            cfg["model_path"] = str(models[0])

    return {key: str(value) for key, value in cfg.items()}


def save_cfg(cfg: dict) -> None:
    LOCAL_CONFIG.write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_runtime_cfg(context: int, max_tokens: int) -> None:
    payload = {
        "engine_base": "http://127.0.0.1:5001",
        "memory_base": "http://127.0.0.1:8765",
        "context_size": context,
        "max_tokens": max_tokens,
        "disable_thinking": True,
        "generation_timeout_seconds": 900,
    }
    RUNTIME_CONFIG.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def tail_file(path: Path, max_bytes: int = 64_000) -> str:
    if not path.exists():
        return "(nessun log ancora)"
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
        return data.decode("utf-8", errors="replace")
    except Exception as exc:
        return f"(errore leggendo {path.name}: {exc})"


def rotate_log(path: Path) -> None:
    try:
        if path.exists():
            previous = path.with_suffix(path.suffix + ".previous")
            if previous.exists():
                previous.unlink()
            path.replace(previous)
    except Exception:
        pass


def service_probe(port: int, expected_service: str, expected_api: str) -> dict:
    result = {
        "port": port,
        "running": False,
        "ok": False,
        "service": None,
        "api_version": None,
        "error": None,
    }

    try:
        data = request_json(f"http://127.0.0.1:{port}/health", timeout=0.8)
        result["running"] = True
        result["service"] = data.get("service")
        result["api_version"] = data.get("api_version")
        result["ok"] = (
            data.get("ok") is True
            and data.get("service") == expected_service
            and data.get("api_version") == expected_api
        )
        if not result["ok"]:
            result["error"] = (
                f"Servizio inatteso/vecchio su porta {port}: "
                f"{data.get('service')!r} api={data.get('api_version')!r}"
            )
        return result
    except Exception as exc:
        result["running"] = port_open(port)
        if result["running"]:
            result["error"] = f"Porta {port} occupata ma /health non compatibile: {exc}"
        return result


def engine_probe() -> dict:
    result = {
        "running": False,
        "ok": False,
        "model_path": None,
        "n_ctx": None,
        "build_info": None,
        "chat_template": False,
        "error": None,
    }

    try:
        health = request_json("http://127.0.0.1:5001/health", timeout=0.8)
        result["running"] = True
        if health.get("status") not in {"ok", None} and health.get("ok") is not True:
            result["error"] = f"/health non pronto: {health}"
            return result

        props = request_json("http://127.0.0.1:5001/props", timeout=1.2)
        result["model_path"] = props.get("model_path")
        result["build_info"] = props.get("build_info")
        result["n_ctx"] = props.get("default_generation_settings", {}).get("n_ctx")
        result["chat_template"] = bool(props.get("chat_template"))
        result["ok"] = bool(result["model_path"]) and result["n_ctx"] is not None
        if not result["ok"]:
            result["error"] = "La porta 5001 risponde, ma non sembra il llama-server atteso."
    except Exception as exc:
        result["running"] = port_open(PORT_ENGINE)
        if result["running"]:
            result["error"] = (
                "Porta 5001 occupata da un servizio che non espone /props come llama.cpp: "
                + str(exc)
            )
    return result


class DiagnosticsWindow:
    def __init__(self, app: "App"):
        self.app = app
        self.win = Toplevel(app.root)
        self.win.title("GPTina Offline — Diagnostica ed errori")
        self.win.geometry("900x640")
        self.win.protocol("WM_DELETE_WINDOW", self.hide)

        top = Frame(self.win, padx=10, pady=8)
        top.pack(fill=X)
        self.summary = Label(top, text="Aggiornamento…", anchor="w", justify=LEFT)
        self.summary.pack(side=LEFT, fill=X, expand=True)
        Button(top, text="Aggiorna ora", command=self.refresh).pack(side=RIGHT)

        self.notebook = ttk.Notebook(self.win)
        self.notebook.pack(fill=BOTH, expand=True, padx=10, pady=(0, 10))

        self.tabs = {}
        for name in ("Motore", "Memoria", "Chat", "Launcher"):
            frame = Frame(self.notebook)
            text = Text(frame, wrap="none")
            yscroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            text.configure(yscrollcommand=yscroll.set)
            text.pack(side=LEFT, fill=BOTH, expand=True)
            yscroll.pack(side=RIGHT, fill="y")
            self.notebook.add(frame, text=name)
            self.tabs[name] = text

        self.visible = True
        self.refresh()
        self.win.after(1000, self._tick)

    def hide(self):
        self.visible = False
        self.win.withdraw()

    def show(self, tab: str | None = None):
        self.visible = True
        self.win.deiconify()
        self.win.lift()
        if tab in self.tabs:
            index = list(self.tabs).index(tab)
            self.notebook.select(index)
        self.refresh()

    def _set_text(self, name: str, content: str):
        widget = self.tabs[name]
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert("1.0", content)
        widget.configure(state="disabled")
        widget.see(END)

    def refresh(self):
        services = self.app.last_services or {}
        engine = services.get("engine", {})
        memory = services.get("memory", {})
        chat = services.get("chat", {})

        self.summary.configure(
            text=(
                f"Motore: {'OK' if engine.get('ok') else 'OFF/ERRORE'}   |   "
                f"Memoria: {'OK' if memory.get('ok') else 'OFF/ERRORE'}   |   "
                f"Chat: {'OK' if chat.get('ok') else 'OFF/ERRORE'}"
            )
        )

        engine_head = json.dumps(engine, ensure_ascii=False, indent=2)
        memory_head = json.dumps(memory, ensure_ascii=False, indent=2)
        chat_head = json.dumps(chat, ensure_ascii=False, indent=2)

        self._set_text(
            "Motore",
            "=== STATO ===\n" + engine_head + "\n\n=== LOG ===\n" + tail_file(LOG_DIR / "engine.log"),
        )
        self._set_text(
            "Memoria",
            "=== STATO ===\n" + memory_head + "\n\n=== LOG ===\n" + tail_file(LOG_DIR / "memory.log"),
        )
        self._set_text(
            "Chat",
            "=== STATO ===\n" + chat_head + "\n\n=== LOG ===\n" + tail_file(LOG_DIR / "chat.log"),
        )
        self._set_text(
            "Launcher",
            "\n".join(self.app.launcher_lines[-500:]) or "(nessun messaggio)",
        )

    def _tick(self):
        try:
            if self.visible:
                self.refresh()
            self.win.after(1000, self._tick)
        except Exception:
            pass


class App:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(f"GPTina Offline {APP_VERSION}")
        self.root.geometry("760x540")
        self.root.minsize(680, 500)

        self.procs: dict[str, subprocess.Popen] = {}
        self.handles = []
        self.events = queue.Queue()
        self.launcher_lines = []
        self.last_services = {}
        self.diagnostics: DiagnosticsWindow | None = None
        self.monitor_busy = False

        cfg = load_cfg()

        box = Frame(root, padx=14, pady=14)
        box.pack(fill=BOTH, expand=True)

        Label(box, text=f"GPTina Offline {APP_VERSION}", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        Label(
            box,
            text="Motore llama.cpp + memoria + RAG + chat. Gli errori sono visibili in Diagnostica.",
        ).pack(anchor="w", pady=(0, 14))

        row = Frame(box)
        row.pack(fill=X, pady=5)
        Label(row, text="Modello GGUF:", width=14, anchor="w").pack(side=LEFT)
        self.model = StringVar(value=cfg["model_path"])
        Entry(row, textvariable=self.model).pack(side=LEFT, fill=X, expand=True, padx=(0, 8))
        Button(row, text="Sfoglia…", command=self.browse).pack(side=RIGHT)

        row = Frame(box)
        row.pack(fill=X, pady=5)
        Label(row, text="Thread:").pack(side=LEFT)
        self.threads = StringVar(value=cfg["threads"])
        Entry(row, width=5, textvariable=self.threads).pack(side=LEFT, padx=(4, 14))

        Label(row, text="Context:").pack(side=LEFT)
        self.context = StringVar(value=cfg["context"])
        Entry(row, width=7, textvariable=self.context).pack(side=LEFT, padx=(4, 14))

        Label(row, text="Max risposta:").pack(side=LEFT)
        self.predict = StringVar(value=cfg["predict"])
        Entry(row, width=7, textvariable=self.predict).pack(side=LEFT, padx=(4, 14))

        erow = Frame(box)
        erow.pack(fill=X, pady=(8, 4))
        self.engine_label = Label(erow, text="")
        self.engine_label.pack(side=LEFT)
        Button(erow, text="Installa / aggiorna motore", command=self.install_engine).pack(side=RIGHT)

        row = Frame(box)
        row.pack(fill=X, pady=8)
        self.start_button = Button(row, text="AVVIA GPTINA", height=2, command=self.start)
        self.start_button.pack(side=LEFT, fill=X, expand=True, padx=(0, 5))
        Button(row, text="Apri chat", height=2, command=lambda: webbrowser.open("http://127.0.0.1:8766")).pack(side=LEFT, padx=5)
        Button(row, text="Diagnostica / errori", height=2, command=self.open_diagnostics).pack(side=LEFT, padx=5)
        Button(row, text="Ferma", height=2, command=self.stop).pack(side=RIGHT, padx=(5, 0))

        self.status = Label(box, text="Pronta.", anchor="w")
        self.status.pack(fill=X)

        self.services_label = Label(box, text="Motore: ?   Memoria: ?   Chat: ?", anchor="w")
        self.services_label.pack(fill=X, pady=(3, 0))

        self.log = Text(box, height=15, wrap="word")
        self.log.pack(fill=BOTH, expand=True, pady=(8, 0))

        self._append_log("Profilo iniziale: 2 thread, context 1024, output 160 token.")
        self._append_log("La chat ora usa streaming: i token devono comparire mentre vengono generati.")
        self._append_log("Apri 'Diagnostica / errori' per vedere engine.log, memory.log e chat.log in tempo reale.")

        self.refresh_engine_label()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(100, self._drain_events)
        self.root.after(300, self._schedule_monitor)

    def _append_log(self, text: str):
        stamp = time.strftime("%H:%M:%S")
        line = f"[{stamp}] {str(text).rstrip()}"
        self.launcher_lines.append(line)
        self.log.insert(END, line + "\n")
        self.log.see(END)

    def emit(self, kind: str, payload=None):
        self.events.put((kind, payload))

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "status":
                    self.status.configure(text=str(payload))
                elif kind == "start_enabled":
                    self.start_button.configure(state="normal" if payload else "disabled")
                elif kind == "error":
                    message, tab = payload
                    self._append_log("ERRORE: " + message)
                    self.status.configure(text="Errore. Apri Diagnostica.")
                    self.open_diagnostics(tab)
                    messagebox.showerror("GPTina Offline", message)
                elif kind == "services":
                    self.last_services = payload
                    self._render_services()
                elif kind == "engine_label":
                    self.refresh_engine_label()
        except queue.Empty:
            pass

        self.root.after(100, self._drain_events)

    def _render_services(self):
        e = self.last_services.get("engine", {})
        m = self.last_services.get("memory", {})
        c = self.last_services.get("chat", {})

        def mark(item):
            if item.get("ok"):
                return "OK"
            if item.get("running"):
                return "ERRORE"
            return "OFF"

        extra = ""
        if e.get("ok") and e.get("n_ctx"):
            extra = f"   ctx={e.get('n_ctx')}"
        self.services_label.configure(
            text=f"Motore: {mark(e)}{extra}   Memoria: {mark(m)}   Chat: {mark(c)}"
        )

    def _schedule_monitor(self):
        if not self.monitor_busy:
            self.monitor_busy = True
            threading.Thread(target=self._monitor_worker, daemon=True).start()
        self.root.after(2000, self._schedule_monitor)

    def _monitor_worker(self):
        try:
            data = {
                "engine": engine_probe(),
                "memory": service_probe(
                    PORT_MEMORY,
                    "GPTina Offline Memory",
                    MEMORY_API_VERSION,
                ),
                "chat": service_probe(
                    PORT_CHAT,
                    "GPTina Offline Chat Bridge",
                    CHAT_API_VERSION,
                ),
            }
            self.emit("services", data)

            for name, proc in list(self.procs.items()):
                code = proc.poll()
                if code is not None:
                    self.emit("log", f"Processo {name} terminato con exit code {code}.")
                    self.procs.pop(name, None)
        finally:
            self.monitor_busy = False

    def open_diagnostics(self, tab: str | None = None):
        if self.diagnostics is None or not self.diagnostics.win.winfo_exists():
            self.diagnostics = DiagnosticsWindow(self)
        else:
            self.diagnostics.show(tab)

    def refresh_engine_label(self):
        text = "Motore: installato" if ENGINE_EXE.exists() else "Motore: NON installato"
        self.engine_label.configure(text=text)

    def browse(self):
        path = filedialog.askopenfilename(
            title="Scegli il modello GGUF",
            initialdir=str(Path.home() / "Downloads"),
            filetypes=[("Modelli GGUF", "*.gguf"), ("Tutti i file", "*.*")],
        )
        if path:
            self.model.set(path)

    def install_engine(self):
        if not INSTALLER_SCRIPT.exists():
            messagebox.showerror("GPTina Offline", "Installer del motore non trovato.")
            return
        if any(proc.poll() is None for proc in self.procs.values()):
            messagebox.showinfo("GPTina Offline", "Ferma prima GPTina, poi aggiorna il motore.")
            return

        threading.Thread(target=self._install_worker, daemon=True).start()

    def _install_worker(self):
        self.emit("status", "Installazione motore…")
        self.emit("log", "Scarico il runtime llama.cpp preparato per Sandy Bridge…")
        try:
            proc = subprocess.run(
                [sys.executable, str(INSTALLER_SCRIPT)],
                cwd=str(SCRIPT_DIR),
                capture_output=True,
                text=True,
                timeout=300,
            )
            for line in (proc.stdout or "").splitlines():
                self.emit("log", line)
            for line in (proc.stderr or "").splitlines():
                self.emit("log", line)

            if proc.returncode != 0 or not ENGINE_EXE.exists():
                raise RuntimeError(f"Installazione fallita (exit {proc.returncode}).")

            self.emit("engine_label", None)
            self.emit("status", "Motore pronto.")
            self.emit("log", "Motore installato.")
        except Exception as exc:
            self.emit("error", (f"Installazione motore: {exc}", "Motore"))

    def validate(self):
        model = Path(self.model.get().strip())
        if not model.is_file() or model.suffix.lower() != ".gguf":
            raise ValueError("Seleziona un file modello .gguf valido.")
        if not ENGINE_EXE.is_file():
            raise ValueError("Il motore non è installato. Premi 'Installa / aggiorna motore'.")

        threads = int(self.threads.get())
        context = int(self.context.get())
        predict = int(self.predict.get())

        if not 1 <= threads <= 8:
            raise ValueError("Thread: usa un valore da 1 a 8.")
        if not 512 <= context <= 8192:
            raise ValueError("Context: usa un valore da 512 a 8192.")
        if not 32 <= predict <= 1024:
            raise ValueError("Max risposta: usa un valore da 32 a 1024.")

        # With a small context, leave enough room for system + memory + current turn.
        if predict >= context - 256:
            raise ValueError(
                "Max risposta è troppo alto rispetto al Context. "
                "Con Context 1024 usa, per esempio, 128-192 token."
            )

        return model, threads, context, predict

    def _prepare_log(self, name: str):
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = LOG_DIR / name
        rotate_log(path)
        handle = open(path, "w", encoding="utf-8", buffering=1)
        self.handles.append(handle)
        return handle

    def spawn(self, name: str, command: list[str], log_name: str):
        handle = self._prepare_log(log_name)
        kwargs = {
            "cwd": str(SCRIPT_DIR),
            "stdout": handle,
            "stderr": subprocess.STDOUT,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        proc = subprocess.Popen(command, **kwargs)
        self.procs[name] = proc
        self.emit("log", f"Avviato {name} (PID {proc.pid}).")
        return proc

    def wait_service(self, proc, url: str, seconds: float, label: str) -> dict:
        end = time.time() + seconds
        last_error = None

        while time.time() < end:
            if proc is not None and proc.poll() is not None:
                raise RuntimeError(f"{label} è terminato con exit code {proc.returncode}.")

            try:
                return request_json(url, timeout=1.0)
            except Exception as exc:
                last_error = exc
            time.sleep(0.35)

        raise RuntimeError(f"{label} non è diventato pronto: {last_error}")

    def start(self):
        try:
            model, threads, context, predict = self.validate()
        except Exception as exc:
            messagebox.showerror("GPTina Offline", str(exc))
            return

        save_cfg({
            "model_path": str(model),
            "threads": str(threads),
            "context": str(context),
            "predict": str(predict),
        })
        write_runtime_cfg(context, predict)

        self.start_button.configure(state="disabled")
        threading.Thread(
            target=self._start_worker,
            args=(model, threads, context, predict),
            daemon=True,
        ).start()

    def _assert_no_stale_service(self, probe: dict, name: str, port: int):
        if probe.get("running") and not probe.get("ok"):
            raise RuntimeError(
                f"Su porta {port} c'è un {name} vecchio o un altro programma. "
                "Chiudi le vecchie finestre GPTina/KoboldCpp, poi riprova. "
                f"Dettaglio: {probe.get('error')}"
            )

    def _start_worker(self, model: Path, threads: int, context: int, predict: int):
        try:
            self.emit("status", "Controllo porte e servizi…")

            memory_before = service_probe(PORT_MEMORY, "GPTina Offline Memory", MEMORY_API_VERSION)
            chat_before = service_probe(PORT_CHAT, "GPTina Offline Chat Bridge", CHAT_API_VERSION)
            self._assert_no_stale_service(memory_before, "memory runtime", PORT_MEMORY)
            self._assert_no_stale_service(chat_before, "chat bridge", PORT_CHAT)

            current_engine = engine_probe()
            if current_engine.get("running") and not current_engine.get("ok"):
                raise RuntimeError(
                    "La porta 5001 è occupata da un servizio diverso dal motore llama.cpp atteso. "
                    "Chiudi KoboldCpp o l'altro programma e riprova. "
                    f"Dettaglio: {current_engine.get('error')}"
                )

            self.emit("status", "Avvio motore…")
            if current_engine.get("ok"):
                active = Path(str(current_engine.get("model_path") or "")).name.casefold()
                wanted = model.name.casefold()
                if active and active != wanted:
                    raise RuntimeError(
                        f"Un motore è già attivo con '{active}', ma hai selezionato '{model.name}'. "
                        "Ferma il vecchio motore e riprova."
                    )
                active_ctx = int(current_engine.get("n_ctx") or 0)
                if active_ctx and active_ctx != context:
                    raise RuntimeError(
                        f"Il motore già attivo usa Context {active_ctx}, ma hai richiesto {context}. "
                        "Premi Ferma, poi AVVIA GPTINA per applicare il nuovo Context."
                    )
                self.emit(
                    "log",
                    "Motore llama.cpp già attivo e compatibile. "
                    "Per cambiare thread/context bisogna prima fermarlo."
                )
            else:
                self.emit("log", f"Modello: {model.name}")
                self.emit("log", f"CPU: {threads} thread · context {context} · max risposta {predict}")

                command = [
                    str(ENGINE_EXE),
                    "-m", str(model),
                    "--host", "127.0.0.1",
                    "--port", str(PORT_ENGINE),
                    "-t", str(threads),
                    "-tb", str(threads),
                    "-c", str(context),
                    "-n", str(predict),
                    "-b", "256",
                    "-ub", "128",
                    "-ngl", "0",
                    "--flash-attn", "off",
                    "--jinja",
                ]
                proc = self.spawn("engine", command, "engine.log")
                self.wait_service(proc, "http://127.0.0.1:5001/health", 180, "Motore")

            props = request_json("http://127.0.0.1:5001/props", timeout=4.0)
            n_ctx = props.get("default_generation_settings", {}).get("n_ctx")
            self.emit(
                "log",
                f"Motore OK · ctx={n_ctx} · template chat={'SI' if props.get('chat_template') else 'NO'} · "
                f"build={props.get('build_info')}",
            )
            if int(n_ctx or 0) != context:
                self.emit(
                    "log",
                    f"ATTENZIONE: context richiesto {context}, context esposto dal motore {n_ctx}.",
                )

            self.emit("status", "Avvio memoria…")
            memory = service_probe(PORT_MEMORY, "GPTina Offline Memory", MEMORY_API_VERSION)
            if not memory.get("ok"):
                proc = self.spawn(
                    "memory",
                    [sys.executable, str(MEMORY_SCRIPT), "--host", "127.0.0.1", "--port", str(PORT_MEMORY)],
                    "memory.log",
                )
                data = self.wait_service(proc, "http://127.0.0.1:8765/health", 30, "Memoria")
                if data.get("api_version") != MEMORY_API_VERSION:
                    raise RuntimeError(
                        f"Memory runtime API inattesa: {data.get('api_version')}, attesa {MEMORY_API_VERSION}."
                    )
            self.emit("log", "Memoria: OK")

            self.emit("status", "Avvio chat…")
            chat = service_probe(PORT_CHAT, "GPTina Offline Chat Bridge", CHAT_API_VERSION)
            if not chat.get("ok"):
                proc = self.spawn(
                    "chat",
                    [sys.executable, str(CHAT_SCRIPT), "--host", "127.0.0.1", "--port", str(PORT_CHAT)],
                    "chat.log",
                )
                data = self.wait_service(proc, "http://127.0.0.1:8766/health", 30, "Chat")
                if data.get("api_version") != CHAT_API_VERSION:
                    raise RuntimeError(
                        f"Chat bridge API inattesa: {data.get('api_version')}, attesa {CHAT_API_VERSION}."
                    )
            self.emit("log", "Chat streaming: OK")

            self.emit("status", "GPTina Offline pronta.")
            self.emit("log", "Tutto pronto. Apro la chat.")
            webbrowser.open("http://127.0.0.1:8766")

        except Exception as exc:
            text = str(exc)
            tab = "Motore"
            if "Memoria" in text or "memory" in text.lower():
                tab = "Memoria"
            elif "Chat" in text or "chat" in text.lower():
                tab = "Chat"
            self.emit("error", (text, tab))
        finally:
            self.emit("start_enabled", True)

    def stop(self):
        self._append_log("Arresto dei processi avviati da questa finestra…")
        for name, proc in list(self.procs.items())[::-1]:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                self._append_log(f"{name}: fermato.")
            except Exception as exc:
                self._append_log(f"{name}: errore durante arresto: {exc}")

        self.procs.clear()
        for handle in self.handles:
            try:
                handle.close()
            except Exception:
                pass
        self.handles.clear()

        self.status.configure(text="Fermata.")

    def close(self):
        if any(proc.poll() is None for proc in self.procs.values()):
            if messagebox.askyesno(
                "GPTina Offline",
                "Vuoi fermare anche i processi locali avviati da questa finestra?",
            ):
                self.stop()
        self.root.destroy()


def main():
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
