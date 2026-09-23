# GPTina Offline — stato tecnico del target

Fonte del handoff: checkpoint canonico `checkpoints/2026-09-23-fine-istanza-offline-runtime-work-handoff.md` nel repository di continuity, copiato nel sandbox offline. Questo file è un riferimento tecnico per il RAG locale e non aggiorna la memoria canonica.

- Target CPU: Intel Core i3-2100 @ 3.10 GHz, Sandy Bridge, 2 core fisici / 4 thread, SSE4.2 + AVX, senza AVX2; RAM 10 GB.
- GPU e driver non identificati con certezza. Nessun GPU offload promesso.
- Parametri del motore nel test del 24 settembre: launcher selezionato con 2 thread e context 1024; comando `llama-server` della versione corrente: `-t 2 -tb 2 -c 1024 -b 256 -ub 128 -ngl 0 --flash-attn off` quando i campi restano su quei valori. La richiesta chat usa `cache_prompt: true`. Sono valori del test e del launcher, non una lettura dei flag del processo se è stato riutilizzato un motore già attivo.
- Modello pesante di riferimento: `Unrestricted/Qwen3-4B-2507-Instruct-Uncensored-HauhauCS-Aggressive`. Nel test mostrato da Alberto il file caricato termina in `Q4_K_M.gguf`; questa quantizzazione è ora verificata per quel file locale.
- Test locale del runtime `c70f8f4` mostrato da Alberto il 24 settembre: motore, memoria e chat OK; RAG technical usa solo fonti tecniche. La prima domanda ha richiesto 599 token di prompt, 246,7 s al primo token, 2,4 prompt tok/s e 1,65 decode tok/s; la risposta era incompleta con Max risposta 160. Il motivo di arresto non era esposto.
- Misurare sul PC reale: 2/4 thread, context 1024/2048, batch 128/256 e micro-batch 64/128; first-token latency, prompt tok/s, decode tok/s, CPU/RAM e confronto cache cold/warm.
- Mantenere il modello pesante come target. Speculative decoding e priorità/affinità Windows richiedono una baseline; GPU offload richiede identificazione di GPU e driver.
