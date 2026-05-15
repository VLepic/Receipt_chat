# Rozhodnutí a otevřené otázky

## Navržená rozhodnutí

### D1: Backend bude ve FastAPI

FastAPI dobre sedi na Python API, validaci pres Pydantic, OpenAPI dokumentaci a budouci streaming odpovedi z modelu.

### D2: Ollama bude za adapterem

Kod chatu nebude volat Ollama primo z mnoha mist. Vznikne `llm` modul, ktery schova HTTP komunikaci, konfiguraci modelu, timeouty a format odpovedi.

### D2a: Ollama bude primarne externi server

Backend a SpeechCloud dialog manager se budou pripojovat na externi Ollama endpoint pres `OLLAMA_BASE_URL`. Lokalni Ollama kontejner v Docker Compose zustava pouze volitelny profil pro fallback nebo offline vyvoj.

### D3: RAG bude oddelená služba uvnitř backendu

Chat service si vyzada relevantni kontext pres `rag` modul. Diky tomu pujde prvni chat-only verzi postavit bez RAG a pozdeji ji doplnit bez prepisu UI.

### D4: PostgreSQL bude hlavní databáze

PostgreSQL pokryje uzivatele, chat, dokumentova metadata a pres pgvector i budouci embeddings. Tim se omezi pocet infrastrukturnich komponent v prvnich fazich.

### D5: Vektorova vrstva bude nejdriv pgvector

Pro RAG se nejdriv pouzije `pgvector` v PostgreSQL kontejneru. Specializovana vektorova databaze jako Qdrant, Chroma nebo Milvus zustava alternativa pro pozdejsi fazi, pokud naroste objem dokumentu nebo naroky na retrieval.

### D6: Lokalni prostredi pobezi pres Docker Compose

Backend, frontend a PostgreSQL budou spoustene jako kontejnery pres Docker Compose. Speech-dialog pobezi take v compose. Ollama bude primarne externi endpoint a lokalni kontejner bude jen volitelny profil. Pozdeji se do compose stacku muze pridat Redis pro job queue a MinIO pro dokumentove soubory.

### D7: SpeechCloud bude hlavni hlasova vrstva

Pro hlasove rozhrani se pouzije SpeechCloud.dialog podle dokumentace `docs/SpeechCloud.dialog.md` a ukazek v `example`. Vlastni speech-to-text/text-to-speech kod se nebude v prvni fazi implementovat mimo SpeechCloud.

### D8: MVP prihlasovani bude email + heslo

Prvni verze pouzije email jako prihlasovaci identitu a heslo hashovane pres Argon2. Doporučená knihovna je `FastAPI Users` se SQLAlchemy adapterem, protoze poskytuje hotove routery pro registraci, login/logout, aktualniho uzivatele, reset hesla, overeni emailu a OAuth rozsireni. Google prihlaseni bude volitelna pozdejsi faze pres `Authlib` nebo OAuth router ve FastAPI Users.

### D9: Auth transport bude secure HTTP-only cookie

Webova aplikace bude pouzivat secure HTTP-only cookie. Frontend nebude ukladat auth tokeny do `localStorage`. V produkci musi cookie bezet pres HTTPS se `Secure`; pro bezny web flow pouzit `SameSite=Lax`, pokud se pozdeji neukaze potreba jineho nastaveni.

### D10: OCR text bude vstup pro LLM post-processing

Raw a normalizovany OCR text se uklada kvuli auditu a debugovani. Pro strukturovana data a semanticke vyhledavani se pouzije dalsi LLM krok pres Ollama s few-shot promptem. Vysledkem bude JSON s poli dokladu a kratky lidsky popisek.

### D11: Popisek dokladu bude reviewovatelny

Vygenerovany popisek a hlavni extrahovana pole nebudou automaticky povazovana za schvalena. Uzivatel je po nahrani zkontroluje, upravi nebo schvali. Pro RAG se preferuje schvaleny popisek; draft hodnoty mohou byt oznacene jako nejiste.

### D12: Chat bude odkazovat na detail celeho dokladu

Pokud model v chatu pouzije data z dokladu, odpoved musi umet vratit odkaz na detail dokladu ve strance Doklady. UI nebude zobrazovat pouze textovou citaci, ale klikatelny odkaz na celou "slozku" dokladu.

## Otevřené otázky

1. Ma byt aplikace primarne lokalni pro jednoho uzivatele, nebo od zacatku multi-user?
2. Ma byt frontend React/Vite, nebo chces Next.js?
3. Jaka bude produkcni hodnota `OLLAMA_BASE_URL` a vyzadovana autentizace?
4. Jake typy dokumentu budou prvni: PDF faktury, fotky uctenek, skeny, nebo vse najednou?
5. Je prioritou cestina, nebo i anglictina/nemcina na fakturach?
6. Chces ve fazi RAG citace na konkretni dokument a pasaz?
7. Ktere modely budou vychozi pro chat, OCR post-processing, extrakci a embeddings?
8. Ma se neschvaleny popisek pouzivat v RAG, nebo az po rucnim schvaleni?
9. Ma aplikace umet export do CSV/Excel nebo napojeni na ucetni system?
10. Jake bude finalni SpeechCloud application id a verejne dostupna URL/port dialog manageru?
11. Bude webovy klient pouzivat SpeechCloud proxy statickych souboru, nebo vlastni frontend s napojenim na SpeechCloud JS?

## Rizika

- OCR kvalita u fotek uctenek muze byt vyrazne horsi nez u PDF faktur.
- Mensi LLM modely mohou mit potize se spolehlivou extrakci strukturovanych dat.
- RAG bez citaci muze davat odpovedi, ktere se hure overuji.
- Pokud se auth strategie zmeni pozde, muze to znamenat upravy frontend i backend architektury.

## Doporučené další rozhodnutí

Nejdrive rozhodnout frontend framework a provozni topologii pro SpeechCloud/Ollama. Auth metoda i transport jsou rozhodnute: email + heslo + secure HTTP-only cookie.
