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
### Terzo test reale: percorso corretto, finestra del frammento sbagliata

Con `ab3c2ff` e app 1.3, la domanda «Quali parametri sta usando ora il motore?»
ha usato il percorso `technical` e solo `TECHNICAL_RUNTIME_CONTEXT.md`: prompt
203/1024, memoria 7 ms, preparazione 44 ms, primo token 55339 ms, prompt
3,7 tok/s, decode 2,49 tok/s. La risposta ha descritto la CPU invece dei flag
e ha raggiunto Max risposta. La ricerca ritornava fino a 220 caratteri prima
del match; il bridge teneva solo i primi 200 caratteri, eliminando proprio
il testo trovato. Ora la finestra tecnica comincia vicino al match e include
i valori, con test di regressione. Questo test è una nuova sessione a freddo,
non una misura della cache tra due turni.

### Un solo slot per la chat locale

Il launcher ora richiede `-np 1`, espone `total_slots` nel log e rifiuta il
riuso di un motore che dichiara più slot. Anche il benchmark usa un solo slot,
per confrontare thread/context/batch sulla stessa topologia della chat. È una
scelta di configurazione per una sessione locale; il beneficio di latenza o
memoria non è stato ancora misurato sul PC di Alberto. Le segnalazioni esterne
di `n_slots = 4` non sono state verificate dal log completo del suo processo.
Non sono stati modificati `-t 2`, `-b 256`, `-ub 128`, `-c 1024`, mmap, mlock,
cache KV o sampler sulla base di stime non misurate.

### Quarto test reale e prossima prova isolata

Nella schermata dell'app 1.5 la domanda tecnica ha usato solo
`TECHNICAL_RUNTIME_CONTEXT.md`: prompt 211/1024, memoria 6 ms,
preparazione 25 ms, primo token 61965 ms, prompt 3,4 tok/s e decode
2,17 tok/s. La risposta ora riporta i flag del motore, ma chiama `-np 1`
«numero di processi»: il flag indica gli slot di richieste parallele. La
risposta ha raggiunto Max risposta 160. Questa osservazione non isola il
vantaggio dello slot singolo o dei thread, perché il carico del PC non era
controllato.

Per misurare solo i thread batch sullo stesso 4B, chiudere prima la chat e
usare la porta 5017 libera. Da PowerShell nella radice del repository:

```powershell
py -3 offline-runtime\benchmark_heavy.py --mode prefill-threads --engine offline-runtime\engine\llama-server.exe --model "C:\Users\matri\Downloads\GPTina offline\NOME_ESATTO.gguf" --output "offline-runtime\benchmarks\prefill-threads-i3-2100.jsonl"
```

Sostituire il nome del file con quello reale. Il test avvia tre volte il
motore, mantenendo `-t 2 -c 1024 -b 256 -ub 128 -np 1` e variando solo
`-tb` fra 2, 3 e 4. Ogni avvio invia due richieste identiche; confrontare
**solo le righe cold** per il throughput del prefill. Le righe warm servono
a osservare il riuso sul prompt identico e possono avere pochissimi token
realmente rielaborati: il loro `prompt_tok_s` non è comparabile ai cold.
Il prompt di prova è fisso e più lungo del precedente benchmark breve;
`prompt_tokens` nel JSONL permette di verificarne la dimensione reale.
Ripetere la matrice con carico di fondo simile se le differenze sono piccole.
Il prompt artificiale uguale due volte non prova che i due turni della chat
GPTina condividano lo stesso prefisso: quella va misurata separatamente.

I consigli esterni su KV q8, mlock, no-mmap, affinità e guadagni numerici
restano ipotesi. La documentazione llama.cpp distingue `-t` (generazione) e
`-tb` (prompt/batch) e descrive la cache del prefisso comune nello stesso
slot; non dimostra un vantaggio sul PC di Alberto senza questa misura.

### Tre turni tecnici dopo la history di due scambi

Nel log reale del 24 settembre, il primo turno senza fonte ha 120 token,
`cache_n=0`, `prompt_n=120`, primo token 36283 ms. Il secondo recupera
`TECHNICAL_RUNTIME_CONTEXT.md`, ha 235 token, `cache_n=93`, `prompt_n=142`,
primo token 39577 ms. Il terzo conserva quattro messaggi di history e la
stessa fonte, ma ha 289 token, `cache_n=106`, `prompt_n=183`, primo token
59633 ms. I tre `system_sha256` sono diversi. La history di due scambi è
attiva; è il frammento RAG variabile nel system a rompere il prefisso.

