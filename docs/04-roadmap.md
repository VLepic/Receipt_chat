# Fáze vývoje

## Pravidlo pro testy

Kazda zmena roadmapy musi mit odpovidajici zmenu testovaci strategie. Pokud se do faze prida nova funkcionalita, musi se doplnit minimalne jeden testovaci bod, ktery overi jeji hlavni riziko.

## Fáze 0: plánování a dokumentace

Cil: ujasnit scope, architekturu, stack a prvni backlog.

Výstupy:

- Projektovy prehled.
- Architektonicky navrh.
- Volba stacku.
- Backlog pro MVP.
- Otevrene otazky k rozhodnuti.

Testy:

- Zkontrolovat, ze README odkazuje na vsechny dulezite dokumenty.
- Pri zmene architektury aktualizovat roadmapu, stack a backlog.
- Pri zmene scope zkontrolovat, ze testovaci body v roadmapě stale odpovidaji realnemu planu.

## Fáze 1: textovy chat + SpeechCloud voice MVP

Cil: prihlaseny uzivatel muze chatovat s Ollama modelem pres webove rozhrani a hlasove pres SpeechCloud.

Status: hotovo. Existuje prvni skeleton pro `backend`, `frontend`, `speech-dialog`, Docker Compose a zakladni testy. UI podporuje login a textovy chat bez RAG; rozsirena sprava vlaken zustava pro pozdejsi krok.

Scope:

- Backend ve FastAPI.
- Frontend ve React/Vite.
- Registrace a prihlaseni.
- Zakladni chat UI.
- API endpoint pro odeslani zpravy.
- Napojeni na Ollama.
- SpeechCloud dialog manager podle ukazek v `example`.
- ASR vstup ze SpeechCloud do Ollama chatu.
- TTS vystup odpovedi pres SpeechCloud.
- Ulozeni konverzaci a zprav.
- Konfigurace pres `.env`.

Definition of Done:

- Aplikacni kontejnery lze spustit lokalne a pripojit na externi Ollama server.
- Uzivatel se prihlasi a zalozi konverzaci.
- Odpovedi prichazeji z Ollama serveru.
- Hlasovy vstup a vystup funguje pres SpeechCloud testovaci/proxy prostredi.
- Historie se po refreshi neztrati.
- Chyby Ollama serveru jsou uzivatelsky srozumitelne.

Testy:

- Backend unit testy pro auth helpery, hashovani hesel a validaci vstupu.
- Backend API testy pro registraci, login, logout, aktualniho uzivatele a chranene endpointy.
- Backend API testy pro vytvoreni konverzace, odeslani zpravy a nacteni historie.
- Mockovany test Ollama adapteru pro uspesnou odpoved, timeout a chybu serveru.
- Smoke test SpeechCloud dialog manageru: start kontejneru, dostupnost `/ws`, inicializace bez padu.
- Frontend testy pro login formular, stav prihlaseni a zakladni chat flow.
- Docker Compose test: spustit testovaci stack a overit, ze backend, frontend, postgres a speech-dialog nastartuji.

## Fáze 2: stabilizace backendu a API

Cil: pripravit kod na budouci dokumenty, OCR a RAG a zaroven zprovoznit zakladni textovy chat proti externi Ollame.

Status: hotovo. Pridany jsou jednotny error format, request ID/logging middleware, Alembic migrace, dokumentovy model pro budouci OCR/RAG, `ProcessingJob` model pro budouci workery, `VectorStore` interface, dokumentove placeholder API kontrakty, textovy chat bez RAG, endpoint pro seznam Ollama modelu a backend kontraktove testy pro auth/chat izolaci.

Scope:

- Struktura backend modulu.
- OpenAPI kontrakty.
- Testy pro auth a chat.
- Textovy chat bez RAG nad externim Ollama serverem.
- Nacteni dostupnych Ollama modelu pres `/api/tags`.
- Volba modelu pro odeslanou zpravu.
- Odstraneni vlastni konverzace vcetne zprav.
- Logovani a error handling.
- Role pro budouci background jobs.

Testy:

