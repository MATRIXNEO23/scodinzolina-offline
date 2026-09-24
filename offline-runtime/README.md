# GPTina Offline — launcher unico

Audit e alleggerimento della memoria personale: [AUDIT_MEMORY_LIGHT_2026-09-24.md](AUDIT_MEMORY_LIGHT_2026-09-24.md).

Runtime locale per usare un modello GGUF su llama.cpp insieme alla continuity offline di GPTina.

Percorso normale:

`launcher → llama.cpp → memoria read-only → RAG/chat bridge → finestra chat nativa`

KoboldCpp non è necessario.

## Avvio

Dalla radice della repository:

1. chiudi KoboldCpp e vecchie finestre GPTina;
2. doppio clic su `AVVIA_GPTINA_OFFLINE.bat`;
3. la prima volta premi **Installa / aggiorna motore**;
4. seleziona il file `.gguf`;
5. premi **AVVIA GPTINA**.

L'app avvia:

- llama.cpp: `127.0.0.1:5001`;
- GPTina Memory: `127.0.0.1:8765`;
- GPTina Chat/RAG: `127.0.0.1:8766`;
- finestra chat Tkinter nello stesso programma.

La chat si apre automaticamente dopo l'avvio dei servizi. Il pulsante **Apri chat**
la riporta in primo piano; chiuderla la nasconde senza perdere la conversazione.
**Enter** invia e **Shift+Enter** inserisce una nuova riga. Il browser resta
disponibile manualmente su `http://127.0.0.1:8766` se serve un fallback.

## Streaming

### Recupero semantico sperimentale

La ricerca semantica è **disattivata** finché non la selezioni nel launcher.
Usa un modello multilingue ONNX aggiuntivo (circa 220 MB). La continuity resta
in sola lettura; vettori e modello sono cache locali ignorate da Git.

Nel launcher premi **Prepara indice**, attendi «Indice pronto», spunta
**Memoria semantica (prova)** e premi **AVVIA GPTINA**. Per tornare alla ricerca
normale, togli la spunta, premi **Ferma** e riavvia GPTina.

In alternativa, per prepararla da PowerShell dalla radice della repo:

```powershell
py -3 -m pip install -r offline-runtime/requirements-semantic.txt
py -3 offline-runtime/gptina_semantic_index.py
```

La preparazione stampa frammenti e millisecondi. Una modifica delle fonti
invalida l'indice e richiede di ripetere la preparazione. Se la cache diventa
obsoleta, il runtime continua con
FTS5 e registra `semantic_unavailable`; non scarica né costruisce durante
una domanda. L'esperimento deve misurare qualità delle fonti, primo token e
RAM sul vero i3 prima di tenere questa opzione attiva.

La finestra interna e la pagina web opzionale usano lo stesso `/chat/stream`.

I token vengono mostrati mentre il motore li genera. Non è più necessario aspettare la fine dell'intera risposta per vedere testo.

Sotto la risposta vengono mostrati, quando disponibili:

- token prompt / context;
- tempo retrieval memoria;
- tempo preparazione;
- tempo al primo token;
- token/sec di generazione;
- prompt token/sec.

Nella finestra interna il pulsante **Fonti ultimo turno** mostra i passaggi
selezionati con i rispettivi percorsi. La finestra rimane reattiva durante la
generazione: la rete è letta da un thread separato e solo il thread Tkinter
aggiorna la grafica.

## Diagnostica ed errori

Nel launcher premi:

**Diagnostica / errori**

Si apre una finestra con quattro pannelli:

- Motore
- Memoria
- Chat
- Launcher

I log vengono aggiornati automaticamente.

File:

- `offline-runtime\logs\engine.log`
- `offline-runtime\logs\memory.log`
- `offline-runtime\logs\chat.log`

Il log della sessione precedente viene conservato come `.previous`.

Gli errori di avvio aprono automaticamente la diagnostica.

## Protezione contro servizi vecchi

Memory runtime e chat bridge hanno una versione API.

Il launcher non riutilizza silenziosamente:

- una vecchia istanza GPTina;
- una porta occupata da un programma diverso;
- KoboldCpp sulla porta del motore;
- un llama-server già aperto con un GGUF differente.

