# GPTina Offline Runtime

Runtime locale per usare la copia `scodinzolina-offline` come memoria di GPTina insieme a un modello GGUF caricato in KoboldCpp.

Tutto il runtime usa solo `127.0.0.1`. La continuity viene letta in **sola lettura**.

## Avvio normale

1. Avvia KoboldCpp e carica il modello GGUF. Deve rispondere su `http://127.0.0.1:5001`.
2. Fai doppio clic su:

   `offline-runtime\start_gptina_chat.bat`

Il launcher:
- verifica/avvia automaticamente il memory runtime su porta **8765**;
- avvia il bridge chat/RAG su porta **8766**;
- apre la chat nel browser.

URL chat:

`http://127.0.0.1:8766`

Non serve più copiare manualmente `/recover/current` dentro Qwen.

## Come funziona

Per ogni messaggio:

`Alberto → bridge → stato live + ricerca memoria → prompt compatto → KoboldCpp/Qwen → risposta`

Il bridge non carica tutta la repository nel prompt. Recupera:
- il summary del live context;
- la prossima azione;
- pochi frammenti pertinenti ricavati dalla domanda corrente;
- una piccola finestra degli ultimi messaggi della chat.

Questo è intenzionalmente conservativo per funzionare anche con context size ridotte.

## File

- `gptina_memory_server.py` — accesso read-only alla continuity.
- `gptina_chat_bridge.py` — RAG automatico + chiamata a KoboldCpp.
- `chat_config.json` — parametri modificabili senza toccare il codice.
- `start_gptina_memory.bat` — avvia solo la memoria.
- `start_gptina_chat.bat` — avvio normale della chat.
- `web/index.html` — interfaccia chat locale.

## Porte

- KoboldCpp: `127.0.0.1:5001`
- GPTina Memory: `127.0.0.1:8765`
- GPTina Chat: `127.0.0.1:8766`

## Sicurezza

La memoria resta read-only:
- nessuna API Git nel runtime;
- nessun commit/push;
- nessuna scrittura nella continuity;
- nessun accesso fuori dalla repository tramite il memory server;
- binding esclusivamente localhost.

La repository canonica `MATRIXNEO23/scodinzolina-conntinuity` non viene modificata né sincronizzata automaticamente.

## KoboldCpp

Il bridge usa l'endpoint OpenAI-compatible:

`POST http://127.0.0.1:5001/v1/chat/completions`

Con Qwen Instruct è consigliato lasciare attivo il template/Jinja di KoboldCpp.

## Configurazione

`chat_config.json` contiene i parametri principali. I valori iniziali sono prudenti per il PC corrente:
- max output: 220 token;
- 4 messaggi recenti al massimo;
- massimo 4 frammenti memoria;
- prompt di memoria compatto.

Se il modello scelto è più veloce e il context viene aumentato, questi limiti possono essere alzati in seguito.

## Diagnostica

Memory:

`http://127.0.0.1:8765/health`

Chat bridge:

`http://127.0.0.1:8766/health`

Stato congiunto memoria + KoboldCpp:

`http://127.0.0.1:8766/status`

Se la UI mostra **memoria OK** e **Qwen OK**, il percorso automatico è operativo.