- `pytest` pro backend sluzby a API kontrakty.
- Test databazovych migraci na ciste testovaci databazi.
- Test izolace dat: uzivatel nesmi cist konverzace jineho uzivatele.
- Mockovany test odeslani zpravy do vybraneho Ollama modelu.
- Mockovany test seznamu dostupnych Ollama modelu.
- Test smazani vlastni konverzace.
- Test, ze uzivatel nesmi smazat konverzaci jineho uzivatele.
- Test jednotneho error formatu pro validacni chyby, auth chyby a chyby integraci.
- CI/Docker prikaz pro spusteni backend testu v kontejneru.

## Fáze 3: upload dokumentů

Cil: uzivatel muze nahrat uctenku nebo fakturu a videt stav zpracovani.

Status: hotovo. Backend prijima PNG, JPEG a PDF, uklada soubory do perzistentniho Docker volume, vytvari metadata dokumentu a zaklada OCR job ve stavu `queued`. Jeden doklad muze mit vice fotek/souboru pro dlouhe uctenky. Frontend ma samostatnou stranku Doklady, upload souboru, mobilni vstup pro vyfoceni dokladu kamerou, seznam dokladu, detail s metadata placeholdery a misto pro budouci nahled.

Scope:

- Upload PDF/obrazku.
- Vyfoceni dokladu kamerou pres mobilni browser.
- Ulozeni jednoho nebo vice souboru k jednomu dokladu.
- Metadata dokumentu.
- Stav dokumentu: uploaded, processing, processed, failed.
- Zakladni seznam dokumentu.
- Samostatna frontend stranka pro doklady vedle menu.
- Detail dokumentu s pripravenym mistem pro nahled a OCR metadata.
- Pridani dalsi fotky/souboru k existujicimu dokladu.
- Smazani jednotlive fotky/souboru a smazani celeho dokladu.
- Zalozeni budouciho OCR jobu po uploadu.

Testy:

- API test uploadu validniho obrazku `image/png` a `image/jpeg`.
- API test uploadu validniho PDF, pokud bude PDF v teto fazi povolene.
- Frontend build kontrola vstupu pro upload souboru a mobilni capture kamerou.
- Negativni testy: `.exe`, textovy soubor prejmenovany na `.jpg`, prazdny soubor, prilis velky soubor.
- Validace magic bytes/MIME typu, ne pouze pripony souboru.
- Test, ze dokument je prirazen spravnemu `user_id`.
- Test, ze uzivatel nevidi ani nestahne dokument jineho uzivatele.
- Test cisteni docasnych souboru pri chybe uploadu.
- Test pridani druhe fotky k dokladu.
- Test smazani jednotlive fotky a celeho dokladu.
- Hotovo: backend integrity test, ze cizi uzivatel nesmi pridavat/mazat soubory, cist joby ani spoustet nebo upravovat extrakci ciziho dokumentu.
- Hotovo: backend integrity test, ze smazani celeho dokladu smaze navazane DB zaznamy i fyzicky ulozene soubory.

## Fáze 4: OCR pipeline

Cil: z dokumentu se vytahne text a ulozi se k dokumentu.

Status: hotovo. Pridan je `ocr-worker` kontejner, OCR service s volitelnym enginem Ollama GLM-OCR/DeepSeek-OCR/EasyOCR/Tesseract, PDF rasterizace pres `pdftoppm`, tabulka `ocr_results`, API pro nacteni OCR vysledku a vyvojove spusteni OCR nad dokumentem. OCR zpracuje vsechny fotky/soubory jednoho dokladu dohromady. Detail dokladu ukazuje tri vrstvy po OCR: OCR text, strukturovany JSON z Ollamy a kratky popisek pouzivany jako RAG text. Vychozi LLM zpracovani je hybridni: model dostane OCR text i obrazky dokladu. V nastaveni lze vybrat model pro LLM zpracovani OCR; pokud neni vybran, pouzije se `EXTRACTION_MODEL` a potom `OLLAMA_MODEL`.

Scope:

