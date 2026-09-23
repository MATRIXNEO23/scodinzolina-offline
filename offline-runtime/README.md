# GPTina Offline Memory Runtime

Piccolo bridge locale **in sola lettura** per permettere a un modello locale di consultare la copia offline della continuity GPTina.

## Percorso previsto

La repository deve trovarsi qui:

`C:\Users\matri\Documents\GitHub\scodinzolina-offline`

Il runtime calcola comunque il root anche dalla propria posizione, quindi può continuare a funzionare se l'intera repository viene spostata.

## Avvio

Su Windows fai doppio clic su:

`offline-runtime\start_gptina_memory.bat`

Il server ascolta esclusivamente su:

`http://127.0.0.1:8765`

Non viene aperta alcuna porta verso la rete locale.

## Endpoint

- `/health` — verifica che il server sia attivo.
- `/status` — mostra modalità, root e upstream canonico.
- `/recover/current` — legge il percorso live-first corrente: live context, ultimo micro-checkpoint, ultimo checkpoint pieno, capsula, Fast Recall e Current Context.
- `/search?q=testo&limit=12` — ricerca case-insensitive nelle fonti testuali della continuity.
- `/find_exact?q=testo&limit=12` — ricerca esatta.
- `/read?path=rag/index/CURRENT_CONTEXT.md` — legge un singolo file relativo alla repository.

Esempi da browser:

`http://127.0.0.1:8765/health`

`http://127.0.0.1:8765/recover/current`

`http://127.0.0.1:8765/search?q=zampina`

## Sicurezza

Il server è intenzionalmente **read-only**:

- accetta soltanto GET;
- POST/PUT/PATCH/DELETE vengono rifiutati;
- impedisce path traversal fuori dalla repository;
- non contiene funzioni Git di push/commit;
- non scrive nella continuity;
- l'upstream `MATRIXNEO23/scodinzolina-conntinuity` resta separato.

## Importante: KoboldCpp

Questo server rende la memoria disponibile localmente, ma **KoboldCpp da solo non trasforma automaticamente il modello in un agente capace di chiamare questi endpoint**.

Il primo test può essere fatto aprendo `/recover/current` nel browser e passando il contesto a Qwen.

Il passo successivo è un piccolo bridge chat/RAG che, prima di ogni messaggio a Qwen, interroga automaticamente questo server e inserisce solo i frammenti pertinenti nel prompt. Questo evita di caricare tutta la repository nel contesto del modello.