In questi casi mostra un errore esplicito.

## Context

Il bridge legge il context reale da llama.cpp tramite `/props`.

Prima della generazione usa:

- `/apply-template`;
- `/tokenize`.

In questo modo verifica che prompt, memoria, history e spazio di risposta entrino davvero nel context.

Quando serve riduce prima la history vecchia e poi il materiale RAG meno prioritario. Il messaggio corrente dell'utente non viene eliminato.

## Memoria

Il memory runtime resta **read-only**.

Per la ricerca normale il bridge usa `/search_multi`: più termini vengono cercati con una sola scansione della continuity, invece di rileggere più volte gli stessi file.

Endpoint principali:

- `http://127.0.0.1:8765/health`
- `http://127.0.0.1:8765/recover/current`
- `http://127.0.0.1:8765/search_multi?q=termine&q=altro`

## Chat bridge

Endpoint:

- `http://127.0.0.1:8766/health`
- `http://127.0.0.1:8766/status`
- `http://127.0.0.1:8766/diagnostics`
- `POST /chat` — compatibilità sincrona;
- `POST /chat/stream` — percorso normale streaming.

## Profilo iniziale i3-2100

Impostazioni conservative:

- CPU only;
- 2 thread;
- context 1024;
- output massimo 160 token;
- batch 256;
- micro-batch 128;
- GPU layers 0;
- Flash Attention off.

Il launcher 2.1 permette di cambiare senza ricompilare **Thread generazione**
(`-t`), **Thread prompt** (`-tb`), **Batch** (`-b`), **Micro-batch** (`-ub`),
Context, Max risposta e il file GGUF. Salva i valori nel file locale ignorato
da Git `.gptina_app_config.json`. Ferma l'app e riavviala per applicare i
parametri del motore; il launcher rifiuta di riutilizzare un processo già
attivo, perché `/props` non permette di verificarne tutti i flag.

Valori iniziali: `-t 2 -tb 2 -b 256 -ub 128 -c 1024 -np 1 -ngl 0`.
Per provare il risultato già misurato sul PC di Alberto si può cambiare
**solo Thread prompt da 2 a 4**, mantenendo lo stesso modello e gli altri
campi. Quel benchmark ha ridotto il prefill cold di circa 20 secondi su 282
token, con maggior carico CPU; non garantisce lo stesso guadagno nella chat.
Micro-batch non può superare Batch. I parametri di compilazione AVX/SSE
restano propri della singola build Sandy Bridge e non sono opzioni runtime.

Il campo **Max risposta** del launcher viene propagato anche al bridge tramite:

`offline-runtime\.gptina_runtime_config.json`

Questo file è locale e ignorato da Git.

Dopo una prima risposta breve, confrontare 2 e 4 thread usando lo stesso prompt e il valore tok/s mostrato dalla chat.

## Qwen e thinking

Il bridge prova a disattivare thinking/reasoning per evitare di consumare tempo e token inutilmente sui Qwen che lo supportano:

- `enable_thinking=false`;
- `reasoning_effort=none`.

Se un template produce soltanto reasoning e nessuna risposta finale, viene mostrato un errore diagnostico.

## Motore Sandy Bridge

Il workflow:

`.github/workflows/build-gptina-sandybridge-engine.yml`

costruisce un `llama-server.exe` x64 fissato a una revisione di llama.cpp.

Target CPU:

- SSE4.2 ON;
- AVX ON;
- AVX2 OFF;
- FMA OFF;
- F16C OFF.

La release è:

`gptina-engine-v1`

e contiene:

`gptina-llama-sandybridge-engine.zip`

Il pulsante **Installa / aggiorna motore** scarica quel pacchetto in:

`offline-runtime\engine\`

## Sicurezza

- servizi solo localhost;
- nessun commit/push nel runtime;
- nessuna scrittura nella continuity;
- nessuna sincronizzazione automatica verso la canonica;
- la repository `MATRIXNEO23/scodinzolina-conntinuity` resta separata e non viene modificata.

## Audit

I problemi trovati e i relativi fix sono documentati in:

`offline-runtime/AUDIT_2026-09-23.md`
