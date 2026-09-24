# GPTina Offline — audit e alleggerimento della memoria

## Perimetro e misure

Questa modifica interessa il mirror `scodinzolina-offline` e il prompt locale.
Non riscrive né elimina le fonti della continuity canonica.

Nella fotografia offline del 24 settembre l'indice include 373 fonti, 1652
frammenti, circa 952 KB di testo sorgente. La ricerca nei tre log forniti da
Alberto richiede 6–105 ms; il prefill del 4B richiede 47–59 s per 154–235 token
nuovi. La latenza deriva dal testo elaborato dal modello, non dal tempo della
query. Questa distinzione non quantifica quanto della latenza appartenga alla
sola memoria: serve una prova controllata sul PC target.

## Difetti riprodotti

- La fonte tecnica privilegiata con +1000 punti conteneva parametri del launcher
  1.5 (`-tb 2`); il launcher attivo era stato avviato con `-tb 4`.
- La correzione della numerazione delle immagini 48–50 esisteva ma il filtro
  visuale escludeva il file perché il nome non conteneva `immagine` o `foto`.
- La memoria personale includeva sempre uno stato live visuale anche per una
  domanda sulla canzone, due frammenti con path lunghi e fino a quattro
  messaggi di conversazione.
- Il testo YAML all'inizio delle memorie e i metadati JSON dei media link
  potevano occupare tutto il frammento mostrato al modello.
- Una domanda generica su un progetto attivo poteva ricevere un vecchio
  checkpoint: il live context elenca molti `active_threads`, non uno stato
  corrente univoco per ciascun progetto.

## Intervento nel runtime 2.2

1. Instradamento conservativo in `relationship`, `projects`, `reflections`,
   `visual`, `technical` e `all`. Le domande miste restano in `all`.
2. Nei percorsi personali, due fonti al massimo, 200 caratteri ciascuna
   (300 nel percorso visuale), una coppia di messaggi recenti, e stato live
   soltanto per domande correnti sui progetti. Nel prompt le fonti diventano
   `[1]` e `[2]`; path e passaggi sono visibili nella UI. Le fonti storiche
   restano leggibili e recuperabili.
3. L'indice in RAM separa i candidati per tipo di fonte; il percorso visuale
   ammette tutte le memorie GPTina, poi le ordina lessicalmente. Lo schema
   esistente continua a escludere memorie invalidated/superseded e altrui.
4. I front matter YAML non diventano frammenti conversazionali. Per i media
   link vengono indicizzati identificativo, file, cue, stato e riferimenti
   alla memoria, senza hash e byte nel prompt breve.
5. Il launcher scrive i parametri effettivi dopo la verifica del motore; le
   domande sui parametri usano questa fonte locale. La voce del launcher 1.5
   è stata rimossa dal riferimento tecnico. Se lo stato attivo manca, non
   viene inventato.
6. Una richiesta generica sul progetto corrente riceve un limite esplicito
   dal live context invece di scegliere un checkpoint arbitrario.

La cronologia tecnica continua a conservare i suoi frammenti precedenti nel
prompt: i test reali mostravano riuso della cache del prefisso. Togliendoli
senza una misura sul PC si rischiava di peggiorare il tempo tecnico. Nel
percorso personale la cronologia della UI contiene solo la domanda visibile.

## Verifica

`python -m unittest discover -s offline-runtime -p 'test_*.py' -q`: 33 test OK
nel checkout locale. Tutti i 16 casi `search` del gold set offline mantengono
una fonte attesa nei primi otto risultati con la route scelta dal bridge;
la correzione visuale 48–50 ora è al primo posto. Il caso della canzone trova
la memoria corretta e Fast Recall nei primi due risultati.

Questi test verificano la selezione della fonte e del passaggio, non la
correttezza finale della risposta del 4B. Misurare sul vero i3 la stessa
domanda personale prima/dopo: fonte e passaggio, `prompt_n`, `cache_n`,
tempo al primo token, risposta e attribuzione. Non attribuire guadagni di
secondi alla modifica prima di quel confronto.

## Limiti ancora aperti

- Una query parafrasata senza parole in comune può sfuggire a FTS5.
- `projects` è un filtro di tipi di fonte, non un database di stati progetto:
  la continuity dovrà esporre una proiezione corrente per progetto, con
  `as_of`, owner, stato, decisione e fonte, prima di rispondere a tutte le
  domande correnti su progetti nominati.
- `reflections` seleziona fonti pertinenti ma non certifica l'attribuzione
  di ogni frase; il modello deve distinguere GPTina, Alberto e terzi.
- Il fallback testuale quando FTS5 non è disponibile è più ampio delle route
  personali. La UI mostra le fonti, ma quel caso richiede una verifica
  specifica sul PC target.