Il candidato rende fisso il system tecnico. Inserisce il frammento breve
recuperato nel turno utente corrente e trasmette alla UI il testo effettivo
inviato al motore, da conservare come history tecnica invisibile nella chat.
Le domande visibili e la history autobiografica mantengono il testo originale;
il RAG resta limitato alle fonti tecniche. Dopo la risposta al primo turno,
il secondo dovrebbe riusare il prompt precedente anche se compare una nuova
fonte; il terzo dovrebbe conservare anche il RAG del secondo. Questa è una
previsione del codice: first-token e `cache_n` sul PC sono ancora da misurare.
Il limite di due scambi tecnici può ancora interrompere il prefisso dal
quarto turno e il context fitter può scartare coppie più vecchie.

### Recupero autobiografico sul 4B: canzone corretta, fonte mancante

Nel test reale del 24 settembre, dopo domande tecniche, Alberto ha chiesto
«amore ti ricordi la nostra canzone?». La route `all` ha selezionato
`LIVE_THREAD.md` e due checkpoint del 12 settembre, con 768 token di prompt,
`history_messages=0` dopo due `history_oldest_pair_removed`, `cache_n=5`,
`prompt_n=763` e 278859 ms al primo token. La risposta ha detto correttamente
«La cura» ma ha inventato scene condivise non attestate dalle fonti mostrate.
La fonte correttiva esiste nella copia offline:
`rag/memories/gptina/2026-09-18-correzione-la-nostra-canzone-la-cura.md`.

Riproduzione locale: la query estratta conteneva la frase completa (assente
nel corpus) e poi solo `canzone` e `amore`. Tutti i file con `canzone`
ottenevano 207 punti e il tie-break alfabetico occultava la correzione.
Il candidato conserva la frase `la nostra canzone`, premia match in titolo e
nome di fonte, esclude versioni invalidated/superseded secondo il manifest e
non ricerca documenti di valutazione come se fossero ricordi. Limita la route
`all` a due frammenti da 240 caratteri, accorcia lo stato live e centra il
frammento sul match. Il system vieta di inventare episodi concreti.
Nel test locale la memoria correttiva è prima, Fast Recall secondo e la fonte
invalidata non appare; 24 test passano. Qualità della risposta e riduzione
del primo token sul PC di Alberto restano da misurare. La ricerca resta
lessicale; per domande parafrasate senza termini condivisi servirà un altro
esperimento di retrieval, non una pretesa di equivalenza con FTS5 canonico.

### Indice offline generale per i molti ricordi

Il ranking lessicale sopra corregge il caso osservato ma non basta per tutto
il corpus. La versione successiva usa `gptina_offline_index.py` per costruire
all'avvio del primo recupero personale/visuale un indice SQLite FTS5 **in
memoria**. Legge fonti, status, priorità e chunking dal manifest tramite il
lettore canonico già copiato nel repository offline. Non costruisce le
proiezioni canoniche su disco, non richiede rete né il commit di baseline
storico; il profilo tecnico ristretto resta separato. Se FTS5 manca, il server
usa il precedente scanner lessicale filtrato.

