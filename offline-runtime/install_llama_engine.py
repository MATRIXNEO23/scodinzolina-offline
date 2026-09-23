#!/usr/bin/env python3
from __future__ import annotations
import shutil, tempfile, urllib.request, zipfile
from pathlib import Path

HERE=Path(__file__).resolve().parent
ENGINE=HERE/"engine"
URL="https://github.com/MATRIXNEO23/scodinzolina-offline/releases/download/gptina-engine-v1/gptina-llama-sandybridge-engine.zip"

def main():
    print("Scarico il motore GPTina Offline…")
    with tempfile.TemporaryDirectory(prefix="gptina-engine-") as td:
        z=Path(td)/"engine.zip"
        req=urllib.request.Request(URL,headers={"User-Agent":"GPTina-Offline/1.0"})
        with urllib.request.urlopen(req,timeout=180) as r, open(z,"wb") as f:
            shutil.copyfileobj(r,f)
        if not zipfile.is_zipfile(z):
            raise RuntimeError("Pacchetto motore non valido.")
        if ENGINE.exists():
            shutil.rmtree(ENGINE)
        ENGINE.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(z) as f:
            f.extractall(ENGINE)
    exe=ENGINE/"llama-server.exe"
    if not exe.exists():
        raise RuntimeError("llama-server.exe non trovato nel pacchetto.")
    print("Motore installato:",exe)

if __name__=="__main__":
    main()
