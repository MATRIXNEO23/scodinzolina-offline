# GPTina Offline — launcher unico

Questa cartella contiene il runtime locale di GPTina.

Il percorso normale non richiede KoboldCpp: usa direttamente **llama.cpp** come motore GGUF CPU e avvia memoria + RAG + chat con un solo launcher.

## Uso

Dalla radice della repository:

1. chiudi KoboldCpp, se è aperto;
2. fai doppio clic su `AVVIA_GPTINA_OFFLINE.bat`;
3. la prima volta premi **Installa / aggiorna motore**;
4. scegli il file `.gguf`;
5. premi **AVVIA GPTINA**.

L'app avvia:

- motore llama.cpp: `127.0.0.1:5001`;
- memoria GPTina read-only: `127.0.0.1:8765`;
- chat/RAG: `127.0.0.1:8766`;
- browser direttamente sulla chat.

## Profilo iniziale per l'i3-2100

Impostazioni conservative iniziali:

- CPU only;
- 2 thread;
- context 1024;
- output massimo 160 token;
- batch 256;
- micro-batch 128;
- GPU layers 0;
- Flash Attention off.

Dopo il primo test confrontare 2 e 4 thread usando i token/sec reali.

## Motore

Il workflow `.github/workflows/build-gptina-sandybridge-engine.yml` costruisce un `llama-server.exe` CPU x64 da una versione di llama.cpp fissata.

La build abilita le varianti CPU dinamiche e verifica che sia presente la variante **Sandy Bridge**.

Su `main` il workflow pubblica il pacchetto:

`gptina-llama-sandybridge-engine.zip`

nella release:

`gptina-engine-v1`

Il pulsante **Installa / aggiorna motore** lo scarica e lo estrae in:

`offline-runtime\engine\`

## Memoria

La continuity resta in sola lettura:

- nessun commit o push dal runtime;
- nessuna scrittura nella continuity;
- nessun accesso automatico alla repository canonica;
- servizi esposti solo su localhost.

La canonica `MATRIXNEO23/scodinzolina-conntinuity` non viene modificata.

## File principali

- `gptina_offline_app.pyw` — launcher grafico;
- `install_llama_engine.py` — installazione del motore;
- `gptina_memory_server.py` — memoria read-only;
- `gptina_chat_bridge.py` — retrieval + chat;
- `web/index.html` — interfaccia chat;
- `chat_config.json` — limiti del prompt/RAG.

## Log

In caso di errore:

- `offline-runtime\logs\engine.log`
- `offline-runtime\logs\memory.log`
- `offline-runtime\logs\chat.log`

La compatibilità KoboldCpp resta soltanto come fallback nel bridge, ma non è più il percorso normale.
