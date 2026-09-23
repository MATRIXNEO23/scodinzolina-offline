# GPTina Offline — stato tecnico del target

Fonte del handoff: checkpoint canonico `checkpoints/2026-09-23-fine-istanza-offline-runtime-work-handoff.md` nel repository di continuity, copiato nel sandbox offline. Questo file è un riferimento tecnico per il RAG locale e non aggiorna la memoria canonica.

- Target CPU: Intel Core i3-2100 @ 3.10 GHz, Sandy Bridge, 2 core fisici / 4 thread, SSE4.2 + AVX, senza AVX2; RAM 10 GB.
- GPU e driver non identificati con certezza. Nessun GPU offload promesso.
- Modello pesante di riferimento: `Unrestricted/Qwen3-4B-2507-Instruct-Uncensored-HauhauCS-Aggressive`. La quantizzazione del GGUF locale non è stata verificata.
- Una versione locale precedente della chat su `127.0.0.1:8766` funzionava end-to-end; la versione auditata al commit `f2669ce40ce77cc891ae68b52d9dfa63342875de` non era ancora installata sul PC al momento del handoff.
- Misurare sul PC reale: 2/4 thread, context 1024/2048, batch 128/256 e micro-batch 64/128; first-token latency, prompt tok/s, decode tok/s, CPU/RAM e confronto cache cold/warm.
- Mantenere il modello pesante come target. Speculative decoding e priorità/affinità Windows richiedono una baseline; GPU offload richiede identificazione di GPU e driver.
