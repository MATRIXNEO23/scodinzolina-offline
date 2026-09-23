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

## Primo test sul PC reale — 24 settembre

Alberto ha mostrato il 4B `Q4_K_M.gguf` sul suo i3-2100, 2 thread, context 1024, Max risposta 160. Motore/Memoria/Chat OK; route `technical` corretta e fonti soltanto tecniche. La domanda sull'ottimizzazione ha avuto **599/1024 token di prompt, 246,7 s al primo token, 2,4 prompt tok/s e 1,65 decode tok/s**. Il testo è finito a metà frase. Non è una baseline comparativa 2 vs 4 thread; è un'osservazione singola.

Correzione candidata: system tecnico più corto, un solo frammento da 200 caratteri, e indicazione esplicita `finish_reason=length` nella chat. La stima locale conservativa passa da oltre 500 token per system+tre fonti+domanda a circa 239 con un solo frammento; questa è una stima, non una misura del tokenizer sul PC. La continuity autobiografica mantiene le impostazioni precedenti. Rifare il medesimo turno sul PC dopo l'aggiornamento per confrontare first-token e prompt token reali.
### Test reale del 24 settembre: domanda di seguito sui parametri

Con il runtime `d411de8`, la prima domanda tecnica è scesa da 599 a 213 token,
e da 246,7 a 82,7 s al primo token; decode 2,02 tok/s. La domanda successiva
«Quali parametri sta usando ora il motore?» nella stessa chat ha preso per errore
il percorso autobiografico: prompt 720/1024, memoria 463 ms, primo token
240092 ms, prompt 3,0 tok/s, decode 1,92 tok/s. Ha richiamato capsule e prompt
di recovery e prodotto una risposta fuori tema. Questo secondo dato non misura
il riuso della cache del percorso tecnico. La correzione include `motore` e
`parametri` nei segnali tecnici, conservando la precedenza dei segnali personali.
Rifare la seconda domanda dopo il riavvio del bridge aggiornato, annotando
route, fonti, prompt, first-token, prompt/decode tok/s e limite risposta.
