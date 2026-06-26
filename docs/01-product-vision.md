# Zamer

## Shrnutí

Aplikace slouzi jako osobni nebo firemni asistent pro praci s uctenkami, fakturami a dalsimi financnimi dokumenty. Uzivatel nahraje dokument, system z nej vytahne text pomoci OCR, ulozi strukturovana data, zaindexuje obsah pro RAG a umozni nad dokumenty konverzaci prirozenym jazykem.

Aktualni implementace obsahuje webove rozhrani s autentizaci, dokumentovou pipeline, RAG, textovy chat, hlasovy hovor pres SpeechCloud a napojeni na jeden nebo vice Ollama serveru.

## Cile

- Umoznit uzivateli vest textovy i hlasovy chat nad vlastnimi doklady.
- Pouzit SpeechCloud jako technickou ASR/TTS vrstvu a backend jako autoritu pro uzivatele, historii a dokumenty.
- Ukladat historii konverzaci a oddelit data jednotlivych uzivatelu.
- Zpracovat dokumenty pres OCR, strukturovani a RAG index.
- Podporovat volitelny reranking zdroju a routing vypocetnich roli mezi Ollama servery.
- Drzet projekt lokalne spustitelny a vhodny pro iterativni vyvoj.

## Mimo rozsah aktualni verze

- Produkcni platebni nebo ucetni integrace.
- Vlastni implementace hlasoveho rozpoznavani a generovani hlasu mimo SpeechCloud.
- Multi-tenant firemni administrace.

## Cilovi uzivatele

- Jednotlivec, ktery chce rychle dohledavat informace v uctenkach a fakturach.
- Mala firma nebo zivnostnik, ktery potrebuje jednoduche dotazovani nad doklady.
- Vyvojar/operator, ktery bude system rozsirovat, nasazovat nebo ladit modely a infrastrukturu.

## Zakladni use cases

- Uzivatel se prihlasi do aplikace.
- Uzivatel nahraje uctenku, fakturu, fotografii nebo PDF.
- System dokument zpracuje pres OCR, strukturovani a RAG index.
- Uzivatel zalozi novou konverzaci.
- Uzivatel polozi dotaz textem nebo hlasem.
- Backend rozhodne, zda je potreba hledat v dokladech, pripadne pouzije RAG a reranker.
- Odpoved se zobrazi v chatu; ve hlasovem hovoru se zaroven precte pres TTS.
- Historie konverzace zustane ulozena.