- OCR engine: vychozi Ollama `glm-ocr:latest` pro dokumentove OCR pres vision model, EasyOCR (`cs,en`) a Tesseract (`ces+eng`) jako lokalni fallback.
- Konfigurace OCR modelu pres `OLLAMA_OCR_MODEL`, vychozi `glm-ocr:latest`.
- Konfigurace OCR promptu pres `OLLAMA_OCR_PROMPT`, vychozi `Text Recognition:` pro kompletni GLM-OCR text; `Table Recognition:` zustava testovaci varianta pro tabulkove vyrezy.
- EasyOCR preprocessing: respektovat EXIF orientaci, prevest fotku do RGB PNG a zmensit dlouhou stranu na `EASYOCR_MAX_IMAGE_SIDE`.
- Predzpracovani obrazku.
- Extrakce textu.
- Spojeni OCR textu z vice fotek jednoho dokladu.
- Ulozeni raw a normalizovaneho textu.
- Predzpracovani OCR textu do RAG-ready vrstvy (`rag_text`).
- LLM post-processing OCR textu do `DocumentExtraction.structured_json`.
- Hybridni LLM post-processing: OCR text jako datova kotva a obrazky dokladu jako vizualni kotva pro layout a role poli.
- Vygenerovany popisek dokladu ulozeny jako `DocumentExtraction.summary` a promitnuty do `rag_text`.
- Perzistentni uzivatelske nastaveni modelu pro zpracovani OCR.
- Zakladni metadata pro RAG: kandidati datumu, kandidati castek, pocet radku.
- Zakladni kontrola kvality OCR.
- Worker pro zpracovani `queued` OCR jobu.
- Frontend zobrazeni OCR vysledku v detailu dokladu.

Testy:

- Unit test predzpracovani obrazku na malych fixture souborech.
- Integration test OCR workeru nad jednim vzorovym obrazkem uctenky a jednim PDF/fakturou.
- Test ulozeni `OcrResult` a prechodu stavu dokumentu na `processed`.
- Test vyberu OCR enginu podle konfigurace.
- Test, ze Ollama OCR engine posila obrazek na nakonfigurovany model a vraci text/markdown.
- Test chyboveho stavu `failed`, pokud OCR engine spadne nebo vrati prazdny vysledek.
- Regresni test normalizace textu pro castky, datumy a zakladni ceske znaky.
- Test vytvoreni RAG-ready textu a metadata kandidatu.
- Mockovany API test rucniho OCR spusteni a nacteni OCR vysledku.
- Mockovany API test LLM extrakce po OCR: strukturovany JSON, popisek a aktualizovany RAG text.
- Mockovany test hybridni extrakce, ze se do Ollamy posila OCR text i obrazek.
- Test ulozeni nastaveni modelu a jeho pouziti pri LLM extrakci.
- Hotovo: backend integrity test opakovaneho OCR spusteni, ze zustane jediny `OcrResult` pro dokument a vysledek se konzistentne aktualizuje.

## Fáze 5: RAG nad dokumenty

Cil: chat umi odpovidat s vyuzitim nahranych dokumentu a odkazovat na jejich detail.

Status: rozpracovano. Prvni implementace pridava tabulku `document_chunks` nad `pgvector`, embedding pres Ollama, automatickou indexaci jednoho semanticky silneho `rag_text` po LLM strukturaci dokladu a agentni chat flow, ve kterem model bud odpovi primo, nebo si internim JSON prikazem vyzada hledani v dokladech. V teto verzi se neembeduje cely raw OCR text, ale deterministicky slozeny text ze summary, klicovych poli, polozek a rucnich uzivatelskych aliasu polozek.

Scope:

- Prvni RAG vrstva: jeden chunk na doklad slozeny z `DocumentExtraction.summary`, klicovych strukturovanych poli a polozek.
- Neembedovat kompletni raw OCR, pravni paticky ani debug/confidence hodnoty; OCR zustava auditni zdroj v detailu dokladu.
- Embeddings pres Ollama model konfigurovany `RAG_EMBEDDING_MODEL`.
- Vector index v PostgreSQL tabulce `document_chunks` s pgvector sloupcem.
- Automaticka obnova embeddingu po uspesnem strukturovani dokladu.
- Smazani/stale invalidace embeddingu pri zmene souboru dokladu nebo smazani dokladu.
- Retrieval podle dotazu uzivatele ve stejnem `user_id` scope.
- Prompt sablona s dokumentovym kontextem pred volanim chat modelu.
- Interni agentni prikaz `search_documents`, ktery umi vyzadat RAG dotazy a zakladni strukturovane hledani bez vypisu do chatu.
- Frontend zobrazuje nenapadne stitky `used rag`, `used search`, `direct answer` a pocet zdroju.
- Citace nebo odkazy na zdrojove dokumenty.
- Pokud chat mluvi o dokladu, odpoved musi umet vratit odkaz na detail cele "slozky" dokladu.
- Frontend zobrazi odkazy/citace jako klikatelne prvky do stranky Doklady.
- Pozdeji doplnit hybridni hledani: kombinace semantic search + presne SQL filtry podle datumu, castky, dodavatele, cisla faktury a variabilniho symbolu.

