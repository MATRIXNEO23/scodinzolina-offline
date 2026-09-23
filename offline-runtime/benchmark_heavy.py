#!/usr/bin/env python3
"""Repeatable Windows CPU benchmark of the selected heavy GGUF with llama-server.

Runs eight configurations, two identical turns each (cold/warm prompt cache).
No model is downloaded or substituted. Keep the PC idle during the run.
"""

import argparse
import ctypes
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from urllib.request import Request, urlopen

PROMPT = "Spiega in italiano, in modo concreto, come confrontare 2 e 4 thread su un Intel i3-2100 per un modello GGUF 4B."
SYSTEM = "Rispondi in italiano con chiarezza e brevità."


def process_sample(pid):
    if os.name != "nt":
        try:
            data = Path(f"/proc/{pid}/stat").read_text().split()
            return (int(data[13]) + int(data[14])) / os.sysconf("SC_CLK_TCK"), int(
                Path(f"/proc/{pid}/status").read_text().split("VmRSS:")[1].split()[0]
            ) * 1024
        except (OSError, ValueError, IndexError):
            return None, None
    from ctypes import wintypes
    class FILETIME(ctypes.Structure):
        _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
    class COUNTERS(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("faults", wintypes.DWORD),
                    ("peak_working", ctypes.c_size_t), ("working", ctypes.c_size_t),
                    ("peak_pagefile", ctypes.c_size_t), ("pagefile", ctypes.c_size_t),
                    ("peak_nonpaged", ctypes.c_size_t), ("nonpaged", ctypes.c_size_t),
                    ("pagefile_usage", ctypes.c_size_t), ("peak_pagefile_usage", ctypes.c_size_t),
                    ("private_usage", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME),
                                       ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME),
                                       ctypes.POINTER(FILETIME)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(COUNTERS), wintypes.DWORD]
    handle = kernel.OpenProcess(0x1000 | 0x0400, False, pid)
    if not handle:
        return None, None
    try:
        c, e, k, u = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        counters = COUNTERS()
        counters.size = ctypes.sizeof(counters)
        ok = kernel.GetProcessTimes(handle, ctypes.byref(c), ctypes.byref(e),
                                    ctypes.byref(k), ctypes.byref(u))
        mem_ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.size)
        ticks = lambda f: (f.high << 32) | f.low
        return ((ticks(k) + ticks(u)) / 10_000_000 if ok else None,
                counters.working if mem_ok else None)
    finally:
        kernel.CloseHandle(handle)


def wait_ready(proc, port):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"llama-server exited: {proc.returncode}")
        try:
            with urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                if json.load(response).get("status") == "ok":
                    return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError("llama-server did not become ready within 240 seconds")


def one_turn(proc, port):
    payload = {"model": "local", "messages": [
        {"role": "system", "content": SYSTEM}, {"role": "user", "content": PROMPT}],
        "temperature": 0, "seed": 42, "max_tokens": 64, "stream": True,
        "cache_prompt": True, "chat_template_kwargs": {"enable_thinking": False},
        "reasoning_effort": "none"}
    req = Request(f"http://127.0.0.1:{port}/v1/chat/completions",
                  data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json"}, method="POST")
    stop = Event()
    samples = []
    def sampler():
        while not stop.is_set():
            samples.append(process_sample(proc.pid))
            stop.wait(0.1)
    thread = Thread(target=sampler, daemon=True)
    thread.start()
    start = time.monotonic()
    first = None
    timings = {}
    output = []
    try:
        with urlopen(req, timeout=900) as response:
            for raw in response:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data: ") or line == "data: [DONE]":
                    continue
                event = json.loads(line[6:])
                timings.update(event.get("timings") or {})
                for choice in event.get("choices", []):
                    content = choice.get("delta", {}).get("content")
                    if content:
                        first = first or time.monotonic()
                        output.append(content)
    finally:
        stop.set()
        thread.join()
    elapsed = time.monotonic() - start
    cpu = [v[0] for v in samples if v[0] is not None]
    rss = [v[1] for v in samples if v[1] is not None]
    return {"first_token_ms": round((first - start) * 1000) if first else None,
            "wall_s": round(elapsed, 3), "cpu_core_equivalents": round((cpu[-1] - cpu[0]) / elapsed, 2) if len(cpu) > 1 else None,
            "peak_rss_mb": round(max(rss) / 1048576, 1) if rss else None,
            "prompt_tokens": timings.get("prompt_n"),
            "prompt_tok_s": timings.get("prompt_per_second"),
            "decode_tokens": timings.get("predicted_n"),
            "decode_tok_s": timings.get("predicted_per_second"),
            "output_sha256": hashlib.sha256("".join(output).encode()).hexdigest(),
            "timings": timings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--port", type=int, default=5017)
    args = parser.parse_args()
    if not args.engine.is_file() or not args.model.is_file():
        parser.error("Engine and model must be existing local files")
    with args.model.open("rb") as model_file:
        digest = hashlib.file_digest(model_file, "sha256").hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for threads in (2, 4):
        for context in (1024, 2048):
            for batch, ubatch in ((128, 64), (256, 128)):
                command = [str(args.engine), "-m", str(args.model), "--host", "127.0.0.1",
                           "--port", str(args.port), "-t", str(threads), "-tb", str(threads),
                           "-c", str(context), "-b", str(batch), "-ub", str(ubatch),
                           "-np", "1",
                           "-ngl", "0", "--flash-attn", "off", "--jinja"]
                with args.output.open("a", encoding="utf-8") as out, args.output.with_suffix(".engine.log").open("a", encoding="utf-8") as log:
                    proc = subprocess.Popen(command, stdout=log, stderr=log)
                    try:
                        wait_ready(proc, args.port)
                        with urlopen(f"http://127.0.0.1:{args.port}/props", timeout=4) as response:
                            slots = json.load(response).get("total_slots")
                        if slots is not None and int(slots) != 1:
                            raise RuntimeError(f"llama-server exposed {slots} slots, expected 1")
                        for phase in ("cold", "warm"):
                            result = one_turn(proc, args.port)
                            record = {"at": datetime.now(timezone.utc).isoformat(),
                                      "model": str(args.model), "model_sha256": digest,
                                      "model_bytes": args.model.stat().st_size,
                                      "engine": str(args.engine), "threads": threads,
                                      "context": context, "batch": batch, "ubatch": ubatch,
                                      "slots_requested": 1, "slots_reported": slots,
                                      "phase": phase, **result}
                            out.write(json.dumps(record, ensure_ascii=False) + "\n")
                            out.flush()
                            print(f"{threads=} {context=} {batch=} {phase}: "
                                  f"{result['decode_tok_s']} decode tok/s, {result['first_token_ms']} ms first token")
                    finally:
                        proc.terminate()
                        try:
                            proc.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                            proc.wait()


if __name__ == "__main__":
    main()