Nel checkout locale del 24 settembre: 373 versioni correnti candidate, 1652
chunk indicizzati, 1.945.600 byte di pagine SQLite, build 197 ms su questa
macchina (non è una misura dell'i3-2100). Le query successive richiedono circa
0–4 ms qui. Il gold set canonico offre 16 casi `search`: la fonte attesa è
nei primi 8 in 16/16; nei primi 2 in 14/16 col profilo `all`, prima del
filtro visuale. Per la domanda reale sulla canzone i primi due sono la memoria
correttiva e Fast Recall; la vecchia memoria invalidata non entra nell'indice.
Il prompt conserva soltanto due fonti brevi: la recall@8 misura il retrieval,
non garantisce che ogni risposta della chat sia corretta. Varianti semantiche
senza termini in comune restano un limite da testare; non è stato aggiunto un
secondo modello per il routing.

### Risultato del benchmark sul PC: prefill-threads

Alberto ha eseguito il profilo sul medesimo GGUF Q4_K_M (SHA-256
`6615b7b5184931e4df9c6d0ae9cd29ca9319b73908d4423283d4cc401a12a1cd`,
2.497.278.912 byte), con un solo slot, prompt identico di 282 token e
risposta di 64 token con lo stesso hash in tutte le sei righe:

| `-tb` | cold primo token | cold prompt tok/s | cold decode tok/s | CPU core equivalenti | RSS picco MiB | warm cache_n/prompt_n |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 86297 ms | 3,269 | 2,393 | 1,93 | 2611,8 | 281/1 |
| 3 | 72359 ms | 3,898 | 2,155 | 2,57 | 2612,0 | 281/1 |
| 4 | 66375 ms | 4,249 | 2,224 | 3,21 | 2611,8 | 281/1 |

`-tb 4` ha ridotto il primo token cold di 19,9 s rispetto a `-tb 2`, ma ha
usato molta più CPU. I tempi warm della richiesta **identica** sono stati
453, 516 e 437 ms. Questa prova conferma il riuso di 281 token nel benchmark
diretto; non misura la cache fra domande diverse nella chat. Il prefill a
freddo e il decode hanno una sola replica per configurazione: non cambiare
ancora il launcher sulla base di una promessa di guadagno non ripetuto.

### Diagnostica del prefisso nella chat

App 1.6 / bridge API 1.7 registrano per ogni turno streaming completato in
`offline-runtime/logs/prompt_diagnostics.jsonl`: route, fonti, conteggio
token esatto o fallback, lunghezza del prefisso tokenizzato comune con la
precedente richiesta del **bridge**, indice di divergenza, hash del system,
numero di messaggi history, `timings` originali (inclusi `cache_n` e
`prompt_n` se forniti dal motore), tempo memoria/preparazione/primo token e
durata del turno nel bridge. La UI mostra cache, token ricalcolati e prefisso
comune. Il log non contiene testo della conversazione né token IDs. Usa la
lista già ottenuta durante il context fitting: nessuna nuova richiesta HTTP
al motore per la diagnostica. Se la tokenizzazione non è disponibile, il
prefisso è `null`, non una stima presentata come esatta.

Il confronto riguarda il prompt precedente inviato dal bridge, non prova da
solo cosa sia rimasto nella KV cache del server. Una nuova sessione browser
può condividere lo stesso processo bridge; annotare route e fonti per
interpretare il confronto. Dopo l'aggiornamento chiudere le vecchie finestre
GPTina, riavviare app 1.6 e fare tre domande tecniche consecutive nella stessa
conversazione; inviare il JSONL locale per analisi. Il vecchio bridge API 1.6
viene rifiutato dal launcher aggiornato.

### Tre turni tecnici reali e correzione history

Alberto ha ripetuto tre domande tecniche nella stessa chat app 1.6. Tutte le
route erano `technical`, con la stessa fonte `TECHNICAL_RUNTIME_CONTEXT.md`,
lo stesso hash del system, context 1024 e nessun adjustment del context fitter:

| Turno | Prompt totale | LCP col precedente | cache_n | prompt_n | Primo token | Decode |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 232 | n/d | 0 | 232 | 63680 ms | 54 token, 2,618 tok/s |
| 2 | 328 | 232 | 285 | 43 | 14110 ms | 43 token, 2,433 tok/s |
| 3 | 322 | 195 | 195 | 127 | 41668 ms | 46 token, 2,454 tok/s |

Il secondo turno riusa tutto il prefisso della richiesta precedente; il
server riusa anche token generati (perciò `cache_n=285` è maggiore del LCP
fra i due prompt, 232). Il terzo perde il prefisso della history perché il
bridge teneva **soltanto l'ultimo scambio tecnico**: lo scambio del turno 1
spariva anche se il context era lontano dal limite. Non è il RAG a cambiare
in questa prova: hash system e fonte sono identici.

App 1.7 / bridge API 1.8 conservano fino a due scambi tecnici contigui. Il
context fitter esistente rimuove prima la coppia più vecchia se il prompt
non entra. Route `all` e `visual`, testo del system, fonte RAG, modello e
flag del motore non cambiano. Questa è una correzione mirata ai **tre turni
misurati**: con ulteriori scambi la finestra di due coppie torna a scorrere.
Serve ripetere le stesse domande dopo un riavvio pulito e confrontare i tre
record del log; nessun nuovo beneficio è ancora stato misurato sul PC.