Testy:

- Unit test skladby RAG textu, aby byl kratky, vyhledatelny a neobsahoval zbytecny raw OCR sum.
- Test ulozeni a smazani embeddingu pro dokument.
- Test, ze se embeduje summary a vybrana strukturovana vrstva.
- Retrieval test nad malou sadou fixture dokumentu s ocekavanym top vysledkem.
- Test filtrovani podle `user_id`, aby RAG nikdy nevratil cizi dokument.
- Mockovany test prompt builderu, ze do modelu vklada pouze relevantni kontext.
- Test citaci/odkazu na zdroj a navigace na detail dokladu.
- Test, ze chat dostane dokumentovy RAG kontext, pokud retrieval vrati relevantni chunk.
- Hotovo: backend test, ze agent umi vratit primou odpoved bez RAG/search.
- Hotovo: backend test, ze agent umi vyzadat kombinaci RAG a strukturovaneho hledani a metadata se propisou k odpovedi.
- Hotovo: backend integrity test, ze pridani dalsiho souboru k dokladu smaze stare OCR/extraction vystupy, invaliduje RAG chunky a zalozi novy OCR job.
- Hotovo: backend integrity test, ze smazani dokladu vola invalidaci RAG chunku spolu s cleanupem dokumentovych dat.

## Fáze 6: extrakce strukturovaných dat

Cil: system umi z faktur a uctenek vytahnout hlavni pole a navrhnout lidsky kontrolovatelny popisek.

Scope:

- Datum vystaveni, datum splatnosti, dodavatel, ICO/DIC, castka, DPH, mena.
- Bohate vnorene schema pro faktury: `merchant`, `buyer`, `payment`, `order`, `items`, `tax_summary`.
- Rozliseni adres a kontaktu podle vlastnika a role: sidlo/provozovna uvnitr `merchant`, fakturacni/dodaci adresa uvnitr `buyer`.
- Platebni udaje uvnitr `payment`: celkova castka, mena, zpusob platby, bankovni ucet, variabilni/konstantni symbol.
- Rozsireni persistentniho nastaveni modelu pro LLM zpracovani OCR, extrakci, tvorbu popisku a embedding.
- Rozsireni LLM post-processingu OCR textu few-shot metodou pres Ollama.
- Polozky dokladu, pokud OCR kvalita dovoli.
- Vygenerovany popisek typu: "Nakup potravin v Lidl dne 12.05.2026 za 423,90 Kc".
- Review workflow: uzivatel po nahrani zkontroluje a schvali/upravi popisek i hlavni pole.
- Validace a rucni oprava hodnot.
- Ukladat stav review: draft, approved, rejected/needs_review.

Testy:

- Fixture testy pro extrakci hlavickovych poli z ruznych typu faktur.
- Test persistentniho nastaveni modelu: ulozeni, nacteni, pouziti v jobu.
- Mockovany test few-shot promptu a validace JSON vystupu z Ollamy.
- Test validace castky, meny, data a ICO/DIC.
- Test, ze fakturacni nebo dodaci adresa neskonci v poli `place`, pokud nejde o realne misto nakupu/prodeje.
- Test rucni opravy hodnot a auditni stopy zmeny.
- Test schvaleni popisku a zmeny review stavu.
- Test, ze nejiste hodnoty maji confidence a nejsou automaticky prezentovane jako jiste.

## Fáze 7: pokrocile hlasove rozhrani

Cil: rozsireni hlasoveho ovladani nad zakladni SpeechCloud MVP.

Scope:

- Pokrocile ovladani mikrofonu ve vlastnim frontendu.
- Napojeni vlastniho kodu pro text-to-speech, pokud bude potreba mimo SpeechCloud.
- Frontend ovladani mikrofonu.
- Stav nahravani a prehravani.
- Prace s chybami hlasovych sluzeb.

Testy:

- Frontend test stavu mikrofonu: idle, recording, processing, playing, error.
- Test preruseni nahravani a preruseni TTS.
- Mockovany test SpeechCloud udalosti ve frontend vrstve.
- Integration smoke test hlasove session pres SpeechCloud testovaci/proxy prostredi.
- Test fallbacku na textovy chat pri chybe hlasove vrstvy.
