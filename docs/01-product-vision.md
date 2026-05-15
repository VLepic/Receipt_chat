# Produktovy zamer

## Shrnutí

Aplikace bude slouzit jako osobni nebo firemni asistent pro praci s uctenkami, fakturami a dalsimi financnimi dokumenty. Uzivatel nahraje dokument, system z nej vytahne text pomoci OCR, ulozi strukturovana data, zaindexuje obsah pro RAG a umozni nad dokumenty konverzaci prirozenym jazykem.

Prvni implementacni krok je chat-only a voice-chat MVP: webove rozhrani s autentizaci, Python backendem, napojenim na Ollama server a integraci SpeechCloud pro rozpoznavani a syntetizaci reci.

## Cile

- Umoznit uzivateli vest chat s LLM pres externi Ollama server.
- Pripravit backend tak, aby podporoval textovy chat i hlasove vstupy/vystupy pres SpeechCloud.
- Ukladat historii konverzaci a oddelit data jednotlivych uzivatelu.
- Navrhnout rozhrani pro dokumenty tak, aby OCR a RAG slo pridat bez velkeho prepisu chatu.
- Drzet projekt lokalne spustitelny a vhodny pro iterativni vyvoj.

## Mimo rozsah prvni verze

- OCR z uctenek a faktur.
- Automaticka extrakce polozek, castek, DPH a dodavatelu.
- Produkcni platebni nebo ucetni integrace.
- Vlastni implementace hlasoveho rozpoznavani a generovani hlasu mimo SpeechCloud.
- Multi-tenant firemni administrace.

## Cilovi uzivatele

- Jednotlivec, ktery chce rychle dohledavat informace v uctenkach a fakturach.
- Mala firma nebo zivnostnik, ktery potrebuje jednoduche dotazovani nad doklady.
- Vyvojar/operator, ktery bude system rozsirovat o OCR, RAG a hlasove API.

## Zakladni use cases

- Uzivatel se prihlasi do aplikace.
- Uzivatel zalozi novou konverzaci.
- Uzivatel polozi dotaz modelu textem nebo hlasem bez dokumentoveho kontextu.
- Backend preda dotaz Ollama serveru a vrati odpoved.
- SpeechCloud varianta precte odpoved pres TTS.
- Historie konverzace zustane ulozena.
- V budouci fazi uzivatel nahraje fakturu a pta se na castky, datum splatnosti, dodavatele nebo souhrny.
