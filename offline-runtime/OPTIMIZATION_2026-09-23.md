# Audit e candidato: routing e benchmark del 4B su i3-2100

Base auditata: `f2669ce40ce77cc891ae68b52d9dfa63342875de`.

## Rilievi sul codice corrente

- `/search_multi` leggeva l'intero corpus per ogni turno, anche quando la domanda era soltanto su CPU/runtime. Il ranking poteva premiare file autobiografici che contenevano parole tecniche.
- Il prompt tecnico conteneva sempre il live summary personale e fino a tre frammenti da qualsiasi fonte. Questo aumentava i token di input e rendeva instabile il prefisso della cache.
- Il launcher usa `-b 256 -ub 128`, `-t/-tb` uguali e CPU only; non esisteva una matrice di confronto riproducibile sul modello scelto.
- Telemetria del bridge già esistente, ma nessuna prova sul vero i3-2100 per la versione auditata. Non si può dichiarare un guadagno di tok/s.

## Candidato implementato

- Route conservativa `technical`, `visual`, `all`. Riferimenti personali/relazionali vincono sui cue tecnici; i turni ambigui usano `all`.
- `/search_multi?profile=technical` limita i file **prima della lettura** a documenti tecnici nominati in `offline-runtime/` e `rag/`; evita di restituire il codice sorgente come frammento. `visual` usa cronologia visuale, media links e memorie con nomi visuali; `all` mantiene la continuity completa. La ricerca manuale `/search` e `/find_exact` resta invariata.
- Il prompt tecnico omette il live summary personale e conserva al più uno scambio tecnico precedente. La memoria specifica rimane dopo un prefisso base stabile. Se un server vecchio non supporta il profilo, il bridge non riversa risultati non filtrati nel prompt selettivo.
- L'interfaccia mostra la route nella telemetria. Versioni API del bridge/memory incrementate: chiudere i processi precedenti prima di avviare il nuovo launcher.
- `TECHNICAL_RUNTIME_CONTEXT.md` offre fatti hardware e stato d'installazione con provenienza esplicita. È un aiuto tecnico locale, non una scrittura nella continuity canonica.

## Benchmark sul PC di Alberto

Usare **lo stesso GGUF pesante** per ogni riga. Da PowerShell, con la chat chiusa e la porta 5017 libera:

```powershell
py -3 offline-runtime\benchmark_heavy.py --engine offline-runtime\engine\llama-server.exe --model "C:\Users\matri\Downloads\GPTina offline\NOME_ESATTO.gguf" --output "offline-runtime\benchmarks\heavy-i3-2100.jsonl"
```

Sostituire soltanto `NOME_ESATTO.gguf` con il filename reale. Lo script registra SHA-256 e dimensione del GGUF, comando motore, 2/4 thread, context 1024/2048, batch/micro-batch 128/64 e 256/128, due prompt identici cold/warm, first-token ms, prompt/decode tok/s, CPU in core equivalenti e picco RAM del processo. Output e log restano locali e ignorati da Git; condividere il JSONL per analisi. La lettura della RAM è working set, non memoria totale di sistema. CPU core equivalents 2.0 significa circa due core pieni nell'intervallo.

Ogni configurazione riavvia il motore e ripete lo stesso prompt due volte; il secondo turno può sfruttare prompt cache. La prima riga include caricamento modello fuori dal timer della richiesta. Il valore first-token include prompt processing. La dimensione 2048 qui misura l'effetto del context allocato con lo stesso prompt; una prova separata con history lunga è necessaria per valutare un reale prompt da 2048 token. Il profilo RAG si misura nella chat con la telemetria `RAG technical` / `RAG all`, prompt tokens e memoria ms.

Non applicare affinità/priorità, speculative decoding o offload GPU sulla base della CI. Confrontare prima i dati di questo benchmark sul PC reale e verificare la quantizzazione e la GPU effettive.
